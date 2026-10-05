"""OS-backed peer identity and no-follow app-created credentials."""
from __future__ import annotations

import errno
import hmac
import os
import re
import socket
import stat
import struct
from pathlib import Path

from .paths import _namespace_directories, _repair_namespace_directory, private_directory


def private_parent(path: Path | str, *, create: bool = False) -> tuple[Path, int]:
    """Hold a no-follow parent; accept existing modes and repair only our namespace."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in str(path)):
        raise ValueError("IPC path must be absolute")
    if create:
        private_directory(path.parent)
    namespace = _namespace_directories(path.parent)
    current = Path("/")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in path.parent.parts[1:]:
            current /= name
            try:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as exc:
                raise OSError(exc.errno, exc.strerror, str(current)) from None
            os.close(fd)
            fd = child
            _repair_namespace_directory(fd, current, namespace, kind="IPC")
            info = os.fstat(fd)
            if info.st_uid not in {0, os.geteuid()}:
                raise PermissionError(errno.EACCES, "foreign IPC ancestor", str(current))
        return path, fd
    except BaseException:
        os.close(fd)
        raise


def load_token(token_file: Path | str) -> str:
    path, parent = private_parent(token_file)
    try:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except OSError as exc:
            raise OSError(exc.errno, exc.strerror, str(path)) from None
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != 64):
                raise PermissionError(errno.EACCES, "unsafe IPC credential file", str(path))
            data = os.read(fd, 65)
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    if not re.fullmatch(rb"[0-9a-fA-F]{64}", data):
        raise PermissionError(errno.EACCES, "invalid IPC credential", str(path))
    return data.decode("ascii")


read_token = load_token


def token_matches(expected: str, supplied: str) -> bool:
    try:
        candidate = supplied.encode("utf-8")
    except UnicodeError:
        return False
    return hmac.compare_digest(expected.encode("ascii"), candidate)


def peer_uid(sock: socket.socket) -> int:
    """Never consume a client-provided UID."""
    data = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", data)
    return uid
