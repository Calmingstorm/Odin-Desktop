"""Odin 4.20.0 (PR #671) in Desktop, on Desktop's own routes.

- search_audit on the engine's own audit logger answers one result per tool call, while the
  record view (``audit.query``) keeps returning the raw records, as Odin's raw audit API does.
- A remote job start is one direct SSH attempt through each registry constructor the
  executor really uses (Linux, and macOS through the production variant router), down to
  the subprocess boundary. Windows' route runs natively, in tests/windows.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.config.schema import RetryConfig, ToolsConfig
from src.desktop.paths import ProfilePaths
from src.desktop.platform import macos_jobs
from src.desktop.platform.variants import darwin_variant
from src.desktop.records import RecordsService
from src.tools import ssh as ssh_module
from src.tools.executor import ToolExecutor
from tests.test_desktop_audit_call_search import _call

pytest_plugins = ["tests.test_desktop_engine_services"]


@pytest.mark.asyncio
async def test_native_search_audit_groups_calls_and_the_record_view_stays_raw(graph, tmp_path):
    _requests, engine, _provider, _transcript, _cid = graph
    knowledge = engine.deps.native_owners["knowledge"]
    audit = knowledge.audit
    written = _call(1, 10) + _call(2, 20, error="exit 7")
    audit.path.parent.mkdir(parents=True, exist_ok=True)
    with audit.path.open("a", encoding="utf-8") as handle:
        handle.writelines(json.dumps(record) + "\n" for record in written)

    text = await knowledge._handle_search_audit({})
    assert text.startswith("**Audit log (2 calls):**")
    assert "(approved, 140ms, failed)" in text and "(approved, 140ms, succeeded)" in text
    assert "ERROR: exit 7" in text
    limited = await knowledge._handle_search_audit({"limit": 1})
    assert limited.startswith("**Audit log (1 call):**") and "exit 7" in limited

    records = RecordsService(ProfilePaths.from_xdg("test", home=tmp_path, environ={}),
                             audit=audit)
    raw = await records.handle("audit.query", {})
    assert raw == list(reversed(written))  # every start, call and end record, as stored
    assert len(await records.handle("audit.query", {"limit": 1})) == 1
    errors = await records.handle("audit.query", {"error_only": True})
    assert [entry["call_id"] for entry in errors] == ["call_2"]


# --- One direct attempt for remote starts, through the real constructors ---------------------

TIMED_OUT = "ssh: connect to host 192.0.2.10 port 22: Connection timed out\n"
RESET = "Connection reset by peer\n"


class _Process:
    def __init__(self, code: int, output: str) -> None:
        self.returncode, self.pid, self._output = code, 4242, output.encode()

    async def communicate(self):
        return self._output, b""


class _Lease:
    revoked = False

    def __init__(self) -> None:
        self.target = SimpleNamespace(
            alias="macbook", address="192.0.2.10", ssh_user="odin", key_path="/k",
            known_hosts_path="/kh", port=22, host_key_alias="", runtime_key="rk", local=False)
        self.release_count = 0

    async def run(self, factory):
        assert self.release_count == 0
        return await factory()

    def release(self) -> None:
        self.release_count += 1


class _Pool:
    """A connection pool that records its use; pooled runs are marked in their arguments."""

    def __init__(self) -> None:
        self.calls = []

    def is_connected(self, *_args):
        return True

    async def acquire(self, *args, **_kwargs):
        self.calls.append(args)
        return True

    def get_ssh_args(self, host, command, *_args, **_kwargs):
        return ["ssh", "-o", "ControlPath=pooled", host, command]

    async def ensure_master_registered(self, *_args):
        return None

    def master_process(self, *_args):
        return None  # Odin 4.23.0: no master of this pool's to watch

    def release(self, *_args):
        return None


def _route(monkeypatch, tmp_path, platform, replies):
    """The executor and registry each platform builds, with ssh at its subprocess boundary."""
    spawned = []

    async def spawn(*argv, **_kwargs):
        spawned.append(argv)
        return _Process(*replies[min(len(spawned), len(replies)) - 1])

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(ssh_module.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(ssh_module.asyncio, "sleep", no_sleep)
    routed = []
    if platform == "macos":
        variant = macos_jobs.exec_command

        async def observed(self, address, command, *args, **kwargs):
            routed.append((command, kwargs.get("max_ssh_attempts"), kwargs.get("ssh_multiplex")))
            return await variant(self, address, command, *args, **kwargs)

        monkeypatch.setattr(macos_jobs, "exec_command", observed)
        # Exactly what the macOS app installs: the variant routers in front of Linux's methods
        # (already in place when this runs on a Mac).
        for method, target in (("_ensure_process_registry", "ensure_process_registry"),
                               ("_exec_command", "exec_command")):
            if getattr(getattr(ToolExecutor, method), "darwin_target", None) is None:
                router = darwin_variant(f"src.desktop.platform.macos_jobs:{target}",
                                        system="darwin")(getattr(ToolExecutor, method))
                monkeypatch.setattr(ToolExecutor, method, router)
    executor = ToolExecutor(config=ToolsConfig(ssh_retry=RetryConfig(max_retries=3)))
    executor._memory_path = str(tmp_path / "memory.json")  # retention under the test's folder
    executor.ssh_pool = _Pool()
    registry = executor._ensure_process_registry()
    expected = macos_jobs.MacOSProcessRegistry if platform == "macos" else None
    assert expected is None or type(registry) is expected
    executor.routed = routed  # what reached the macOS variant of _exec_command
    return executor, registry, spawned


@pytest.mark.parametrize("platform", ["linux", "macos"])
async def test_an_unreachable_host_start_is_one_direct_attempt_and_definite(
        monkeypatch, tmp_path, platform):
    executor, registry, spawned = _route(monkeypatch, tmp_path, platform, [(255, TIMED_OUT)])
    lease = _Lease()

    result = await registry.start_remote(lease, "sleep 45")

    assert result.startswith("Failed to start process: could not connect to macbook;")
    assert "nothing was started, so retrying is safe" in result
    assert len(spawned) == 1  # configured retries are 3; no teardown either
    assert spawned[0][0] == "ssh"
    assert "ControlMaster=no" in spawned[0] and "ControlPath=none" in spawned[0]
    assert executor.ssh_pool.calls == []  # never a shared connection
    if platform == "macos":  # the start reached the macOS variant as one direct attempt
        assert [call[1:] for call in executor.routed] == [(1, False)]
    assert lease.release_count == 1
    assert registry._pending_remote_reservations == 0 and registry._pending_starts == 0


@pytest.mark.parametrize("platform", ["linux", "macos"])
async def test_an_ambiguous_start_stays_unknown_and_is_torn_down(monkeypatch, tmp_path, platform):
    executor, registry, spawned = _route(
        monkeypatch, tmp_path, platform, [(255, RESET), (0, "{}")])
    lease = _Lease()

    result = await registry.start_remote(lease, "sleep 45")

    assert "outcome_unknown=true" in result and "safe" not in result
    assert len(spawned) == 2  # the one start attempt, then the normal teardown
    assert "ControlMaster=no" in spawned[0]
    assert "ControlPath=pooled" in spawned[1]  # teardown is an ordinary remote operation
    assert len(executor.ssh_pool.calls) == 1
    assert lease.release_count == 1


@pytest.mark.parametrize("platform", ["linux", "macos"])
async def test_other_remote_operations_keep_their_retries(monkeypatch, tmp_path, platform):
    executor, _registry, spawned = _route(monkeypatch, tmp_path, platform, [(255, TIMED_OUT)])

    await executor._exec_remote_target(_Lease().target, "poll the job", 30)

    assert len(spawned) == 3  # retried, and still sharing connections
    assert all("ControlPath=pooled" in argv for argv in spawned)


# --- An unverified retained start keeps ownership through Desktop's adapters ----------------


def _retained_start(monkeypatch, alias):
    """The real registry holding an agent's remote start whose teardown can't be proven."""
    from tests.test_desktop_agent_kill_stops_jobs import (
        AGENT,
        UNPROVEN_KILL,
        _failing_start_registry,
    )
    from tests.test_remote_processes import _Lease as JobLease

    registry = _failing_start_registry(monkeypatch, {"teardown": UNPROVEN_KILL},
                                       failure="malformed")
    lease = JobLease(alias)
    return registry, lease, registry.start_remote(lease, "sleep 30", origin=AGENT)


async def test_desktop_shutdown_claims_no_release_while_a_retained_start_may_run(monkeypatch):
    from src.desktop.resource_cleanup import close_execution_owners

    registry, lease, start = _retained_start(monkeypatch, "remote")
    assert "outcome_unknown=true" in await start

    resources = await close_execution_owners(computer=None, registry=registry)

    assert resources["processes"] == {"state": "unknown", "error_type": "ProcessCleanupError"}
    assert lease.release_count == 0 and len(registry._unsettled_remote_starts) == 1


async def test_desktop_host_revoke_reports_a_retained_start_it_cannot_prove_stopped(
        monkeypatch, tmp_path):
    from src.desktop.hosts import HostsService
    from tests.test_desktop_hosts import Settings, prepare_test

    paths = ProfilePaths.from_xdg(environ={
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }, home=tmp_path)
    service = HostsService(Settings(paths))
    await service.handle("hosts.commit", {"token": await prepare_test(service)})
    registry, lease, start = _retained_start(monkeypatch, "lab")
    assert "outcome_unknown=true" in await start
    service.executor = SimpleNamespace(_process_registry=registry)

    revoked = await service.handle("hosts.force_revoke", {"alias": "lab"})

    assert revoked["processes"] == {"attempted": 1, "killed": 0, "unknown": 1}
    assert lease.release_count == 0 and len(registry._unsettled_remote_starts) == 1


# --- Desktop's wiring of the cascade and the reaper ------------------------------------------


@pytest.mark.asyncio
async def test_a_stopped_turn_stops_its_agents_jobs_through_the_engines_wiring(graph,
                                                                              monkeypatch):
    """The tool loop's turn cascade reaches the same manager, its reaper and the executor's
    own process registry, as Desktop's services compose them."""
    from src.agents.manager import AgentInfo, AgentState
    from src.tools.process_manager import AgentJobCleanup

    _requests, engine, _provider, _transcript, cid = graph
    cascade = engine.runner._kill_agents_for_turn
    manager = cascade.__self__
    reaped = []

    def reap_agent_jobs(agent_ids):
        reaped.append(set(agent_ids))
        return AgentJobCleanup(jobs=[])

    monkeypatch.setattr(engine.deps.tool_executor, "_ensure_process_registry",
                        lambda: SimpleNamespace(reap_agent_jobs=reap_agent_jobs))
    item = AgentInfo(id="agent-a", label="test", goal="harmless", channel_id=cid,
                     requester_id="owner", requester_name="Owner", turn_id="turn-1")
    item.transition(AgentState.READY)
    manager._agents[item.id] = item

    assert cascade("turn-1") == ["agent-a"]
    assert reaped == [{"agent-a"}]
    assert item._cancel_event.is_set()
    assert cascade("turn-2") == [] and reaped == [{"agent-a"}]  # another turn's agents only


def test_only_kills_reap_jobs_never_completion_failure_or_timeout():
    """Odin 4.20.0: established jobs survive an agent's normal end; only a kill reaps them."""
    import ast
    import inspect

    from src.agents import manager as module

    tree = ast.parse(inspect.getsource(module))
    callers = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for call in ast.walk(node):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "_reap_jobs"):
                    callers.add(node.name)
    assert callers == {"kill_for_turn", "kill_with_receipt"}


# --- The defensive branches Odin 4.20.0 added to the shared engine ----------------------------


async def test_the_audit_stream_skips_unparseable_records_and_reports_read_errors(tmp_path,
                                                                                  monkeypatch):
    from unittest.mock import Mock

    from src.audit import logger as audit_logger

    path = tmp_path / "audit.jsonl"
    path.write_text('{"tool_name": "first"}\nnot a record\n{"tool_name": "second"}\n')
    audit = audit_logger.AuditLogger(str(path))
    assert [entry["tool_name"] async for entry in audit.iter_entries_newest_first()] == [
        "second", "first"]

    async def unreadable(_fd):
        raise OSError("fixture: unreadable snapshot")
        yield  # an async generator, like the real reader

    recorder = Mock()
    monkeypatch.setattr(audit_logger, "_iter_lines_reverse", unreadable)
    monkeypatch.setattr(audit_logger, "log", recorder)
    assert [entry async for entry in audit.iter_entries_newest_first()] == []
    recorder.error.assert_called_once()
    assert "Failed to read audit log snapshot" in recorder.error.call_args.args[0]


def test_a_repeated_local_hour_that_never_ends_is_refused():
    from datetime import datetime, timedelta, tzinfo

    from src.scheduler import scheduler as module

    class EndlessRepeat(tzinfo):
        """Every local time happens twice: the second copy is an hour later."""

        def utcoffset(self, dt):
            return timedelta(hours=-5 if dt.fold else -4)

        def dst(self, dt):
            return timedelta(0)

        def tzname(self, dt):
            return "REPEAT"

    with pytest.raises(RuntimeError, match="no end to the repeated local time"):
        module._end_of_repeat(datetime(2026, 11, 1, 1, 30, tzinfo=EndlessRepeat()))


def test_a_fixed_time_job_that_never_leaves_a_repeated_hour_is_refused(monkeypatch):
    from datetime import UTC, timedelta

    from src.scheduler import scheduler as module

    monkeypatch.setattr(module, "_is_repeated_wall_time", lambda candidate, now: True)
    monkeypatch.setattr(module, "_end_of_repeat",
                        lambda candidate: candidate.astimezone(UTC) + timedelta(hours=1))
    with pytest.raises(RuntimeError, match="no eligible next run"):
        module._cron_next_run("30 1 * * *", "America/New_York")
