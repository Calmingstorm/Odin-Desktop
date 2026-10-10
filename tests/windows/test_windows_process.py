"""Process ownership and lifetime on Windows (phase 2 plan B3).

Nothing here puts the test process in a job or lets a watchdog target it: the
kill-on-close and watchdog-expiry cases run in their own child "engines".
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.desktop.platform import win32
from src.desktop.platform import windows_process as wp

ROOT = Path(__file__).resolve().parents[2]
PROCESS_SET_QUOTA = 0x0100
# The base interpreter: a virtual environment's python.exe is a launcher with a child.
PYTHON = getattr(sys, "_base_executable", "") or sys.executable
SLEEPER = [PYTHON, "-I", "-S", "-c", "import time; time.sleep(60)"]


class Exited(BaseException):
    """What the test double of ``os._exit`` raises."""


def run_engine(program: str, *, timeout: float = 60) -> subprocess.CompletedProcess:
    """Run ``program`` as its own process with this checkout importable."""
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run([sys.executable, "-c", program], cwd=ROOT, env=env, timeout=timeout,
                          capture_output=True, text=True)


def ends_within(handle, seconds: float) -> bool:
    return win32.WaitForSingleObject(handle, int(seconds * 1000)) == win32.WAIT_OBJECT_0


@pytest.fixture
def isolated(monkeypatch):
    """Module state restored, and a hard exit that raises instead of ending pytest."""
    monkeypatch.setattr(wp, "_JOB", None)
    monkeypatch.setattr(wp, "_WATCHDOG_PID", None)
    monkeypatch.setattr(wp, "_UNSETTLED_READERS", [])
    exits = []

    def fake_exit(code):
        exits.append(code)
        raise Exited(code)

    monkeypatch.setattr(os, "_exit", fake_exit)
    return exits


@pytest.fixture
def plain_job():
    """A job WITHOUT kill-on-close: membership is tested apart from it."""
    job = win32.CreateJobObjectW(None, None)
    assert job
    children = []

    def add():
        child = subprocess.Popen(SLEEPER)
        handle = win32.OpenProcess(PROCESS_SET_QUOTA | win32.PROCESS_TERMINATE
                                   | win32.SYNCHRONIZE, False, child.pid)
        assert handle and win32.AssignProcessToJobObject(job, handle)
        children.append((child, handle))
        return child, handle

    yield job, add
    for child, handle in children:
        child.kill()
        child.wait(10)
        win32.close(handle)
    win32.close(job)


# --- Membership and containment ----------------------------------------------------------------


def test_job_membership_lists_exactly_its_processes(plain_job, monkeypatch):
    job, add = plain_job
    assert wp.job_process_ids(job) == []
    monkeypatch.setattr(wp, "_LIST_CAPACITY", 1)  # the list must grow past its first buffer
    first, _ = add()
    second, handle = add()
    assert sorted(wp.job_process_ids(job)) == sorted([first.pid, second.pid])
    win32.TerminateProcess(handle, 1)
    assert ends_within(handle, 10)
    assert wp.job_process_ids(job) == [first.pid]


def test_a_membership_query_on_something_else_fails():
    event = wp._inheritable_event()
    try:
        with pytest.raises(OSError):
            wp.job_process_ids(event)
    finally:
        win32.close(event)


def test_joining_records_the_job_once_and_a_refused_join_keeps_nothing(isolated, monkeypatch):
    created = []
    real_create = wp.create_job

    def create():
        created.append(real_create())
        return created[-1]

    monkeypatch.setattr(wp, "create_job", create)
    monkeypatch.setattr(wp.win32, "AssignProcessToJobObject", lambda job, process: 0)
    with pytest.raises(OSError):
        wp.join_job()
    assert wp._JOB is None
    monkeypatch.setattr(wp.win32, "AssignProcessToJobObject", lambda job, process: 1)
    wp.join_job()  # pretend: the test process stays outside any job
    wp.join_job()
    assert wp._JOB == created[1] and len(created) == 2
    win32.close(wp._JOB)


def test_a_job_that_cannot_be_limited_is_closed_and_refused(monkeypatch):
    monkeypatch.setattr(wp.win32, "SetInformationJobObject", lambda *args: 0)
    with pytest.raises(OSError):
        wp.create_job()


def test_an_abrupt_engine_death_ends_its_descendants():
    launcher = subprocess.Popen(
        [sys.executable, "-c",
         "import os, subprocess, sys, time\n"
         "from src.desktop.platform import windows_process as wp\n"
         "wp.join_job()\n"
         f"child = subprocess.Popen({SLEEPER!r})\n"
         "print(os.getpid(), child.pid, flush=True)\n"
         "time.sleep(60)\n"],
        cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)}, stdout=subprocess.PIPE, text=True)
    engine_pid, child_pid = (int(pid) for pid in launcher.stdout.readline().split())
    # The engine itself, not a virtual environment's launcher in front of it.
    engine = win32.OpenProcess(win32.PROCESS_TERMINATE | win32.SYNCHRONIZE, False, engine_pid)
    child = win32.OpenProcess(win32.SYNCHRONIZE, False, child_pid)
    assert engine and child, "the engine and its descendant should be running"
    try:
        assert not ends_within(child, 0.2)
        win32.TerminateProcess(engine, 1)  # no cleanup code runs: the job's last handle closes
        assert ends_within(engine, 10)
        assert ends_within(child, 10), "the descendant outlived the engine"
    finally:
        win32.close(child)
        win32.close(engine)
        launcher.wait(10)
        launcher.stdout.close()


def test_containment_is_enabled_only_inside_the_job(isolated, monkeypatch, caplog):
    import logging

    from src.tools.process_manager import JOB_TOKEN_ENV, PROC_TOKEN_ENV

    monkeypatch.delenv(PROC_TOKEN_ENV, raising=False)
    monkeypatch.delenv(JOB_TOKEN_ENV, raising=False)
    log = logging.getLogger("test.containment")
    assert wp.enable_process_containment(log) is False
    assert "refuses to start" in caplog.text
    assert os.environ[PROC_TOKEN_ENV] and os.environ[JOB_TOKEN_ENV]
    monkeypatch.setattr(wp, "_JOB", object())
    assert wp.enable_process_containment(log) is True


def test_main_joins_the_job_before_anything_else(isolated, monkeypatch, capsys):
    order = []

    class Entry:
        class main:  # noqa: N801 - stands in for the routed function
            @staticmethod
            def linux_original():
                order.append("main")

    monkeypatch.setattr(wp, "join_job", lambda: order.append("job"))
    monkeypatch.setattr(wp, "_entry_module", lambda: Entry)
    wp.core_main()
    assert order == ["job", "main"]

    def refused():
        raise OSError(None, "refused", None, 5)

    monkeypatch.setattr(wp, "join_job", refused)
    with pytest.raises(SystemExit) as stopped:
        wp.core_main()
    assert stopped.value.code == 1 and order == ["job", "main"]
    assert "WinError 5" in capsys.readouterr().err


def test_the_entry_module_is_the_running_one(monkeypatch):
    import src.__main__ as entry

    assert wp._entry_module() is entry

    class Running:
        __spec__ = type("Spec", (), {"name": "src.__main__"})

    monkeypatch.setitem(sys.modules, "__main__", Running)
    assert wp._entry_module() is Running


# --- Drain and survivors -----------------------------------------------------------------------


def test_the_drain_counts_survivors_and_the_emergency_path_ends_them(isolated, plain_job,
                                                                    monkeypatch):
    job, add = plain_job
    monkeypatch.setattr(wp, "_DRAIN_SECONDS", 0.2)
    assert wp.drain_at_teardown(None) == (0, False)  # no job: nothing is proven
    monkeypatch.setattr(wp, "_JOB", job)
    assert wp.drain_at_teardown(None) == (0, True)
    child, handle = add()
    assert wp.drain_at_teardown(None) == (0, False)
    wp.terminate_survivors(timeout=5)
    assert ends_within(handle, 0)
    assert wp.drain_at_teardown(None) == (0, True)
    monkeypatch.setattr(wp, "_UNSETTLED_READERS", [object()])
    assert wp.drain_at_teardown(None) == (0, False)


def test_the_armed_watchdog_is_allowed_to_remain(isolated, plain_job, monkeypatch):
    job, add = plain_job
    child, _ = add()
    monkeypatch.setattr(wp, "_JOB", job)
    monkeypatch.setattr(wp, "_WATCHDOG_PID", child.pid)
    assert wp.drain_at_teardown(None) == (0, True)


def test_survivor_termination_skips_processes_that_left_the_job(isolated, plain_job,
                                                               monkeypatch):
    job, add = plain_job
    monkeypatch.setattr(wp, "_JOB", job)
    child, handle = add()
    monkeypatch.setattr(wp.win32, "IsProcessInJob", lambda *args: 0)
    wp.terminate_survivors(timeout=1)
    assert not ends_within(handle, 0.2)
    monkeypatch.setattr(wp, "job_process_ids", lambda job=None: [os.getpid(), 0])
    wp.terminate_survivors(timeout=1)  # itself skipped, PID 0 not openable

    def broken(job=None):
        raise OSError("query failed")

    monkeypatch.setattr(wp, "job_process_ids", broken)
    wp.terminate_survivors(timeout=1)  # best effort: the hard exit still follows


# --- The finalize watchdog ---------------------------------------------------------------------


@pytest.fixture
def long_deadline(monkeypatch):
    """A helper left armed by a failing test must not end pytest during the run."""
    import src.__main__ as entry

    monkeypatch.setattr(entry, "_FINALIZE_WATCHDOG_TIMEOUT", 600.0)


def test_an_armed_watchdog_is_disarmed_and_its_helper_reaped(isolated, long_deadline):
    watchdog = wp.arm_finalize_watchdog(0)
    disarmed = False
    try:
        assert wp._WATCHDOG_PID == watchdog.pid
        assert not os.get_handle_inheritable(watchdog.disarm)
        wp.disarm_finalize_watchdog(watchdog, 0)
        disarmed = True
    finally:
        if not disarmed:
            win32.SetEvent(watchdog.disarm)
    assert wp._WATCHDOG_PID is None and isolated == []
    helper = win32.OpenProcess(win32.SYNCHRONIZE, False, watchdog.pid)
    if helper:  # still referenced by its Popen object: it must have exited
        assert ends_within(helper, 0)
        win32.close(helper)


def test_a_watchdog_that_cannot_start_exits_at_once(isolated, long_deadline, monkeypatch):
    def refused(*args, **kwargs):
        raise OSError("no helper")

    monkeypatch.setattr(wp.subprocess, "Popen", refused)
    with pytest.raises(Exited):
        wp.arm_finalize_watchdog(5)
    assert isolated[-1] == 5


def test_an_unprovable_disarm_takes_the_hard_exit(isolated):
    calls = []

    def hard_exit(code):
        calls.append(code)
        raise Exited(code)

    def watchdog(**overrides):
        fields = dict(process=None, helper=1, pid=1, disarm=2, handles=(), hard_exit=hard_exit,
                      set_event=lambda handle: 1, wait=lambda handle, ms: win32.WAIT_OBJECT_0,
                      exit_code_of=lambda handle, status: 1, close=lambda handle: None)
        fields.update(overrides)
        return wp.WindowsWatchdog(**fields)

    for broken in (dict(set_event=lambda handle: 0),
                   dict(wait=lambda handle, ms: 0x102),
                   dict(exit_code_of=lambda handle, status: 0)):
        calls.clear()
        with pytest.raises(Exited):
            wp.disarm_finalize_watchdog(watchdog(**broken), 0)
        assert calls == [1, 1]  # the refusal, then the handler's own hard exit


def test_a_stuck_finalizer_is_ended_by_the_watchdog():
    started = time.monotonic()
    result = run_engine(
        "import time\n"
        "import src.__main__ as entry\n"
        "from src.desktop.platform import windows_process as wp\n"
        "entry._FINALIZE_WATCHDOG_TIMEOUT = 0.5\n"
        "wp.join_job()\n"
        "entry._arm_finalize_watchdog(3)\n"
        "print('armed', flush=True)\n"
        "time.sleep(30)  # a finalizer that never returns\n"
        "print('not ended', flush=True)\n")
    assert result.stdout.split() == ["armed"], result.stderr
    assert result.returncode == 3 and time.monotonic() - started < 25


def test_a_helper_that_never_reports_ready_ends_the_engine():
    result = run_engine(
        "from src.desktop.platform import windows_process as wp\n"
        "wp.join_job()\n"
        "real = wp.win32.WaitForSingleObject\n"
        "def never_ready(handle, ms):\n"
        "    return 0x102 if ms == 2000 else real(handle, ms)\n"
        "wp.win32.WaitForSingleObject = never_ready\n"
        "import src.__main__ as entry\n"
        "entry._arm_finalize_watchdog(4)\n"
        "print('unguarded', flush=True)\n")
    assert result.returncode == 4 and "unguarded" not in result.stdout, result.stderr


# --- The parent link ---------------------------------------------------------------------------


def watched(lifetime: wp.WindowsCoreLifetime):
    read_fd, write_fd = os.pipe()
    lifetime.watch_parent(read_fd)
    return read_fd, write_fd


async def test_parent_eof_stops_the_core():
    lifetime = wp.WindowsCoreLifetime()
    read_fd, write_fd = watched(lifetime)
    reader = lifetime._reader
    try:
        os.write(write_fd, b"ignored")
        await asyncio.sleep(0.1)
        assert lifetime.admitting
        os.close(write_fd)
        await asyncio.wait_for(lifetime.wait(), 5)
        assert lifetime.reason == "parent_eof" and not lifetime.admitting
        assert lifetime._reader is None and reader.done.is_set()
    finally:
        lifetime.close()
        os.close(read_fd)


async def test_a_silent_parent_keeps_admitting_until_shutdown_cancels_the_read():
    lifetime = wp.WindowsCoreLifetime()
    read_fd, write_fd = watched(lifetime)
    reader = lifetime._reader
    try:
        await asyncio.sleep(0.3)
        assert lifetime.admitting and not reader.done.is_set()
        lifetime.request_stop("shutdown")
        started = time.monotonic()
        lifetime.close()
        assert reader.done.is_set() and time.monotonic() - started < 1
        assert lifetime.reason == "shutdown" and wp._UNSETTLED_READERS == []
    finally:
        os.close(write_fd)
        os.close(read_fd)


async def test_watching_the_pipe_never_blocks_other_calls_on_it():
    """A waiting ReadFile would hold the pipe's file object; DLL start-up then hangs."""
    lifetime = wp.WindowsCoreLifetime()
    read_fd, write_fd = watched(lifetime)
    handle = wp.msvcrt.get_osfhandle(read_fd)
    try:
        await asyncio.sleep(0.3)  # the watcher is polling a silent parent
        answers = []
        caller = threading.Thread(target=lambda: answers.append(win32.GetFileType(handle)))
        started = time.monotonic()
        caller.start()
        caller.join(2)
        assert answers == [win32.FILE_TYPE_PIPE] and time.monotonic() - started < 1
    finally:
        lifetime.close()
        os.close(write_fd)
        os.close(read_fd)


def test_a_reader_still_blocked_after_its_bound_is_recorded_unproven(isolated, monkeypatch):
    lifetime = wp.WindowsCoreLifetime()
    reader = type("Stuck", (), {"stop": lambda self: False})()
    lifetime._reader = reader
    lifetime.close()
    assert wp._UNSETTLED_READERS == [reader]
    assert wp.drain_at_teardown(None) == (0, False)


async def test_the_parent_link_must_be_a_pipe_and_watched_once(tmp_path):
    lifetime = wp.WindowsCoreLifetime()
    with open(tmp_path / "not-a-pipe", "wb") as file:
        with pytest.raises(ValueError, match="stdin pipe"):
            lifetime.watch_parent(file.fileno())
    read_fd, write_fd = watched(lifetime)
    try:
        with pytest.raises(RuntimeError, match="already watched"):
            lifetime.watch_parent(read_fd)
    finally:
        lifetime.close()
        os.close(write_fd)
        os.close(read_fd)


async def test_a_signal_without_a_parent_link_stops_at_once():
    lifetime = wp.WindowsCoreLifetime()
    before = signal.getsignal(signal.SIGBREAK)
    lifetime.watch_signals()
    try:
        signal.raise_signal(signal.SIGBREAK)
        await asyncio.wait_for(lifetime.wait(), 5)
        assert lifetime.reason == "sigbreak"
    finally:
        lifetime.close()
    assert signal.getsignal(signal.SIGBREAK) is before


async def test_a_signal_with_a_parent_link_waits_the_grace_first(monkeypatch):
    from src.desktop import lifecycle

    monkeypatch.setattr(lifecycle, "PARENT_EXIT_GRACE_SECONDS", 0.3)
    lifetime = wp.WindowsCoreLifetime()
    read_fd, write_fd = watched(lifetime)
    lifetime.watch_signals()
    try:
        signal.raise_signal(signal.SIGINT)
        await asyncio.sleep(0.1)
        assert lifetime.admitting  # the parent's own request or EOF gets the grace first
        await asyncio.wait_for(lifetime.wait(), 5)
        assert lifetime.reason == "sigint"
    finally:
        lifetime.close()
        os.close(write_fd)
        os.close(read_fd)


def test_a_signal_after_the_loop_closed_is_ignored():
    loop = asyncio.new_event_loop()
    lifetime = wp.WindowsCoreLifetime()
    loop.run_until_complete(asyncio.sleep(0))

    async def watch():
        lifetime.watch_signals()

    loop.run_until_complete(watch())
    loop.close()
    try:
        signal.raise_signal(signal.SIGBREAK)  # no RuntimeError escapes the handler
        assert lifetime.admitting
    finally:
        lifetime.close()


def test_finalize_hands_linux_barrier_the_job_drain(isolated, monkeypatch):
    seen = []

    class Entry:
        class _finalize_and_exit:  # noqa: N801 - stands in for the routed function
            @staticmethod
            def linux_original(loop, reaper, log, code):
                seen.append((loop, reaper.drain_at_teardown(), log, code))

    monkeypatch.setattr(wp, "_entry_module", lambda: Entry)
    wp.finalize_and_exit("loop", object(), "log", 3)
    assert seen == [("loop", (0, False), "log", 3)]  # no job in this test process
