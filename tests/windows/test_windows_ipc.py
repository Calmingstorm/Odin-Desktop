"""The Windows transport (phase 2 plan B1, B2): a real engine IPC server on an owner-only pipe."""
from __future__ import annotations

import asyncio
import json
import struct
import uuid

import pytest

from src.desktop.platform import win32
from src.desktop.platform.windows import windows_profile_paths
from src.desktop.platform.windows_files import user_sid
from src.desktop.platform.windows_ipc import NamedPipeEndpoint, pipe_name


@pytest.fixture
def engine(tmp_path):
    from src.desktop.authority import OwnerAuthority
    from src.desktop.ipc import IpcServer

    paths = windows_profile_paths("test", environ={"LOCALAPPDATA": str(tmp_path)})
    paths.create_private()
    token_file = paths.config_dir / "ipc.token"
    token_file.write_text("ab" * 32)
    # The app writes its token before the engine's first start, as here.
    authority = OwnerAuthority(paths, app_bootstrap=True)
    name = pipe_name(f"t{uuid.uuid4().hex[:12]}")
    calls = []

    async def dispatch(connection, message):
        calls.append(message["method"])
        return {"t": "res", "id": message["id"], "ok": True, "result": {"echo": message["method"]}}

    def welcome():
        return {"core": {"instance_id": "core-1", "version": "test"}, "capabilities": [],
                "features": [], "event_high": 0}

    def make():
        return IpcServer(name, token_file, "test", authority, welcome, dispatch)

    return SimpleEngine(make, name, token_file, paths, calls)


class SimpleEngine:
    def __init__(self, make, name, token_file, paths, calls):
        self.make, self.name, self.token_file, self.paths, self.calls = (
            make, name, token_file, paths, calls)


async def test_a_local_client_talks_to_the_engine_over_a_sealed_pipe(engine):
    from src.desktop.local_client import LocalClient

    server = engine.make()
    await server.start()
    try:
        client = await LocalClient.connect(engine.name, engine.token_file, "test")
        assert client.welcome["profile_id"] == "test"
        request = await client.request("status.get")
        response = await client.read()
        assert response == {"t": "res", "id": request, "ok": True, "result": {"echo": "status.get"}}
        assert engine.calls == ["status.get"]
        await client.close()
    finally:
        await server.shutdown()


async def test_a_client_without_the_token_is_refused(engine):
    from src.desktop.local_client import LocalClient

    server = engine.make()
    await server.start()
    wrong = engine.paths.config_dir / "wrong.token"
    wrong.write_text("cd" * 32)
    try:
        with pytest.raises(PermissionError, match="engine proof refused"):
            await LocalClient.connect(engine.name, wrong, "test")
        assert engine.calls == []
    finally:
        await server.shutdown()


async def test_a_squatted_pipe_name_stops_the_engine_from_starting(engine):
    squatter = NamedPipeEndpoint(engine.name)
    await squatter.listen(lambda reader, writer: writer.close())
    try:
        server = engine.make()
        with pytest.raises(OSError):
            await server.start()
        assert server._token is None
    finally:
        squatter.close()


async def test_the_pipe_admits_only_this_user_and_releases_its_name(engine):
    from src.desktop.platform.windows_ipc import WindowsIpc

    server = engine.make()
    await server.start()
    try:
        reader, writer = await WindowsIpc().connect(engine.name)
        security = win32.object_security(writer.get_extra_info("pipe").handle)
        allowed = [ace for ace in security.aces if ace[0] == win32.ACCESS_ALLOWED_ACE_TYPE]
        assert security.protected and [ace[3] for ace in allowed] == [user_sid()]
        assert WindowsIpc.peer(writer, client=False) == user_sid()
        writer.close()
    finally:
        await server.shutdown()
    again = engine.make()
    await again.start()
    await again.shutdown()


async def test_a_token_bearing_hello_gets_a_plain_refusal(engine):
    from src.desktop.platform.windows_ipc import WindowsIpc
    from src.desktop.protocol import encode_frame, read_frame

    server = engine.make()
    await server.start()
    try:
        reader, writer = await WindowsIpc().connect(engine.name)
        writer.write(encode_frame({"t": "hello", "protocol": {"major": 0, "minor": 2},
                                   "client": {"name": "x", "version": "0"}, "profile_id": "test",
                                   "token": "ab" * 32, "features": []}))
        await writer.drain()
        assert await read_frame(reader) == {"t": "bye", "reason": "unauthorized"}
        writer.close()
        assert engine.calls == []
    finally:
        await server.shutdown()


HELLO = {"t": "hello", "protocol": {"major": 0, "minor": 2},
         "client": {"name": "x", "version": "0"}, "profile_id": "test", "features": [],
         "auth": {"v": 1, "client_nonce": "33" * 32}}


def _escaped(message: dict) -> bytes:
    """A frame as JSON with ASCII escapes, so a lone surrogate reaches the engine as sent."""
    body = json.dumps(message, separators=(",", ":")).encode("ascii")
    return struct.pack("!I", len(body)) + body


async def _refused_and_closed(server, reader, reason: str) -> None:
    from src.desktop.protocol import read_frame

    assert await asyncio.wait_for(read_frame(reader), 5) == {"t": "bye", "reason": reason}
    assert await asyncio.wait_for(reader.read(), 5) == b""  # the engine closed its end
    for _ in range(250):
        if not server._writers and not server._tasks:
            break
        await asyncio.sleep(0.02)
    assert not server._writers and not server._tasks


@pytest.mark.parametrize("change", [
    {"protocol": {"major": 0, "minor": 1 << 64}},
    {"client": {"name": "\ud800", "version": "0"}},
    {"auth": {"v": True, "client_nonce": "33" * 32}},
])
async def test_a_malformed_hello_is_refused_and_its_pipe_closed(engine, change):
    from src.desktop.platform.windows_ipc import WindowsIpc

    server = engine.make()
    await server.start()
    try:
        reader, writer = await WindowsIpc().connect(engine.name)
        writer.write(_escaped({**HELLO, **change}))
        await writer.drain()
        await _refused_and_closed(server, reader, "protocol_error")
        writer.close()
        assert engine.calls == []
    finally:
        await server.shutdown()


async def test_an_unexpected_handshake_failure_still_closes_the_pipe(engine, monkeypatch):
    from src.desktop import ipc_auth
    from src.desktop.platform.windows_ipc import WindowsIpc

    async def broken(*args, **kwargs):
        raise RuntimeError("never shown to the peer")

    monkeypatch.setattr(ipc_auth, "server_session", broken)
    server = engine.make()
    await server.start()
    try:
        reader, writer = await WindowsIpc().connect(engine.name)
        writer.write(_escaped(HELLO))
        await writer.drain()
        await _refused_and_closed(server, reader, "internal_error")
        writer.close()
    finally:
        await server.shutdown()


async def test_shutdown_during_a_handshake_closes_the_pipe(engine):
    from src.desktop.platform.windows_ipc import WindowsIpc

    server = engine.make()
    await server.start()
    reader, writer = await WindowsIpc().connect(engine.name)
    for _ in range(250):  # the engine is waiting for this client's hello
        if server._tasks:
            break
        await asyncio.sleep(0.02)
    await server.shutdown()
    assert await asyncio.wait_for(reader.read(), 5) == b""
    assert not server._writers and not server._tasks
    writer.close()


async def test_connecting_to_a_busy_pipe_is_bounded(engine, monkeypatch):
    from src.desktop import protocol
    from src.desktop.platform.windows_ipc import WindowsIpc

    mode = win32.PIPE_TYPE_BYTE | win32.PIPE_READMODE_BYTE | win32.PIPE_WAIT
    handle = win32.CreateNamedPipeW(engine.name, win32.PIPE_ACCESS_DUPLEX, mode, 1, 4096, 4096,
                                    0, None)
    assert handle not in (None, win32.INVALID_HANDLE_VALUE)
    first = open(engine.name, "r+b", buffering=0)  # takes the pipe's only instance
    monkeypatch.setattr(protocol, "HANDSHAKE_TIMEOUT", 1.0)
    try:
        loop = asyncio.get_running_loop()
        started = loop.time()
        with pytest.raises(TimeoutError):
            await WindowsIpc().connect(engine.name)
        assert loop.time() - started < 10
    finally:
        first.close()
        win32.close(handle)


def test_a_process_that_cannot_be_opened_has_no_user():
    with pytest.raises(OSError):
        win32.process_user_sid(0)  # the idle process: never opened for a token
