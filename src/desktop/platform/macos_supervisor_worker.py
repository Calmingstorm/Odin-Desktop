"""Stdlib-only macOS subprocess ownership worker: Linux's worker protocol, a session's scope.

Invoke in a new session with --control-fd FD --command COMMAND, exactly as Linux's
local_supervisor_worker; FD is a duplex socket, never stdin, and cwd, environment and stdio are
inherited. The frames and control operations are Linux's (started, exit, settled, error;
terminate, settled_ack), so Odin's SupervisedShell drives this worker unchanged.

The command's shell is this worker's child and starts a session of its own, so its session ID,
group ID and PID are one number. The worker keeps it unreaped (waitid with WNOWAIT) until
settlement, so that number stays pinned: a signal to the leader's group can only reach that group.
Every other member is signalled through its identity (proc_signal_with_audittoken), which refuses
a stale PID version.

Best effort, by the contract approved on 2026-10-13. macOS has no child subreaper and no pidfd,
and shows a session's members only as snapshots: getsid over libproc's process list, each member
read as one incarnation. Settled means the leader has exited and two consecutive rounds saw no
live member, no fork among watched members, no signallable member in the leader's group and every
other group seen empty. A member that detaches into a new session, or forks and exits between
rounds, can survive a settled result; the engine labels this cleanup best effort.

A normal leader exit keeps background members, as on Linux, until they exit or a stop is
requested. Losing the control channel requests a stop. Cleanup reports an error at ten seconds and
keeps trying: an uninterruptible process cannot have a bounded death.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import math
import os
import select
import selectors
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Never

_libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)

PROC_PIDT_SHORTBSDINFO = 13
PROC_PIDUNIQIDENTIFIERINFO = 17
SZOMB = 5
P_PID, WNOHANG, WEXITED, WNOWAIT = 1, 0x1, 0x4, 0x20
CLD_EXITED, CLD_KILLED, CLD_DUMPED = 1, 2, 3
IDLE_SCAN_SECONDS = 1.0
SETTLING_SCAN_SECONDS = 0.25
STOPPING_SCAN_SECONDS = 0.05


class _ShortInfo(ctypes.Structure):
    _fields_ = [
        ("pid", ctypes.c_uint32), ("ppid", ctypes.c_uint32), ("pgid", ctypes.c_uint32),
        ("status", ctypes.c_uint32), ("comm", ctypes.c_char * 16), ("flags", ctypes.c_uint32),
        ("uid", ctypes.c_uint32), ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32),
        ("rgid", ctypes.c_uint32), ("svuid", ctypes.c_uint32), ("svgid", ctypes.c_uint32),
        ("rfu", ctypes.c_uint32),
    ]


class _UniqInfo(ctypes.Structure):
    _fields_ = [
        ("uuid", ctypes.c_uint8 * 16), ("uniqueid", ctypes.c_uint64),
        ("puniqueid", ctypes.c_uint64), ("idversion", ctypes.c_int32),
        ("orig_ppidversion", ctypes.c_int32), ("reserve3", ctypes.c_uint64),
        ("reserve4", ctypes.c_uint64),
    ]


class _AuditToken(ctypes.Structure):
    _fields_ = [("val", ctypes.c_uint32 * 8)]


class _SigInfo(ctypes.Structure):
    _fields_ = [
        ("si_signo", ctypes.c_int), ("si_errno", ctypes.c_int), ("si_code", ctypes.c_int),
        ("si_pid", ctypes.c_int), ("si_uid", ctypes.c_uint32), ("si_status", ctypes.c_int),
        ("si_addr", ctypes.c_void_p), ("si_value", ctypes.c_void_p), ("si_band", ctypes.c_long),
        ("pad", ctypes.c_ulong * 7),
    ]


for _struct, _size in ((_ShortInfo, 64), (_UniqInfo, 56), (_AuditToken, 32), (_SigInfo, 104)):
    if ctypes.sizeof(_struct) != _size:
        raise ImportError(f"unexpected {_struct.__name__} layout")

_libc.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
_libc.proc_listallpids.restype = ctypes.c_int
_libc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p,
                               ctypes.c_int]
_libc.proc_pidinfo.restype = ctypes.c_int
_libc.waitid.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(_SigInfo), ctypes.c_int]
_libc.waitid.restype = ctypes.c_int
_signal_by_token = _libc.proc_signal_with_audittoken  # missing: import fails, nothing spawned
_signal_by_token.argtypes = [ctypes.POINTER(_AuditToken), ctypes.c_int]
_signal_by_token.restype = ctypes.c_int  # 0 or an errno value


class ObservationError(RuntimeError):
    """A scan could not be completed; the scope is unknown, never empty."""


@dataclass(frozen=True)
class Member:
    pid: int
    pgid: int
    zombie: bool
    identity: tuple[int, int] | None  # (pid, PID version); None: unreadable, never signalled


def list_pids() -> list[int]:
    for _ in range(5):
        estimate = _libc.proc_listallpids(None, 0)
        if estimate <= 0:
            raise ObservationError("process list sizing failed")
        capacity = estimate + 64
        buffer = (ctypes.c_int * capacity)()
        filled = _libc.proc_listallpids(buffer, ctypes.sizeof(buffer))
        if filled <= 0:
            raise ObservationError("process list failed")
        if filled < capacity:
            return [pid for pid in buffer[:filled] if pid > 0]
    raise ObservationError("the process list kept growing")


def session_of(pid: int) -> int | None:
    try:
        return os.getsid(pid)
    except ProcessLookupError:
        return None
    except PermissionError as error:
        raise ObservationError("a session lookup was refused") from error


def _pidinfo(pid: int, flavor: int, info: ctypes.Structure) -> int:
    ctypes.set_errno(0)
    if _libc.proc_pidinfo(pid, flavor, 0, ctypes.byref(info), ctypes.sizeof(info)) == \
            ctypes.sizeof(info):
        return 0
    return ctypes.get_errno() or errno.EIO


def _identity(pid: int) -> tuple[int, tuple[int, int] | None, int]:
    """(errno, (pid, PID version), unique ID): ESRCH means gone, EPERM unreadable."""
    uniq = _UniqInfo()
    error = _pidinfo(pid, PROC_PIDUNIQIDENTIFIERINFO, uniq)
    if error:
        return error, None, 0
    return 0, (pid, int(uniq.idversion)), int(uniq.uniqueid)


def observe_session(sid: int) -> dict[int, Member]:
    """Every member of session sid, each read before and after as one incarnation."""
    members = {}
    for pid in list_pids():
        if session_of(pid) != sid:
            continue
        for _ in range(3):
            before_error, before, before_unique = _identity(pid)
            session = session_of(pid)
            short = _ShortInfo()
            short_error = _pidinfo(pid, PROC_PIDT_SHORTBSDINFO, short)
            after_error, after, after_unique = _identity(pid)
            if errno.ESRCH in (before_error, short_error, after_error) or session is None:
                break  # gone
            if short_error or any(e and e != errno.EPERM for e in (before_error, after_error)):
                raise ObservationError("a member could not be read")
            if before is None and after is None:
                identity = None  # unreadable both times: kept, never signalled
            elif before is not None and (before, before_unique) == (after, after_unique):
                identity = after
            else:
                continue  # it changed between the reads: read it again
            if session == sid:
                members[pid] = Member(pid, int(short.pgid), short.status == SZOMB, identity)
            break
        else:
            raise ObservationError("a member kept changing while it was read")
    return members


def signal_identity(identity: tuple[int, int], number: int) -> int:
    token = _AuditToken()
    token.val[5] = identity[0]
    token.val[7] = identity[1] & 0xFFFFFFFF
    return int(_signal_by_token(ctypes.byref(token), number))


def group_probe(pgid: int) -> str:
    """Signal 0 to the group: "live", "no-signallable" (EPERM) or "empty" (ESRCH); not atomic."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return "empty"
    except PermissionError:
        return "no-signallable"
    return "live"


def exit_status(pid: int) -> int | None:
    """The child's status in Popen's form once it has exited, leaving it unreaped; else None."""
    info = _SigInfo()
    ctypes.set_errno(0)
    if _libc.waitid(P_PID, pid, ctypes.byref(info), WEXITED | WNOHANG | WNOWAIT) != 0:
        raise OSError(ctypes.get_errno() or errno.EIO, "waitid failed")
    if info.si_pid != pid:
        return None
    if info.si_code == CLD_EXITED:
        return int(info.si_status)
    if info.si_code in (CLD_KILLED, CLD_DUMPED):
        return -int(info.si_status)
    raise OSError(errno.EIO, "unexpected child status")


class Worker:
    def __init__(self, control: socket.socket) -> None:
        self.control = control
        control.setblocking(False)
        control.set_inheritable(False)
        self.selector = selectors.DefaultSelector()
        self.selector.register(control, selectors.EVENT_READ)
        self.queue = select.kqueue()
        self.selector.register(self.queue.fileno(), selectors.EVENT_READ)
        self.watched: set[int] = set()
        self.connected = True
        self.incoming = bytearray()
        self.outgoing = bytearray()
        self.leader: subprocess.Popen[bytes] | None = None
        self.sid = 0
        self.exit_reported = False
        self.groups: set[int] = set()
        self.termed: set[tuple[int, int]] = set()
        self.leader_group_termed = False
        self.quiet_rounds = 0
        self.observation_failures = 0
        self.next_scan = 0.0
        self.stop_at: float | None = None
        self.kill_at = 0.0
        self.timeout_reported = False
        self.failed = False
        self.signal_requested = False
        self.reported_errors: set[str] = set()
        self.settlement_published = False
        self.settlement_ack = False

    def emit(self, event: str, **values: object) -> None:
        if not self.connected:
            return
        data = (json.dumps({"event": event, **values}) + "\n").encode()
        if len(self.outgoing) + len(data) > 65536:
            self.disconnect()
            return
        self.outgoing.extend(data)

    def terminate(self, grace: float) -> None:
        now = time.monotonic()
        deadline = now + min(8.0, max(0.0, grace))
        if self.stop_at is None:
            self.stop_at = now
            self.kill_at = deadline
        else:
            self.kill_at = min(self.kill_at, deadline)
        self.next_scan = 0.0

    def error(self, category: str, exc: BaseException | None = None) -> None:
        # Never quote exception text, which can contain command/env/path secrets.
        label = category if exc is None else f"{category} ({type(exc).__name__})"
        self.failed = True
        if label not in self.reported_errors:
            self.reported_errors.add(label)
            self.emit("error", message=label)
        self.terminate(0.0)

    def disconnect(self) -> None:
        if self.connected:
            self.connected = False
            try:
                self.selector.unregister(self.control)
            except (OSError, KeyError, ValueError):
                pass
            self.control.close()
            self.outgoing.clear()
        self.terminate(0.5)

    def watch(self, pid: int) -> None:
        if pid in self.watched:
            return
        event = select.kevent(pid, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD,
                              fflags=select.KQ_NOTE_FORK | select.KQ_NOTE_EXIT)
        try:
            self.queue.control([event], 0)
        except (ProcessLookupError, PermissionError):
            return  # gone, or not ours to watch: it blocks settling while it is seen
        self.watched.add(pid)

    def drain_events(self) -> int:
        """Forks seen since the last drain; an exit wakes the next round at once."""
        forks = 0
        while events := self.queue.control(None, 64, 0):
            for event in events:
                if event.fflags & select.KQ_NOTE_FORK:
                    forks += 1
                if event.fflags & select.KQ_NOTE_EXIT:
                    self.watched.discard(event.ident)
                    self.next_scan = 0.0
        if forks:
            self.next_scan = 0.0
        return forks

    def io(self, timeout: float) -> None:
        try:
            if self.connected:
                events = selectors.EVENT_READ
                if self.outgoing:
                    events |= selectors.EVENT_WRITE
                self.selector.modify(self.control, events)
            for key, mask in self.selector.select(timeout):
                if key.fileobj != self.control:
                    self.next_scan = 0.0  # the kqueue: the next round drains it
                    continue
                if mask & selectors.EVENT_WRITE and self.outgoing:
                    try:
                        sent = self.control.send(self.outgoing)
                    except BlockingIOError:
                        sent = 0
                    if sent:
                        del self.outgoing[:sent]
                if mask & selectors.EVENT_READ:
                    try:
                        data = self.control.recv(16384)
                    except BlockingIOError:
                        continue
                    if not data:
                        self.disconnect()
                        return
                    self.incoming.extend(data)
                    if len(self.incoming) > 65536:
                        raise ValueError("oversized control frame")
                    while b"\n" in self.incoming:
                        line, _, rest = self.incoming.partition(b"\n")
                        self.incoming = bytearray(rest)
                        message = json.loads(line)
                        if (isinstance(message, dict) and message == {"op": "settled_ack"}
                                and self.settlement_published):
                            self.settlement_ack = True
                            continue
                        if not isinstance(message, dict) or message.get("op") != "terminate":
                            raise ValueError("unsupported control operation")
                        grace = message.get("grace", 1.0)
                        if isinstance(grace, bool) or not isinstance(grace, (int, float)):
                            raise ValueError("invalid grace")
                        grace = float(grace)
                        if not math.isfinite(grace) or grace < 0:
                            raise ValueError("invalid grace")
                        self.terminate(grace)
        except OSError:
            self.disconnect()
        except Exception as exc:
            self.error("invalid control message", exc)
            self.incoming.clear()

    def poll_leader(self) -> None:
        if self.leader is not None and not self.exit_reported:
            status = exit_status(self.sid)
            if status is not None:
                self.exit_reported = True
                self.emit("exit", returncode=status)
                self.io(0.0)

    def scan_interval(self) -> float:
        if self.stop_at is not None:
            return STOPPING_SCAN_SECONDS
        return SETTLING_SCAN_SECONDS if self.exit_reported else IDLE_SCAN_SECONDS

    def round(self) -> bool:
        """One observation of the session; True when it was quiet.

        On Stop the pinned leader group is signalled first, before anything that can fail to
        observe: it is the unreaped leader's own group, so reaching it needs no discovery, and an
        observation failure must not hold back the cleanup the worker can still do. Members found
        by observation are signalled after it, by identity; settling still needs quiet rounds.
        """
        if self.stop_at is not None:
            self.signal_leader_group()
        forks = self.drain_events()
        members = observe_session(self.sid)
        live = {pid: member for pid, member in members.items() if not member.zombie}
        for member in live.values():
            self.groups.add(member.pgid)
            self.watch(member.pid)
        forks += self.drain_events()
        groups = {pgid: group_probe(pgid) for pgid in sorted(self.groups)}
        self.groups -= {pgid for pgid, state in groups.items() if state == "empty"}
        self.groups.add(self.sid)
        if self.stop_at is not None:
            self.signal(live, groups)
        return (not live and not forks and groups.get(self.sid) != "live"
                and all(state == "empty" for pgid, state in groups.items() if pgid != self.sid))

    def signal_leader_group(self) -> None:
        """TERM the pinned leader group once, then KILL it each round from the kill deadline.

        The leader is never reaped before settlement, so its group can't be reused: a probe that
        fails to answer counts as live, and the group is signalled anyway. Neither ESRCH nor EPERM
        is an error here. EPERM, no member this worker may signal, is also macOS's answer for a
        group left with only zombies, as when its last live members end between the probe and the
        signal. A live member it truly can't signal is still observed, keeps the session from
        settling, and the ten-second limit reports it."""
        kill = time.monotonic() >= self.kill_at
        if not (kill or not self.leader_group_termed):
            return
        try:
            if group_probe(self.sid) != "live":
                return
        except (ObservationError, OSError):
            pass
        try:
            os.killpg(self.sid, signal.SIGKILL if kill else signal.SIGTERM)  # pinned, unreaped
        except (ProcessLookupError, PermissionError):
            pass
        self.leader_group_termed = True

    def signal(self, live: dict[int, Member], groups: dict[int, str]) -> None:
        kill = time.monotonic() >= self.kill_at
        number = signal.SIGKILL if kill else signal.SIGTERM
        for member in live.values():
            if member.pgid == self.sid:
                continue  # reached through the pinned group
            if member.identity is None:
                self.error("a member's identity is unreadable")
                continue
            if not kill and member.identity in self.termed:
                continue
            result = signal_identity(member.identity, number)
            if result and result != errno.ESRCH:
                self.error("descendant signal refused")
            self.termed.add(member.identity)
        if self.stop_at is not None and time.monotonic() - self.stop_at >= 10.0 \
                and not self.timeout_reported:
            self.timeout_reported = True
            self.error("cleanup exceeded ten seconds; retaining descendant ownership")

    def run(self, command: str, shell: str = "sh", executable: str = "/bin/sh") -> int:
        try:
            self.leader = subprocess.Popen(
                [executable, *(["--norc", "--noprofile"] if shell == "bash" else []),
                 "-c", command],
                start_new_session=True, close_fds=True,
            )
            self.sid = self.leader.pid
            self.groups.add(self.sid)
            self.watch(self.sid)
            self.emit("started", pid=self.sid)
        except Exception as exc:
            self.error("command setup failed", exc)
        finally:
            # Child owns independent references; worker copies delay pipe EOF.
            for fd in (0, 1, 2):
                try:
                    os.close(fd)
                except OSError:
                    pass
        if self.leader is None:
            while self.connected and self.outgoing:
                self.io(0.05)
            return 1
        while True:
            try:
                if self.signal_requested:
                    self.terminate(0.5)
                # Stop's escalation of the pinned leader group needs no observation, so it comes
                # first: an exit observation that keeps failing must not hold it back.
                if self.stop_at is not None:
                    self.signal_leader_group()
                self.poll_leader()
                if time.monotonic() >= self.next_scan:
                    try:
                        quiet = self.round()
                        self.observation_failures = 0
                    except (ObservationError, OSError):
                        quiet = False
                        self.observation_failures += 1
                        if self.observation_failures >= 10:
                            self.error("session observation failed")
                    self.quiet_rounds = self.quiet_rounds + 1 if quiet else 0
                    self.next_scan = time.monotonic() + self.scan_interval()
                    if quiet and self.quiet_rounds < 2:
                        self.next_scan = time.monotonic() + STOPPING_SCAN_SECONDS
                self.poll_leader()
                if self.exit_reported and self.quiet_rounds >= 2:
                    _, status = os.waitpid(self.sid, 0)  # settled: give up the pinned number
                    self.leader.returncode = os.waitstatus_to_exitcode(status)
                    self.emit("settled", clean=True)
                    self.settlement_published = True
                    end = time.monotonic() + 2.0
                    while (self.connected and not self.settlement_ack
                           and time.monotonic() < end):
                        self.io(0.02)
                    return 1 if self.failed else 0
                self.io(max(0.0, min(self.next_scan - time.monotonic(), 0.25)))
            except Exception as exc:
                self.error("worker iteration failed", exc)
                self.io(0.05)


class QuietParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise ValueError("invalid worker arguments")


def main() -> int:
    if sys.platform != "darwin":
        return 2
    parser = QuietParser(exit_on_error=False, add_help=False)
    parser.add_argument("--control-fd", required=True, type=int)
    parser.add_argument("--command", required=True)
    parser.add_argument("--shell", choices=("bash", "sh"), default="sh")
    parser.add_argument("--shell-executable", default="/bin/sh")
    try:
        args, extras = parser.parse_known_args()
        if extras or args.control_fd < 3:
            return 2
        worker = Worker(socket.socket(fileno=args.control_fd))
    except (Exception, SystemExit):
        return 2  # No subprocess spawned; no argument echo to standard streams.

    def request_cleanup(_signum: int, _frame: object) -> None:
        worker.signal_requested = True

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, request_cleanup)
    # An inherited SIG_IGN would auto-reap children and destroy the leader's status.
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    return worker.run(args.command, args.shell, args.shell_executable)


if __name__ == "__main__":
    raise SystemExit(main())
