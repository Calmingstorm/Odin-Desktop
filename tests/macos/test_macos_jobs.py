"""The macOS supervisor worker and the job helpers, through Odin's own parent side."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.desktop.platform import macos_jobs

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "src/desktop/platform/macos_supervisor_worker.py"
PIPE, STDOUT = asyncio.subprocess.PIPE, asyncio.subprocess.STDOUT


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def gone(pids, seconds=10.0) -> bool:
    deadline = time.monotonic() + seconds
    while any(alive(pid) for pid in pids):
        if time.monotonic() > deadline:
            return False
        await asyncio.sleep(0.05)
    return True


async def shell(command: str):
    return await macos_jobs.create_supervised_shell(command, stdout=PIPE, stderr=STDOUT,
                                                    stdin=PIPE)


async def test_a_command_runs_reports_and_settles():
    proc = await shell("echo hi")
    out, _ = await proc.communicate()
    assert out == b"hi\n" and proc.returncode == 0
    assert await asyncio.wait_for(asyncio.shield(proc._settled), 10) is True


@pytest.mark.parametrize("command,expected", [("exit 3", 3),
                                              ("kill -USR1 $$", -signal.SIGUSR1)])
async def test_the_exit_status_passes_through(command, expected):
    proc = await shell(command)
    await proc.communicate()
    assert proc.returncode == expected
    assert await asyncio.wait_for(asyncio.shield(proc._settled), 10) is True


async def test_a_background_member_outlives_the_leader_until_it_exits():
    proc = await shell("sleep 2 >/dev/null 2>&1 & echo $!")
    out, _ = await proc.communicate()
    member = int(out.split()[0])
    assert proc.returncode == 0 and alive(member)
    await asyncio.sleep(0.5)
    assert not proc._settled.done()  # the leader exited; its session has not
    assert await asyncio.wait_for(asyncio.shield(proc._settled), 10) is True
    assert not alive(member)


async def test_stop_ends_a_term_immune_member_and_one_in_another_group():
    command = ("(trap '' TERM; sleep 60) >/dev/null 2>&1 & echo $!; "
               "set -m; sleep 60 >/dev/null 2>&1 & echo $!; echo ready; wait")
    proc = await shell(command)
    lines = [await proc.stdout.readline() for _ in range(3)]
    assert lines[2] == b"ready\n"
    members = [int(line) for line in lines[:2]]
    assert os.getpgid(members[1]) != os.getpgid(members[0])  # job control: its own group
    started = time.monotonic()
    assert await proc.terminate_tree(grace=0.5) is True
    assert time.monotonic() - started < 10
    assert await gone(members)


async def test_a_detached_member_is_outside_the_scope(tmp_path):
    """The documented limit: a member that starts its own session is neither seen nor stopped."""
    record = tmp_path / "pid"
    detach = (f'"{sys.executable}" -c "import os, time; os.setsid(); '
              f"open('{record}', 'w').write(str(os.getpid())); time.sleep(30)\" "
              ">/dev/null 2>&1 &")
    proc = await shell(detach + " echo ready; wait")
    assert await proc.stdout.readline() == b"ready\n"
    deadline = time.monotonic() + 10
    while not record.exists() or not record.read_text():
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    escaped = int(record.read_text())
    try:
        assert await proc.terminate_tree(grace=0.2) is True
        assert alive(escaped)  # survived a settled stop: why macOS cleanup is best effort
    finally:
        os.kill(escaped, signal.SIGKILL)


async def test_a_detached_member_holding_the_output_makes_the_stop_fail_not_succeed():
    """An escaped process still holding the job's pipe keeps it unconfirmed: never a success."""
    from src.tools.local_supervisor import SupervisorError

    detach = (f'"{sys.executable}" -c "import os, sys, time; os.setsid(); '
              'print(os.getpid(), flush=True); time.sleep(30)" &')
    proc = await shell(detach + " wait")
    escaped = int((await proc.stdout.readline()).split()[0])
    try:
        with pytest.raises((SupervisorError, TimeoutError)):
            await proc.terminate_tree(grace=0.2)
    finally:
        os.kill(escaped, signal.SIGKILL)


def _worker(command: str, *, shell_path: str = "/bin/sh"):
    parent, child = socket.socketpair()
    process = subprocess.Popen(
        [sys.executable, "-I", str(WORKER), "--control-fd", str(child.fileno()),
         "--command", command, "--shell", "sh", "--shell-executable", shell_path],
        pass_fds=(child.fileno(),), start_new_session=True, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL)
    child.close()
    return parent, process


def _frames(sock: socket.socket, seconds: float = 10.0) -> list[dict]:
    sock.settimeout(seconds)
    data = b""
    try:
        while chunk := sock.recv(65536):
            data += chunk
    except (TimeoutError, OSError):
        pass
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def test_losing_the_control_channel_stops_the_session():
    """The engine dying closes the channel: the worker still stops what it owns."""
    parent, process = _worker("sleep 60 >/dev/null 2>&1 & echo $!; wait")
    try:
        member = int(process.stdout.readline())
        assert alive(member)
        parent.close()
        assert process.wait(20) in (0, 1)
        deadline = time.monotonic() + 10
        while alive(member) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not alive(member)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_an_invalid_control_message_is_reported_and_the_session_stopped():
    parent, process = _worker("sleep 60")
    try:
        parent.sendall(b'{"op": "bogus"}\n')
        frames = _frames(parent, 10)
        events = [frame["event"] for frame in frames]
        assert events[0] == "started"
        assert {"event": "error", "message": "invalid control message (ValueError)"} in frames
        assert "settled" in events  # stopped and settled, its failure already reported
        assert process.wait(20) == 1
    finally:
        parent.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def test_a_command_that_cannot_start_is_reported():
    parent, process = _worker("true", shell_path="/nonexistent/shell")
    try:
        frames = _frames(parent, 10)
        assert {"event": "error", "message": "command setup failed (FileNotFoundError)"} in frames
        assert process.wait(20) == 1
    finally:
        parent.close()


# --- The job helpers ---------------------------------------------------------------------------


def test_internal_commands_get_the_engines_python3_and_raw_ones_keep_path(monkeypatch):
    monkeypatch.setattr(macos_jobs, "_internal_bin", None)
    environment = macos_jobs._internal_environment({"PATH": "/usr/bin:/bin", "KEEP": "1"})
    folder = Path(environment["PATH"].split(os.pathsep)[0])
    assert environment["PATH"].split(os.pathsep)[1:] == ["/usr/bin", "/bin"]
    assert environment["KEEP"] == "1"
    assert os.readlink(folder / "python3") == sys.executable
    info = os.lstat(folder)
    assert stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.geteuid()
    again = macos_jobs._internal_environment(None)  # reused, and the engine's own PATH
    assert again["PATH"].split(os.pathsep)[0] == str(folder)


def test_the_poll_metadata_carries_the_scope_and_caveat():
    meta = {"kind": "process_output", "pid": 7, "cleanup_verified": True}
    plain = json.dumps(meta, separators=(",", ":"))
    extended = json.loads(macos_jobs._with_caveat_fields(plain))
    assert extended["containment"] == "session_best_effort"
    assert extended["cleanup_caveat"] == "detached or raced descendants are unverified"
    preview = "[PID 7] status=killed\nout\n[output retention] " + plain
    head, _, tail = macos_jobs._with_caveat_fields(preview).rpartition("\n[output retention] ")
    assert head == "[PID 7] status=killed\nout" and json.loads(tail)["containment"]
    for unchanged in ("Error: offset is not a UTF-8 code point boundary.",
                      json.dumps({"kind": "other"})):
        assert macos_jobs._with_caveat_fields(unchanged) == unchanged


def test_the_registry_states_the_caveat_for_local_jobs_only():
    local = SimpleNamespace(remote=False, containment="session_best_effort")
    remote = SimpleNamespace(remote=True, containment="process_group_only")
    other = SimpleNamespace(remote=False, containment="")
    caveat = macos_jobs.MacOSProcessRegistry._remote_cleanup_caveat
    assert caveat(local) == " containment=session_best_effort; detached or raced descendants " \
                            "are unverified."
    assert caveat(remote) == " containment=process_group_only; escaped descendants are unverified."
    assert caveat(other) == ""
