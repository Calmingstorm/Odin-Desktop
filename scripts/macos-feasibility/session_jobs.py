"""Prototype session-per-job supervisor for the macOS feasibility spike (phase 1).

Evidence harness only: phase 2 re-implements what this proves under src/ with the full gates.

Each job's first process starts a new session, so the session ID, the leader's group ID and the
leader's PID are the same number. The leader stays our unreaped child until release(): while it
exists (even as a zombie) that number cannot be reused, so signalling the leader's group can never
reach an unrelated process. Members that moved to another group inside the session are signalled
only after re-checking a live member's identity (PID plus start time); a changed identity is
refused, never signalled. A process that detaches into a session of its own is outside the scope,
which is why a settled result carries the caveat Odin already uses for remote cleanup.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from darwin_proc import Identity, ObservationError, ProcessFact, process_fact, scan, session_members

CAVEAT = "escaped descendants are unverified"


@dataclass
class StopResult:
    outcome: (
        str  # "settled": the session was verified empty twice in a row; "unknown": anything else
    )
    caveat: str | None
    rounds: int
    escalated: bool
    survivors: list[ProcessFact] = field(default_factory=list)
    refused: list[Identity] = field(default_factory=list)
    detail: str = ""


class SessionJob:
    def __init__(self, argv: list[str], **popen):
        self.process = subprocess.Popen(argv, start_new_session=True, close_fds=True, **popen)
        self.sid = self.process.pid
        self.released = False

    def leader_exited(self) -> bool:
        """Whether the leader exited, observed without reaping it (WNOWAIT keeps the IDs pinned)."""
        return os.waitid(os.P_PID, self.sid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None

    def members(
        self, scanner: Callable[[], dict[int, ProcessFact]] = scan
    ) -> dict[int, ProcessFact]:
        return session_members(self.sid, scanner())

    def stop(
        self,
        term_grace: float = 2.0,
        deadline: float = 10.0,
        poll: float = 0.05,
        scanner: Callable[[], dict[int, ProcessFact]] = scan,
    ) -> StopResult:
        """SIGTERM each group in the session, then SIGKILL, until two empty scans or a deadline."""
        if self.released:
            raise RuntimeError("the job was released; its identifiers are no longer pinned")
        started = time.monotonic()
        rounds = 0
        empty_scans = 0
        escalated = False
        refused: list[Identity] = []
        while True:
            rounds += 1
            try:
                members = session_members(self.sid, scanner())
            except ObservationError as error:
                return StopResult(
                    "unknown",
                    None,
                    rounds,
                    escalated,
                    refused=refused,
                    detail=f"observation failed: {error}",
                )
            live = {pid: fact for pid, fact in members.items() if not fact.zombie}
            if not live:
                empty_scans += 1
                if empty_scans >= 2:
                    return StopResult("settled", CAVEAT, rounds, escalated, refused=refused)
                time.sleep(poll)
                continue
            empty_scans = 0
            elapsed = time.monotonic() - started
            if elapsed >= deadline:
                return StopResult(
                    "unknown",
                    None,
                    rounds,
                    escalated,
                    survivors=list(live.values()),
                    refused=refused,
                    detail="session members remained at the deadline",
                )
            escalated = escalated or elapsed >= term_grace
            sent = signal.SIGKILL if escalated else signal.SIGTERM
            for pgid in sorted({fact.pgid for fact in live.values()}):
                self.signal_group(pgid, live, sent, refused)
            time.sleep(poll)

    def signal_group(
        self, pgid: int, live: dict[int, ProcessFact], sent: int, refused: list[Identity]
    ) -> bool:
        """Signal one process group of the session; True when a signal was sent."""
        if pgid == self.sid:
            return _killpg(pgid, sent)
        for fact in sorted(
            (f for f in live.values() if f.pgid == pgid), key=lambda f: f.identity.pid
        ):
            current = process_fact(fact.identity.pid)
            if current is None:
                continue
            if current.identity != fact.identity or current.sid != self.sid or current.pgid != pgid:
                refused.append(fact.identity)
                continue
            # A verified live member proves the group still exists and is ours.
            return _killpg(pgid, sent)
        return False

    def release(self, timeout: float = 5.0) -> int:
        """Reap the leader, giving up the pinned IDs. Only after the job settled or finished."""
        code = self.process.wait(timeout=timeout)
        self.released = True
        return code


def _killpg(pgid: int, sent: int) -> bool:
    try:
        os.killpg(pgid, sent)
    except ProcessLookupError:
        return False
    return True
