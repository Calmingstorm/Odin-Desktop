"""Darwin process facts for the macOS feasibility spike (phase 1).

Evidence harness only: phase 2 re-implements what this proves under src/ with the full gates. It
reads processes through public interfaces: libproc's proc_listallpids and
proc_pidinfo(PROC_PIDTBSDINFO) and getsid(2). Darwin has no kernel session filter (sysctl
KERN_PROC_SESSION fails with ENOENT on macOS 27), so session membership is getsid over the full
process table, cross-checked against the kernel's process-group filter (KERN_PROC_PGRP).
proc_pidinfo does not report exited, unreaped processes. A scan that cannot complete raises
ObservationError; callers treat that scope as unknown, never as empty.
"""

from __future__ import annotations

import ctypes
import errno
import os
import select
import sys
from dataclasses import dataclass

if sys.platform != "darwin":
    raise ImportError("darwin_proc is macOS-only")

_libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)

PROC_PIDTBSDINFO = 3
MAXCOMLEN = 16
SZOMB = 5
CTL_KERN, KERN_PROC, KERN_PROC_PGRP = 1, 14, 2
KINFO_PROC_SIZE = (
    648  # sizeof(struct kinfo_proc) on 64-bit macOS; checked against every sysctl reply
)
P_PID_OFFSET = 40  # offsetof(struct kinfo_proc, kp_proc.p_pid)


class _BsdInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * MAXCOMLEN),
        ("pbi_name", ctypes.c_char * (2 * MAXCOMLEN)),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


if ctypes.sizeof(_BsdInfo) != 136:
    raise ImportError(f"unexpected proc_bsdinfo layout: {ctypes.sizeof(_BsdInfo)} bytes")

_libc.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
_libc.proc_listallpids.restype = ctypes.c_int
_libc.proc_pidinfo.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint64,
    ctypes.c_void_p,
    ctypes.c_int,
]
_libc.proc_pidinfo.restype = ctypes.c_int
_libc.sysctl.argtypes = [
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_uint,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_size_t),
    ctypes.c_void_p,
    ctypes.c_size_t,
]
_libc.sysctl.restype = ctypes.c_int


class ObservationError(RuntimeError):
    """A process scan could not be completed."""


@dataclass(frozen=True)
class Identity:
    """A PID pinned to one process incarnation by its start time."""

    pid: int
    start: tuple[int, int]


@dataclass(frozen=True)
class ProcessFact:
    identity: Identity
    ppid: int
    pgid: int
    sid: int
    zombie: bool
    name: str


def list_pids() -> list[int]:
    """Every PID on the system, or ObservationError; never a silently partial list."""
    for _ in range(5):
        ctypes.set_errno(0)
        estimate = _libc.proc_listallpids(None, 0)
        if estimate <= 0:
            raise ObservationError(f"proc_listallpids sizing failed: errno {ctypes.get_errno()}")
        capacity = estimate + 64
        buffer = (ctypes.c_int * capacity)()
        ctypes.set_errno(0)
        filled = _libc.proc_listallpids(buffer, ctypes.sizeof(buffer))
        if filled <= 0:
            raise ObservationError(f"proc_listallpids failed: errno {ctypes.get_errno()}")
        if (
            filled < capacity
        ):  # a full buffer may have been truncated, so only a short one is complete
            return [pid for pid in buffer[:filled] if pid > 0]
    raise ObservationError("the process table kept growing during the scan")


def process_fact(pid: int) -> ProcessFact | None:
    """Facts for one PID, or None when it is gone or belongs to someone we cannot inspect."""
    info = _BsdInfo()
    ctypes.set_errno(0)
    size = _libc.proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info))
    if size != ctypes.sizeof(info):
        error = ctypes.get_errno()
        if error in (0, errno.ESRCH, errno.EPERM):
            return None
        raise ObservationError(f"proc_pidinfo({pid}) failed: errno {error}")
    try:
        sid = os.getsid(pid)
    except (ProcessLookupError, PermissionError):
        return None
    return ProcessFact(
        identity=Identity(pid, (int(info.pbi_start_tvsec), int(info.pbi_start_tvusec))),
        ppid=int(info.pbi_ppid),
        pgid=int(info.pbi_pgid),
        sid=sid,
        zombie=info.pbi_status == SZOMB,
        name=info.pbi_comm.decode(errors="replace"),
    )


def scan() -> dict[int, ProcessFact]:
    """One full pass over the process table."""
    facts = {}
    for pid in list_pids():
        fact = process_fact(pid)
        if fact is not None:
            facts[pid] = fact
    return facts


def session_members(
    sid: int, facts: dict[int, ProcessFact] | None = None
) -> dict[int, ProcessFact]:
    """Processes whose session is sid, from one full scan (getsid over the whole table)."""
    facts = scan() if facts is None else facts
    return {pid: fact for pid, fact in facts.items() if fact.sid == sid}


def sysctl_group_pids(pgid: int) -> set[int]:
    """The kernel's own process-group filter, for cross-checking the getsid scan.

    Raises ObservationError when the call fails or the reply has an unexpected record size.
    """
    mib = (ctypes.c_int * 4)(CTL_KERN, KERN_PROC, KERN_PROC_PGRP, pgid)
    for _ in range(5):
        size = ctypes.c_size_t(0)
        ctypes.set_errno(0)
        if _libc.sysctl(mib, 4, None, ctypes.byref(size), None, 0) != 0:
            raise ObservationError(
                f"sysctl KERN_PROC_PGRP sizing failed: errno {ctypes.get_errno()}"
            )
        size = ctypes.c_size_t(size.value + 16 * KINFO_PROC_SIZE)
        buffer = ctypes.create_string_buffer(size.value)
        ctypes.set_errno(0)
        if _libc.sysctl(mib, 4, buffer, ctypes.byref(size), None, 0) != 0:
            if ctypes.get_errno() == errno.ENOMEM:
                continue
            raise ObservationError(f"sysctl KERN_PROC_PGRP failed: errno {ctypes.get_errno()}")
        if size.value % KINFO_PROC_SIZE:
            raise ObservationError(f"unexpected kinfo_proc reply size {size.value}")
        raw = buffer.raw[: size.value]
        return {
            int.from_bytes(
                raw[offset + P_PID_OFFSET : offset + P_PID_OFFSET + 4], sys.byteorder, signed=True
            )
            for offset in range(0, len(raw), KINFO_PROC_SIZE)
        }
    raise ObservationError("the group table kept growing")


def watch_exit(pid: int) -> select.kqueue:
    """A kqueue that fires once when pid exits (EVFILT_PROC/NOTE_EXIT); it never reaps."""
    queue = select.kqueue()
    event = select.kevent(
        pid,
        filter=select.KQ_FILTER_PROC,
        flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
        fflags=select.KQ_NOTE_EXIT,
    )
    queue.control([event], 0)
    return queue


def wait_exit(queue: select.kqueue, timeout: float) -> bool:
    """True when the watched process exited within timeout."""
    return bool(queue.control(None, 1, timeout))
