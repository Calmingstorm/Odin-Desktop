"""Whole-file advisory locks for profile and runtime files.

On POSIX these are the ``fcntl.flock`` calls the callers made directly before
this seam. ``fcntl.flock`` is looked up at call time, so a test that replaces it
still reaches every caller. Windows routes both calls to ``windows_locks``.
"""
from __future__ import annotations

from .variants import windows_variant

try:
    import fcntl
except ImportError:  # pragma: no cover - no fcntl on this system
    fcntl = None


def _require_fcntl():
    if fcntl is None:
        raise NotImplementedError("file locks are not available on this system yet")
    return fcntl


@windows_variant("src.desktop.platform.windows_locks:lock_exclusive")
def lock_exclusive(fd, *, blocking: bool = True) -> None:
    """Hold an exclusive lock on ``fd``, a descriptor or a file object.

    Non-blocking acquisition raises ``BlockingIOError`` while another holder has it.
    """
    module = _require_fcntl()
    module.flock(fd, module.LOCK_EX if blocking else module.LOCK_EX | module.LOCK_NB)


@windows_variant("src.desktop.platform.windows_locks:unlock")
def unlock(fd) -> None:
    module = _require_fcntl()
    module.flock(fd, module.LOCK_UN)
