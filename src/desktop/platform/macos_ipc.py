"""macOS app ↔ engine transport: an owner-only Unix socket.

Linux binds and connects through /proc/self/fd/<parent>, so a parent link cannot be swapped during
startup. macOS has no procfs, so the socket is bound and connected by its canonical path, while the
parent stays held open after ipc_auth.private_parent verified it: every ancestor is root's or this
user's, and the odin-desktop/<profile> folders are 0700. Only this user or root could swap a
component in between, which is outside the same-user boundary Linux keeps too. After bind, and again
after connect, the entry at the path must be the same inode as the entry in the held parent.
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
from . import darwin
from .macos import SOCKET_PATH_LIMIT


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


class MacOSSocketEndpoint:
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
            if len(os.fsencode(path)) > SOCKET_PATH_LIMIT:
                raise ValueError("IPC socket path too long")
            await self._remove_stale_socket(path)
            sock.bind(os.fspath(path))
            held = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            self._socket_identity = _identity(held)
            named = os.stat(path, follow_symlinks=False)
            if not stat.S_ISSOCK(held.st_mode) or _identity(named) != self._socket_identity:
                raise PermissionError("IPC socket was not created in the verified folder")
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

    async def _remove_stale_socket(self, path: Path) -> None:
        try:
            info = os.stat(path.name, dir_fd=self._parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
            raise PermissionError("existing IPC path is not an owned socket")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.setblocking(False)
        try:
            try:
                await asyncio.wait_for(
                    asyncio.get_running_loop().sock_connect(probe, os.fspath(path)), 1.0
                )
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
        current = os.stat(path.name, dir_fd=self._parent_fd, follow_symlinks=False)
        if _identity(current) != _identity(info):
            raise RuntimeError("IPC socket changed during probe")
        os.unlink(path.name, dir_fd=self._parent_fd)

    def _unlink_owned_socket(self) -> None:
        if self._parent_fd is None or self._socket_identity is None:
            return
        try:
            info = os.stat(self.socket_path.name, dir_fd=self._parent_fd, follow_symlinks=False)
            if stat.S_ISSOCK(info.st_mode) and _identity(info) == self._socket_identity:
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


class MacOSIpc:
    """The transport's OS pieces on macOS."""

    load_token = staticmethod(ipc_auth.load_token)
    endpoint = MacOSSocketEndpoint

    @staticmethod
    def peer(writer) -> int:
        """The kernel's answer (getpeereid); never a client-provided UID."""
        return darwin.peer_uid(writer.get_extra_info("socket"))

    @property
    def owner(self) -> int:
        return os.geteuid()

    @staticmethod
    async def connect(socket_path: Path | str):
        path, parent = ipc_auth.private_parent(socket_path)
        try:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISSOCK(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise PermissionError("unsafe IPC socket")
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(os.fspath(path)), HANDSHAKE_TIMEOUT
            )
            try:
                named = os.stat(path, follow_symlinks=False)
            except OSError:
                named = None
            if named is None or _identity(named) != _identity(info):
                writer.close()
                raise PermissionError("IPC socket changed while connecting")
            return reader, writer
        finally:
            os.close(parent)
