"""Process-global relaunch intent and unresolved-teardown veto.

The desktop app owns relaunch in Phase 2. No in-process exec or independent
service resurrection is available here.
"""

from __future__ import annotations

from .odin_log import get_logger

log = get_logger("restart")
_requested: bool = False
_reexec_blocked: str | None = None


def request_restart() -> None:
    """Record a relaunch request without granting or performing it."""
    global _requested
    _requested = True


def restart_requested() -> bool:
    return _requested


def block_reexec(reason: str) -> None:
    """Veto relaunch when owned descendants or input teardown are unproven."""
    global _reexec_blocked
    _reexec_blocked = reason
    log.error("Relaunch vetoed: %s", reason)


def reexec_blocked() -> str | None:
    return _reexec_blocked


def reset() -> None:
    global _requested, _reexec_blocked
    _requested = False
    _reexec_blocked = None


def reexec() -> None:
    if _reexec_blocked:
        raise RuntimeError("Relaunch blocked by unproven teardown")
    raise RuntimeError("Desktop supervised relaunch is deferred to Phase 2")
