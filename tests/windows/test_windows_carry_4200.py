"""Odin 4.20.0 (PR #671) on Windows: the carried fixes through Windows' own routes.

- A remote job start is one direct SSH attempt through the registry the executor builds here,
  down to Windows' OpenSSH launch; other remote operations keep their retries.
- Jobs an agent started are recorded with it and stopped when it is killed, including a start
  still settling.
- A local read refuses directories and directory links in both modes; a remote read sends
  Odin's own command (directory guard, ``rc``, newline placement) and drops only gawk's
  locale warning.
- Process previews offer a continuation exactly as Odin's do.
- apply_patch keeps exact line endings through the Windows handler and its child.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from types import SimpleNamespace

import pytest

from src.agents.execution_context import JobOrigin
from src.config.schema import RetryConfig, ToolsConfig
from src.desktop.platform import windows_tools
from src.desktop.platform.windows_jobs import WindowsProcessRegistry
from src.desktop.platform.windows_tools import handle_read_file
from src.tools.executor import ToolExecutor
from src.tools.handlers.files_docs import FilesDocsTools
from src.tools.process_manager import ProcessRegistry
from tests.test_desktop_process_preview_continuation import _info, _meta
from tests.windows.test_windows_patch import apply, junction, patch
from tests.windows.test_windows_read import tool as read_tool

AGENT = JobOrigin("agent-a", "root-a")
TIMED_OUT = "ssh: connect to host 192.0.2.10 port 22: Connection timed out\r\n"
RESET = "Connection reset by peer\r\n"


# --- One direct attempt for remote starts ----------------------------------------------------


class _Process:
    def __init__(self, code: int, output: str) -> None:
        self.returncode, self.pid, self._output = code, 4242, output.encode()

    async def communicate(self):
        return self._output, b""


class _Lease:
    revoked = False

    def __init__(self) -> None:
        self.target = SimpleNamespace(
            alias="server", address="192.0.2.10", ssh_user="odin", key_path=r"C:\k",
            known_hosts_path=r"C:\kh", port=22, host_key_alias="", runtime_key="rk", local=False)
        self.release_count = 0

    async def run(self, factory):
        assert self.release_count == 0
        return await factory()

    def release(self) -> None:
        self.release_count += 1


def _route(monkeypatch, tmp_path, replies):
    """The executor and registry this platform builds, with ssh at its subprocess boundary."""
    spawned = []

    async def spawn(*argv, **kwargs):
        spawned.append((argv, kwargs))
        return _Process(*replies[min(len(spawned), len(replies)) - 1])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    executor = ToolExecutor(config=ToolsConfig(
        ssh_retry=RetryConfig(max_retries=3, base_delay=0.0, max_delay=0.0)))
    executor._memory_path = str(tmp_path / "memory.json")  # retention under the test's folder
    registry = executor._ensure_process_registry()
    assert type(registry) is WindowsProcessRegistry
    return executor, registry, spawned


async def test_an_unreachable_host_start_is_one_direct_attempt_and_definite(
        monkeypatch, tmp_path):
    _executor, registry, spawned = _route(monkeypatch, tmp_path, [(255, TIMED_OUT)])
    lease = _Lease()

    result = await registry.start_remote(lease, "sleep 45")

    assert result.startswith("Failed to start process: could not connect to server;")
    assert "nothing was started, so retrying is safe" in result
    assert len(spawned) == 1  # configured retries are 3; no teardown either
    argv, kwargs = spawned[0]
    assert argv[0].lower().endswith(r"\openssh\ssh.exe")
    assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert lease.release_count == 1
    assert registry._pending_remote_reservations == 0 and registry._pending_starts == 0
    await registry.shutdown()


async def test_an_ambiguous_start_stays_unknown_and_is_torn_down(monkeypatch, tmp_path):
    _executor, registry, spawned = _route(monkeypatch, tmp_path, [(255, RESET), (0, "{}")])
    lease = _Lease()

    result = await registry.start_remote(lease, "sleep 45")

    assert "outcome_unknown=true" in result and "safe" not in result
    assert len(spawned) == 2  # the one start attempt, then the normal teardown
    assert lease.release_count == 1
    await registry.shutdown()


async def test_other_remote_operations_keep_their_retries(monkeypatch, tmp_path):
    executor, registry, spawned = _route(monkeypatch, tmp_path, [(255, TIMED_OUT)])

    await executor._exec_remote_target(_Lease().target, "poll the job", 30)

    assert len(spawned) == 3
    await registry.shutdown()


# --- Jobs an agent started --------------------------------------------------------------------


@pytest.fixture
async def jobs(tmp_path):
    registry = WindowsProcessRegistry(workspace=str(tmp_path), command_shell="auto")
    yield registry
    await registry.shutdown()


def pid_of(started: str) -> int:
    return int(started.split("PID ")[1].split(")")[0])


async def test_an_agents_job_is_recorded_and_stopped_with_it(jobs):
    plain = pid_of(await jobs.start("localhost", "Start-Sleep 60"))
    pid = pid_of(await jobs.start("localhost", "Start-Sleep 60", origin=AGENT))
    info = jobs._processes[pid]
    assert (info.origin_agent_id, info.origin_root_id) == ("agent-a", "root-a")
    assert (jobs._processes[plain].origin_agent_id, jobs._processes[plain].origin_root_id) == (
        "", "")

    assert jobs.reap_agent_jobs({"someone-else"}).jobs == []
    cleanup = jobs.reap_agent_jobs({"agent-a"})
    outcome = await cleanup.wait(timeout=60)

    assert outcome == {"jobs": {info.generation: "stopped"}, "starts": []}
    assert cleanup.describe(outcome) == f"Stopped 1 background job(s) it started (PID {pid})."
    assert jobs._processes[plain].status == "running"  # an ordinary job is not the agent's


async def test_a_start_settling_when_its_agent_is_killed_is_stopped(jobs, monkeypatch):
    gate = asyncio.Event()
    real = windows_tools.create_job_shell
    shells = []

    async def spawn(*args, **kwargs):
        await gate.wait()  # the kill lands while the job is still being started
        shell = await real(*args, **kwargs)
        shells.append(shell)
        return shell

    monkeypatch.setattr(windows_tools, "create_job_shell", spawn)
    invocation = asyncio.create_task(jobs.start("localhost", "Start-Sleep 60", origin=AGENT))
    for _ in range(200):
        if jobs._agent_starts:
            break
        await asyncio.sleep(0.01)
    cleanup = jobs.reap_agent_jobs({"agent-a"})
    gate.set()

    outcome = await cleanup.wait(timeout=60)
    assert outcome == {"jobs": {}, "starts": ["stopped"]}
    assert cleanup.describe(outcome) == "Stopped 1 job(s) whose start was in progress."
    assert "stopped while it started" in await invocation
    assert len(shells) == 1 and shells[0].returncode is not None  # the real job ended


# --- read_file ----------------------------------------------------------------------------------


@pytest.fixture
def budget(monkeypatch):
    import src.tools.output_delivery as delivery

    monkeypatch.setattr(delivery, "get_delivery_budget", lambda config: 11_500)


@pytest.mark.parametrize("raw", [False, True], ids=["numbered", "raw"])
@pytest.mark.parametrize("kind", ["directory", "junction", "symlink"])
async def test_a_local_directory_or_directory_link_is_refused(tmp_path, budget, kind, raw):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "inside.txt").write_bytes(b"inside\n")
    path = folder
    if kind == "junction":
        path = tmp_path / "joined"
        junction(path, folder)
    elif kind == "symlink":
        path = tmp_path / "linked"
        try:
            os.symlink(folder, path, target_is_directory=True)
        except OSError:
            pytest.skip("this account can't create symbolic links")
    fake, calls = read_tool()

    result = await handle_read_file(fake, {"path": str(path), "host": "localhost", "raw": raw})

    text, code = result
    assert code == 2 and "cannot open" in text, result
    assert "inside" not in text and "[returned" not in text
    assert calls == []


async def _odins_command(args: dict) -> str:
    """The command Odin's own handler (the Linux original behind the router) sends."""
    odin = FilesDocsTools.__new__(FilesDocsTools)
    odin._deps = SimpleNamespace(config=lambda: SimpleNamespace())
    sent = []

    async def run_on_host(_host, command):
        sent.append(command)
        return "", 0

    odin._run_on_host = run_on_host
    await FilesDocsTools._handle_read_file.linux_original(odin, args)
    return sent[0]


def _ignoring_indentation(command: str) -> str:
    """The command with each line's leading spaces removed. The Windows copy of the handler is
    lifted with one dedent of the whole function (the port's convention), which also dedents
    the awk program text inside it. awk ignores that whitespace."""
    return "\n".join(line.lstrip(" ") for line in command.split("\n"))


@pytest.mark.parametrize("raw", [False, True], ids=["numbered", "raw"])
async def test_a_remote_read_sends_odins_own_command(budget, raw):
    args = {"path": "/srv/a dir/it's.txt", "host": "server", "raw": raw, "lines": 7,
            "start_line": 3}
    fake, calls = read_tool(address="192.0.2.10")

    await handle_read_file(fake, args)

    odin = await _odins_command(args)
    assert len(calls) == 1
    assert _ignoring_indentation(calls[0]) == _ignoring_indentation(odin)
    # Everything around the awk program is byte for byte Odin's.
    assert calls[0].split("\n", 1)[0] == odin.split("\n", 1)[0]
    assert calls[0].rsplit("\n", 1)[1] == odin.rsplit("\n", 1)[1]
    assert calls[0].startswith("if [ -d ")  # the directory guard, in both modes
    assert "status=$?" not in calls[0]
    assert ("rc=$?" in calls[0]) is raw


async def test_a_remote_numbered_read_drops_only_gawks_locale_warning(budget):
    warning = ("awk: cmd. line:16: (FILENAME=- FNR=1) warning: Invalid multibyte data "
               "detected. There may be a mismatch between your data and your locale\n")
    other = "awk: cmd. line:3: warning: something else\n"
    calls = []

    async def exec_command(address, command, ssh_user, target=None):
        calls.append(command)
        return 0, "1: caf\ufffd\n" + warning + other + "\n[returned 1-1]"

    fake, _ = read_tool(address="192.0.2.10")
    fake._exec_command = exec_command

    text, code = await handle_read_file(fake, {"path": "/srv/latin1.txt", "host": "server"})

    assert code == 0
    assert "Invalid multibyte data" not in text
    assert "something else" in text and "1: caf" in text


# --- Process previews ---------------------------------------------------------------------------

CLIPPED = b"".join(b"line %04d of retained output\n" % i for i in range(400))
PREVIEWS = {
    "complete": (dict(status="completed", retained=11), b"job-1-done\n", 0, 8000, {}),
    "tail-only": (dict(status="completed", retained=5000), b"last lines\n", 4989, 8000, {}),
    "clipped": (dict(status="completed", retained=len(CLIPPED)), CLIPPED, 0, 2000, {}),
    "empty": (dict(status="running", retained=0), b"", 0, 8000, {}),
    "withheld-tail": (dict(status="completed", retained=11), b"job-1-done\n", 0, 8000,
                      {"tail_withheld": True}),
    "capture-loss": (dict(status="completed", retained=11, emitted=50), b"job-1-done\n", 0, 8000,
                     {}),
}


@pytest.mark.parametrize("name", sorted(PREVIEWS))
def test_a_windows_preview_offers_a_continuation_as_odins_does(name):
    fields, data, start, budget_chars, extra = PREVIEWS[name]
    info = _info(**fields)
    page = WindowsProcessRegistry._output_page(info, data, start, 4000, budget_chars,
                                               preview=True, **extra)
    assert page == ProcessRegistry._output_page(info, data, start, 4000, budget_chars,
                                                preview=True, **extra)
    expected_cursor = {"complete": None, "empty": None, "capture-loss": None}
    assert _meta(page)["cursor"] == expected_cursor.get(name, "gen:0")
    assert len(page) <= budget_chars


# --- apply_patch line endings -------------------------------------------------------------------


@pytest.mark.parametrize("source,hunks,expected", [
    (b"", ["+hello"], b"hello\n"),
    (b"", ["+one", "+two"], b"one\ntwo\n"),
    (b"one\ntwo", [" two\n+three"], b"one\ntwo\nthree"),
    (b"a\r\nb", [" b\n+c"], b"a\r\nb\r\nc"),
    (b"a\r\nb\nc", [" a\n b\n c\n+d"], b"a\r\nb\nc\nd"),
    (b"a\nb\r\nc", [" b\n c\n+d\n+e"], b"a\nb\r\nc\r\nd\r\ne"),
    (b"one\r\ntwo\r\n", [" two\n+three"], b"one\r\ntwo\r\nthree\r\n"),
    (b"1\n2\n3\n4\n5\n6\n7\n8\n9", [" 1\n-2\n+TWO", " 8\n-9\n+NINE\n+TEN"],
     b"1\nTWO\n3\n4\n5\n6\n7\n8\nNINE\nTEN"),
], ids=["empty", "empty-two-hunks", "unterminated-tail", "crlf-tail", "mixed-kept",
        "mixed-repaired", "crlf-terminated", "multi-hunk"])
async def test_patched_bytes_are_exact_through_the_windows_child(tmp_path, source, hunks,
                                                                   expected):
    target = tmp_path / "text.txt"
    target.write_bytes(source)
    body = [line for hunk in hunks for line in ("@@", *hunk.split("\n"))]

    result, sent = await apply(tmp_path, patch("*** Update File: text.txt", *body))

    assert sent == []  # the local child did the work
    assert target.read_bytes() == expected, result


async def test_a_start_its_agent_lost_keeps_an_unproven_job_unknown(jobs, monkeypatch):
    from src.tools.process_manager import _AgentStart

    async def unproven(_info):
        return False

    monkeypatch.setattr(jobs, "_terminate_bound_host_job", unproven)
    start = _AgentStart(origin=AGENT)
    start.abandoned = True  # the invocation was cancelled while this start settled

    result = await windows_tools.start_local_reserved(
        jobs, "localhost", "Start-Sleep 60", origin=AGENT, agent_start=start)

    assert result.endswith("process outcome unknown outcome_unknown=true.")
    assert start.outcome == "unknown"
    (info,) = jobs._processes.values()
    assert info.status == "unknown" and info.capture_error
    monkeypatch.undo()
    await jobs.kill(info.pid)


async def test_a_lifecycle_that_cannot_be_installed_stops_the_new_job(jobs, monkeypatch):
    shells = []
    real = windows_tools.create_job_shell

    async def spawn(*args, **kwargs):
        shell = await real(*args, **kwargs)
        shells.append(shell)
        return shell

    def broken(_info):
        raise RuntimeError("fixture: output persistence unavailable")

    monkeypatch.setattr(windows_tools, "create_job_shell", spawn)
    monkeypatch.setattr(jobs, "_persist_output", broken)

    with pytest.raises(RuntimeError, match="output persistence unavailable"):
        await jobs.start("localhost", "Start-Sleep 60")

    (shell,) = shells
    for _ in range(200):
        if shell.returncode is not None:
            break
        await asyncio.sleep(0.05)
    assert shell.returncode is not None  # torn down, not left running untracked
