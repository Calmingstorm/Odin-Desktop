"""The macOS socket transport: bind, connect, peer, refusals and cleanup."""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import stat
import tempfile
from pathlib import Path

import pytest

from src.desktop.platform.macos_ipc import MacOSIpc


@pytest.fixture
def socket_path():
    # pytest's own folders are too long for a 103-byte socket path, so use a short private one.
    root = Path(os.path.realpath(tempfile.mkdtemp(prefix="odm-", dir="/tmp")))
    yield root / "odin-desktop" / "test" / "core.sock"
    shutil.rmtree(root, ignore_errors=True)


async def test_listen_connect_and_the_kernel_peer(socket_path):
    ipc = MacOSIpc()
    endpoint = ipc.endpoint(socket_path)
    peers = []

    async def accept(reader, writer):
        peers.append(ipc.peer(writer))
        writer.write(b"hi")
        await writer.drain()
        writer.close()

    server = await endpoint.listen(accept)
    try:
        info = os.stat(socket_path, follow_symlinks=False)
        assert stat.S_ISSOCK(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
        for folder in (socket_path.parent, socket_path.parent.parent):
            assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700
        reader, writer = await ipc.connect(socket_path)
        assert await reader.read(2) == b"hi"
        writer.close()
        await asyncio.sleep(0.05)
        assert peers == [os.geteuid()]
    finally:
        server.close()
        await server.wait_closed()
        endpoint.close()
    assert not socket_path.exists()


async def test_a_stale_socket_is_replaced(socket_path):
    socket_path.parent.mkdir(parents=True, mode=0o700)
    leftover = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    leftover.bind(os.fspath(socket_path))
    leftover.close()  # the file stays, with no listener behind it
    endpoint = MacOSIpc().endpoint(socket_path)
    server = await endpoint.listen(lambda reader, writer: writer.close())
    try:
        assert stat.S_ISSOCK(os.stat(socket_path).st_mode)
    finally:
        server.close()
        await server.wait_closed()
        endpoint.close()


async def test_a_live_listener_is_never_replaced(socket_path):
    first = MacOSIpc().endpoint(socket_path)
    server = await first.listen(lambda reader, writer: writer.close())
    try:
        with pytest.raises(RuntimeError, match="already active"):
            await MacOSIpc().endpoint(socket_path).listen(lambda reader, writer: writer.close())
        assert stat.S_ISSOCK(os.stat(socket_path).st_mode)  # the first one is untouched
    finally:
        server.close()
        await server.wait_closed()
        first.close()


async def test_an_overlong_path_is_refused(socket_path):
    long_path = socket_path.parent / ("x" * 120) / "core.sock"
    with pytest.raises((ValueError, OSError)):
        await MacOSIpc().endpoint(long_path).listen(lambda reader, writer: writer.close())


async def test_connect_refuses_what_is_not_an_owner_only_socket(socket_path):
    socket_path.parent.mkdir(parents=True, mode=0o700)
    socket_path.write_text("not a socket")
    with pytest.raises(PermissionError, match="unsafe IPC socket"):
        await MacOSIpc.connect(socket_path)
    socket_path.unlink()
    open_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    open_socket.bind(os.fspath(socket_path))
    open_socket.listen(1)
    try:
        os.chmod(socket_path, 0o644)
        with pytest.raises(PermissionError, match="unsafe IPC socket"):
            await MacOSIpc.connect(socket_path)
    finally:
        open_socket.close()
