"""Private atomic publication for profile policy, state and credentials."""
from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

from ..odin_log import get_logger

log = get_logger("permissions.persistence")


def write_private_atomic(path: Path, content: str) -> bool:
    """Publish a complete 0600 file; return whether directory durability is proven.

    Every pre-replace failure leaves the previous file intact and raises. Once
    replace succeeds the candidate is committed: a directory-fsync failure is
    explicitly degraded, not a rejected mutation or a fictitious rollback.
    """
    from ..desktop.paths import private_directory
    private_directory(path.parent)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary: str | None = None
    try:
        try:
            owner = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            owner = None
        if owner is not None and (
            not stat.S_ISREG(owner.st_mode) or owner.st_uid != os.geteuid()
        ):
            raise PermissionError("private state must be a regular owner-owned file")
        temporary = f".{path.name}.{secrets.token_hex(16)}.tmp"
        fd = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        try:
            if owner is not None:
                current = os.fstat(fd)
                if (current.st_uid, current.st_gid) != (owner.st_uid, owner.st_gid):
                    os.fchown(fd, owner.st_uid, owner.st_gid)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                fd = -1
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if fd >= 0:
                os.close(fd)
        os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        temporary = None
        try:
            os.fsync(directory)
        except OSError:
            log.error("Private state committed but directory fsync failed; durability degraded")
            return False
        return True
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
        os.close(directory)
