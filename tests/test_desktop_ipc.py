"""Real isolated Unix sockets; refusal tests use harmless envelopes/OS stubs."""
from __future__ import annotations

import asyncio
import os
import socket
import stat
import struct
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from src.desktop import ipc_auth
from src.desktop.authority import OwnerAuthority
from src.desktop.ipc import IpcServer
from src.desktop.local_client import LocalClient, main
from src.desktop.paths import ProfilePaths
from src.desktop.protocol import (
    MAX_FRAME,
    ProtocolError,
    encode_frame,
    read_frame,
    validate_max_frame,
    validate_request,
)


def hello(credential, **changes):
    value = {"t": "hello", "protocol": {"major": 0, "minor": 2},
             "client": {"name": "fixture", "version": "0"},
             "profile_id": "default", "token": credential, "features": []}
    value.update(changes)
    return value


@asynccontextmanager
async def fixture_server(dispatch=None):
    with tempfile.TemporaryDirectory(prefix="ipc-") as root:
        root = Path(root)
        paths = ProfilePaths.from_xdg(home=root, environ={})
        authority = OwnerAuthority(paths)
        token_dir = root / "credentials"
        token_dir.mkdir(mode=0o700)
        token_file = token_dir / "ipc.token"
        token_file.write_text("a" * 64)
        token_file.chmod(0o600)
        calls = []

        async def default_dispatch(connection, request):
            assert authority.accepts(connection.owner_context)
            calls.append(request)
            return {"t": "res", "id": request["id"], "ok": True,
                    "result": {"phase": "ready"}}

        server = IpcServer(root / "runtime" / "core.sock", token_file, "default", authority,
                           lambda: {"core": {"instance_id": authority.runtime_id, "version": "0"},
                                    "capabilities": ["status.get"], "features": [],
                                    "event_high": "0"},
                           dispatch or default_dispatch)
        try:
            await server.start()
            yield server, token_file, authority, calls
        finally:
            await server.shutdown()
            authority.release_runtime()


async def receive(reader):
    return await asyncio.wait_for(read_frame(reader), 2)


async def raw_connect(server, token_file, **changes):
    reader, writer = await asyncio.open_unix_connection(server.socket_path)
    writer.write(encode_frame(hello(ipc_auth.load_token(token_file), **changes)))
    await writer.drain()
    return reader, writer, await receive(reader)


async def close_writer(writer):
    writer.close()
    await asyncio.wait_for(writer.wait_closed(), 2)


@pytest.mark.asyncio
async def test_real_welcome_status_ping_unknown_fields_and_client():
    async with fixture_server() as (server, token_file, authority, calls):
        client = await LocalClient.connect(server.socket_path, token_file)
        assert client.welcome["protocol"] == {"major": 0, "minor": 3}
        assert client.welcome["core"]["instance_id"] == authority.runtime_id
        assert client.welcome["features"] == []
        assert client.welcome["event_high"] == "0"
        assert client.welcome["max_frame"] == MAX_FRAME
        request_id = await client.request("status.get")
        assert await client.read() == {"t": "res", "id": request_id, "ok": True,
                                       "result": {"phase": "ready"}}
        await client.send({"t": "ping", "n": "probe", "future": {"enabled": True}})
        assert await client.read() == {"t": "pong", "n": "probe"}
        assert calls[0]["id"] == request_id
        assert len(server.connections) == 1
        assert stat.S_IMODE(server.socket_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(server.socket_path.parent.stat().st_mode) == 0o700
        await client.close()
        for _ in range(10):
            if not server.connections:
                break
            await asyncio.sleep(0.01)
        assert not server.connections


@pytest.mark.asyncio
async def test_fragmented_handshake_and_coalesced_frames():
    async with fixture_server() as (server, token_file, _, _):
        reader, writer = await asyncio.open_unix_connection(server.socket_path)
        frame = encode_frame(hello(ipc_auth.load_token(token_file), future=True))
        for fragment in (frame[:1], frame[1:3], frame[3:9], frame[9:]):
            writer.write(fragment)
            await writer.drain()
            await asyncio.sleep(0)
        assert (await receive(reader))["t"] == "welcome"
        writer.write(encode_frame({"t": "ping", "n": 1}) + encode_frame({"t": "ping", "n": 2}))
        assert await receive(reader) == {"t": "pong", "n": 1}
        assert await receive(reader) == {"t": "pong", "n": 2}
        await close_writer(writer)


@pytest.mark.parametrize("changes,reason", [
    ({"token": "b" * 64}, "unauthorized"),
    ({"token": "é"}, "unauthorized"),
    ({"profile_id": "other"}, "wrong_profile"),
    ({"protocol": {"major": 1, "minor": 2}}, "incompatible"),
    ({"protocol": {"major": False, "minor": 2}}, "protocol_error"),
])
@pytest.mark.asyncio
async def test_handshake_refusals(changes, reason):
    async with fixture_server() as (server, token_file, _, calls):
        reader, writer, message = await raw_connect(server, token_file, **changes)
        assert message == {"t": "bye", "reason": reason}
        assert await asyncio.wait_for(reader.read(), 2) == b""
        assert not server.connections and not calls
        await close_writer(writer)


@pytest.mark.asyncio
async def test_peer_rejection_checks_os_primitive(monkeypatch):
    monkeypatch.setattr(ipc_auth, "peer_uid", lambda _sock: os.geteuid() + 1)
    async with fixture_server() as (server, _, _, calls):
        reader, writer = await asyncio.open_unix_connection(server.socket_path)
        assert await receive(reader) == {"t": "bye", "reason": "unauthorized"}
        assert not server.connections and not calls
        await close_writer(writer)


@pytest.mark.asyncio
async def test_handshake_deadline_and_partial_eof(monkeypatch):
    monkeypatch.setattr("src.desktop.ipc.HANDSHAKE_TIMEOUT", 0.04)
    async with fixture_server() as (server, _, _, _):
        reader, writer = await asyncio.open_unix_connection(server.socket_path)
        writer.write(b"\0")
        assert await receive(reader) == {"t": "bye", "reason": "protocol_error"}
        assert await reader.read() == b""
        await close_writer(writer)
        reader, writer = await asyncio.open_unix_connection(server.socket_path)
        writer.write(b"\0\0")
        writer.write_eof()
        assert await reader.read() == b""
        await close_writer(writer)
        assert not server.connections


@pytest.mark.parametrize("payload", [
    b'[]', b'{"t":"hello","t":"hello"}', b'{"n":NaN}',
    b'{"n":Infinity}', b'{"n":1e999}', b'{"n":"\xff"}', b'{',
])
@pytest.mark.asyncio
async def test_invalid_json_rejected(payload):
    async with fixture_server() as (server, _, _, _):
        reader, writer = await asyncio.open_unix_connection(server.socket_path)
        writer.write(struct.pack("!I", len(payload)) + payload)
        assert await receive(reader) == {"t": "bye", "reason": "protocol_error"}
        assert await reader.read() == b""
        await close_writer(writer)


@pytest.mark.parametrize("size", [0, MAX_FRAME + 1, 0xffffffff])
@pytest.mark.asyncio
async def test_length_limit_before_body(size):
    async with fixture_server() as (server, _, _, _):
        reader, writer = await asyncio.open_unix_connection(server.socket_path)
        writer.write(struct.pack("!I", size))
        assert await receive(reader) == {"t": "bye", "reason": "protocol_error"}
        await close_writer(writer)


@pytest.mark.parametrize("limit", [0, -1, True, 4.0, MAX_FRAME + 1])
def test_bad_max_frame(limit):
    with pytest.raises(ValueError, match="invalid frame limit"):
        validate_max_frame(limit)


def test_encode_finite_object_and_limit():
    assert encode_frame({"value": "é"})[4:].decode("utf-8") == '{"value":"é"}'
    for value in ([1], {"n": float("nan")}, {"n": float("inf")}):
        with pytest.raises(ProtocolError):
            encode_frame(value)
    with pytest.raises(ProtocolError, match="size"):
        encode_frame({"message": "long"}, max_frame=1)


@pytest.mark.asyncio
async def test_envelope_errors_and_semantic_params_reach_dispatch():
    async with fixture_server() as (server, token_file, _, calls):
        client = await LocalClient.connect(server.socket_path, token_file)
        await client.request("conversations.update", {"expected_rev": "invalid"})
        assert (await client.read())["ok"] is True
        assert calls[0]["params"]["expected_rev"] == "invalid"
        await client.send({"t": "req", "id": "not-a-uuid", "method": "status.get", "params": {}})
        assert await client.read() == {"t": "bye", "reason": "protocol_error"}
        await client.close()
        client = await LocalClient.connect(server.socket_path, token_file)
        await client.send({"t": "future-message"})
        assert await client.read() == {"t": "bye", "reason": "protocol_error"}
        await client.close()


def test_invalid_request_envelope():
    for identity, method in ((str(uuid.uuid1()), "status.get"), (str(uuid.uuid4()), "")):
        with pytest.raises(ProtocolError):
            validate_request({"t": "req", "id": identity, "method": method, "params": {}})
    with pytest.raises(ProtocolError):
        validate_request({"t": "req", "id": str(uuid.uuid4()), "method": "status.get"})
    validate_request({"t": "req", "id": str(uuid.uuid4()), "method": "status.get", "params": []})


@pytest.mark.asyncio
async def test_one_slow_connection_does_not_block_another():
    async with fixture_server() as (server, token_file, _, _):
        _, slow = await asyncio.open_unix_connection(server.socket_path)
        slow.write(b"\0")
        client = await LocalClient.connect(server.socket_path, token_file)
        await client.ping(3)
        assert await asyncio.wait_for(client.read(), 1) == {"t": "pong", "n": 3}
        await client.close()
        await close_writer(slow)


@pytest.mark.parametrize("mode", [0o644, 0o400, 0o660])
def test_token_mode_privacy(tmp_path, mode):
    tmp_path.chmod(0o700)
    path = tmp_path / "ipc.token"
    path.write_text("a" * 64)
    path.chmod(mode)
    with pytest.raises(PermissionError, match="unsafe IPC credential"):
        ipc_auth.load_token(path)


def test_token_leaf_nofollow_with_linked_parent_accepted(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "ipc.token"
    for text in ("a" * 63, "g" * 64, "a" * 64 + "\n"):
        path.write_text(text)
        path.chmod(0o600)
        with pytest.raises(PermissionError):
            ipc_auth.load_token(path)
    path.write_text("a" * 64)
    assert ipc_auth.load_token(path) == "a" * 64
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        ipc_auth.load_token(link)
    linked_parent = tmp_path / "parent"
    linked_parent.symlink_to(tmp_path, target_is_directory=True)
    assert ipc_auth.load_token(linked_parent / "ipc.token") == "a" * 64
    with pytest.raises(OSError):
        ipc_auth.load_token(linked_parent / "link")
    tmp_path.chmod(0o755)
    assert ipc_auth.load_token(path) == "a" * 64
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755


@pytest.mark.asyncio
async def test_live_socket_refused_without_handshake():
    async with fixture_server() as (server, token_file, authority, _):
        identity = server.socket_path.stat().st_ino
        second = IpcServer(server.socket_path, token_file, "default", authority,
                           lambda: {}, lambda *_: None)
        with pytest.raises(RuntimeError, match="already active"):
            await second.start()
        await second.shutdown()
        assert server.socket_path.stat().st_ino == identity


@pytest.mark.asyncio
async def test_stale_socket_replaced_and_non_socket_not_replaced():
    async with fixture_server() as (server, token_file, authority, _):
        await server.shutdown()
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(server.socket_path))
        stale.close()
        second = IpcServer(server.socket_path, token_file, "default", authority,
                           lambda: {"core": {}, "event_high": "0"}, lambda *_: None)
        await second.start()
        assert stat.S_IMODE(server.socket_path.stat().st_mode) == 0o600
        await second.shutdown()
        server.socket_path.write_text("fixture")
        third = IpcServer(server.socket_path, token_file, "default", authority,
                          lambda: {}, lambda *_: None)
        with pytest.raises(PermissionError):
            await third.start()
        assert server.socket_path.read_text() == "fixture"
        server.socket_path.unlink()
        server.socket_path.symlink_to(token_file)
        fourth = IpcServer(server.socket_path, token_file, "default", authority,
                           lambda: {}, lambda *_: None)
        with pytest.raises(PermissionError):
            await fourth.start()
        assert server.socket_path.is_symlink()


@pytest.mark.asyncio
async def test_shutdown_inode_safety_scrubbed_reason_and_pending_handshake():
    async with fixture_server() as (server, token_file, _, _):
        client = await LocalClient.connect(server.socket_path, token_file)
        _, pending = await asyncio.open_unix_connection(server.socket_path)
        await asyncio.sleep(0)
        server.socket_path.unlink()
        server.socket_path.write_text("replacement")
        await asyncio.wait_for(server.shutdown("arbitrary private detail"), 8)
        assert await asyncio.wait_for(client.read(), 2) == {"t": "bye", "reason": "shutdown"}
        assert server.socket_path.read_text() == "replacement"
        assert not server.connections and not server._tasks
        await client.close()
        await close_writer(pending)


@pytest.mark.asyncio
async def test_subscribe_response_before_replay_then_live_no_gap():
    lock = asyncio.Lock()
    replayed = asyncio.Event()
    events = [{"t": "evt", "seq": seq, "cursor": str(seq), "type": "runtime.status",
               "entity": {"kind": "runtime", "id": "fixture"}, "at": "2026-10-05T00:00:00Z",
               "payload": {"phase": "ready"}} for seq in (1, 2, 3)]

    async def dispatch(connection, request):
        async with lock:
            await connection.send({"t": "res", "id": request["id"], "ok": True,
                                   "result": {"event_high": "2", "reset_required": False}})
            for event in events[:2]:
                await connection.send(event)
                connection.event_seq = event["seq"]
                await asyncio.sleep(0)
            connection.subscribed = True
            replayed.set()
        return None

    async with fixture_server(dispatch) as (server, token_file, _, _):
        client = await LocalClient.connect(server.socket_path, token_file)
        await server.publish(events[0])
        identity = await client.request("events.subscribe", {"after": "0"})

        async def publish_live():
            await replayed.wait()
            async with lock:
                await server.publish(events[2])
                await server.publish(events[2])

        task = asyncio.create_task(publish_live())
        messages = [await client.read() for _ in range(4)]
        assert messages[0]["t"] == "res" and messages[0]["id"] == identity
        assert [message["seq"] for message in messages[1:]] == [1, 2, 3]
        await task
        await client.ping()
        assert await client.read() == {"t": "pong", "n": 0}
        await client.close()


def test_cli_missing_args_are_usage_error():
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2


@pytest.mark.asyncio
async def test_cli_run_status_success_and_failure(capsys):
    from argparse import Namespace

    from src.desktop.local_client import _run

    async with fixture_server() as (server, token_file, _, _):
        args = Namespace(socket=server.socket_path, token_file=token_file,
                         profile="default", method="status.get")
        assert await _run(args) == 0
        assert '"phase": "ready"' in capsys.readouterr().out

    async def refused(_connection, request):
        return {"t": "res", "id": request["id"], "ok": False,
                "error": {"code": "bad_request", "message": "Refused", "disposition": "rejected"}}

    async with fixture_server(refused) as (server, token_file, _, _):
        args.socket, args.token_file = server.socket_path, token_file
        assert await _run(args) == 1
        assert '"bad_request"' in capsys.readouterr().out


def test_cli_connection_failure_scrubbed(tmp_path, capsys):
    assert main(["--socket", str(tmp_path / "core.sock"), "--token-file",
                 str(tmp_path / "ipc.token"), "--profile", "default"]) == 1
    assert capsys.readouterr().err == "Desktop core connection failed\n"


@pytest.mark.asyncio
async def test_local_client_refuses_foreign_uid_before_token_send(monkeypatch):
    # The peer check lives in the platform's transport, shared by server and client;
    # "foreign IPC listener" is the client's own refusal, raised before any token is sent.
    monkeypatch.setattr(ipc_auth, "peer_uid", lambda _sock: os.geteuid() + 1)
    async with fixture_server() as (server, token_file, _, calls):
        with pytest.raises(PermissionError, match="foreign IPC listener"):
            await LocalClient.connect(server.socket_path, token_file)
        assert not calls and not server.connections


@pytest.mark.asyncio
async def test_local_client_refuses_socket_mode_and_handshake():
    async with fixture_server() as (server, token_file, _, _):
        server.socket_path.chmod(0o644)
        with pytest.raises(PermissionError, match="unsafe IPC socket"):
            await LocalClient.connect(server.socket_path, token_file)
        server.socket_path.chmod(0o600)
        token_file.write_text("b" * 64)
        with pytest.raises(ProtocolError, match="handshake refused"):
            await LocalClient.connect(server.socket_path, token_file)


@pytest.mark.asyncio
async def test_authority_revoked_after_handshake(monkeypatch):
    async with fixture_server() as (server, token_file, authority, calls):
        client = await LocalClient.connect(server.socket_path, token_file)
        monkeypatch.setattr(authority, "accepts", lambda _context: False)
        await client.request("status.get")
        assert await client.read() == {"t": "bye", "reason": "unauthorized"}
        assert not calls
        await client.close()


@pytest.mark.asyncio
async def test_callback_exception_is_scrubbed():
    async def failing(_connection, _request):
        raise ValueError("private detail")

    async with fixture_server(failing) as (server, token_file, _, _):
        client = await LocalClient.connect(server.socket_path, token_file)
        await client.request("status.get")
        assert await client.read() == {"t": "bye", "reason": "internal_error"}
        await client.close()


@pytest.mark.asyncio
async def test_exact_frame_limit_real_roundtrip():
    async with fixture_server() as (server, token_file, _, _):
        client = await LocalClient.connect(server.socket_path, token_file)
        overhead = len(encode_frame({"t": "ping", "n": ""})) - 4
        await client.ping("x" * (MAX_FRAME - overhead))
        message = await asyncio.wait_for(client.read(), 3)
        assert message["t"] == "pong" and len(message["n"]) == MAX_FRAME - overhead
        await client.close()


def test_token_foreign_file_owner_stub(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    path = tmp_path / "ipc.token"
    path.write_text("a" * 64)
    path.chmod(0o600)
    original = os.fstat

    def foreign(fd):
        info = original(fd)
        if stat.S_ISREG(info.st_mode):
            values = list(info)
            values[4] = os.geteuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(ipc_auth.os, "fstat", foreign)
    with pytest.raises(PermissionError, match="unsafe IPC credential"):
        ipc_auth.load_token(path)


def test_token_surrogate_and_relative_path_scrubbed():
    assert not ipc_auth.token_matches("a" * 64, "\ud800")
    with pytest.raises(ValueError, match="absolute"):
        ipc_auth.private_parent("relative/core.sock")


@pytest.mark.parametrize("mode", [0o775, 0o755, 0o777])
def test_token_validation_repairs_namespace_before_core_provisioning(tmp_path, mode):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    paths.config_dir.mkdir(parents=True)
    paths.config_dir.parent.parent.chmod(0o755)
    unrelated_mode = paths.config_dir.parent.parent.stat().st_mode
    paths.config_dir.parent.chmod(mode)
    paths.config_dir.chmod(mode)
    token = paths.config_dir / "ipc.token"
    token.write_text("a" * 64)
    token.chmod(0o600)
    assert not paths.data_dir.exists()
    assert ipc_auth.load_token(token) == "a" * 64
    for path in (paths.config_dir, paths.config_dir.parent):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert paths.config_dir.parent.parent.stat().st_mode == unrelated_mode
    assert not paths.data_dir.exists()


@pytest.mark.parametrize("create", [False, True])
@pytest.mark.parametrize("mode", [0o755, 0o775, 0o777, 0o1700])
def test_private_parent_accepts_unrelated_modes_without_chmod(tmp_path, create, mode):
    shared = tmp_path / "shared"
    directory = shared / "odin-desktop" / "default"
    directory.mkdir(parents=True)
    shared.chmod(mode)
    path, fd = ipc_auth.private_parent(directory / "ipc.token", create=create)
    try:
        assert path == directory / "ipc.token"
    finally:
        os.close(fd)
    assert stat.S_IMODE(shared.stat().st_mode) == mode
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


@pytest.mark.parametrize("component", ["odin-desktop", "default"])
@pytest.mark.parametrize("owner", ["foreign", "root"])
def test_private_parent_checks_namespace_owner_without_repairing_other_owners(
    tmp_path, monkeypatch, component, owner
):
    directory = tmp_path / "odin-desktop" / "default"
    directory.mkdir(parents=True)
    directory.parent.chmod(0o700)
    foreign = directory.parent if component == "odin-desktop" else directory
    foreign.chmod(0o775)
    inode = foreign.stat().st_ino
    original = os.fstat

    def foreign_owner(fd):
        info = original(fd)
        if info.st_ino == inode:
            values = list(info)
            values[4] = 0 if owner == "root" else os.geteuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", foreign_owner)
    if owner == "foreign":
        with pytest.raises(PermissionError, match="foreign"):
            ipc_auth.private_parent(directory / "ipc.token")
    else:
        _, fd = ipc_auth.private_parent(directory / "ipc.token")
        os.close(fd)
    assert stat.S_IMODE(foreign.stat().st_mode) == 0o775


@pytest.mark.parametrize("location", ["ancestor", "leaf"])
@pytest.mark.parametrize("owner", ["foreign", "root"])
def test_private_parent_checks_unrelated_owners_without_chmod(
    tmp_path, monkeypatch, location, owner
):
    directory = tmp_path / "shared" / "runtime"
    directory.mkdir(parents=True)
    foreign = directory.parent if location == "ancestor" else directory
    foreign.chmod(0o775)
    inode = foreign.stat().st_ino
    original = os.fstat

    def foreign_owner(fd):
        info = original(fd)
        if info.st_ino == inode:
            values = list(info)
            values[4] = 0 if owner == "root" else os.geteuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", foreign_owner)
    if owner == "foreign":
        with pytest.raises(PermissionError, match="foreign") as refusal:
            ipc_auth.private_parent(directory / "ipc.token")
        assert refusal.value.filename == str(foreign)
    else:
        _, fd = ipc_auth.private_parent(directory / "ipc.token")
        os.close(fd)
    assert stat.S_IMODE(foreign.stat().st_mode) == 0o775


@pytest.mark.parametrize("component", ["odin-desktop", "default"])
def test_private_parent_follows_namespace_link_without_chmod_of_unrelated_target(
    tmp_path, component
):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    outside.chmod(0o775)
    directory = tmp_path / "odin-desktop" / "default"
    link = directory.parent if component == "odin-desktop" else directory
    link.parent.mkdir(exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    directory.mkdir(exist_ok=True)
    path, fd = ipc_auth.private_parent(directory / "ipc.token")
    try:
        assert path == directory.resolve() / "ipc.token"
        assert os.fstat(fd).st_ino == directory.stat().st_ino
    finally:
        os.close(fd)
    assert stat.S_IMODE(outside.stat().st_mode) == 0o775


@pytest.mark.parametrize("create", [False, True])
@pytest.mark.parametrize("owner", ["foreign", "root"])
def test_private_parent_symlink_checks_target_owner(tmp_path, monkeypatch, create, owner):
    target = tmp_path / "disk"
    target.mkdir()
    target.chmod(0o775)
    link = tmp_path / "linked"
    link.symlink_to(target, target_is_directory=True)
    inode = target.stat().st_ino
    original = os.fstat

    def target_owner(fd):
        info = original(fd)
        if info.st_ino == inode:
            values = list(info)
            values[4] = 0 if owner == "root" else os.geteuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", target_owner)
    if owner == "foreign":
        with pytest.raises(PermissionError, match="foreign") as refusal:
            ipc_auth.private_parent(link / "ipc.token", create=create)
        assert refusal.value.filename == str(target)
    else:
        path, fd = ipc_auth.private_parent(link / "ipc.token", create=create)
        try:
            assert path == target / "ipc.token"
            assert os.fstat(fd).st_ino == inode
        finally:
            os.close(fd)
    assert stat.S_IMODE(target.stat().st_mode) == 0o775
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("create", [False, True])
def test_private_parent_still_refuses_nondirectory_after_link_resolution(tmp_path, create):
    target = tmp_path / "not-a-directory"
    target.write_text("unchanged")
    link = tmp_path / "linked"
    link.symlink_to(target)
    with pytest.raises(NotADirectoryError) as refusal:
        ipc_auth.private_parent(link / "ipc.token", create=create)
    assert refusal.value.filename == str(target)
    assert target.read_text() == "unchanged"


@pytest.mark.parametrize("kind", ["missing", "unsafe", "invalid"])
def test_token_refusals_report_path_never_credential(tmp_path, kind):
    token = tmp_path / "ipc.token"
    if kind != "missing":
        token.write_text("not-a-credential".ljust(64, "z"))
        token.chmod(0o644 if kind == "unsafe" else 0o600)
    with pytest.raises(OSError) as refusal:
        ipc_auth.load_token(token)
    assert refusal.value.filename == str(token)
    assert "not-a-credential" not in str(refusal.value)
    if kind == "missing":
        assert isinstance(refusal.value, FileNotFoundError)
    else:
        assert isinstance(refusal.value, PermissionError)


@pytest.mark.asyncio
async def test_close_listener_preserves_subscribers_until_shutdown():
    async with fixture_server() as (server, token_file, _, _):
        client = await LocalClient.connect(server.socket_path, token_file)
        connection = next(iter(server.connections))
        connection.subscribed = True
        await asyncio.wait_for(server.close_listener(), 0.5)
        event = {"t": "evt", "seq": 1, "cursor": "1", "type": "runtime.status",
                 "payload": {"phase": "quiescing"}}
        await server.publish(event)
        assert await client.read() == event
        await server.shutdown()
        assert await client.read() == {"t": "bye", "reason": "shutdown"}
        await client.close()


@pytest.mark.asyncio
async def test_idle_subscriber_revocation_prevents_unsolicited_event(monkeypatch):
    async with fixture_server() as (server, token_file, authority, _):
        client = await LocalClient.connect(server.socket_path, token_file)
        connection = next(iter(server.connections))
        connection.subscribed = True
        monkeypatch.setattr(authority, "accepts", lambda _context: False)
        await server.publish({"t": "evt", "seq": 1, "cursor": "1", "payload": {}})
        assert await client.read() == {"t": "bye", "reason": "unauthorized"}
        assert await client.reader.read() == b""
        assert connection.event_seq == 0
        await client.close()
