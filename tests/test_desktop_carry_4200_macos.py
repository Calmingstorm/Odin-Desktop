"""Odin 4.20.0 (PR #671) in Desktop: the macOS seams of agent job cleanup and one-attempt starts.

Run on any system: they drive the macOS registry and variants with the platform's process
layer stubbed. The native behaviour (a real worker session) is in tests/macos.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agents.execution_context import JobOrigin
from src.desktop.platform import macos_jobs
from src.tools.executor import ToolExecutor
from src.tools.process_manager import AgentJobCleanup, ProcessRegistry
from tests.test_desktop_process_preview_continuation import _info, _meta

AGENT = JobOrigin("agent-a", "root-a")
CAVEAT = " containment=session_best_effort; detached or raced descendants are unverified."


@pytest.fixture
def registry(tmp_path, monkeypatch):
    reg = macos_jobs.MacOSProcessRegistry(workspace=str(tmp_path), retention_dir=tmp_path / "out",
                                          command_shell="sh")
    monkeypatch.setattr(reg, "_read_output", AsyncMock())
    monkeypatch.setattr(reg, "_watch_exit", AsyncMock())
    monkeypatch.setattr("src.async_utils.fire_and_forget", lambda coro, **kw: coro.close())
    return reg


def _spawn(monkeypatch, pid: int, gate: asyncio.Event | None = None):
    async def spawn(*_args, **_kwargs):
        if gate is not None:
            await gate.wait()
        return SimpleNamespace(pid=pid, returncode=None)

    monkeypatch.setattr(macos_jobs, "create_supervised_shell", spawn)


# --- One direct attempt for starts ---------------------------------------------------------


def test_the_macos_registry_starts_remote_jobs_through_the_one_attempt_route(tmp_path):
    executor = SimpleNamespace(
        _ensure_local_workspace=lambda: str(tmp_path), _exec_remote_target=object(),
        _exec_remote_target_once=object(), _retention_root=lambda: tmp_path,
        _acquire_process_cleanup_lease=object(), _command_shell_mode=lambda: "sh")
    registry = macos_jobs.ensure_process_registry(executor)
    assert isinstance(registry, macos_jobs.MacOSProcessRegistry)
    assert registry._remote_exec_once is executor._exec_remote_target_once
    assert registry._remote_exec is executor._exec_remote_target


async def test_macos_exec_command_forwards_the_one_attempt_policy_for_remote_hosts(monkeypatch):
    seen = {}

    async def linux_original(self, address, command, ssh_user, timeout, on_output,
                             use_workspace, target, use_command_shell, **kwargs):
        seen.update(address=address, **kwargs)
        return 255, "ssh: connect to host 192.0.2.7 port 22: Connection refused"

    router = SimpleNamespace(linux_original=linux_original)
    monkeypatch.setattr(ToolExecutor, "_exec_command", router, raising=False)
    result = await macos_jobs.exec_command(
        object(), "192.0.2.7", "true", "root", 30, None, False, None, False,
        max_ssh_attempts=1, ssh_multiplex=False)
    assert result[0] == 255
    assert seen == {"address": "192.0.2.7", "max_ssh_attempts": 1, "ssh_multiplex": False,
                    "end_with_channel": False}

    seen.clear()
    await macos_jobs.exec_command(object(), "192.0.2.7", "true")
    assert seen == {"address": "192.0.2.7", "max_ssh_attempts": None, "ssh_multiplex": True,
                    "end_with_channel": False}


# --- Kill receipts carry the weaker native guarantee -----------------------------------------


@pytest.mark.parametrize("outcome,expected", [
    ({"jobs": {"g1": macos_jobs.BEST_EFFORT_STOP}, "starts": []},
     "Stopped 1 background job(s) it started (PID 41). PID 41:" + CAVEAT),
    ({"jobs": {}, "starts": [macos_jobs.BEST_EFFORT_STOP]},
     "Stopped 1 job(s) whose start was in progress. A job whose start was in progress:" + CAVEAT),
    ({"jobs": {"g1": "unknown"}, "starts": ["unknown"]},
     "Could not confirm that job(s) PID 41 stopped (outcome_unknown=true). Could not confirm "
     "the outcome of 1 start(s) in progress (outcome_unknown=true)."),
    ({"jobs": {"g1": "stopped_group_only"}, "starts": []},
     "Stopped 1 background job(s) it started (PID 41). PID 41: "
     "containment=process_group_only; escaped descendants are unverified."),
], ids=["registered", "settling-start", "unknown-kept", "remote-group-only-kept"])
def test_a_macos_kill_receipt_states_best_effort_stops(outcome, expected):
    starts = len(outcome["starts"])
    receipt = macos_jobs.MacOSAgentJobCleanup(jobs=[("g1", 41)] if outcome["jobs"] else [],
                                              starts=starts)
    assert receipt.describe(outcome) == expected


def test_a_pending_macos_receipt_reads_like_odins():
    receipt = macos_jobs.MacOSAgentJobCleanup(jobs=[("g1", 41)], starts=1)
    plain = AgentJobCleanup(jobs=[("g1", 41)], starts=1)
    assert receipt.describe(None) == plain.describe(None)


async def test_only_a_proven_local_stop_becomes_best_effort(registry, monkeypatch):
    async def proven(_generation):
        return True

    monkeypatch.setattr(registry, "terminate_generation", proven)
    local = SimpleNamespace(remote=False, containment=macos_jobs.SCOPE, generation="g1", pid=4)
    remote = SimpleNamespace(remote=True, containment="process_group_only", generation="g2",
                             pid=-1, _remote_lock=asyncio.Lock())
    assert await registry._stop_generation(local) == macos_jobs.BEST_EFFORT_STOP
    assert await registry._stop_generation(remote) == "stopped_group_only"

    async def unproven(_generation):
        return False

    monkeypatch.setattr(registry, "terminate_generation", unproven)
    assert await registry._stop_generation(local) == "unknown"


# --- The local starter, lifted from Odin 4.20.0 --------------------------------------------


async def test_an_ordinary_local_start_still_starts(registry, monkeypatch):
    _spawn(monkeypatch, 4101)
    started = await registry.start("localhost", "sleep 30")
    assert started.startswith("Process started (PID 4101)")
    info = registry._processes[4101]
    assert (info.origin_agent_id, info.origin_root_id) == ("", "")
    assert info.containment == macos_jobs.SCOPE


async def test_an_agent_start_records_its_origin_and_a_kill_stops_it_with_the_caveat(
        registry, monkeypatch):
    _spawn(monkeypatch, 4102)
    await registry.start("localhost", "sleep 30", origin=AGENT)
    info = registry._processes[4102]
    assert (info.origin_agent_id, info.origin_root_id) == ("agent-a", "root-a")

    async def proven(generation):
        record = registry._retained_generations[generation]
        record.status, record.session_confirmed_empty = "killed", True
        return True

    monkeypatch.setattr(registry, "terminate_generation", proven)
    cleanup = registry.reap_agent_jobs({"agent-a"})
    assert isinstance(cleanup, macos_jobs.MacOSAgentJobCleanup)
    outcome = await cleanup.wait(timeout=5)
    assert outcome == {"jobs": {info.generation: macos_jobs.BEST_EFFORT_STOP}, "starts": []}
    assert cleanup.describe(outcome) == (
        "Stopped 1 background job(s) it started (PID 4102). PID 4102:" + CAVEAT)


async def test_a_start_settling_when_its_agent_is_killed_is_stopped_as_best_effort(
        registry, monkeypatch):
    gate = asyncio.Event()
    _spawn(monkeypatch, 4103, gate)
    terminate = AsyncMock(return_value=True)
    monkeypatch.setattr(registry, "_terminate_bound_host_job", terminate)
    invocation = asyncio.create_task(registry.start("localhost", "sleep 30", origin=AGENT))
    for _ in range(100):
        if registry._agent_starts:
            break
        await asyncio.sleep(0.01)
    cleanup = registry.reap_agent_jobs({"agent-a"})
    gate.set()

    outcome = await cleanup.wait(timeout=5)
    assert outcome == {"jobs": {}, "starts": [macos_jobs.BEST_EFFORT_STOP]}
    assert cleanup.describe(outcome) == (
        "Stopped 1 job(s) whose start was in progress. A job whose start was in progress:"
        + CAVEAT)
    assert terminate.await_count == 1
    assert "stopped while it started" in await invocation


async def test_a_refused_remote_address_releases_the_lease(registry):
    released = []
    lease = SimpleNamespace(revoked=False, release=lambda: released.append(True))
    result = await macos_jobs.start_local_reserved(registry, "192.0.2.5", "true", host_lease=lease)
    assert result.startswith("Error: remote process start")
    assert released == [True]


# --- Odin 4.20.0's preview continuation through the macOS page --------------------------------

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
def test_a_macos_preview_keeps_odins_continuation_and_its_caveat(name):
    fields, data, start, budget, extra = PREVIEWS[name]
    info = _info(**fields)
    info.containment = macos_jobs.SCOPE
    page = macos_jobs.MacOSProcessRegistry._output_page(info, data, start, 4000, budget,
                                                        preview=True, **extra)
    shared = ProcessRegistry._output_page(info, data, start, 4000,
                                          budget - macos_jobs._META_RESERVE, preview=True,
                                          **extra)
    meta, odin = _meta(page), _meta(shared)
    for key in ("shown_intervals", "truncated", "cursor", "retrieval", "tail_status",
                "not_retained_bytes"):
        assert meta.get(key) == odin.get(key), key
    assert meta["containment"] == "session_best_effort"
    assert meta["cleanup_caveat"] == macos_jobs.CAVEAT
    assert len(page) <= budget  # the caveat fits inside the delivery budget
    expected_cursor = {"complete": None, "empty": None, "capture-loss": None}
    assert meta["cursor"] == expected_cursor.get(name, "gen:0")
