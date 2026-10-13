"""Phase 1 feasibility: session-per-job cleanup on macOS.

Harmless stand-ins only: sleep, a shell running background sleeps, and small Python snippets that
fork, change their process group or detach into a new session, then sleep. Every stand-in ends on
its own within 30 seconds, and the tests signal only their own processes, by identity.

Run with: python -m pytest scripts/macos-feasibility/test_session_jobs.py
"""

from __future__ import annotations

import dataclasses
import errno
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
    from session_jobs import CAVEAT, AuthorityLostError, SessionJob

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

# A chain in its own group: each generation forks, and the parent leaves at once, handing the
# group to its child. It runs for two seconds, then the last generation sleeps.
CHAIN = """
import os, sys, time
if os.fork() == 0:
    os.setpgid(0, 0)
    end = time.monotonic() + 2
    while time.monotonic() < end:
        time.sleep(0.02)
        if os.fork() != 0:
            os._exit(0)
        sys.stdout.write(f"{os.getpid()}\\n")
        sys.stdout.flush()
    time.sleep(20)
    os._exit(0)
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


def live(job) -> dict:
    return {pid: member for pid, member in job.members().items() if not member.zombie}


def members_when(job, condition):
    def probe():
        members = live(job)
        return members if condition(members) else None

    return wait_for(probe)


def gone(member) -> bool:
    current = darwin_proc.identity_of(member.pid)
    return current is None or current.uniqueid != member.identity.uniqueid


def sleeper() -> subprocess.Popen:
    process = subprocess.Popen(["/bin/sleep", "30"])
    wait_for(lambda: darwin_proc.identity_of(process.pid))
    return process


@pytest.fixture
def harness():
    jobs, escaped, children = [], [], []

    def start(argv, **options):
        job = SessionJob(argv, **options)
        jobs.append(job)
        return job

    yield SimpleNamespace(start=start, escaped=escaped, children=children)
    for job in jobs:
        if not job.retired:
            job.stop(term_grace=0.5, deadline=8)
            job.release(force=True)
    for identity in escaped:
        darwin_proc.signal_identity(identity, signal.SIGKILL)  # refused if no longer that process
    for child in children:
        child.kill()
        child.wait(5)


def test_a_single_job_stops_and_its_session_settles(harness):
    job = harness.start(["/bin/sleep", "30"])
    wait_for(lambda: job.sid in live(job))
    result = job.stop()
    assert (result.outcome, result.caveat, result.escalated) == ("settled", CAVEAT, False)
    assert job.leader_exited()
    assert job.release() == -signal.SIGTERM


def test_background_children_are_stopped_with_the_job(harness):
    job = harness.start(["/bin/sh", "-c", "sleep 30 & sleep 30 & wait"])
    members = members_when(job, lambda m: len(m) == 3)
    assert job.stop().outcome == "settled"
    assert all(gone(member) for member in members.values())
    job.release()


def test_a_member_that_changes_group_is_stopped_through_its_identity(harness):
    job = harness.start(stand_in(MOVE_GROUP))
    members = members_when(job, lambda m: any(f.pgid != job.sid for f in m.values()))
    moved = next(f for f in members.values() if f.pgid != job.sid)
    assert moved.identity is not None
    result = job.stop()
    assert result.outcome == "settled" and result.groups[job.sid] != "live"
    assert gone(moved)
    job.release()


def test_a_process_that_detaches_into_its_own_session_is_outside_the_scope(harness):
    job = harness.start(stand_in(DETACH), stdout=subprocess.PIPE, text=True)
    escaped_pid = int(job.stdout.readline())
    escaped = wait_for(lambda: darwin_proc.identity_of(escaped_pid))
    harness.escaped.append(escaped)
    assert darwin_proc.session_of(escaped_pid) != job.sid
    assert escaped_pid not in job.members()
    result = job.stop()
    assert (result.outcome, result.caveat) == ("settled", CAVEAT)
    assert darwin_proc.identity_of(escaped_pid) == escaped  # the documented limit: it survives
    job.release()


def test_the_session_stays_in_scope_after_its_leader_exits(harness):
    job = harness.start(["/bin/sh", "-c", "sleep 30 & exit 0"])
    wait_for(job.leader_exited)
    members = wait_for(lambda: live(job) or None)
    assert job.sid not in members
    os.kill(job.sid, 0)  # the exited leader is still an unreaped entry: its IDs stay pinned
    assert job.leader_exited()
    assert job.stop().outcome == "settled"
    assert job.release() == 0


def test_a_job_that_keeps_forking_and_ignores_sigterm_still_settles(harness):
    job = harness.start(stand_in(FORKER))
    members_when(job, lambda m: len(m) >= 5)
    result = job.stop(term_grace=0.5, deadline=10)
    assert result.outcome == "settled" and result.escalated and result.rounds > 1
    job.release()


def test_an_identity_whose_version_changed_is_refused_by_the_kernel(harness):
    process = sleeper()
    harness.children.append(process)
    current = darwin_proc.identity_of(process.pid)
    stale = dataclasses.replace(current, idversion=current.idversion + 1)
    assert darwin_proc.signal_identity(stale, signal.SIGKILL) == errno.ESRCH
    time.sleep(0.2)
    assert darwin_proc.identity_of(process.pid) == current  # untouched


def test_an_identity_from_before_an_exec_is_refused(harness):
    process = subprocess.Popen(["/bin/sh", "-c", "sleep 0.5; exec /bin/sleep 30"])
    harness.children.append(process)
    before = wait_for(lambda: darwin_proc.identity_of(process.pid))
    after = wait_for(
        lambda: (
            (now := darwin_proc.identity_of(process.pid))
            and now.idversion != before.idversion
            and now
        )
    )
    assert after.uniqueid == before.uniqueid
    assert darwin_proc.signal_identity(before, signal.SIGKILL) == errno.ESRCH
    assert darwin_proc.signal_identity(after, signal.SIGKILL) == 0
    assert process.wait(5) == -signal.SIGKILL


def test_an_observation_failure_is_unknown_never_empty(harness):
    failing = {"on": True}

    def observer(sid):
        if failing["on"]:
            raise darwin_proc.ObservationError("injected scan failure")
        return darwin_proc.observe_session(sid)

    job = harness.start(["/bin/sleep", "30"], observer=observer)
    result = job.stop()
    assert (result.outcome, result.caveat) == ("unknown", None) and "injected" in result.detail
    failing["on"] = False
    assert job.sid in live(job)  # nothing was signalled on a failed observation
    assert job.stop().outcome == "settled"
    job.release()


def test_members_left_at_the_deadline_make_the_job_unknown(harness):
    job = harness.start(["/bin/sh", "-c", "trap '' TERM; sleep 30"])  # both ignore SIGTERM
    members_when(job, lambda m: len(m) == 2)
    result = job.stop(term_grace=10, deadline=1.0)
    assert (result.outcome, result.caveat, result.escalated) == ("unknown", None, False)
    assert job.sid in {member.pid for member in result.survivors}
    result = job.stop(term_grace=0.2)
    assert result.outcome == "settled" and result.escalated
    job.release()


def test_a_member_whose_identity_cannot_be_read_keeps_the_job_unknown(harness):
    hidden = {"on": True}

    def observer(sid):
        members = darwin_proc.observe_session(sid)
        if not hidden["on"]:
            return members
        return {
            pid: dataclasses.replace(m, identity=None) if m.pgid != sid else m
            for pid, m in members.items()
        }

    job = harness.start(stand_in(MOVE_GROUP), observer=observer)
    members = members_when(job, lambda m: any(f.pgid != job.sid for f in m.values()))
    moved = next(f for f in members.values() if f.pgid != job.sid)
    result = job.stop(term_grace=0.2, deadline=1.5)
    assert result.outcome == "unknown" and moved.pid in result.unresolved
    assert darwin_proc.session_of(moved.pid) == job.sid  # it was never dropped, never signalled
    hidden["on"] = False
    assert job.stop().outcome == "settled"
    job.release()


def test_a_refused_signal_is_reported_not_raised(harness):
    refusing = {"on": True}

    def signaller(identity, sent):
        if refusing["on"]:
            return errno.EPERM
        return darwin_proc.signal_identity(identity, sent)

    job = harness.start(stand_in(MOVE_GROUP), signaller=signaller)
    members_when(job, lambda m: any(f.pgid != job.sid for f in m.values()))
    result = job.stop(term_grace=0.2, deadline=1.5)
    assert result.outcome == "unknown"
    assert "Operation not permitted" in " ".join(result.unresolved.values())
    refusing["on"] = False
    assert job.stop().outcome == "settled"
    job.release()


def test_a_fork_and_exit_chain_in_its_own_group_never_settles_falsely(harness):
    job = harness.start(stand_in(CHAIN), stdout=subprocess.PIPE, text=True)
    printed = [int(job.stdout.readline()) for _ in range(10)]  # the chain is well under way
    result = job.stop(term_grace=0.5, deadline=15)
    assert result.outcome == "settled", result
    printed += [int(line) for line in job.stdout.read().split()]  # every writer is gone: EOF
    assert all(darwin_proc.session_of(pid) != job.sid for pid in printed)
    job.release()


def test_a_live_group_blocks_settling_even_when_the_scan_misses_it(harness):
    blind, inert = {"on": False}, {"on": True}

    def observer(sid):
        return {} if blind["on"] else darwin_proc.observe_session(sid)

    def signaller(identity, sent):
        return 0 if inert["on"] else darwin_proc.signal_identity(identity, sent)

    job = harness.start(stand_in(MOVE_GROUP), observer=observer, signaller=signaller)
    members = members_when(job, lambda m: any(f.pgid != job.sid for f in m.values()))
    moved = next(f for f in members.values() if f.pgid != job.sid)
    assert job.stop(term_grace=0.2, deadline=0.5).outcome == "unknown"  # records the moved group
    blind["on"] = True  # from now on the scan sees nothing at all
    result = job.stop(term_grace=0.2, deadline=1.5)
    assert result.outcome == "unknown" and result.groups[moved.pgid] == "live"
    assert darwin_proc.session_of(moved.pid) == job.sid
    blind["on"] = inert["on"] = False
    assert job.stop().outcome == "settled"
    assert gone(moved)
    job.release()


def test_release_needs_a_settled_stop_and_then_ends_all_authority(harness):
    job = harness.start(["/bin/sleep", "30"])
    with pytest.raises(RuntimeError, match="not settled"):
        job.release()
    assert job.stop().outcome == "settled"
    assert job.release() == -signal.SIGTERM
    for action in (job.stop, job.members, job.leader_exited):
        with pytest.raises(AuthorityLostError):
            action()


def test_the_leader_group_holds_no_signallable_member_once_only_the_leader_remains(harness):
    job = harness.start(["/bin/sh", "-c", "exit 0"])
    wait_for(job.leader_exited)
    assert darwin_proc.group_probe(job.sid) == "no-signallable"
    assert darwin_proc.group_probe(99998) == "empty"
    assert job.stop().outcome == "settled"
    assert job.release() == 0


def test_the_kernel_group_filter_agrees_with_the_getsid_scan(harness):
    job = harness.start(stand_in(MOVE_GROUP))
    members = members_when(job, lambda m: len(m) == 2 and len({f.pgid for f in m.values()}) == 2)
    groups = {member.pgid for member in members.values()}
    kernel = set().union(*(darwin_proc.sysctl_group_pids(pgid) for pgid in groups))
    assert kernel == set(members)  # both groups, every member, and nothing outside the session
    assert job.stop().outcome == "settled"
    job.release()
