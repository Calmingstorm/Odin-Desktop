"""macOS variants of the core's process boundary (src/__main__.py and the teardown drain).

macOS has no child subreaper and no pidfd. Containment is the session-scoped, best-effort
contract Aaron approved on 2026-10-13: background work runs in its own session, and Stop and Quit
stop what can be observed there (the process supervision itself arrives in phase 3). Nothing is
adopted, so the final drain has only this process's own exited children to reap; it reports
that no exited child is left, never that no child or session member is alive.

The finalize watchdog's helper kills through the engine's PID version, so a reused PID never
receives it. That call (proc_signal_with_audittoken) is private but exported libproc API: the
helper preflights it on itself before acknowledging, and when it is missing or misbehaves the arm
fails, so finalization exits at once with its code. There is no fallback to a numeric PID.
"""

from __future__ import annotations

import errno
import importlib
import os
import select
import sys

from src.tools.process_manager import AdoptedZombieReaper

_FINALIZE_WATCHDOG_PROGRAM = r"""
import ctypes
import errno
import os
import select
import signal
import sys

class _AuditToken(ctypes.Structure):
    _fields_ = [("val", ctypes.c_uint32 * 8)]

class _UniqInfo(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8 * 16), ("uniqueid", ctypes.c_uint64),
                ("puniqueid", ctypes.c_uint64), ("idversion", ctypes.c_int32),
                ("orig_ppidversion", ctypes.c_int32), ("reserve3", ctypes.c_uint64),
                ("reserve4", ctypes.c_uint64)]

def token(pid, version):
    value = _AuditToken()
    value.val[5] = pid
    value.val[7] = version & 0xFFFFFFFF
    return value

control_fd = int(sys.argv[1])
ready_fd = int(sys.argv[2])
parent = token(int(sys.argv[3]), int(sys.argv[4]))
deadline = float(sys.argv[5])
try:
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    send = libc.proc_signal_with_audittoken
    send.argtypes = [ctypes.POINTER(_AuditToken), ctypes.c_int]
    send.restype = ctypes.c_int
    libc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p,
                                  ctypes.c_int]
    libc.proc_pidinfo.restype = ctypes.c_int
    info = _UniqInfo()
    if ctypes.sizeof(info) != 56 or libc.proc_pidinfo(os.getpid(), 17, 0, ctypes.byref(info),
                                                      56) != 56:
        raise OSError("no identity")
    # Preflight on this helper itself, with a signal that is discarded by default: the token
    # reaches the current incarnation and refuses a stale one. Only then is the guard acknowledged.
    me, stale = token(os.getpid(), info.idversion), token(os.getpid(), info.idversion + 1)
    if send(ctypes.byref(me), signal.SIGURG) != 0:
        raise OSError("the identity signal is unavailable")
    if send(ctypes.byref(stale), signal.SIGURG) != errno.ESRCH:
        raise OSError("the identity signal is not conditioned on the incarnation")
    os.write(ready_fd, b"R")
    os.close(ready_fd)
    readable, _, _ = select.select([control_fd], [], [], deadline)
    if not readable:
        send(ctypes.byref(parent), signal.SIGKILL)  # exactly that engine, or ESRCH if it is gone
finally:
    os._exit(0)
"""


def _entry_module():
    """The running ``src.__main__``: under ``python -m src`` it is ``__main__``, not a copy."""
    running = sys.modules.get("__main__")
    spec = getattr(running, "__spec__", None)
    if spec is not None and spec.name == "src.__main__":
        return running
    return importlib.import_module("src.__main__")


def enable_process_containment(log) -> bool:
    """macOS has no child subreaper: containment is session-scoped, best effort (phase 3)."""
    import secrets

    from src.tools.process_manager import DEFAULT_JOB_TOKEN, JOB_TOKEN_ENV, PROC_TOKEN_ENV

    os.environ.setdefault(PROC_TOKEN_ENV, secrets.token_hex(8))
    os.environ.setdefault(JOB_TOKEN_ENV, DEFAULT_JOB_TOKEN)
    log.info("macOS process containment: session-scoped, best effort (no child subreaper)")
    return True


def arm_finalize_watchdog(exit_code: int):
    """The Linux watchdog's contract, with the engine named by PID and PID version.

    The helper is spawned and acknowledges before this returns; any arm failure exits at once, so
    finalization never starts unguarded.
    """
    from .darwin import process_identity

    entry = _entry_module()

    code = exit_code or 1
    hard_exit = os._exit
    pipe, close, read, write = os.pipe, os.close, os.read, os.write
    waitpid, set_inheritable, spawn = os.waitpid, os.set_inheritable, os.posix_spawn
    select_ready = select.select
    control_r = control_w = ready_r = ready_w = -1
    try:
        identity = process_identity(os.getpid())
        if identity is None:
            raise OSError(errno.ESRCH, "the engine's own identity is unreadable")
        control_r, control_w = pipe()
        ready_r, ready_w = pipe()
        for fd in (control_r, ready_w):
            set_inheritable(fd, True)
        argv = (
            sys.executable,
            "-I",
            "-S",
            "-c",
            _FINALIZE_WATCHDOG_PROGRAM,
            str(control_r),
            str(ready_w),
            str(identity.pid),
            str(identity.idversion),
            str(entry._FINALIZE_WATCHDOG_TIMEOUT),
        )
        pid = spawn(sys.executable, argv, os.environ)
        for fd in (control_r, ready_w):
            close(fd)
        control_r = ready_w = -1
        readable, _, _ = select_ready([ready_r], [], [], 2.0)
        if not readable or read(ready_r, 1) != b"R":
            hard_exit(code)
            raise AssertionError("os._exit returned")  # test doubles only
        close(ready_r)
        ready_r = -1
        return entry._FinalizeWatchdog(
            control_fd=control_w,
            pid=pid,
            hard_exit=hard_exit,
            write=write,
            close=close,
            waitpid=waitpid,
        )
    except BaseException:  # noqa: BLE001 - no unguarded finalize is allowed
        for fd in (control_r, control_w, ready_r, ready_w):
            if fd >= 0:
                try:
                    close(fd)
                except BaseException:
                    pass
        hard_exit(code)
        raise AssertionError("os._exit returned")  # test doubles only


class MacOSZombieReaper(AdoptedZombieReaper):
    """Odin's reaper, unchanged but for its final drain: nothing is adopted on macOS."""

    def drain_at_teardown(self) -> tuple[int, bool]:
        """Reap this process's own exited children.

        It runs after every subprocess owner has stopped, so an exited child left now is ours
        to reap. Verified means waitpid reported no further exited child (none left, or only
        live ones); any other failure is unverified.
        """
        reaped = 0
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return reaped, True
            except OSError:
                return reaped, False
            if pid == 0:
                return reaped, True
            reaped += 1
            self.reaped_total += 1


def zombie_reaper() -> MacOSZombieReaper:
    """src.__main__._zombie_reaper on macOS."""
    return MacOSZombieReaper()
