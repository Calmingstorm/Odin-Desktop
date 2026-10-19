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
from unittest.mock import Mock

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


async def test_a_term_immune_member_in_its_own_group_waits_for_the_kill_deadline():
    """Sent TERM once, then left alone each round until the deadline, when it is killed."""
    command = "set -m; (trap '' TERM; sleep 60) >/dev/null 2>&1 & echo $!; echo ready; wait"
    proc = await shell(command)
    lines = [await proc.stdout.readline() for _ in range(2)]
    assert lines[1] == b"ready\n"
    member = int(lines[0])
    assert os.getpgid(member) == member  # job control: the job leads its own group
    started = time.monotonic()
    assert await proc.terminate_tree(grace=0.5) is True
    assert 0.4 < time.monotonic() - started < 10  # it outlived TERM until the deadline
    assert await gone([member])


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


def test_a_member_that_exits_before_it_is_watched_is_skipped():
    """The race between seeing a member and watching it: a gone process is not watched."""
    from src.desktop.platform import macos_supervisor_worker as worker

    left, right = socket.socketpair()
    supervisor = worker.Worker(left)
    try:
        child = subprocess.Popen(["/usr/bin/true"])
        child.wait()  # reaped: macOS hands out numbers in order, so this one names nothing now
        supervisor.watch(child.pid)
        assert child.pid not in supervisor.watched
        supervisor.watch(os.getpid())
        supervisor.watch(os.getpid())
        assert supervisor.watched == {os.getpid()}
    finally:
        supervisor.selector.close()
        supervisor.queue.close()
        left.close()
        right.close()


def test_a_member_that_exits_while_it_is_read_is_left_out(monkeypatch):
    """The race between listing a session and reading a member: a gone member is not kept."""
    import errno

    from src.desktop.platform import macos_supervisor_worker as worker

    child = subprocess.Popen(["/usr/bin/true"])
    child.wait()  # reaped: its number names nothing now
    assert worker._identity(child.pid) == (errno.ESRCH, None, 0)
    monkeypatch.setattr(worker, "list_pids", lambda: [child.pid])
    monkeypatch.setattr(worker, "session_of", lambda pid: 4242)  # listed in the session, then gone
    assert worker.observe_session(4242) == {}


# A worker process whose leader's exit observation always fails: run() itself (it closes the
# process's own standard descriptors, so it runs in a child of the test). The first failure
# reports an error, which requests Stop with an immediate kill deadline.
_FAILING_POLL = r"""
import json, os, signal, socket, sys, time
from src.desktop.platform import macos_supervisor_worker as worker

def broken(sid):
    raise OSError("injected exit observation failure")

worker.exit_status = broken
left, right = socket.socketpair()
supervisor = worker.Worker(left)
real_io, deadline = supervisor.io, time.monotonic() + 4.0

def io(timeout):
    if time.monotonic() > deadline:
        raise SystemExit(0)
    return real_io(timeout)

supervisor.io = io
try:
    supervisor.run("trap '' TERM; exec /bin/sleep 60")
except SystemExit:
    pass
pid, status, waited = 0, 0, time.monotonic() + 5.0
while pid == 0 and time.monotonic() < waited:
    pid, status = os.waitpid(supervisor.sid, os.WNOHANG)
    time.sleep(0.05)
if pid == 0:
    os.kill(supervisor.sid, signal.SIGKILL)  # never left running by the test
    os.waitpid(supervisor.sid, 0)
with open(sys.argv[1], "w") as out:
    json.dump({"ended": pid != 0, "signal": os.WTERMSIG(status) if pid and os.WIFSIGNALED(status)
               else None, "errors": sorted(supervisor.reported_errors)}, out)
"""


def test_stop_escalates_through_run_while_the_exit_observation_keeps_failing(tmp_path):
    """run() reaches the pinned group before any observation: a leader that ignores TERM is
    killed even though its exit is never observed, and nothing is reported settled."""
    result = tmp_path / "result.json"
    subprocess.run([sys.executable, "-c", _FAILING_POLL, str(result)], cwd=ROOT, timeout=60,
                   check=True)
    outcome = json.loads(result.read_text())
    assert outcome["ended"] and outcome["signal"] == signal.SIGKILL, outcome
    assert any("worker iteration failed" in error for error in outcome["errors"]), outcome


def test_a_group_probe_that_fails_still_lets_the_pinned_group_be_signalled(monkeypatch):
    from src.desktop.platform import macos_supervisor_worker as worker

    def broken(pgid):
        raise worker.ObservationError("injected probe failure")

    left, right = socket.socketpair()
    supervisor = worker.Worker(left)
    leader = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    try:
        supervisor.leader, supervisor.sid = leader, leader.pid
        monkeypatch.setattr(worker, "group_probe", broken)
        supervisor.terminate(5.0)
        supervisor.signal_leader_group()
        assert leader.wait(10) == -signal.SIGTERM and supervisor.leader_group_termed
    finally:
        if leader.poll() is None:
            leader.kill()
            leader.wait(10)
        supervisor.selector.close()
        supervisor.queue.close()
        left.close()
        right.close()


_KILLPG = os.killpg


def _refused(pgid, number):
    """EPERM for every real signal to a group; the probe's signal 0 still answers truthfully."""
    if number == 0:
        return _KILLPG(pgid, 0)
    raise PermissionError(1, "Operation not permitted")


def test_a_group_that_empties_between_the_probe_and_the_signal_is_no_error(monkeypatch):
    """macOS answers EPERM for a group left with only zombies: its last live members ended after
    the probe said live. That isn't a refusal (CI saw it as a spurious error, 1 stop in 160 under
    load), so the stop goes on to settle."""
    from src.desktop.platform import macos_supervisor_worker as worker

    left, right = socket.socketpair()
    supervisor = worker.Worker(left)
    leader = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    try:
        supervisor.leader, supervisor.sid = leader, leader.pid
        monkeypatch.setattr(worker.os, "killpg", _refused)
        supervisor.terminate(0.0)
        supervisor.signal_leader_group()
        assert supervisor.leader_group_termed and not supervisor.failed
        assert not supervisor.reported_errors and not supervisor.outgoing
    finally:
        leader.kill()
        leader.wait(10)
        supervisor.selector.close()
        supervisor.queue.close()
        left.close()
        right.close()


def test_a_live_member_the_group_signal_cannot_reach_still_ends_unknown(monkeypatch):
    """A refused group signal with a member still alive keeps the session from settling, and the
    ten-second limit reports it: the stop ends unknown, never settled."""
    from src.desktop.platform import macos_supervisor_worker as worker

    left, right = socket.socketpair()
    supervisor = worker.Worker(left)
    leader = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    try:
        supervisor.leader, supervisor.sid = leader, leader.pid
        monkeypatch.setattr(worker.os, "killpg", _refused)  # nothing reaches the live leader
        supervisor.terminate(0.0)
        supervisor.stop_at = time.monotonic() - 11
        assert supervisor.round() is False  # the live leader is observed
        assert "cleanup exceeded ten seconds; retaining descendant ownership" in \
            supervisor.reported_errors
        assert leader.poll() is None
    finally:
        leader.kill()
        leader.wait(10)
        supervisor.selector.close()
        supervisor.queue.close()
        left.close()
        right.close()


@pytest.mark.parametrize("failing", ["observation", "event drain", "secondary group probe"])
@pytest.mark.parametrize("deadline", ["TERM", "KILL"])
def test_stop_reaches_the_pinned_group_whatever_observation_does(failing, deadline, monkeypatch):
    """The leader's own group needs no discovery: a failing observation never holds it back."""
    from src.desktop.platform import macos_supervisor_worker as worker

    def broken(*args, **kwargs):
        raise worker.ObservationError(f"injected {failing} failure")

    command = ["/bin/sleep", "60"] if deadline == "TERM" else [
        "/bin/sh", "-c", "trap '' TERM; exec /bin/sleep 60"]  # only KILL ends this one
    left, right = socket.socketpair()
    supervisor = worker.Worker(left)
    leader = subprocess.Popen(command, start_new_session=True)
    try:
        supervisor.leader, supervisor.sid = leader, leader.pid
        if failing == "observation":
            monkeypatch.setattr(worker, "observe_session", broken)
        elif failing == "event drain":
            monkeypatch.setattr(supervisor, "drain_events", broken)
        else:
            real = worker.group_probe
            monkeypatch.setattr(worker, "group_probe",
                                lambda pgid: real(pgid) if pgid == leader.pid else broken())
            supervisor.groups.add(leader.pid + 100000)  # a recorded group whose probe fails
        supervisor.terminate(5.0 if deadline == "TERM" else 0.0)
        with pytest.raises(worker.ObservationError):
            supervisor.round()
        expected = signal.SIGTERM if deadline == "TERM" else signal.SIGKILL
        assert leader.wait(10) == -expected
        assert supervisor.leader_group_termed
    finally:
        if leader.poll() is None:
            leader.kill()
            leader.wait(10)
        supervisor.selector.close()
        supervisor.queue.close()
        left.close()
        right.close()


def test_internal_commands_get_the_engines_python3_and_raw_ones_keep_path(monkeypatch):
    monkeypatch.setattr(macos_jobs, "_internal_bin", None)
    environment = macos_jobs._internal_environment({"PATH": "/usr/bin:/bin", "KEEP": "1"})
    folder = Path(environment["PATH"].split(os.pathsep)[0])
    assert environment["PATH"].split(os.pathsep)[1:] == ["/usr/bin", "/bin"]
    assert environment["KEEP"] == "1"
    info = os.lstat(folder)
    assert stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.geteuid()
    # The engine's interpreter, isolated and writing no bytecode, whatever the user's settings.
    probe = ("import sys; print(sys.executable, sys.flags.isolated, "
             "sys.flags.dont_write_bytecode, sys.argv[1:])")
    ran = subprocess.run(["python3", "-c", probe, "a b"], capture_output=True, text=True,
                         check=True, env={**environment, "PYTHONPATH": "/nowhere"})
    executable, isolated, no_bytecode, args = ran.stdout.split(" ", 3)
    assert os.path.realpath(executable) == os.path.realpath(sys.executable)
    assert (isolated, no_bytecode, args.strip()) == ("1", "1", "['a b']")
    again = macos_jobs._internal_environment(None)  # reused, and the engine's own PATH
    assert again["PATH"].split(os.pathsep)[0] == str(folder)


def test_the_engines_python3_survives_a_path_with_spaces_and_quotes(monkeypatch, tmp_path):
    odd = tmp_path / "Odin Acceptance's" / "python3.12"
    odd.parent.mkdir()
    odd.symlink_to(sys.executable)
    monkeypatch.setattr(macos_jobs.sys, "executable", str(odd))
    monkeypatch.setattr(macos_jobs, "_internal_bin", None)
    environment = macos_jobs._internal_environment({"PATH": "/usr/bin:/bin"})
    ran = subprocess.run(["python3", "-c", "print('ok')"], capture_output=True, text=True,
                         check=True, env=environment)
    assert ran.stdout == "ok\n"


@pytest.mark.parametrize("settled,release", [(True, "best_effort"), (False, "unproven")])
def test_the_poll_metadata_carries_the_scope_caveat_and_works_verdict(settled, release):
    meta = {"kind": "process_output", "pid": 7, "cleanup_verified": settled}
    plain = json.dumps(meta, separators=(",", ":"))
    extended = json.loads(macos_jobs._with_caveat_fields(plain))
    assert extended["containment"] == "session_best_effort"
    assert extended["cleanup_caveat"] == "detached or raced descendants are unverified"
    # Convergence is never a verified cleanup; the verdict is Work's own word.
    assert (extended["cleanup_verified"], extended["resource_release"]) == (False, release)
    preview = "[PID 7] status=killed\nout\n[output retention] " + plain
    head, _, tail = macos_jobs._with_caveat_fields(preview).rpartition("\n[output retention] ")
    assert head == "[PID 7] status=killed\nout"
    assert json.loads(tail) == extended
    running = json.loads(macos_jobs._with_caveat_fields(json.dumps({"kind": "process_output"})))
    assert "resource_release" not in running and "cleanup_verified" not in running
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


# --- Odin's own GNU-written commands, made portable ---------------------------------------------


async def built(tool: str, request: dict) -> str:
    """The exact command Odin's own handler builds for this request (captured, never run).

    The handler is set up as Odin's own handler tests set it up (tests/test_handlers_files_docs.py).
    """
    from unittest.mock import AsyncMock, MagicMock

    from src.tools.handlers.files_docs import FilesDocsTools
    from src.tools.hosts import HostRegistry

    resolved = ("127.0.0.1", "root", "macos")
    tools = FilesDocsTools.__new__(FilesDocsTools)
    tools._run_on_host = AsyncMock(return_value=("", 1))
    tools._govern_command = MagicMock(return_value=(True, "", None))
    tools._resolve_host = lambda host: resolved
    tools._acquire_host = lambda host: HostRegistry.unmanaged_lease(host, resolved)
    tools._deps = SimpleNamespace(config=lambda: SimpleNamespace(
        ssh_key_path="/dev/null", ssh_known_hosts_path="/dev/null"))
    await getattr(tools, f"_handle_{tool}")({"host": "localhost", **request})
    return tools._run_on_host.call_args.args[1]


def add_file(text: str) -> str:
    return f"*** Begin Patch\n*** Add File: added.txt\n+{text}\n*** End Patch\n"


LARGE = "large \u03bb payload " * 2800  # over Odin's plain command limit: it compresses this one


def runner_of(command: str) -> str:
    import base64
    import re
    import zlib

    match = re.search(r'printf %s ([A-Za-z0-9+/=]+) \| (base64 -d|python3 -c )', command)
    raw = base64.b64decode(match.group(1))
    return (raw if match.group(2) == "base64 -d" else zlib.decompress(raw)).decode()


@pytest.mark.parametrize("text", ["small", LARGE], ids=["plain", "compressed"])
async def test_odins_patch_command_is_recognized_and_portable_as_written(tmp_path, text):
    command = await built("apply_patch", {"root": str(tmp_path), "patch_text": add_file(text)})
    assert ("python3 -c" in command) == (text is LARGE)
    assert macos_jobs.engine_command(command) == "apply_patch"
    assert command.startswith(macos_jobs._APPLY_PATCH)
    assert 'chmod -- 600 "$runner" "$plan"' in command and "chmod 600 --" not in command
    runner = runner_of(command)
    assert "renameatx_np" in runner and "0x4" in runner  # Odin's own macOS rename, RENAME_EXCL


async def test_every_other_command_is_not_odins_patch():
    numbered = await built("read_file", {"path": "/etc/hosts"})
    raw = await built("read_file", {"path": "/tmp/a chmod 600 -- b", "raw": True})
    assert 'chmod -- 600 "$metadata"' in raw  # Odin's raw read is portable as written
    not_a_runner = (macos_jobs._APPLY_PATCH
                    + 'printf %s aGVsbG8= | base64 -c > "$runner" || exit 1; true')
    for command in (numbered, raw, "echo hello", 'chmod -- 600 "$runner" "$plan"', not_a_runner,
                    "x" + macos_jobs._APPLY_PATCH):
        assert macos_jobs.engine_command(command) is None


async def test_exec_command_runs_commands_as_written_and_only_patches_get_its_python(
        monkeypatch, tmp_path):
    from src.tools.executor import ToolExecutor

    patch = await built("apply_patch", {"root": str(tmp_path), "patch_text": add_file("x")})
    read = await built("read_file", {"path": "/etc/hosts", "raw": True})
    script = 'TMPF=$(mktemp) && python3 "$TMPF"'  # run_script's shape: the user's own python3
    seen = []

    async def local(command, **kwargs):
        seen.append(("local", command, kwargs["internal"]))
        return 0, "ok"

    async def remote(self, address, command, *rest):
        seen.append(("remote", command, None))
        return 0, "ok"

    monkeypatch.setattr(macos_jobs, "run_local_command", local)
    monkeypatch.setattr(ToolExecutor._exec_command, "linux_original", remote)
    fake = SimpleNamespace(config=SimpleNamespace(command_timeout_seconds=30),
                           bulkheads={}, _ensure_local_workspace=lambda: "/tmp",
                           _command_shell_mode=lambda: "bash")
    await macos_jobs.exec_command(fake, "127.0.0.1", patch)
    await macos_jobs.exec_command(fake, "127.0.0.1", read)
    await macos_jobs.exec_command(fake, "127.0.0.1", script, use_workspace=True)
    await macos_jobs.exec_command(fake, "127.0.0.1", patch, use_command_shell=True)  # raw route
    await macos_jobs.exec_command(fake, "192.0.2.5", patch)
    assert seen == [("local", patch, True), ("local", read, False), ("local", script, False),
                    ("local", patch, False), ("remote", patch, None)]


def test_a_privacy_refusal_names_the_setting_once():
    from src.tools.command_shell import CommandOutput

    refused = CommandOutput("cat: /Users/ada/Desktop/x: Operation not permitted", shell="bash",
                            reason="exited", returncode=1)
    hinted = macos_jobs.with_privacy_hint(1, refused)
    assert hinted.endswith(macos_jobs.PRIVACY_HINT) and hinted.startswith(str(refused))
    assert (hinted.effective_shell, hinted.termination_reason, hinted.raw_returncode) == (
        "bash", "exited", 1)
    assert macos_jobs.with_privacy_hint(1, hinted) == hinted  # once
    assert macos_jobs.with_privacy_hint(
        1, "ls: /Volumes/Backup: Operation not permitted").endswith("then try again.")
    for code, text in ((0, "cat: /Users/ada/Desktop/x: Operation not permitted, then it worked"),
                       (1, "cat: /Users/ada/Desktop/x: No such file or directory"),
                       (1, "chflags: /tmp/locked: Operation not permitted")):  # not a privacy place
        assert macos_jobs.with_privacy_hint(code, text) == text


async def test_exec_command_adds_the_privacy_hint_to_local_failures_only(monkeypatch):
    from src.tools.executor import ToolExecutor

    async def local(command, **kwargs):
        return 1, "ls: /Users/ada/Documents: Operation not permitted"

    async def remote(self, address, command, *rest):
        return 1, "ls: /Users/ada/Documents: Operation not permitted"

    monkeypatch.setattr(macos_jobs, "run_local_command", local)
    monkeypatch.setattr(ToolExecutor._exec_command, "linux_original", remote)
    fake = SimpleNamespace(config=SimpleNamespace(command_timeout_seconds=30),
                           bulkheads={}, _ensure_local_workspace=lambda: "/tmp",
                           _command_shell_mode=lambda: "bash")
    code, text = await macos_jobs.exec_command(fake, "127.0.0.1", "ls ~", use_command_shell=True)
    assert code == 1 and text.endswith(macos_jobs.PRIVACY_HINT)
    code, text = await macos_jobs.exec_command(fake, "192.0.2.5", "ls ~", use_command_shell=True)
    assert text == "ls: /Users/ada/Documents: Operation not permitted"  # another computer's


async def test_a_full_bulkhead_refuses_a_local_command(monkeypatch):
    from src.tools.bulkhead import BulkheadFullError

    class Full:
        def acquire(self):
            raise BulkheadFullError("subprocess", 1, 0)

    fake = SimpleNamespace(config=SimpleNamespace(command_timeout_seconds=30),
                           bulkheads={"subprocess": Full()}, _ensure_local_workspace=lambda: "/tmp",
                           _command_shell_mode=lambda: "sh")
    code, text = await macos_jobs.exec_command(fake, "127.0.0.1", "true")
    assert code == 1 and "bulkhead full" in text


# --- run_local_command's other outcomes ---------------------------------------------------------


async def test_a_command_that_outlives_its_timeout_is_stopped():
    started = time.monotonic()
    code, output = await macos_jobs.run_local_command("sleep 30", timeout=1)
    assert code == 1 and "timed out after 1 seconds" in str(output)
    assert time.monotonic() - started < 20


async def test_streamed_output_reaches_the_callback():
    lines = []

    async def collect(line):
        lines.append(line)

    code, output = await macos_jobs.run_local_command("echo one; echo two", timeout=20,
                                                      on_output=collect)
    assert code == 0 and "two" in str(output) and lines


async def test_an_unavailable_shell_and_a_failed_start_are_reported(monkeypatch):
    from src.tools.command_shell import ShellUnavailableError

    def unavailable(mode):
        raise ShellUnavailableError("no bash here")

    monkeypatch.setattr("src.tools.command_shell.resolve_local_shell", unavailable)
    code, output = await macos_jobs.run_local_command("true", command_shell="bash")
    assert code == 1 and "no bash here" in str(output)
    monkeypatch.undo()

    async def broken(*args, **kwargs):
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(macos_jobs, "create_supervised_shell", broken)
    code, output = await macos_jobs.run_local_command("true")
    assert code == 1 and str(output).startswith("Local exec error")


async def test_a_session_start_needs_a_private_session_and_an_open_loop(monkeypatch):
    with pytest.raises(ValueError, match="private session"):
        await macos_jobs.create_supervised_shell("true", start_new_session=False)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(macos_jobs._ls, "_closing_loops", {loop})
    with pytest.raises(macos_jobs._ls.SupervisorError, match="shutting down"):
        await macos_jobs.create_supervised_shell("true")


async def test_a_worker_that_never_starts_is_cleaned_up_and_reported(monkeypatch):
    """No start frame within ten seconds: the shell is torn down and the launch fails."""
    real = asyncio.create_subprocess_exec
    spawned = []

    async def silent(program, *args, **kwargs):
        process = await real(program, "-c", "import time; time.sleep(60)", **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(macos_jobs.asyncio, "create_subprocess_exec", silent)
    try:
        with pytest.raises((TimeoutError, macos_jobs._ls.SupervisorError)):
            await macos_jobs.create_supervised_shell("true", stdout=PIPE)
    finally:
        for process in spawned:  # its control channel closes: the monitor ends
            process.kill()
            await process.wait()
        await asyncio.sleep(0.2)


async def test_the_worker_runs_isolated_and_writes_no_bytecode(monkeypatch):
    """The installed app ships no bytecode and is its user's to write: -B keeps the worker's
    standard library imports from writing any into it."""
    launched = []

    async def record(program, *args, **kwargs):
        launched.append((program, args))
        raise OSError("recorded")

    monkeypatch.setattr(macos_jobs.asyncio, "create_subprocess_exec", record)
    with pytest.raises(OSError):
        await macos_jobs.create_supervised_shell("true", stdout=PIPE)
    (program, args), = launched
    assert program == sys.executable
    assert args[:3] == ("-I", "-B", str(Path(macos_jobs.__file__).with_name(
        "macos_supervisor_worker.py")))


async def test_a_failed_worker_spawn_is_reported(monkeypatch):
    async def refuse(*args, **kwargs):
        raise OSError("no processes")

    monkeypatch.setattr(macos_jobs.asyncio, "create_subprocess_exec", refuse)
    with pytest.raises(OSError):
        await macos_jobs.create_supervised_shell("true", stdout=PIPE)


# --- The registry's own paths ------------------------------------------------------------------


@pytest.fixture
def registry(tmp_path):
    return macos_jobs.MacOSProcessRegistry(workspace=str(tmp_path), retention_dir=tmp_path / "out",
                                           command_shell="sh")


async def test_the_registry_refuses_remote_and_unusable_starts(registry, monkeypatch):
    from src.tools.workspace import WorkspaceError

    assert (await macos_jobs.start_local_reserved(registry, "192.0.2.5", "true")).startswith(
        "Error: remote process start")
    registry._revoking_aliases["localhost"] = 1
    assert "force-revoked" in await macos_jobs.start_local_reserved(registry, "localhost", "true")
    del registry._revoking_aliases["localhost"]

    def no_workspace():
        raise WorkspaceError("missing")

    monkeypatch.setattr(registry, "_resolve_workspace", no_workspace)
    assert "cannot start background process" in await macos_jobs.start_local_reserved(
        registry, "localhost", "true")


async def test_the_registry_reports_a_failed_start(registry, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(macos_jobs, "create_supervised_shell", broken)
    assert (await macos_jobs.start_local_reserved(registry, "localhost", "true")).startswith(
        "Failed to start process")


async def test_a_local_job_is_labelled_and_its_kill_carries_the_caveat(registry):
    started = await registry.start("localhost", "sleep 30")
    pid = int(started.split("PID ")[1].split(")")[0])
    info = registry._processes[pid]
    assert info.containment == "session_best_effort"
    page = macos_jobs.MacOSProcessRegistry._output_page(info, b"", 0, 100, 4000, preview=True)
    assert '"containment":"session_best_effort"' in page
    killed = await registry.kill(pid)
    assert killed == (f"Process {pid} killed. containment=session_best_effort; "
                      "detached or raced descendants are unverified.")
    again = await registry.kill(pid)
    assert again.endswith("detached or raced descendants are unverified.")
    other = SimpleNamespace(**{**info.__dict__, "containment": ""})
    assert '"containment"' not in macos_jobs.MacOSProcessRegistry._output_page(
        other, b"", 0, 100, 4000, preview=True)


# --- Odin 4.19.2: a foreground result survives a late settlement ACK ----------------------------


@pytest.fixture
def owned(monkeypatch):
    """Private supervisor state: a late ACK leaves its shell owned and vetoes relaunch."""
    monkeypatch.setattr(macos_jobs._ls, "_active", set())
    monkeypatch.setattr(macos_jobs._ls, "_pending", set())
    monkeypatch.setattr(macos_jobs._ls, "_closing_loops", set())
    monkeypatch.setattr(macos_jobs._ls, "_unverified_startup", False)
    veto = Mock()
    monkeypatch.setattr("src.restart.block_reexec", veto)
    return veto


async def held_until_the_ack_is_late(proc):
    time.sleep(3.0)  # the command finishes and the worker gives up on the ACK
    await asyncio.wait({proc._monitor_task}, timeout=10)


@pytest.mark.parametrize("streamed", [False, True])
async def test_the_foreground_wrapper_keeps_its_result_after_a_late_ack(
        owned, monkeypatch, streamed):
    real, shells, seen = macos_jobs.create_supervised_shell, [], []

    async def holding(*args, **kwargs):
        proc = await real(*args, **kwargs)
        shells.append(proc)
        await held_until_the_ack_is_late(proc)
        return proc

    async def collect(text):
        seen.append(text)

    monkeypatch.setattr(macos_jobs, "create_supervised_shell", holding)
    code, output = await macos_jobs.run_local_command(
        "printf 'late-ack\\nresult\\n'; exit 7", timeout=30,
        on_output=collect if streamed else None)
    assert code == 7 and "result" in str(output)
    if streamed:
        assert "".join(seen) == "late-ack\nresult\n"
    (proc,) = shells
    assert proc._allow_foreground_ack_result and proc._ack_lost_after_clean
    assert proc._settled.exception() is not None and proc in macos_jobs._ls._active
    owned.assert_called_with("local command supervisor ownership lost")


async def test_a_shell_without_the_opt_in_still_reports_ownership_lost(owned):
    proc = await shell("printf done; exit 7")
    await held_until_the_ack_is_late(proc)
    assert proc._ack_lost_after_clean and not proc._allow_foreground_ack_result
    with pytest.raises(macos_jobs._ls.SupervisorError, match="ownership lost"):
        await proc.communicate()
    owned.assert_called_with("local command supervisor ownership lost")


async def test_background_jobs_never_opt_in(registry):
    started = await registry.start("localhost", "sleep 30")
    pid = int(started.split("PID ")[1].split(")")[0])
    assert registry._processes[pid].process._allow_foreground_ack_result is False
    await registry.kill(pid)
