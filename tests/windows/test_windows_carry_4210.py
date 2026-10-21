"""Odin 4.21.0 (PR #672) on Windows: remote foreground commands through Windows' own routes.

- run_command, run_script, run_command_multi and validate_action send a remote command under
  Odin's coordinator with the ssh client's stdin held open and never written, so the command
  ends when its connection closes. Windows' OpenSSH has no ControlMaster, so such a command
  gets one attempt: a 255 or a timeout is returned once and marked uncertain.
- The client's cleanup is carried to its reap through cancellation. An exit Windows does not
  confirm within the bound is marked uncertain and said in the result, never passed off as
  settled.
- A command line over CreateProcess's limit is refused before anything starts; the count is
  checked against CreateProcess itself.
- Live, with this machine's SSH test target: a cancelled remote command ends on the host.
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
import subprocess
import sys

import pytest

from src.desktop.platform import windows_ssh as wssh
from src.desktop.platform import windows_tools
from src.desktop.platform.windows_tools import exec_command, handle_validate_action
from src.tools.execution_outcome import DispatchEvidence, dispatch_evidence
from tests.windows.test_windows_scripts import run, tool
from tests.windows.test_windows_ssh import (  # noqa: F401 (target is a fixture)
    FakeProcess,
    live,
    spawning,
    ssh,
    target,
)
from tests.windows.test_windows_ssh import executor as ssh_executor
from tests.windows.test_windows_validate import validator


@contextlib.contextmanager
def _evidence():
    evidence = DispatchEvidence()
    token = dispatch_evidence.set(evidence)
    try:
        yield evidence
    finally:
        dispatch_evidence.reset(token)


class _Client(FakeProcess, asyncio.subprocess.Process):
    """FakeProcess as an asyncio process, so the runner takes its settled cleanup."""

    returncode = None  # a plain attribute here, not the transport's property
    pid = 4242


class _LateExit(_Client):
    """Ended at once, reaped only 0.3 s later."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._exited = asyncio.Event()

    def kill(self):
        self.killed = True
        asyncio.get_running_loop().call_later(0.3, self._exited.set)

    async def wait(self):
        await self._exited.wait()
        self.returncode = 1
        return 1


class _NeverExits(_Client):
    """A client whose end Windows never reports (the kill and the wait settle nothing)."""

    def __init__(self, *args, kill_error=None, wait_error=None, **kwargs):
        super().__init__(*args, hang=True, **kwargs)
        self._kill_error, self._wait_error = kill_error, wait_error

    def kill(self):
        self.killed = True
        if self._kill_error is not None:
            raise self._kill_error

    async def wait(self):
        if self._wait_error is not None:
            raise self._wait_error
        await asyncio.sleep(60)


@pytest.fixture
def short_bound(monkeypatch):
    monkeypatch.setattr(wssh, "END_CLIENT_SECONDS", 0.2)


# --- The runner -------------------------------------------------------------------------------


async def test_a_user_command_runs_under_the_coordinator_with_its_stdin_held_open(monkeypatch):
    argvs = spawning(monkeypatch, FakeProcess(0, lines=[b"ok\n"]))
    assert await ssh(end_with_channel=True) == (0, "ok\n")
    argv, kwargs = argvs[0]
    assert argv[-1].startswith("odin_fg_command=true; ")
    assert kwargs["stdin"] is asyncio.subprocess.PIPE
    assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    # Every other command keeps the plain command and a closed stdin.
    argvs = spawning(monkeypatch, FakeProcess(0, b"ok\n"))
    assert await ssh() == (0, "ok\n")
    argv, kwargs = argvs[0]
    assert argv[-1] == "true" and kwargs["stdin"] is asyncio.subprocess.DEVNULL


async def test_a_255_is_returned_once_and_uncertain(monkeypatch):
    refused = b"ssh: connect to host h port 22: Connection refused\n"
    argvs = spawning(monkeypatch, FakeProcess(255, lines=[refused]),
                     FakeProcess(0, lines=[b"ran twice\n"]))
    with _evidence() as evidence:
        assert await ssh(end_with_channel=True) == (255, refused.decode())
    assert len(argvs) == 1 and evidence.uncertain


async def test_a_timeout_is_never_sent_twice(monkeypatch):
    hung = FakeProcess(hang=True)
    argvs = spawning(monkeypatch, hung, FakeProcess(0, lines=[b"ran twice\n"]))
    with _evidence() as evidence:
        assert await ssh(end_with_channel=True, timeout=0.2) == (
            1, "Command timed out after 0.2 seconds")
    assert len(argvs) == 1 and hung.killed and evidence.uncertain


# --- The settled cleanup ----------------------------------------------------------------------


async def test_the_settled_cleanup_confirms_the_reap():
    client = _Client(hang=True)
    with _evidence() as evidence:
        assert await wssh.end_client_settled(client) is True
    assert client.killed and client.returncode == 1 and not evidence.uncertain


async def test_a_repeated_cancellation_still_waits_for_the_reap():
    client = _LateExit()
    task = asyncio.create_task(wssh.end_client_settled(client))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.killed and client.returncode == 1  # reaped before the cancellation was raised


async def test_an_exit_windows_does_not_confirm_is_uncertain_and_warned(short_bound, caplog):
    client = _NeverExits()
    with _evidence() as evidence, caplog.at_level(logging.WARNING):
        assert await wssh.end_client_settled(client) is False
    assert client.killed and client.returncode is None and evidence.uncertain
    assert any("was not reaped" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("failure", ["kill", "wait"])
async def test_a_failed_kill_or_reap_leaves_the_exit_unconfirmed(short_bound, failure):
    client = (_NeverExits(kill_error=OSError("access denied")) if failure == "kill"
              else _NeverExits(wait_error=OSError("reap failed")))
    with _evidence() as evidence:
        assert await wssh.end_client_settled(client) is False
    assert client.returncode is None and evidence.uncertain


async def test_a_cancellation_near_the_bound_is_raised_with_the_exit_unconfirmed(monkeypatch):
    monkeypatch.setattr(wssh, "END_CLIENT_SECONDS", 0.3)
    client = _NeverExits()
    with _evidence() as evidence:
        task = asyncio.create_task(wssh.end_client_settled(client))
        await asyncio.sleep(0.25)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert client.returncode is None and evidence.uncertain


@pytest.mark.parametrize("streamed", [False, True])
async def test_an_unconfirmed_exit_is_said_in_the_result(monkeypatch, short_bound, streamed):
    spawning(monkeypatch, _NeverExits())

    async def collect(_text):
        return None

    with _evidence() as evidence:
        code, text = await ssh(end_with_channel=True, timeout=0.2,
                               on_output=collect if streamed else None)
    assert code == 1 and "timed out after 0.2 seconds" in text
    assert text.endswith(wssh.UNCONFIRMED_EXIT_NOTE) and evidence.uncertain


# --- The command-line limit -------------------------------------------------------------------


def _fits(argv) -> bool:
    """Whether CreateProcess itself starts *argv*. The child's own exit doesn't count: the venv's
    python.exe is a launcher, which can fail to relaunch an interpreter with a longer line."""
    try:
        subprocess.run(argv, capture_output=True, timeout=60,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError:
        return False
    return True


@pytest.mark.parametrize("unit", ["x", "\U0001f600", 'a"b'], ids=["ascii", "non-bmp", "quote"])
def test_the_unit_count_is_create_processs_own(unit):
    base = [sys.executable, "-c", "pass"]
    count = 1
    while wssh.command_line_units(base + [unit * (count * 2)]) <= wssh.COMMAND_LINE_LIMIT:
        count *= 2
    low, high = count, count * 2  # the boundary lies between these repetition counts
    while high - low > 1:
        middle = (low + high) // 2
        fits = wssh.command_line_units(base + [unit * middle]) <= wssh.COMMAND_LINE_LIMIT
        low, high = (middle, high) if fits else (low, middle)
    assert wssh.command_line_units(base + [unit * low]) <= wssh.COMMAND_LINE_LIMIT
    assert wssh.command_line_units(base + [unit * high]) > wssh.COMMAND_LINE_LIMIT
    assert _fits(base + [unit * low])
    assert not _fits(base + [unit * high])


async def test_a_command_line_over_windows_limit_is_refused_before_anything_starts(monkeypatch):
    argvs = spawning(monkeypatch, FakeProcess(0, lines=[b"ok\n"]))
    code, text = await ssh(command="'" * 9000, end_with_channel=True)
    assert code == 1 and text.startswith("Error: this command is too long to start from Windows")
    assert "Nothing was sent" in text and "'''" not in text  # the command is not echoed
    assert argvs == []


def _script_tool(tmp_path):
    """run_script for a remote host down to the real Windows SSH runner."""
    fake = tool(tmp_path, address="192.0.2.10")
    fake.config = ssh_executor().config
    fake._exec_command = functools.partial(exec_command, fake)
    return fake


async def test_a_remote_script_is_trapped_and_ends_with_its_channel(tmp_path, monkeypatch):
    argvs = spawning(monkeypatch, FakeProcess(0, lines=[b"ok\n"]))
    assert await run(_script_tool(tmp_path), "echo ok") == (0, "ok\n")
    argv, kwargs = argvs[0]
    assert argv[-1].startswith("odin_fg_command=")
    assert "trap" in argv[-1] and "rm -f" in argv[-1] and "exit 143" in argv[-1]
    assert kwargs["stdin"] is asyncio.subprocess.PIPE


async def test_a_script_too_long_for_windows_is_refused(tmp_path, monkeypatch):
    argvs = spawning(monkeypatch, FakeProcess(0, lines=[b"ok\n"]))
    code, text = await run(_script_tool(tmp_path), "echo " + "x" * 30000)
    assert code == 1 and "too long to start from Windows" in text
    assert argvs == []


# --- The routes ---------------------------------------------------------------------------------


async def test_exec_command_forwards_the_flag_only_when_asked(monkeypatch):
    seen = []

    async def remote_ssh(**kwargs):
        seen.append(kwargs)
        return 0, "ok"

    monkeypatch.setattr(windows_tools, "remote_ssh", remote_ssh)
    executor = ssh_executor()
    await exec_command(executor, "192.0.2.10", "uptime", end_with_channel=True)
    await exec_command(executor, "192.0.2.10", "uptime")
    assert seen[0]["end_with_channel"] is True and seen[0]["pool"] is None
    assert "end_with_channel" not in seen[1]


async def test_validation_probes_end_with_their_channel():
    sent = []
    fake = validator([])

    async def route(address, command, ssh_user, **kwargs):
        sent.append(kwargs)
        return 0, "200"

    fake._exec_command = route
    checks = [{"type": "command", "target": "true", "host": "server"},
              {"type": "service", "target": "sshd", "host": "server"},
              {"type": "port", "target": "22", "host": "server"}]
    text = await handle_validate_action(fake, {"checks": checks, "format": "json"})
    assert len(json.loads(text)["checks"]) == 3
    assert len(sent) == 3 and all(kwargs.get("end_with_channel") is True for kwargs in sent)


# --- Live ---------------------------------------------------------------------------------------


@live
async def test_a_cancelled_remote_command_ends_on_the_host(target):  # noqa: F811
    marker = "37.25"
    count = f"ps -eo args | grep -c '^sleep {marker}$'"

    async def remote(command, **kwargs):
        return await exec_command(ssh_executor(), target.address, command, target.ssh_user,
                                  target=target, **kwargs)

    async def wait_for(expected):
        for _ in range(60):
            _code, output = await remote(count, timeout=20)
            if output.strip() == expected:
                return True
            await asyncio.sleep(0.25)
        return False

    _code, found = await remote("command -v python3 || true", timeout=20)
    if "python3" not in found:
        pytest.skip("the SSH test target has no python3: commands take the no-cleanup fallback")
    task = asyncio.create_task(remote(f"sleep {marker}", timeout=120, end_with_channel=True))
    assert await wait_for("1")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await wait_for("0")  # the coordinator ended it when the channel closed
