"""The macOS process boundary: containment, the finalize watchdog, the teardown drain and the
identity-conditioned signal."""
from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.desktop.platform import darwin, macos_process

ROOT = Path(__file__).resolve().parents[2]
_P_PID, _WNOHANG, _WEXITED, _WNOWAIT = 1, 1, 4, 0x20  # libSystem waitid


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, message, *args):
        self.lines.append(("info", message % args if args else message))

    def error(self, message, *args):  # pragma: no cover - only on failure
        self.lines.append(("error", message % args if args else message))

    debug = info


def test_containment_stamps_provenance_and_states_the_missing_subreaper(monkeypatch):
    from src.__main__ import _enable_process_containment
    from src.tools.process_manager import (
        DEFAULT_JOB_TOKEN,
        JOB_TOKEN_ENV,
        PROC_TOKEN_ENV,
        child_subreaper_active,
    )

    monkeypatch.delenv(PROC_TOKEN_ENV, raising=False)
    monkeypatch.delenv(JOB_TOKEN_ENV, raising=False)
    log = _Log()
    assert _enable_process_containment(log) is True
    assert len(os.environ[PROC_TOKEN_ENV]) == 16
    assert os.environ[JOB_TOKEN_ENV] == DEFAULT_JOB_TOKEN
    assert log.lines == [("info", "macOS process containment: session-scoped, best effort "
                                  "(no child subreaper)")]
    # Nothing claims containment the platform does not have.
    assert child_subreaper_active() is False


def test_the_entry_points_route_to_the_macos_variants():
    import src.__main__ as entry
    from src.tools.process_manager import AdoptedZombieReaper

    target = "src.desktop.platform.macos_process:"
    assert entry._enable_process_containment.darwin_target == target + "enable_process_containment"
    assert entry._arm_finalize_watchdog.darwin_target == target + "arm_finalize_watchdog"
    assert AdoptedZombieReaper.drain_at_teardown.darwin_target == target + "drain_at_teardown"


def _engine(body: str, timeout: float) -> subprocess.Popen:
    """A stand-in engine: arms the real watchdog with a short deadline, then runs ``body``."""
    program = (
        "import sys, time\n"
        "import src.__main__ as entry\n"
        f"entry._FINALIZE_WATCHDOG_TIMEOUT = {timeout}\n"
        "watchdog = entry._arm_finalize_watchdog(3)\n"
        "print(watchdog.pid, flush=True)\n" + body
    )
    return subprocess.Popen([sys.executable, "-c", program], cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def test_the_watchdog_kills_a_hung_engine():
    engine = _engine("time.sleep(60)\n", timeout=1.0)
    try:
        assert engine.wait(20) == -signal.SIGKILL
    finally:
        if engine.poll() is None:
            engine.kill()
            engine.wait()


def test_a_disarmed_watchdog_exits_cleanly_and_spares_the_engine():
    engine = _engine("entry._disarm_finalize_watchdog(watchdog, 0)\ntime.sleep(2.5)\n"
                     "print('alive', flush=True)\n", timeout=1.0)
    out, err = engine.communicate(timeout=20)
    assert engine.returncode == 0, err
    assert out.split()[-1] == "alive"


def test_the_watchdog_helper_leaves_when_the_engine_exits_first():
    engine = _engine("sys.exit(0)\n", timeout=30.0)
    out, err = engine.communicate(timeout=20)
    assert engine.returncode == 0, err
    helper = int(out.split()[0])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and darwin.process_identity(helper) is not None:
        time.sleep(0.05)
    assert darwin.process_identity(helper) is None  # gone, not waiting out its 30 s


def test_the_token_signal_reaches_only_that_incarnation():
    later_exec = "import os, time; time.sleep(1); os.execv('/bin/sleep', ['sleep', '30'])"
    child = subprocess.Popen([sys.executable, "-c", later_exec])
    try:
        before = darwin.process_identity(child.pid)
        assert before is not None
        deadline = time.monotonic() + 10
        after = before
        while time.monotonic() < deadline and after.idversion == before.idversion:
            time.sleep(0.05)
            after = darwin.process_identity(child.pid)
        assert after.idversion != before.idversion and after.uniqueid == before.uniqueid
        assert darwin.signal_identity(before, signal.SIGKILL) == errno.ESRCH
        assert child.poll() is None  # the stale token reached nothing
        assert darwin.signal_identity(after, signal.SIGKILL) == 0
        assert child.wait(10) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def _spawn(*argv: str) -> int:
    return os.posix_spawn(argv[0], argv, os.environ)


def test_the_drain_reaps_every_exited_child_and_verifies():
    macos_process.drain_at_teardown(SimpleNamespace(reaped_total=0))  # another test's leftovers
    pids = [_spawn("/usr/bin/true") for _ in range(3)]
    for pid in pids:  # exited, not reaped: waitid with WNOWAIT leaves them zombies
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not _exited(pid):
            time.sleep(0.02)
    reaper = SimpleNamespace(reaped_total=4)
    reaped, verified = macos_process.drain_at_teardown(reaper)
    assert (reaped, verified, reaper.reaped_total) == (3, True, 7)
    for pid in pids:
        with pytest.raises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)


def test_the_drain_leaves_a_live_child_alone():
    pid = _spawn("/bin/sleep", "30")
    try:
        assert macos_process.drain_at_teardown(SimpleNamespace(reaped_total=0)) == (0, True)
        assert os.waitpid(pid, os.WNOHANG) == (0, 0)
    finally:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)


def test_the_drain_reports_unverified_on_an_unexpected_failure(monkeypatch):
    def broken(pid, options):
        raise OSError(errno.EINVAL, "invalid")

    monkeypatch.setattr(os, "waitpid", broken)
    assert macos_process.drain_at_teardown(SimpleNamespace(reaped_total=0)) == (0, False)


def _exited(pid: int) -> bool:
    """True once pid has exited, without reaping it (libSystem waitid with WNOWAIT)."""
    import ctypes

    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    info = ctypes.create_string_buffer(104)  # siginfo_t
    if libc.waitid(_P_PID, pid, info, _WEXITED | _WNOHANG | _WNOWAIT) != 0:
        return False
    return int.from_bytes(info.raw[12:16], sys.byteorder) == pid  # si_pid


def test_descriptor_count_follows_open_descriptors():
    before = darwin.open_descriptor_count()
    fds = [os.open("/dev/null", os.O_RDONLY) for _ in range(10)]
    try:
        assert darwin.open_descriptor_count() == before + 10
    finally:
        for fd in fds:
            os.close(fd)
    assert darwin.open_descriptor_count() == before


# --- The watchdog in this process: the arm contract, the drain, a clean finalize ---------------


class _ExitError(Exception):
    pass


def _record_exits(monkeypatch):
    codes = []

    def hard_exit(code):
        codes.append(code)
        raise _ExitError(code)

    monkeypatch.setattr(os, "_exit", hard_exit)
    return codes


def test_an_armed_helper_survives_the_drain_and_disarms_cleanly(monkeypatch):
    import src.__main__ as entry
    from src.tools.process_manager import AdoptedZombieReaper

    monkeypatch.setattr(entry, "_FINALIZE_WATCHDOG_TIMEOUT", 30.0)
    watchdog = entry._arm_finalize_watchdog(0)
    try:
        assert AdoptedZombieReaper().drain_at_teardown() == (0, True)
        waited, _ = watchdog.waitpid(watchdog.pid, os.WNOHANG)
        assert waited == 0  # the drain neither consumed nor killed the live helper
    finally:
        entry._disarm_finalize_watchdog(watchdog, 0)  # waits for the helper's clean exit


def test_a_clean_finalize_disarms_the_watchdog(monkeypatch):
    import asyncio
    import logging

    import src.__main__ as entry
    from src.tools.process_manager import AdoptedZombieReaper

    monkeypatch.setattr(entry, "_FINALIZE_WATCHDOG_TIMEOUT", 30.0)
    calls = []
    monkeypatch.setattr(entry.os, "_exit", lambda code: calls.append(code))
    real_disarm = entry._disarm_finalize_watchdog
    disarmed = []

    def capture(watchdog, code):
        real_disarm(watchdog, code)
        disarmed.append(watchdog.pid)

    monkeypatch.setattr(entry, "_disarm_finalize_watchdog", capture)
    loop = asyncio.new_event_loop()
    entry._finalize_and_exit(loop, AdoptedZombieReaper(), logging.getLogger("test"), 0)
    assert len(disarmed) == 1 and calls == [] and loop.is_closed()


@pytest.mark.parametrize("failure", ["identity", "spawn", "silent helper", "wrong answer"])
def test_any_arm_failure_exits_at_once_with_the_code(monkeypatch, failure):
    if failure == "identity":
        monkeypatch.setattr(darwin, "process_identity", lambda pid: None)
    elif failure == "spawn":
        def refuse(*args, **kwargs):
            raise OSError(errno.EAGAIN, "no processes")

        monkeypatch.setattr(os, "posix_spawn", refuse)
    elif failure == "silent helper":
        monkeypatch.setattr(macos_process.select, "select",
                            lambda read, write, error, timeout: ([], [], []))
    else:
        monkeypatch.setattr(os, "read", lambda fd, size: b"X")
    before = set(os.listdir("/dev/fd"))
    codes = _record_exits(monkeypatch)
    with pytest.raises(_ExitError):
        macos_process.arm_finalize_watchdog(5)
    # The real exit never returns; this double raises, so the cleanup path may call it again.
    assert codes and set(codes) == {5}
    monkeypatch.undo()
    # A spawned helper is told to stand down by its closed control pipe, and no descriptor leaks.
    assert set(os.listdir("/dev/fd")) <= before | {str(fd) for fd in range(3)}
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if os.waitpid(-1, os.WNOHANG) == (0, 0):
                time.sleep(0.05)
                continue
        except ChildProcessError:
            break


def test_a_zero_exit_code_still_exits_nonzero_when_arming_fails(monkeypatch):
    monkeypatch.setattr(darwin, "process_identity", lambda pid: None)
    codes = _record_exits(monkeypatch)
    with pytest.raises(_ExitError):
        macos_process.arm_finalize_watchdog(0)
    assert codes == [1]


def test_the_entry_module_is_the_running_one(monkeypatch):
    import types

    import src.__main__ as entry

    assert macos_process._entry_module() is entry
    running = types.ModuleType("__main__")
    running.__spec__ = types.SimpleNamespace(name="src.__main__")
    monkeypatch.setitem(sys.modules, "__main__", running)
    assert macos_process._entry_module() is running  # python -m src: never a second copy
