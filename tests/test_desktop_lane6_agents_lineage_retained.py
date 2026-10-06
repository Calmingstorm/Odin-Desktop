"""Whole hash-bound inherited lineage suites, not case samples."""
import pytest
import pytest_asyncio

from src.agents.manager import AgentManager
from src.discord.tool_loop import ToolLoopRunner
from src.tools.executor import ToolExecutor
from tests.desktop_adapters.lane6_agents_lineage_owner import (
    lane6_agents_lineage_current,
    lane6_agents_lineage_graph,
)
from tests.desktop_adapters.lane6_agents_lineage_retained import load
from tests.desktop_adapters.tools_cases import owner_fixture


@pytest_asyncio.fixture(autouse=True)
async def lane6_agents_lineage_owner_fixture(tmp_path, request):
    if not any(stem in request.node.nodeid for stem in (
            "test_tool_loop_provenance", "test_tool_lifecycle_correlation")):
        yield
        return
    with owner_fixture(tmp_path) as owner:
        graph = lane6_agents_lineage_graph(owner)
        token = lane6_agents_lineage_current.set(graph)
        try:
            yield graph
        finally:
            lane6_agents_lineage_current.reset(token)
            await graph.requests.close()
            await graph.engine.close()
            graph.store.close()

load(globals())


@pytest.mark.asyncio
async def test_lane6_agents_lineage_test_tool_loop_provenance_owner_identity(
        lane6_agents_lineage_owner_fixture):
    graph = lane6_agents_lineage_owner_fixture
    assert type(graph.engine.runner) is ToolLoopRunner
    assert type(graph.engine.deps.agent_manager) is AgentManager
    assert type(graph.engine.deps.tool_executor) is ToolExecutor
    assert graph.work.agents is graph.engine.deps.agent_manager
    assert graph.work.requests is graph.requests
    assert graph.engine.requests is graph.requests
    assert graph.engine.runner._tool_executor is graph.engine.deps.tool_executor
    assert graph.engine.runner._native_tools is graph.engine.deps.native_tools
    assert graph.engine.runner._assert_bound_request == graph.requests.assert_bound_request
    async with graph.requests.background_execution(graph.message):
        graph.requests.assert_bound_request(graph.message)
    assert graph.message.owner_id == graph.owner.authority.owner_id
