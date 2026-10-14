"""odin-guardian with stand-in engines, and the real engine started through it.

The guardian is built from app/packaging/macos/guardian (or taken from ODIN_GUARDIAN, which the
CI job builds once). Each stand-in is a short Python program; none touches anything outside its
temporary folder.
"""
from __future__ import annotations

import ast
import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "app/packaging/macos/guardian"


@pytest.fixture(scope="session")
def guardian(tmp_path_factory) -> str:
    built = os.environ.get("ODIN_GUARDIAN")
    if built:
        return built
    output = tmp_path_factory.mktemp("guardian") / "odin-guardian"
    subprocess.run([str(SOURCE / "build.sh"), str(output)], check=True)
    return str(output)


def start(guardian: str, engine: str, *options: str) -> subprocess.Popen:
    return subprocess.Popen([guardian, *options, "--", sys.executable, "-c", engine],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


# A stand-in that reports its link and descriptors, then waits for EOF on its link.
COOPERATIVE = r"""
import os, stat, sys
kind = "pipe" if stat.S_ISFIFO(os.fstat(0).st_mode) else "other"
print(kind, sorted(int(n) for n in os.listdir("/dev/fd")), flush=True)
while os.read(0, 4096):
    pass
print("eof", flush=True)
"""
# A stand-in that ignores SIGTERM and EOF alike, announcing itself first.
HUNG = r"""
import signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
print("ready", flush=True)
while True:
    time.sleep(1)
"""


def test_the_engine_gets_a_fresh_pipe_and_only_the_standard_descriptors(guardian):
    process = start(guardian, COOPERATIVE)
    first = process.stdout.readline().split(" ", 1)
    assert first[0] == "pipe"
    descriptors = ast.literal_eval(first[1])
    assert [fd for fd in descriptors if fd > 2] in ([], [3])  # 3: the listing's own descriptor
    out, err = process.communicate(timeout=20)  # closes the app link
    assert process.returncode == 0, err
    assert out.split() == ["eof"]


def test_other_bytes_on_the_app_link_are_ignored(guardian):
    process = start(guardian, COOPERATIVE)
    process.stdout.readline()
    process.stdin.write("hello there\n")
    process.stdin.flush()
    time.sleep(0.5)
    assert process.poll() is None  # still running: only EOF or "S" stops it
    process.stdin.close()
    assert process.wait(20) == 0


@pytest.mark.parametrize("engine,expected", [
    ("import sys; sys.exit(3)", 3),
    ("import os, signal; os.kill(os.getpid(), signal.SIGUSR1)", -signal.SIGUSR1),
])
def test_the_engine_status_passes_through(guardian, engine, expected):
    process = start(guardian, engine)
    process.communicate(timeout=20)
    assert process.returncode == expected


@pytest.mark.parametrize("edge", ["eof", "stop byte"])
def test_a_hung_engine_gets_sigterm_after_grace_then_sigkill(guardian, edge):
    process = start(guardian, HUNG, "--grace", "1", "--term", "1")
    assert process.stdout.readline().strip() == "ready"
    started = time.monotonic()
    if edge == "eof":
        _, err = process.communicate(timeout=30)  # closes the app link
    else:
        process.stdin.write("S")  # the app's protocol shutdown, with the link still open
        process.stdin.flush()
        process.wait(30)
        err = process.stderr.read()
    elapsed = time.monotonic() - started
    assert process.returncode == -signal.SIGKILL
    assert 1.5 < elapsed < 15
    assert "did not stop within its grace period; sent SIGTERM" in err
    assert "did not stop after SIGTERM; sent SIGKILL" in err


def test_sigterm_skips_the_grace_and_a_cooperative_engine_exits_cleanly(guardian):
    engine = r"""
import signal, sys, time
signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
print("ready", flush=True)
time.sleep(60)
"""
    process = start(guardian, engine, "--grace", "60", "--term", "60")
    assert process.stdout.readline().strip() == "ready"
    started = time.monotonic()
    process.send_signal(signal.SIGTERM)
    process.communicate(timeout=20)
    assert process.returncode == 0 and time.monotonic() - started < 10


def test_a_second_signal_kills_at_once(guardian):
    process = start(guardian, HUNG, "--grace", "60", "--term", "60")
    assert process.stdout.readline().strip() == "ready"
    process.send_signal(signal.SIGTERM)
    time.sleep(0.5)
    started = time.monotonic()
    process.send_signal(signal.SIGINT)
    _, err = process.communicate(timeout=20)
    assert process.returncode == -signal.SIGKILL and time.monotonic() - started < 10
    assert "stop requested again; sent SIGKILL" in err


def gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


# A stand-in that exits slowly but on its own after SIGTERM, announcing its process ID first.
SLOW = r"""
import os, signal, sys, time
signal.signal(signal.SIGTERM, lambda *a: (time.sleep(2), sys.exit(0)))
print(os.getpid(), flush=True)
while True:
    time.sleep(1)
"""
HUNG_PID = HUNG.replace('print("ready", flush=True)', "import os; print(os.getpid(), flush=True)")


def test_a_slow_exit_within_the_term_is_waited_for_not_killed(guardian):
    process = start(guardian, SLOW, "--grace", "1", "--term", "6")
    engine = int(process.stdout.readline())
    _, err = process.communicate(timeout=30)  # EOF: grace, then TERM; the engine needs 2 s
    assert process.returncode == 0, err  # its own exit status, not a KILL
    assert "sent SIGKILL" not in err and gone(engine)


def test_a_dead_apps_link_still_ends_a_hung_engine_and_reaps_it(guardian):
    process = start(guardian, HUNG_PID, "--grace", "1", "--term", "1")
    engine = int(process.stdout.readline())
    process.stdin.close()  # the app is gone: nobody else will signal anything
    assert process.wait(30) == -signal.SIGKILL
    assert gone(engine)  # reaped before the guardian exited


def test_a_signal_racing_the_grace_expiry_still_ends_and_reaps_the_engine(guardian):
    process = start(guardian, HUNG_PID, "--grace", "1", "--term", "30")
    engine = int(process.stdout.readline())
    process.stdin.close()
    time.sleep(1.0)  # the grace expires about now
    process.send_signal(signal.SIGTERM)
    assert process.wait(30) == -signal.SIGKILL  # either order ends in a KILL the guardian sends
    assert gone(engine)


def test_an_engine_that_cannot_start_and_bad_usage(guardian):
    missing = subprocess.run([guardian, "--", "/nonexistent/engine"], capture_output=True,
                             text=True, timeout=20)
    assert missing.returncode == 127 and "could not start the engine" in missing.stderr
    for arguments in ([], ["--grace", "x", "--", sys.executable], ["--", "python3"],
                      ["--grace", "5", sys.executable]):
        usage = subprocess.run([guardian, *arguments], capture_output=True, text=True, timeout=20)
        assert usage.returncode == 2, arguments


def test_the_real_engine_runs_and_stops_under_the_guardian(guardian, tmp_path):
    """The source checkout's engine started as the phase-4 app will start it."""
    from tests.macos.test_core_end_to_end import Core, hello

    home = Path(os.path.realpath(tmp_path))
    core = Core(home)
    environment = {**os.environ, "HOME": str(home), "LANG": "en_US.UTF-8",
                   "TMPDIR": os.environ.get("TMPDIR", "/tmp"), "PYTHONDONTWRITEBYTECODE": "1"}
    with open(core.log, "wb") as stderr:
        core.process = subprocess.Popen(
            [guardian, "--grace", "15", "--term", "4", "--", sys.executable, "-m", "src",
             "--socket", str(core.socket), "--token-file", str(core.token_file),
             "--profile", core.profile, "--data-dir", str(core.paths.data_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr, cwd=ROOT,
            env=environment)
    try:
        async def ready():
            reader, writer, welcome = await hello(core)
            assert welcome["t"] == "welcome"
            writer.close()

        asyncio.run(ready())
        core.process.stdin.close()  # the app quits: the guardian closes the engine's link
        assert core.process.wait(60) == 0, core.stderr()[-3000:]
        assert not core.socket.exists()
        assert "odin-guardian:" not in core.stderr()  # no escalation was needed
    finally:
        core.stop()
