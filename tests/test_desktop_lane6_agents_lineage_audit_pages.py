"""Whole-suite audit/page lineage and authentic canonical owner contracts."""
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio

from src.agents.manager import AgentManager
from src.discord.tool_loop import ToolLoopRunner
from tests.desktop_adapters.lane6_agents_lineage_audit_pages import (
    lane6_agents_lineage_dispatcher,
    lane6_agents_lineage_finish,
    lane6_agents_lineage_graph,
    lane6_agents_lineage_harness,
    lane6_agents_lineage_manager,
    lane6_agents_lineage_state,
    load,
)
from tests.desktop_adapters.tools_cases import owner_fixture


@pytest_asyncio.fixture(autouse=True)
async def lane6_agents_lineage_owner(tmp_path):
    with owner_fixture(tmp_path / "owner") as owner:
        state = SimpleNamespace(owner=owner, graphs=[], managers={})
        token = lane6_agents_lineage_state.set(state)
        try:
            yield state
        finally:
            for graph in reversed(state.graphs):
                await graph.requests.close()
                await graph.engine.close()
                graph.store.close()
            lane6_agents_lineage_state.reset(token)


@pytest.mark.asyncio
async def test_lane6_agents_lineage_canonical_audit_owner(lane6_agents_lineage_owner, tmp_path):
    runner, message, agent = lane6_agents_lineage_harness(tmp_path)
    graph = lane6_agents_lineage_owner.graphs[-1]
    assert isinstance(runner, ToolLoopRunner)
    assert isinstance(graph.work.agents, AgentManager)
    assert graph.work.agents is graph.engine.deps.agent_manager
    assert graph.engine.deps.native_owners["agents"]._agent_manager is graph.work.agents
    assert graph.engine.deps.native_owners["agents"]._tool_loop is runner
    async with graph.requests.background_execution(message):
        record = graph.work.register("agent", agent.id, message)
        assert record["owner_id"] == graph.owner_id
        assert record["conversation_id"] == graph.cid
        assert record["manager_generation"] == str(agent.created_at)
        assert graph.requests.get_request(message.request_id)["state"] == "running"


@pytest.mark.asyncio
async def test_lane6_agents_lineage_real_bound_dispatch():
    graph = lane6_agents_lineage_graph()
    message = graph.requests._register_background(
        "workflow", "bound-dispatch", "parse time", graph.cid, graph.owner_id)
    async with graph.requests.background_execution(message):
        result = await graph.engine.runner.dispatch_loop_tool(
            "parse_time", {"expression": "in 2 hours"}, message, graph.owner_id)
        assert result is not None
    with pytest.raises(PermissionError):
        await graph.engine.runner.dispatch_loop_tool(
            "parse_time", {"expression": "in 2 hours"}, message, graph.owner_id)


@pytest.mark.asyncio
async def test_lane6_agents_lineage_byte_complete_restart_and_owner(tmp_path):
    from src.agents.trajectory import AgentTrajectorySaver

    manager = lane6_agents_lineage_manager()
    saver = AgentTrajectorySaver(str(tmp_path / "trajectories"))
    text = "é水🌍\n" * 2500 + "unique-tail"
    aid = await lane6_agents_lineage_finish(manager, saver, text)
    call = lane6_agents_lineage_dispatcher(tmp_path, manager, saver)
    initial = json.loads(await call("get_agent_results", {"agent_id": aid, "limit": 17}))
    assert initial["original_bytes"] == len(text.encode())
    assert initial["truncated"] is True
    assert (
        await call("get_agent_results", {"agent_id": aid, "cursor": "invalid"})
        == "Invalid or stale result cursor"
    )
    assert manager._remove_agent(aid)
    call = lane6_agents_lineage_dispatcher(tmp_path, lane6_agents_lineage_manager(),
                                          AgentTrajectorySaver(str(saver.directory)))
    pages, cursor = [], ""
    while True:
        page = json.loads(
            await call("get_agent_results", {"agent_id": aid, "cursor": cursor, "limit": 997})
        )
        assert len(page["preview"].encode()) <= 997
        pages.append(page["preview"])
        cursor = page["cursor"]
        if cursor is None:
            break
    assert "".join(pages).encode() == text.encode()
    for uid, cid in [("other", 42), ("7", 43), ("", 42)]:
        assert "not found" in await call("get_agent_results", {"agent_id": aid}, uid, cid)
    wait = await call("wait_for_agents", {"agent_ids": [aid], "timeout": 0})
    assert "completed" in wait and "original_bytes=" in wait and "cursor=" in wait
    assert len(wait.encode()) < 1400


load(globals())
