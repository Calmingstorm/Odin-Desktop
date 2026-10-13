"""Phase 1 feasibility: session-per-job cleanup on macOS.

Harmless stand-ins only: sleep, a shell running background sleeps, and small Python snippets that
fork, change their process group or detach into a new session, then sleep. Every stand-in ends on
its own within 30 seconds.

Run with: python -m pytest scripts/macos-feasibility/test_session_jobs.py
"""

from __future__ import annotations

import dataclasses
import os
import signal
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only evidence harness")

if sys.platform == "darwin":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import darwin_proc
    from session_jobs import CAVEAT, SessionJob

MOVE_GROUP = """
import os, time
if os.fork() == 0:
    os.setpgid(0, 0)
    time.sleep(30)
    os._exit(0)
time.sleep(30)
"""

DETACH = """
import os, sys, time
if os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        sys.stdout.write(f"{os.getpid()}\\n")
        sys.stdout.flush()
        time.sleep(20)
    os._exit(0)
time.sleep(30)
"""

FORKER = """
import os, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
end = time.monotonic() + 3
while time.monotonic() < end:
    if os.fork() == 0:
        time.sleep(30)
        os._exit(0)
    time.sleep(0.02)
time.sleep(30)
"""


def stand_in(code: str) -> list[str]:
    return [sys.executable, "-c", textwrap.dedent(code)]


def wait_for(predicate, timeout: float = 5.0, poll: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(poll)
    raise AssertionError("condition not reached in time")


def live_members(job) -> dict:
    return {pid: fact for pid, fact in job.members().items() if not fact.zombie}


def members_when(job, condition):
    def probe():
        members = live_members(job)
        return members if condition(members) else None

    return wait_for(probe)


def gone(fact) -> bool:
    current = darwin_proc.process_fact(fact.identity.pid)
    return current is None or current.identity != fact.identity or current.zombie


@pytest.fixture
def harness():
    jobs = []
    escaped = []

    def start(argv, **popen):
        job = SessionJob(argv, **popen)
        jobs.append(job)
        return job

    yield SimpleNamespace(start=start, escaped=escaped)
    for job in jobs:
        if not job.released:
            job.stop(term_grace=0.5, deadline=5)
            job.release()
    for identity in escaped:
        current = darwin_proc.process_fact(identity.pid)
        if (
            current is not None and current.identity == identity
        ):  # still our stand-in, so safe to signal
            os.kill(identity.pid, signal.SIGKILL)


def test_a_single_job_stops_and_its_session_settles(harness):
    job = harness.start(["/bin/sleep", "30"])
    wait_for(lambda: job.sid in live_members(job))
    result = job.stop()
    assert (result.outcome, result.caveat, result.escalated) == ("settled", CAVEAT, False)
    assert job.leader_exited()
    assert job.release() == -signal.SIGTERM


def test_background_children_are_stopped_with_the_job(harness):
    job = harness.start(["/bin/sh", "-c", "sleep 30 & sleep 30 & wait"])
    members = members_when(job, lambda m: len(m) == 3)
    assert job.stop().outcome == "settled"
    assert all(gone(fact) for fact in members.values())
    job.release()


def test_a_member_that_changes_group_inside_the_session_is_still_stopped(harness):
    job = harness.start(stand_in(MOVE_GROUP))
    members = members_when(job, lambda m: any(f.pgid != job.sid for f in m.values()))
    moved = next(f for f in members.values() if f.pgid != job.sid)
    assert moved.sid == job.sid
    assert job.stop().outcome == "settled"
    assert gone(moved)
    job.release()


def test_a_process_that_detaches_into_its_own_session_is_outside_the_scope(harness):
    job = harness.start(stand_in(DETACH), stdout=subprocess.PIPE, text=True)
    escaped_pid = int(job.process.stdout.readline())
    escaped = wait_for(lambda: darwin_proc.process_fact(escaped_pid))
    harness.escaped.append(escaped.identity)
    assert escaped.sid != job.sid  # it lives in the session its parent created, not in the job's
    assert escaped_pid not in job.members()
    result = job.stop()
    assert (result.outcome, result.caveat) == ("settled", CAVEAT)
    survivor = darwin_proc.process_fact(escaped_pid)
    assert survivor is not None and survivor.identity == escaped.identity  # the documented limit
    job.release()


def test_the_session_stays_in_scope_after_its_leader_exits(harness):
    job = harness.start(["/bin/sh", "-c", "sleep 30 & exit 0"])
    wait_for(job.leader_exited)
    members = wait_for(lambda: live_members(job) or None)
    assert job.sid not in members
    # proc_pidinfo cannot see an exited, unreaped process, but its entry still exists: it can be
    # signalled (a no-op) and is still waitable, so the PID, group and session IDs cannot be reused
    # yet.
    assert darwin_proc.process_fact(job.sid) is None
    os.kill(job.sid, 0)
    assert job.leader_exited()
    child = next(iter(members.values()))
    exit_watch = darwin_proc.watch_exit(child.identity.pid)
    assert job.stop().outcome == "settled"
    assert darwin_proc.wait_exit(exit_watch, 2.0)
    assert job.release() == 0


def test_a_job_that_keeps_forking_and_ignores_sigterm_still_settles(harness):
    job = harness.start(stand_in(FORKER))
    members_when(job, lambda m: len(m) >= 5)
    result = job.stop(term_grace=0.5, deadline=10)
    assert result.outcome == "settled" and result.escalated and result.rounds > 1
    job.release()


def test_a_member_whose_identity_changed_is_never_signalled(harness):
    job = harness.start(stand_in(MOVE_GROUP))
    members = members_when(job, lambda m: any(f.pgid != job.sid for f in m.values()))
    moved = next(f for f in members.values() if f.pgid != job.sid)
    stale_identity = darwin_proc.Identity(moved.identity.pid, (moved.identity.start[0] - 1, 0))
    stale = dataclasses.replace(moved, identity=stale_identity)
    refused = []
    assert not job.signal_group(moved.pgid, {stale_identity.pid: stale}, signal.SIGKILL, refused)
    assert refused == [stale_identity]
    current = darwin_proc.process_fact(moved.identity.pid)
    assert current is not None and current.identity == moved.identity and not current.zombie
    assert job.stop().outcome == "settled"
    job.release()


def test_an_observation_failure_is_unknown_never_empty(harness):
    job = harness.start(["/bin/sleep", "30"])
    wait_for(lambda: job.sid in live_members(job))

    def failing_scan():
        raise darwin_proc.ObservationError("injected scan failure")

    result = job.stop(scanner=failing_scan)
    assert (result.outcome, result.caveat) == ("unknown", None) and "injected" in result.detail
    assert job.sid in live_members(job)  # nothing was signalled on a failed observation
    assert job.stop().outcome == "settled"
    job.release()


def test_members_left_at_the_deadline_make_the_job_unknown(harness):
    job = harness.start(["/bin/sleep", "30"])
    wait_for(lambda: job.sid in live_members(job))
    result = job.stop(deadline=0)
    assert (result.outcome, result.caveat) == ("unknown", None)
    assert [fact.identity.pid for fact in result.survivors] == [job.sid]
    assert job.stop().outcome == "settled"
    job.release()


def test_the_kernel_group_filter_agrees_with_the_getsid_scan(harness):
    job = harness.start(stand_in(MOVE_GROUP))
    live = members_when(job, lambda m: len(m) == 2 and len({f.pgid for f in m.values()}) == 2)
    kernel = set().union(
        *(darwin_proc.sysctl_group_pids(pgid) for pgid in {f.pgid for f in live.values()})
    )
    assert kernel == set(live)  # both groups, every member, and nothing outside the session
    assert job.stop().outcome == "settled"
    job.release()
