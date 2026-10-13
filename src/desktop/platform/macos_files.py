"""macOS variants for private folders and the IPC credential: Linux's checks, plus ACLs.

Owner and mode bits are not the whole answer on macOS: an extended ACL is evaluated before them,
and its allow entries can grant another user access. These variants run Linux's own checks, then
refuse any allow entry on the profile's own namespace folders (odin-desktop and
odin-desktop/<profile>, and folders beneath them), on the IPC parent and on the credential file.
Folders created there inherit their parent's inheritable entries, so a newly created one is checked
the same way. Deny entries only narrow access and are accepted.

Nothing here adds, removes or repairs an ACL, and folders that are not ours (the Library folders
above the namespace, the per-user temporary root, a configured folder elsewhere) are not inspected.
This user and root can still change an ACL afterwards; both are outside the boundary, as on Linux.
"""
from __future__ import annotations

import errno
import os
import re
import stat
from pathlib import Path

from . import darwin


def _refuse_grants(fd: int, path, what: str) -> None:
    if darwin.allow_entries(fd):
        raise PermissionError(errno.EACCES, f"{what} grants access through an ACL entry", str(path))


def _owned(path: Path, namespace) -> list[Path]:
    inside = any(path == root or root in path.parents for root in namespace)
    return sorted(namespace) + ([path] if inside and path not in namespace else [])


def private_directory(path: Path, *, repair_namespace: bool = True) -> None:
    """paths.private_directory, then no allow entry on the namespace folders it covers."""
    from .. import paths

    paths.private_directory.linux_original(path, repair_namespace=repair_namespace)
    real = Path(os.path.realpath(path))
    for directory in _owned(real, paths._namespace_directories(real)):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            _refuse_grants(fd, directory, "profile directory")
        finally:
            os.close(fd)


def private_parent(path: Path | str, *, create: bool = False) -> tuple[Path, int]:
    """ipc_auth.private_parent, then no allow entry on the held parent."""
    from .. import ipc_auth

    resolved, fd = ipc_auth.private_parent.linux_original(path, create=create)
    try:
        _refuse_grants(fd, resolved.parent, "IPC parent")
    except BaseException:
        os.close(fd)
        raise
    return resolved, fd


def load_token(token_file: Path | str) -> str:
    """ipc_auth.load_token with the credential file's ACL checked on the descriptor it reads."""
    from .. import ipc_auth

    path, parent = ipc_auth.private_parent(token_file)
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
            _refuse_grants(fd, path, "IPC credential file")
            data = os.read(fd, 65)
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    if not re.fullmatch(rb"[0-9a-fA-F]{64}", data):
        raise PermissionError(errno.EACCES, "invalid IPC credential", str(path))
    return data.decode("ascii")
