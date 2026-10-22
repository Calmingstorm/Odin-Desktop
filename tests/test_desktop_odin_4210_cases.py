"""Odin 4.21.0 (PR #672) in Desktop: the 4.21.0 versions of superseded frozen cases.

Odin 4.21.0 never sends a remote user command twice once it may have been dispatched: a
timeout or an exit status of 255 is returned once and marked uncertain. Two frozen
run_command cases of tests/test_successful_retry_provenance.py pinned the old re-send
(``test_real_run_command_internal_ssh_retry_settlement`` and
``test_real_run_command_exhausted_timeouts_remain_failed``), so the tools-extra adapter no
longer selects them. Their 4.21.0 forms run here on the frozen suite's own adapted helpers
(Desktop's owner executor, host registry and SSH retry code; only the subprocess boundary
is faked), with Odin 4.21.0's client double, which a user command reads like a channel
that stays open.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.tools import ssh
from tests.desktop_adapters.tools_cases import owner_fixture
from tests.desktop_adapters.tools_extra import load_suite

_frozen = load_suite("test_successful_retry_provenance")
_executor = _frozen._executor
_fake_clients = _frozen._fake_clients


@pytest.fixture(autouse=True)
def desktop_owner(tmp_path_factory):
    with owner_fixture(tmp_path_factory.mktemp("desktop-4210-owner")):
        yield


class _SSHClient:
    """A dispatched client settles only when its output is read or cleanup completes.

    The plain transport calls communicate(); a user command, whose channel stays
    open, reads stdout to EOF and then waits.
    """

    def __init__(self, *, failure=None, code=0, output="1: recovered\n"):
        self.pid = 54321
        self.returncode = None
        self.failure = failure
        self.code = code
        self.output = output
        self.communications = 0
        self.cleaned = False
        self.stdout = self

    async def _settle(self):
        self.communications += 1
        if self.failure is not None:
            raise self.failure
        self.returncode = self.code
        return self.output.encode()

    async def communicate(self):
        return await self._settle(), None

    async def read(self):
        return await self._settle()

    async def wait(self):
        return self.returncode

    async def cleanup(self):
        assert self.returncode is None
        self.returncode = -15
        self.cleaned = True


def _exiting_clients(monkeypatch, *clients):
    pending = iter(clients)
    spawn = AsyncMock(side_effect=lambda *args, **kwargs: next(pending))
    monkeypatch.setattr(ssh.asyncio, "create_subprocess_exec", spawn)
    return spawn


async def test_real_run_command_timeout_is_never_sent_twice(tmp_path, monkeypatch):
    """A remote command that timed out may have run, so it is never re-sent."""
    exe = _executor(tmp_path, attempts=2)
    first = _SSHClient(failure=TimeoutError("client lost settlement"))
    second = _SSHClient(output="separate invocation")
    spawn = _fake_clients(monkeypatch, first, second)

    result = await exe.execute("run_command", {"host": "remote", "command": "fixture"})

    assert spawn.await_count == 1
    assert first.cleaned and first.communications == 1
    assert not result.ok and result.uncertain_outcome
    assert result.exit_code == 1 and result.error is not None
    assert "timed out" in result.output
    assert exe.recovery_stats.get_summary()["totals"]["attempts"] == 0

    separate = await exe.execute("run_command", {"host": "remote", "command": "fixture"})
    assert spawn.await_count == 2
    assert separate.ok and not separate.uncertain_outcome
    assert separate.output == "separate invocation"


async def test_real_run_command_without_a_master_is_sent_once(tmp_path, monkeypatch):
    """Without the pool there is no separate connection phase to retry: a
    connect-failure line could be the command's own, so it proves nothing."""
    exe = _executor(tmp_path, attempts=2)
    refused = _SSHClient(code=255, output="ssh: connect to host 192.0.2.10 port 22: "
                                          "Connection refused\n")
    spawn = _exiting_clients(monkeypatch, refused, _SSHClient(output="ran twice"))

    result = await exe.execute("run_command", {"host": "remote", "command": "fixture"})

    assert spawn.await_count == 1
    assert not result.ok and result.exit_code == 255 and result.uncertain_outcome
    assert "ran twice" not in result.output


@pytest.mark.parametrize(("code", "output", "uncertain"), [
    (255, "client_loop: send disconnect: Broken pipe\n", True),
    (255, "Connection to 192.0.2.10 closed by remote host.\n", True),
    (255, "", True),
    (7, "Broken pipe\n", False),
])
async def test_real_run_command_255_is_uncertain_and_other_exits_are_definite(
    tmp_path, monkeypatch, code, output, uncertain
):
    exe = _executor(tmp_path, attempts=2)
    spawn = _exiting_clients(monkeypatch, _SSHClient(code=code, output=output),
                             _SSHClient(output="ran twice"))

    result = await exe.execute("run_command", {"host": "remote", "command": "fixture"})

    assert spawn.await_count == 1
    assert result.exit_code == code and result.uncertain_outcome is uncertain
    assert "ran twice" not in result.output


async def test_real_run_command_lost_after_dispatch_is_never_sent_twice(tmp_path, monkeypatch):
    exe = _executor(tmp_path, attempts=2)
    reset = _SSHClient(code=255, output="client_loop: send disconnect: Connection reset by peer\n")
    spawn = _exiting_clients(monkeypatch, reset, _SSHClient(output="ran twice"))

    result = await exe.execute("run_command", {"host": "remote", "command": "fixture"})

    assert spawn.await_count == 1
    assert not result.ok and result.exit_code == 255 and result.uncertain_outcome
    assert "Connection reset" in result.output and "ran twice" not in result.output
