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


# --- Engine-built commands made portable -------------------------------------------------------


def _runner_command(text: str, *, compressed: bool) -> str:
    import base64
    import shlex
    import zlib

    raw = text.encode()
    if compressed:
        payload = base64.b64encode(zlib.compress(raw)).decode()
        decoder = shlex.quote("import base64,sys,zlib; sys.stdout.buffer.write("
                              "zlib.decompress(base64.b64decode(sys.stdin.buffer.read())))")
        return (f'runner=$(mktemp) || exit 1; chmod 600 -- "$runner" || exit 1; '
                f'printf %s {payload} | python3 -c {decoder} > "$runner" || exit 1; '
                'python3 "$runner" /root')
    payload = base64.b64encode(raw).decode()
    return (f'runner=$(mktemp) || exit 1; chmod 600 -- "$runner" || exit 1; '
            f'printf %s {payload} | base64 -d > "$runner" || exit 1; python3 "$runner" /root')


RUNNER = ("def apply_plan(root, plan, *, rename_noreplace=None):\n    pass\n"
          "\nimport json\nimport sys as _sys\ntry:\n    _plan = json.loads(_sys.stdin.read())\n"
          "    _changed = apply_plan(_sys.argv[1], _plan)\nexcept BaseException:\n    pass\n")


@pytest.mark.parametrize("compressed", [False, True])
def test_the_patch_runner_gets_the_hosts_rename(compressed):
    import base64
    import re
    import zlib

    portable = macos_jobs.portable_command(_runner_command(RUNNER, compressed=compressed))
    assert 'chmod -- 600 "$runner"' in portable and "chmod 600 --" not in portable
    payload = re.search(r"printf %s ([A-Za-z0-9+/=]+) \|", portable).group(1)
    raw = base64.b64decode(payload)
    text = (zlib.decompress(raw) if compressed else raw).decode()
    assert "renameatx_np" in text and "rename_noreplace=_rename)" in text
    compile(text, "runner", "exec")  # still a valid program


@pytest.mark.parametrize("command", [
    "echo hello",                                                      # nothing to change
    'printf %s aGVsbG8= | base64 -d > "$runner"',                     # not Odin's runner
    'printf %s %%%% | base64 -d > "$runner"',                         # not base64 at all
])
def test_other_commands_are_left_as_they_are(command):
    assert macos_jobs.portable_command(command) == command


async def test_exec_command_rewrites_only_engine_built_commands(monkeypatch):
    from src.tools.executor import ToolExecutor

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
    await macos_jobs.exec_command(fake, "127.0.0.1", "chmod 600 -- x")
    await macos_jobs.exec_command(fake, "127.0.0.1", "chmod 600 -- x", use_command_shell=True)
    await macos_jobs.exec_command(fake, "192.0.2.5", "chmod 600 -- x")
    assert seen == [("local", "chmod -- 600 x", True), ("local", "chmod 600 -- x", False),
                    ("remote", "chmod -- 600 x", None)]


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
