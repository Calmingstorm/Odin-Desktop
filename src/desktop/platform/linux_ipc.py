"""Linux app ↔ engine transport: an owner-only Unix socket.

This is IpcServer's and LocalClient's socket code, moved here unchanged; ipc.py
keeps the protocol (hello, token, welcome, requests, events, shutdown).
"""
from __future__ import annotations

import asyncio
import errno
import os
import socket
import stat
from pathlib import Path

from .. import ipc_auth
from ..protocol import HANDSHAKE_TIMEOUT


class UnixSocketEndpoint:
    """The engine's listener: a private parent folder, owner-only mode, stale-socket cleanup."""

    def __init__(self, socket_path: Path | str) -> None:
        self.socket_path = Path(socket_path)
        self._parent_fd = None
        self._socket_identity = None

    async def listen(self, accept) -> asyncio.AbstractServer:
        path, parent = ipc_auth.private_parent(self.socket_path, create=True)
        self._parent_fd = parent
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            if len(os.fsencode(path)) > 107:
                raise ValueError("IPC socket path too long")
            await self._remove_stale_socket()
            # Descriptor-relative bind prevents parent-link replacement during startup.
            sock.bind(f"/proc/self/fd/{parent}/{path.name}")
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            self._socket_identity = (info.st_dev, info.st_ino)
            os.chmod(path.name, 0o600, dir_fd=parent, follow_symlinks=False)
            sock.listen(socket.SOMAXCONN)
            sock.setblocking(False)
            return await asyncio.start_unix_server(accept, sock=sock)
        except BaseException:
            sock.close()
            self._unlink_owned_socket()
            os.close(parent)
            self._parent_fd = None
            raise

    async def _remove_stale_socket(self) -> None:
        try:
            info = os.stat(self.socket_path.name, dir_fd=self._parent_fd,
                           follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
            raise PermissionError("existing IPC path is not an owned socket")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.setblocking(False)
        try:
            try:
                await asyncio.wait_for(asyncio.get_running_loop().sock_connect(
                    probe, f"/proc/self/fd/{self._parent_fd}/{self.socket_path.name}"), 1.0)
            except OSError as error:
                if error.errno != errno.ECONNREFUSED:
                    raise RuntimeError("IPC listener state unproven") from None
            except TimeoutError:
                raise RuntimeError("IPC listener state unproven") from None
            else:
                # Any live listener is protected, without needing its protocol/token.
                raise RuntimeError("IPC listener already active")
        finally:
            probe.close()
        current = os.stat(self.socket_path.name, dir_fd=self._parent_fd,
                          follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise RuntimeError("IPC socket changed during probe")
        os.unlink(self.socket_path.name, dir_fd=self._parent_fd)

    def _unlink_owned_socket(self) -> None:
        if self._parent_fd is None or self._socket_identity is None:
            return
        try:
            info = os.stat(self.socket_path.name, dir_fd=self._parent_fd,
                           follow_symlinks=False)
            if stat.S_ISSOCK(info.st_mode) and (info.st_dev, info.st_ino) == self._socket_identity:
                os.unlink(self.socket_path.name, dir_fd=self._parent_fd)
        except FileNotFoundError:
            pass
        self._socket_identity = None

    def close(self) -> None:
        try:
            self._unlink_owned_socket()
        finally:
            if self._parent_fd is not None:
                os.close(self._parent_fd)
                self._parent_fd = None


class LinuxIpc:
    """The transport's OS pieces on Linux."""

    load_token = staticmethod(ipc_auth.load_token)
    endpoint = UnixSocketEndpoint

    @staticmethod
    def peer(writer) -> int:
        """Never consume a client-provided UID."""
        return ipc_auth.peer_uid(writer.get_extra_info("socket"))

    @property
    def owner(self) -> int:
        return os.geteuid()

    @staticmethod
    async def connect(socket_path: Path | str):
        path, parent = ipc_auth.private_parent(socket_path)
        try:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise PermissionError("unsafe IPC socket")
            return await asyncio.wait_for(asyncio.open_unix_connection(
                f"/proc/self/fd/{parent}/{path.name}"), HANDSHAKE_TIMEOUT)
        finally:
            os.close(parent)
