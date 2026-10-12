"""Windows: the whole-file locks, as ``LockFileEx`` on one byte far past the data.

Windows byte-range locks are mandatory, so the locked byte sits beyond anything
the file holds and never blocks its reads or writes. A non-blocking miss raises
``BlockingIOError``, as ``flock`` does, so callers handle both the same way.
"""
from __future__ import annotations

import msvcrt

from . import win32


def _handle(fd):
    return msvcrt.get_osfhandle(fd.fileno() if hasattr(fd, "fileno") else fd)


def lock_exclusive(fd, *, blocking: bool = True) -> None:
    win32.lock(_handle(fd), blocking=blocking)


def unlock(fd) -> None:
    win32.unlock(_handle(fd))
