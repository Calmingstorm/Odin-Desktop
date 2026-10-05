"""OS-backed peer identity and no-follow app-created credentials."""
from __future__ import annotations

import hmac
import os
import re
import socket
import stat
import struct
from pathlib import Path

from .paths import private_directory


def private_parent(path: Path | str, *, create: bool = False) -> tuple[Path, int]:
    """Return a held descriptor, rejecting links and non-private terminal parents."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in str(path)):
        raise ValueError("IPC path must be absolute")
    if create:
        private_directory(path.parent)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in path.parent.parts[1:]:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            mode = stat.S_IMODE(info.st_mode)
            if info.st_uid not in {0, os.geteuid()}:
                raise PermissionError("foreign IPC ancestor")
            if mode & 0o022 and not info.st_mode & stat.S_ISVTX:
                raise PermissionError("IPC ancestor writable by others")
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise PermissionError("IPC parent must be owner-private (0700)")
        return path, fd
    except BaseException:
        os.close(fd)
        raise


def load_token(token_file: Path | str) -> str:
    path, parent = private_parent(token_file)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != 64):
                raise PermissionError("unsafe IPC credential file")
            data = os.read(fd, 65)
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    if not re.fullmatch(rb"[0-9a-fA-F]{64}", data):
        raise PermissionError("invalid IPC credential")
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
