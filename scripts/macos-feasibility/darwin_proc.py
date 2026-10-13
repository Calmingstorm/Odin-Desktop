"""Darwin process facts for the macOS feasibility spike (phase 1).

Evidence harness only: phase 2 re-implements what this proves under src/ with the full gates.

Membership comes first and needs no special access: getsid(2) over libproc's PID list (Darwin has no
kernel session filter; sysctl KERN_PROC_SESSION fails with ENOENT on macOS 27). Group and parent
come from PROC_PIDT_SHORTBSDINFO, which also works for other users' processes. A process's identity
is its 64-bit unique ID plus its PID version (PROC_PIDUNIQIDENTIFIERINFO); the version changes on
exec. A member whose identity cannot be read stays a member with no identity, never a missing one.

Each member record is bracketed by the identity: read before and after the session and group, and
kept only when both reads name the same incarnation, so a reused PID cannot inherit an earlier
member's session.

Signals use the identity, not the number: proc_signal_with_audittoken signals only the process whose
PID version still matches, and returns ESRCH otherwise (qualified on macOS 26 and 27; a private
libproc interface, like proc_pidinfo, so its absence fails closed). group_probe sends signal 0 to a
group, which harms no one even if the number is now someone else's: "live" (a signallable member
was found), "no-signallable" (EPERM: members existed but none could be signalled, including an
exited unreaped one, another user's, or ones that exited during the probe) or "empty" (ESRCH).

Nothing here is atomic. The PID list is a snapshot inspected later, and XNU's group signal also
snapshots member PIDs and looks each up afterwards, so a process that forks and exits faster than
both can stay unobserved. Callers must not treat a quiet scan or probe as proof of emptiness.
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

PROC_PIDT_SHORTBSDINFO = 13
PROC_PIDUNIQIDENTIFIERINFO = 17
SZOMB = 5
CTL_KERN, KERN_PROC, KERN_PROC_PGRP = 1, 14, 2
KINFO_PROC_SIZE = 648  # sizeof(struct kinfo_proc) on 64-bit macOS; checked against every reply
P_PID_OFFSET = 40  # offsetof(struct kinfo_proc, kp_proc.p_pid)
P_PID, WNOHANG, WEXITED, WNOWAIT = 1, 0x1, 0x4, 0x20


class _ShortInfo(ctypes.Structure):
    _fields_ = [
        ("pid", ctypes.c_uint32),
        ("ppid", ctypes.c_uint32),
        ("pgid", ctypes.c_uint32),
        ("status", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16),
        ("flags", ctypes.c_uint32),
        ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32),
        ("ruid", ctypes.c_uint32),
        ("rgid", ctypes.c_uint32),
        ("svuid", ctypes.c_uint32),
        ("svgid", ctypes.c_uint32),
        ("rfu", ctypes.c_uint32),
    ]


class _UniqInfo(ctypes.Structure):
    _fields_ = [
        ("uuid", ctypes.c_uint8 * 16),
        ("uniqueid", ctypes.c_uint64),
        ("puniqueid", ctypes.c_uint64),
        ("idversion", ctypes.c_int32),
        ("orig_ppidversion", ctypes.c_int32),
        ("reserve3", ctypes.c_uint64),
        ("reserve4", ctypes.c_uint64),
    ]


class _AuditToken(ctypes.Structure):
    _fields_ = [("val", ctypes.c_uint32 * 8)]


class _SigInfo(ctypes.Structure):
    _fields_ = [
        ("si_signo", ctypes.c_int),
        ("si_errno", ctypes.c_int),
        ("si_code", ctypes.c_int),
        ("si_pid", ctypes.c_int),
        ("si_uid", ctypes.c_uint32),
        ("si_status", ctypes.c_int),
        ("si_addr", ctypes.c_void_p),
        ("si_value", ctypes.c_void_p),
        ("si_band", ctypes.c_long),
        ("pad", ctypes.c_ulong * 7),
    ]


for _struct, _size in ((_ShortInfo, 64), (_UniqInfo, 56), (_AuditToken, 32), (_SigInfo, 104)):
    if ctypes.sizeof(_struct) != _size:
        raise ImportError(f"unexpected {_struct.__name__} layout: {ctypes.sizeof(_struct)} bytes")

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
_libc.waitid.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(_SigInfo), ctypes.c_int]
_libc.waitid.restype = ctypes.c_int
try:
    _signal_by_token = _libc.proc_signal_with_audittoken
    _signal_by_token.argtypes = [ctypes.POINTER(_AuditToken), ctypes.c_int]
    _signal_by_token.restype = ctypes.c_int  # 0 or an errno value, not -1 with errno
except AttributeError:
    _signal_by_token = None


class ObservationError(RuntimeError):
    """A scan could not be completed; the scope is unknown, never empty."""


@dataclass(frozen=True)
class Identity:
    """One process incarnation: its unique ID, plus the PID version the kernel checks."""

    pid: int
    uniqueid: int
    idversion: int


@dataclass(frozen=True)
class Member:
    pid: int
    pgid: int
    ppid: int
    uid: int
    zombie: bool
    name: str
    identity: Identity | None  # None when the identity cannot be read: it cannot be signalled


def list_pids() -> list[int]:
    """Every PID libproc reports; ObservationError instead of a list known to be partial."""
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
        if filled < capacity:
            return [pid for pid in buffer[:filled] if pid > 0]
    raise ObservationError("the process table kept growing during the scan")


def session_of(pid: int) -> int | None:
    """The PID's session, or None when it no longer exists."""
    try:
        return os.getsid(pid)
    except ProcessLookupError:
        return None
    except PermissionError as error:
        raise ObservationError(f"getsid({pid}) was refused") from error


def _pidinfo(pid: int, flavor: int, info: ctypes.Structure) -> int:
    """0 when filled; otherwise the errno (ESRCH means the process is gone)."""
    ctypes.set_errno(0)
    size = _libc.proc_pidinfo(pid, flavor, 0, ctypes.byref(info), ctypes.sizeof(info))
    if size == ctypes.sizeof(info):
        return 0
    return ctypes.get_errno() or errno.EIO


def _identity_read(pid: int) -> tuple[int, Identity | None]:
    """(0, identity), or (errno, None): ESRCH means gone, EPERM unreadable."""
    uniq = _UniqInfo()
    error = _pidinfo(pid, PROC_PIDUNIQIDENTIFIERINFO, uniq)
    if error:
        return error, None
    return 0, Identity(pid, int(uniq.uniqueid), int(uniq.idversion))


def _bracketed(pid: int):
    """(session, short info, identity) read as one incarnation, None when gone, or raise."""
    for _ in range(3):
        before_error, before = _identity_read(pid)
        session = session_of(pid)
        short = _ShortInfo()
        short_error = _pidinfo(pid, PROC_PIDT_SHORTBSDINFO, short)
        after_error, after = _identity_read(pid)
        if errno.ESRCH in (before_error, short_error, after_error) or session is None:
            return None
        if short_error:
            raise ObservationError(f"short info for {pid} failed: {os.strerror(short_error)}")
        for error in (before_error, after_error):
            if error and error != errno.EPERM:
                raise ObservationError(f"identity of {pid} failed: {os.strerror(error)}")
        if before is None and after is None:
            return session, short, None  # unreadable both times: kept, never signalled
        if before is not None and before == after:
            return session, short, after
        # Exec or a new process at this PID changed the identity between the reads: read again.
    raise ObservationError(f"process {pid} kept changing while it was read")


def observe_session(sid: int) -> dict[int, Member]:
    """One pass over the PID list: every member of session sid, each read as one incarnation."""
    members = {}
    for pid in list_pids():
        if session_of(pid) != sid:
            continue  # a cheap filter; membership is decided by the bracketed read
        record = _bracketed(pid)
        if record is None:
            continue
        session, short, identity = record
        if session != sid:
            continue
        members[pid] = Member(
            pid=pid,
            pgid=int(short.pgid),
            ppid=int(short.ppid),
            uid=int(short.uid),
            zombie=short.status == SZOMB,
            name=short.comm.decode(errors="replace"),
            identity=identity,
        )
    return members


def identity_of(pid: int) -> Identity | None:
    uniq = _UniqInfo()
    if _pidinfo(pid, PROC_PIDUNIQIDENTIFIERINFO, uniq):
        return None
    return Identity(pid, int(uniq.uniqueid), int(uniq.idversion))


def signal_identity(identity: Identity, signal_number: int) -> int:
    """Signal exactly that incarnation; 0, or an errno (ESRCH: it is gone or has exec'd since)."""
    if _signal_by_token is None:
        return errno.ENOSYS
    token = _AuditToken()
    token.val[5] = identity.pid
    token.val[7] = identity.idversion & 0xFFFFFFFF
    return int(_signal_by_token(ctypes.byref(token), signal_number))


def group_probe(pgid: int) -> str:
    """Signal 0 to the group: "live", "no-signallable" (EPERM) or "empty" (ESRCH); not atomic."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return "empty"
    except PermissionError:
        return "no-signallable"
    return "live"


def exited_unreaped(pid: int) -> bool:
    """Whether our child exited, seen through waitid(WNOWAIT) so it stays unreaped.

    Called through libSystem because Python 3.12, the bundled runtime, has no os.waitid on macOS.
    """
    info = _SigInfo()
    ctypes.set_errno(0)
    if _libc.waitid(P_PID, pid, ctypes.byref(info), WEXITED | WNOHANG | WNOWAIT) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return info.si_pid == pid


class ForkWatch:
    """kqueue NOTE_FORK/NOTE_EXIT on observed processes: a fork means the scope may have grown."""

    def __init__(self):
        self._queue = select.kqueue()
        self._watched: set[int] = set()

    def add(self, pid: int) -> None:
        if pid in self._watched:
            return
        event = select.kevent(
            pid,
            filter=select.KQ_FILTER_PROC,
            flags=select.KQ_EV_ADD,
            fflags=select.KQ_NOTE_FORK | select.KQ_NOTE_EXIT,
        )
        try:
            self._queue.control([event], 0)
        except (ProcessLookupError, PermissionError):
            return  # gone, or another user's: such a member blocks settling while it is seen
        self._watched.add(pid)

    def drain_forks(self) -> int:
        """Fork events since the last drain; exited processes stop being watched."""
        forks = 0
        while events := self._queue.control(None, 64, 0):
            for event in events:
                if event.fflags & select.KQ_NOTE_FORK:
                    forks += 1
                if event.fflags & select.KQ_NOTE_EXIT:
                    self._watched.discard(event.ident)
        return forks

    def close(self) -> None:
        self._queue.close()


def sysctl_group_pids(pgid: int) -> set[int]:
    """The kernel's process-group filter, for cross-checking the getsid scan."""
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
            int.from_bytes(raw[i + P_PID_OFFSET : i + P_PID_OFFSET + 4], sys.byteorder, signed=True)
            for i in range(0, len(raw), KINFO_PROC_SIZE)
        }
    raise ObservationError("the group table kept growing")
