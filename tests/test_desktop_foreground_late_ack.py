"""Odin 4.19.2 (PR #670) in Desktop: a foreground command keeps its result after a late ACK.

The loop is held across the supervisor worker's bounded 2 s wait for the settlement
acknowledgement (harmless commands only), so the ACK is lost after a clean settlement.
Through Desktop's owner-bound executor, the result is the ordinary one: the same ok,
uncertainty and text as an undelayed run of the same command, one execution, retained
output that pages back, and the same recovery events with no retry. Settlement still
fails closed: the shell stays owned and relaunch is vetoed.

The last case is the 4.19.2 version of the frozen wrapper case it supersedes: the
foreground wrapper now passes its opt-in by keyword, so the test double accepts it.
"""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.config.schema import ToolHost, ToolsConfig
from src.tools import local_supervisor as s
from tests.desktop_adapters.tools_cases import ToolExecutor, owner_fixture


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(s, '_active', set())
    monkeypatch.setattr(s, '_pending', set())
    monkeypatch.setattr(s, '_closing_loops', set())
    monkeypatch.setattr(s, '_unverified_startup', False)
    veto = Mock()
    monkeypatch.setattr('src.restart.block_reexec', veto)
    return veto


def hold_after_start(monkeypatch):
    """Hold the loop past the worker's ACK wait once each new shell has started."""
    real = s.create_supervised_shell

    async def factory(*args, **kwargs):
        shell = await real(*args, **kwargs)
        time.sleep(3.0)  # the command finishes and the worker gives up on the ACK
        await asyncio.wait({shell._monitor_task}, timeout=10)
        return shell

    monkeypatch.setattr(s, 'create_supervised_shell', factory)
    return real


def executor(tmp_path, **settings):
    executor = ToolExecutor(config=ToolsConfig(
        local_working_dir=str(tmp_path / "workspace"),
        audit_log_path=str(tmp_path / "data" / "audit.jsonl"),
        hosts={"local": ToolHost(address="127.0.0.1")},
        **settings,
    ))
    executor.readiness["run_script"] = True
    return executor


def settlement_still_failed(veto):
    assert s._active, "the late-ACK shell stays owned"
    for shell in s._active:
        assert shell._ack_lost_after_clean and shell._settled.exception() is not None
    veto.assert_called_with('local command supervisor ownership lost')


def shape(result):
    return result.ok, result.uncertain_outcome, str(result.output)


@pytest.mark.parametrize('exit_code', [0, 7])
async def test_a_late_ack_result_is_the_ordinary_result(tmp_path, isolated, monkeypatch, exit_code):
    (tmp_path / "owner").mkdir()
    with owner_fixture(tmp_path / "owner"):
        ex = executor(tmp_path)
        counter = tmp_path / "counter.txt"
        args = {"host": "local",
                "command": f"echo once >> {counter}; printf late-ack-result; exit {exit_code}"}
        ordinary = await ex.execute("run_command", args)
        assert counter.read_text() == "once\n"
        real = hold_after_start(monkeypatch)
        late = await ex.execute("run_command", args)
        assert counter.read_text() == "once\nonce\n"  # one execution each
        assert shape(late) == shape(ordinary)
        assert late.ok is (exit_code == 0) and not late.uncertain_outcome
        assert "late-ack-result" in str(late.output) and "ownership lost" not in str(late.output)
        settlement_still_failed(isolated)
        monkeypatch.setattr(s, 'create_supervised_shell', real)


async def test_large_output_is_retained_and_pages_back(tmp_path, isolated, monkeypatch):
    # The output must fit the pipe so the command can finish while the loop is held: a
    # user's new pipes can hold as little as 8 KiB (pipe-user-pages-soft). A low delivery
    # limit still sends this 6,000-character result through retention and paging.
    (tmp_path / "owner").mkdir()
    with owner_fixture(tmp_path / "owner"):
        ex = executor(tmp_path, tool_output_max_chars=1024)
        hold_after_start(monkeypatch)
        result = await ex.execute("run_command", {
            "host": "local", "command": "printf '%06000d' 0; exit 7"})
        assert not result.ok and not result.uncertain_outcome
        envelope = json.loads(str(result.output))
        assert envelope["total_chars"] >= 6000 and envelope["cursor"]
        rebuilt, cursor = envelope["head"], envelope["cursor"]
        while cursor:
            page = await ex.execute("get_tool_output", {"cursor": cursor})
            assert page.ok, page.output
            data = json.loads(str(page.output))
            rebuilt += data["text"]
            cursor = data["cursor"]
        assert len(rebuilt) == envelope["total_chars"] and "0" * 6000 in rebuilt
        settlement_still_failed(isolated)


@pytest.mark.parametrize("tool", ["run_command", "run_script"])
async def test_transient_text_is_classified_as_usual_and_never_retried(
        tmp_path, isolated, monkeypatch, tool):
    message = "ssh: connect to host fixture port 22: Connection refused"

    def args(counter):
        if tool == "run_command":
            return {"host": "local",
                    "command": f"echo once >> {counter}; echo '{message}'; exit 7"}
        return {"host": "local", "interpreter": "python3", "script": (
            f"open({str(counter)!r}, 'a').write('once\\n')\n"
            f"print({message!r})\nraise SystemExit(7)\n")}

    def events(ex):
        return [(e["tool"], e["category"], e["succeeded"]) for e in ex.recovery_stats.get_recent()]

    (tmp_path / "owner").mkdir()
    with owner_fixture(tmp_path / "owner"):
        ordinary = executor(tmp_path)
        assert not (await ordinary.execute(tool, args(tmp_path / "ordinary.txt"))).ok
        late = executor(tmp_path)
        hold_after_start(monkeypatch)
        result = await late.execute(tool, args(tmp_path / "late.txt"))
        assert (tmp_path / "late.txt").read_text() == "once\n"  # exactly one execution
        assert not result.ok and not result.uncertain_outcome
        assert "Connection refused" in str(result.output)
        assert "ownership lost" not in str(result.output)
        assert late.recovery_stats.get_summary()["totals"]["attempts"] == 0  # never retried
        assert events(late) == events(ordinary)  # classified like an ordinary run
        settlement_still_failed(isolated)


# --- the frozen wrapper case Odin 4.19.2 superseded, in its 4.19.2 form -------------------


async def test_started_shell_cleanup_failure_preserves_launch_error(isolated, monkeypatch):
    started = asyncio.get_running_loop().create_future()
    started.set_exception(ValueError('startup'))
    fake = SimpleNamespace(
        _started=started, terminate_tree=AsyncMock(side_effect=RuntimeError('cleanup')))
    monkeypatch.setattr(s.asyncio, 'create_subprocess_exec', AsyncMock(return_value=object()))
    # The actual socketpair is owned by this test; close the parent as the fake
    # protocol adapter would, rather than leaking it on the success branch.
    async def connection(*, sock, **kwargs):
        sock.close()
        return object(), object()
    monkeypatch.setattr(s.asyncio, 'open_connection', connection)
    monkeypatch.setattr(s, 'SupervisedShell', lambda *args, **kwargs: fake)
    with pytest.raises(ValueError, match='startup'):
        await s.create_supervised_shell('unused')
    fake.terminate_tree.assert_awaited_once_with(grace=.1)
