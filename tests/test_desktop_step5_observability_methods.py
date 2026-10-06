"""Named observability methods over retained owners, with no live resources."""
# ruff: noqa: E501
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.desktop.management import MethodError
from src.desktop.observability import METHODS, READ_METHODS, ObservabilityService
from src.llm.context_compressor import CompressionStats, PrefixTracker
from src.llm.model_breaker import ModelBreakerRegistry
from src.tools.recovery import RecoveryCategory, RecoveryStats
from src.tools.ssh_pool import SSHConnectionPool


async def test_aggregate_preserves_truthful_missing_and_prefix_measurement():
    service = ObservabilityService()
    empty = await service.handle("observability.stats", {})
    assert set(empty) == {"tool_counts", "risk", "freshness", "bulkheads", "compression"}
    assert all(item["available"] is False for item in empty.values())
    stats = CompressionStats()
    service.compression_stats = stats
    measured = await service.handle("observability.compression", {})
    assert measured["prefix_hit_rate"] is None
    assert measured["prefix_measurement"] == "unmeasured"
    tracker = PrefixTracker(stats)
    assert tracker.check("system", []) is False
    assert tracker.check("system", []) is True
    measured = await service.handle("observability.compression", {})
    assert measured["prefix_hit_rate"] == 0.5
    assert measured["prefix_measurement"] == "local_prefix_equality"
    assert measured["upstream_cache_measured"] is False


async def test_recovery_uses_actual_tracker_bounds_and_scrubs_copies():
    tracker = RecoveryStats()
    tracker.record_attempt("test_tool", RecoveryCategory.SSH_TRANSIENT)
    tracker.record_success("test_tool", RecoveryCategory.SSH_TRANSIENT,
                           "authorization=Bearer fixture-token-value")
    service = ObservabilityService(executor=SimpleNamespace(recovery_stats=tracker))
    result = await service.handle("recovery.stats", {})
    assert result["totals"] == {"attempts": 1, "successes": 1, "failures": 0}
    entries = (await service.handle("recovery.recent", {"limit": "invalid"}))["entries"]
    assert len(entries) == 1
    assert "fixture-token-value" not in str(entries)
    assert "fixture-token-value" in str(tracker.get_recent())


async def test_capacity_snapshot_does_not_acquire_admission_and_tracks_late_owner():
    root = SimpleNamespace(services=SimpleNamespace(model_breakers=None))
    service = ObservabilityService(graph=lambda: root)
    assert (await service.handle("capacity.snapshot", {}))["availability"] == "not_enabled"
    registry = ModelBreakerRegistry()
    root.services.model_breakers = registry
    breaker = registry.for_model("fixture", "model:variant")
    before = breaker.snapshot()
    result = await service.handle("capacity.snapshot", {})
    assert result["availability"] == "available"
    assert result["lifetime"] == "process"
    assert result["data"]["breakers"][0]["provider"] == "fixture"
    assert result["data"]["breakers"][0]["model"] == "model:variant"
    assert breaker.snapshot()["state"] == before["state"]
    assert breaker.snapshot()["probe_eligible"] == before["probe_eligible"]


async def test_pool_stats_and_closures_use_real_temporary_pool(tmp_path):
    pool = SSHConnectionPool(socket_dir=str(tmp_path / "sockets"))
    service = ObservabilityService(executor=SimpleNamespace(ssh_pool=pool))
    assert await service.handle("pools.ssh", {}) == pool.get_metrics()
    assert await service.handle("pools.close", {"host": "fixture.invalid"}) == {
        "closed": False, "host": "fixture.invalid"}
    assert await service.handle("pools.close", {}) == {"closed_count": 0}
    assert READ_METHODS == METHODS - {"pools.close"}


async def test_counters_lazy_graph_and_http_clients_are_real_owner_refs():
    root = SimpleNamespace(executor=None, providers=None, records=None)
    service = ObservabilityService(graph=lambda: root)
    with pytest.raises(MethodError, match="SSH pool not available"):
        await service.handle("pools.ssh", {})
    audit = SimpleNamespace(count_by_tool=AsyncMock(return_value={"fixture": 2}))
    root.records = SimpleNamespace(audit=audit)
    assert await service.handle("observability.tools", {}) == {"fixture": 2}
    audit.count_by_tool.assert_awaited_once_with()
    root.providers = SimpleNamespace(ollama_client=SimpleNamespace(pool_stats=lambda: {"active": 3}))
    assert await service.handle("pools.http", {}) == {"ollama": {"active": 3}}


async def test_absent_turn_store_never_constructs_writer_or_manufactures_health():
    service = ObservabilityService(config=SimpleNamespace(turn_state=SimpleNamespace(enabled=True)))
    result = await service.handle("turn_state.snapshot", {})
    assert result["availability"] == "not_enabled"
    assert result["configured_enabled"] is True
    assert result["data"] == {}
    with pytest.raises(MethodError, match="usage history not enabled"):
        await service.handle("observability.usage", {})


async def test_counter_failures_do_not_expose_exception_secrets():
    def fail():
        raise RuntimeError("secret=fixture-secret")
    service = ObservabilityService(compression_stats=SimpleNamespace(as_dict=fail))
    with pytest.raises(MethodError) as caught:
        await service.handle("observability.compression", {})
    assert "fixture-secret" not in str(caught.value)


async def test_nested_request_owners_and_uncertain_pool_effects():
    stats = CompressionStats()
    root = SimpleNamespace(core=SimpleNamespace(requests=SimpleNamespace(
        services=SimpleNamespace(compression_stats=stats))))
    service = ObservabilityService(graph=lambda: root)
    assert (await service.handle("observability.compression", {}))["prefix_measurement"] == "unmeasured"
    pool = SimpleNamespace(close_all=AsyncMock(side_effect=RuntimeError("secret=fixture")))
    service.executor = SimpleNamespace(ssh_pool=pool)
    with pytest.raises(MethodError) as caught:
        await service.handle("pools.close", {})
    assert caught.value.disposition == "outcome_unknown"
    assert caught.value.message == "Pool closure outcome is unknown"


async def test_engine_deps_runtime_graph_and_dynamic_attributes_do_not_invent_measurement():
    stats = CompressionStats()
    service = ObservabilityService(graph=SimpleNamespace(core=SimpleNamespace(
        engine=SimpleNamespace(deps=SimpleNamespace(runtime_context=SimpleNamespace(
            compression_stats=stats))))))
    assert (await service.handle("observability.compression", {}))["prefix_measurement"] == "unmeasured"

    class NoOwners:
        def __getattr__(self, name):
            raise AssertionError("Undeclared composition children must not be manufactured")
    service = ObservabilityService(graph=NoOwners())
    assert (await service.handle("capacity.snapshot", {}))["availability"] == "not_enabled"
