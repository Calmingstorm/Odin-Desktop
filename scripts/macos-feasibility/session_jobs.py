"""Prototype session-per-job supervisor for the macOS feasibility spike (phase 1).

Evidence harness only: phase 2 re-implements what this proves under src/ with the full gates.

Authority. Each job's first process (the leader) starts a new session, so the session ID, the
leader's group ID and its PID are one number. The job keeps the leader as its own unreaped child
until release(): while the leader exists (even exited) that number cannot be reused, so a signal to
the leader's group can only reach that group. Nothing else is signalled by number: each member
outside the leader's group is signalled through its identity (unique ID plus PID version), which
the kernel checks. After release() the job has no authority and refuses to observe or signal.

Settling. A scan of the PID list is not atomic, so it never proves the session empty on its own.
stop() settles only after two consecutive rounds in which no session member was observed, the
watched members reported no fork, the leader's group had no signallable member, and every other
group seen in the session was empty, each group checked with signal 0, which the kernel answers
atomically. Anything else, including a member whose identity cannot be read or a refused signal,
ends as unknown at the deadline, with the evidence kept in the result.

Limits. A process that detaches into a new session is outside the scope, which is why a settled
result carries the caveat Odin already uses for remote cleanup. A process that keeps moving to new
groups while forking and exiting faster than the scan can also stay unobserved; that is the same
"not verified" class.
"""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from darwin_proc import (
    ForkWatch,
    Identity,
    Member,
    ObservationError,
    exited_unreaped,
    group_probe,
    observe_session,
    signal_identity,
)

CAVEAT = "escaped descendants are unverified"


class AuthorityLostError(RuntimeError):
    """The leader was reaped, so the job's identifiers are no longer pinned."""


@dataclass
class StopResult:
    outcome: str  # "settled" or "unknown"
    caveat: str | None
    rounds: int
    escalated: bool
    survivors: list[Member] = field(default_factory=list)
    unresolved: dict[int, str] = field(default_factory=dict)
    groups: dict[int, str] = field(default_factory=dict)
    detail: str = ""


class SessionJob:
    def __init__(
        self,
        argv: list[str],
        *,
        observer: Callable[[int], dict[int, Member]] = observe_session,
        signaller: Callable[[Identity, int], int] = signal_identity,
        prober: Callable[[int], str] = group_probe,
        **popen,
    ):
        self._process = subprocess.Popen(argv, start_new_session=True, close_fds=True, **popen)
        self.sid = self._process.pid
        self._observer, self._signaller, self._prober = observer, signaller, prober
        self._lock = threading.Lock()
        self._retired = False
        self._last: StopResult | None = None
        self._groups: set[int] = {self.sid}
        self._watch = ForkWatch()
        self._watch.add(self.sid)

    @property
    def stdout(self):
        return self._process.stdout

    @property
    def retired(self) -> bool:
        return self._retired

    def leader_exited(self) -> bool:
        with self._lock:
            self._require_authority()
            return exited_unreaped(self.sid)

    def members(self) -> dict[int, Member]:
        with self._lock:
            self._require_authority()
            return self._observer(self.sid)

    def stop(
        self, term_grace: float = 2.0, deadline: float = 10.0, poll: float = 0.05
    ) -> StopResult:
        """SIGTERM, then SIGKILL after term_grace, until the session settles or the deadline."""
        with self._lock:
            self._require_authority()
            self._last = self._stop(term_grace, deadline, poll)
            return self._last

    def release(self, force: bool = False, timeout: float = 5.0) -> int:
        """Reap the leader and give up authority; without force, only after stop() settled."""
        with self._lock:
            self._require_authority()
            if not force and (self._last is None or self._last.outcome != "settled"):
                raise RuntimeError(
                    "the job has not settled; release(force=True) gives up its scope"
                )
            code = self._process.wait(timeout=timeout)
            self._retired = True
            self._watch.close()
            return code

    def _require_authority(self) -> None:
        if self._retired:
            raise AuthorityLostError(f"job {self.sid} was released; its identifiers are not pinned")

    def _stop(self, term_grace: float, deadline: float, poll: float) -> StopResult:
        started = time.monotonic()
        rounds = quiet_rounds = 0
        escalated = False
        unresolved: dict[int, str] = {}
        live: dict[int, Member] = {}
        groups: dict[int, str] = {}

        def unknown(detail: str) -> StopResult:
            return StopResult(
                "unknown",
                None,
                rounds,
                escalated,
                list(live.values()),
                dict(unresolved),
                groups,
                detail,
            )

        while True:
            elapsed = time.monotonic() - started
            if elapsed >= deadline:
                return unknown("the deadline passed before the session was confirmed empty")
            rounds += 1
            forks = self._watch.drain_forks()
            try:
                members = self._observer(self.sid)
            except ObservationError as error:
                return unknown(f"observation failed: {error}")
            live = {pid: member for pid, member in members.items() if not member.zombie}
            for member in live.values():
                self._groups.add(member.pgid)
                self._watch.add(member.pid)
            forks += self._watch.drain_forks()
            groups = {pgid: self._prober(pgid) for pgid in sorted(self._groups)}
            self._groups -= {pgid for pgid, state in groups.items() if state == "empty"}
            self._groups.add(self.sid)
            unresolved = {pid: why for pid, why in unresolved.items() if pid in live}
            if (
                not live
                and not forks
                and groups.get(self.sid) != "live"
                and all(state == "empty" for pgid, state in groups.items() if pgid != self.sid)
            ):
                quiet_rounds += 1
                if quiet_rounds >= 2:
                    return StopResult("settled", CAVEAT, rounds, escalated, groups=groups)
                time.sleep(poll)
                continue
            quiet_rounds = 0
            escalated = escalated or elapsed >= term_grace
            sent = signal.SIGKILL if escalated else signal.SIGTERM
            if groups.get(self.sid) == "live":
                self._signal_leader_group(sent)
            for member in live.values():
                if member.pgid == self.sid:
                    if groups.get(self.sid) != "live":
                        unresolved[member.pid] = "in the leader's group but not signallable"
                    continue
                if member.identity is None:
                    unresolved[member.pid] = (
                        "its identity cannot be read, so it cannot be signalled"
                    )
                    continue
                error = self._signaller(member.identity, sent)
                if error and error != errno.ESRCH:
                    unresolved[member.pid] = f"signal refused: {os.strerror(error)}"
            time.sleep(poll)

    def _signal_leader_group(self, sent: int) -> None:
        try:
            os.killpg(self.sid, sent)
        except (ProcessLookupError, PermissionError):
            pass  # empty, or only members we cannot signal: the next round's probe and scan decide
