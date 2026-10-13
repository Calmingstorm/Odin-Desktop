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
async def test_odins_patch_command_gets_bsd_chmod_and_the_hosts_rename(tmp_path, text):
    command = await built("apply_patch", {"root": str(tmp_path), "patch_text": add_file(text)})
    assert ("python3 -c" in command) == (text is LARGE)
    assert macos_jobs.engine_command(command) == "apply_patch"
    portable = macos_jobs.portable_command(command)
    opening = macos_jobs._APPLY_PATCH
    assert portable.startswith(opening.replace('chmod 600 -- "$runner"', 'chmod -- 600 "$runner"'))
    assert "chmod 600 --" not in portable
    runner = runner_of(portable)
    assert "renameatx_np" in runner and "rename_noreplace=_rename)" in runner
    assert runner_of(command) not in runner and "renameatx_np" not in runner_of(command)
    compile(runner, "runner", "exec")  # still a valid program
    after = '> "$runner" || exit 1; '  # the plan and the call are Odin's, unchanged
    assert portable.split(after, 1)[1] == command.split(after, 1)[1]


async def test_odins_raw_read_command_gets_bsd_chmod_and_nothing_else():
    path = "/tmp/a chmod 600 -- b"  # Odin's text inside a path is the path's: never rewritten
    command = await built("read_file", {"path": path, "raw": True})
    assert macos_jobs.engine_command(command) == "read_file"
    portable = macos_jobs.portable_command(command)
    opening = macos_jobs._READ_FILE_RAW
    assert portable[:len(opening)] == opening.replace("chmod 600 --", "chmod -- 600")
    assert portable[len(opening):] == command[len(opening):]
    assert "'/tmp/a chmod 600 -- b'" in portable


async def test_every_other_command_runs_exactly_as_written():
    numbered = await built("read_file", {"path": "/etc/hosts"})  # numbered reads need nothing
    not_a_runner = (macos_jobs._APPLY_PATCH
                    + 'printf %s aGVsbG8= | base64 -c > "$runner" || exit 1; true')
    for command in (numbered, "echo hello", 'chmod 600 -- "$runner" "$plan"', not_a_runner,
                    "x" + macos_jobs._READ_FILE_RAW):
        assert macos_jobs.engine_command(command) is None
        assert macos_jobs.portable_command(command) == command


def test_a_runner_that_is_not_odins_keeps_its_payload():
    tail = 'printf %s aGVsbG8= | base64 -d > "$runner" || exit 1; python3 "$runner" / < "$plan"'
    command = macos_jobs._APPLY_PATCH + tail
    assert macos_jobs.engine_command(command) == "apply_patch"
    assert macos_jobs.portable_command(command).endswith(tail)  # it fails honestly as written


async def test_exec_command_rewrites_odins_commands_and_only_patches_get_its_python(
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
    portable = macos_jobs.portable_command
    assert seen == [("local", portable(patch), True), ("local", portable(read), False),
                    ("local", script, False), ("local", patch, False),
                    ("remote", portable(patch), None)]


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
