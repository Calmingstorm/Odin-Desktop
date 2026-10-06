"""Completion methods through the actual authenticated profile composition.

Every path is a disposable profile. No renderer, HTTP listener, provider
request, live keyring or graphical environment is used.
"""
from __future__ import annotations

import json
import uuid

import pytest

from tests import test_desktop_management_core as management_tests
from tests.test_desktop_core_lifecycle import request

connected = management_tests.connected
no_network = management_tests.no_network


async def test_completion_capabilities_are_composed_and_read_classified(connected):
    core, _, _, _, welcome = connected
    manager = core.management
    for owner in (manager.records, manager.knowledge, manager.learned,
                  manager.trajectories, manager.observations, manager.openrouter,
                  manager.codex):
        assert owner.METHODS <= set(welcome["capabilities"])
        assert owner.READ_METHODS <= manager.read_methods
        assert not (owner.METHODS - owner.READ_METHODS) & manager.read_methods
        assert all(manager.methods[method] is owner for method in owner.METHODS)
    assert "codex.accounts.refresh" not in manager.read_methods
    assert "pools.close" not in manager.read_methods
    assert "openrouter.select" not in manager.read_methods


@pytest.mark.parametrize("method,params", [
    ("audit.diffs", {"limit": "invalid"}), ("audit.failures", {}),
    ("audit.tail", {}), ("logs.stats", {}), ("logs.tail", {}),
    ("knowledge.duplicates", {}), ("learned.list", {}),
    ("observability.stats", {}), ("recovery.stats", {}),
    ("recovery.recent", {"limit": "invalid"}), ("capacity.snapshot", {}),
    ("pools.ssh", {}), ("trajectories.list", {}),
    ("trajectories.search", {"tool_name": "read_file"}),
])
async def test_completion_read_transport_never_reserves_commands(connected, method, params):
    core, reader, writer, _, _ = connected
    answer = await request(reader, writer, method, params)
    assert answer["ok"], answer
    assert core.store.connection.execute(
        "SELECT COUNT(*) FROM command_receipts").fetchone()[0] == 0


async def test_missing_runtime_measurement_is_not_a_fabricated_counter(connected):
    _, reader, writer, _, _ = connected
    result = await request(reader, writer, "observability.stats")
    assert result["ok"], result
    assert result["result"]["compression"]["available"] is False
    assert "not available" in result["result"]["compression"]["reason"]
    # The actual gateway constructs the breaker registry. Empty measurements
    # from that real owner are different from inventing an absent registry.
    capacity = await request(reader, writer, "capacity.snapshot")
    assert capacity["result"]["availability"] == "available"
    assert capacity["result"]["data"]["breakers"] == []


async def test_completion_reads_share_the_request_graphs_original_owners(connected):
    core, _, _, _, _ = connected
    manager, deps = core.management, core.engine.deps
    assert manager.executor is deps.tool_executor
    assert manager.providers is deps.llm_gateway
    assert manager.records.audit is deps.audit
    assert manager.learned.reflector is deps.reflector
    assert manager.trajectories.saver is deps.turn_recorder._trajectory_saver
    assert manager.observations._owner("model_breakers") is deps.llm_gateway.model_breakers
    assert manager.knowledge.store is deps.knowledge_store
    assert deps.native_tools.owners["knowledge"]._knowledge_store is manager.knowledge.store


async def test_management_ingest_is_visible_to_original_native_knowledge_tools(connected):
    core, reader, writer, _, _ = connected
    result = await request(reader, writer, "knowledge.ingest", {
        "source": "management-reference", "content": "The profile has one shared knowledge store.",
    })
    assert result["ok"], result
    native = core.engine.deps.native_tools.owners["knowledge"]
    assert native._knowledge_store is core.management.knowledge.store
    assert core.engine.deps.readiness()["search_knowledge"] is True
    found = await native._handle_search_knowledge({"query": "shared knowledge"})
    assert "management-reference" in found
    assert "one shared knowledge store" in found


async def test_pool_close_command_replay_does_not_repeat_effect(connected, monkeypatch):
    core, reader, writer, _, _ = connected
    pool = core.management.executor.ssh_pool
    calls = []
    original = pool.close_all

    async def counted():
        calls.append(True)
        return await original()

    monkeypatch.setattr(pool, "close_all", counted)
    command_id = str(uuid.uuid4())
    first = await request(reader, writer, "pools.close", {}, command_id)
    assert first["ok"], first
    assert await request(reader, writer, "pools.close", {}, command_id) == first
    assert calls == [True]
    different = await request(reader, writer, "pools.close", {"host": "other"}, command_id)
    assert different["error"]["code"] == "id_conflict"
    assert calls == [True]


async def test_trajectory_reads_follow_configured_path_without_creating_writers(
    connected, tmp_path,
):
    core, reader, writer, _, _ = connected
    directory = tmp_path / "relocated-traces"
    directory.mkdir()
    entry = {"message_id": "example", "channel_id": "a", "user_id": "owner",
             "iterations": [], "user_content": "intact unicode: 雪"}
    trace = directory / "2026-10-06.jsonl"
    trace.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    core.management.settings.config.tools.trajectory_path = str(directory)
    before = trace.read_bytes()
    result = await request(reader, writer, "trajectories.read", {"filename": trace.name})
    assert result["ok"], result
    assert result["result"]["entries"] == [entry]
    bad = await request(reader, writer, "trajectories.read", {"filename": "../outside.jsonl"})
    assert bad["error"]["code"] == "bad_request"
    assert trace.read_bytes() == before
    assert core.store.connection.execute(
        "SELECT COUNT(*) FROM command_receipts").fetchone()[0] == 0
