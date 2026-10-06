"""Exact whole provider-path corpus plus canonical service identity contracts."""

import pytest_asyncio

from src.agents.manager import AgentManager
from src.desktop.work import WorkService
from src.discord.native_tools.agents_tasks import AgentTaskTools
from src.discord.tool_loop import ToolLoopRunner
from tests.desktop_adapters.lane6_agents_tasks import (
    lane6_agents_tasks_case_map,
    lane6_agents_tasks_graph_context,
    lane6_agents_tasks_native_owner,
    load,
)
from tests.desktop_adapters.test_phase2_runner_characterization import (
    graph as graph,
)

lane6_agents_tasks_graph = graph


@pytest_asyncio.fixture(autouse=True)
async def lane6_agents_tasks_owner_fixture(lane6_agents_tasks_graph):
    graph = lane6_agents_tasks_graph
    deps = graph.engine.deps
    graph.work = WorkService(
        graph.store,
        graph.requests.delivery.events,
        authority=graph.requests.authority,
        permissions=graph.requests.permissions,
        requests=graph.requests,
        conversations=graph.requests.conversations,
        agents=deps.agent_manager,
        tasks=deps.channel_state.background_tasks,
        loops=deps.loop_manager,
    )
    owner = deps.native_owners["agents"]
    owner._background_admission = graph.requests
    owner._work_service = graph.work

    async def lane6_agents_tasks_publish(message, kind, text):
        raise AssertionError("Policy-only frozen suite must not publish background work")

    owner._publish_background = lane6_agents_tasks_publish
    token = lane6_agents_tasks_graph_context.set(graph)
    try:
        yield graph
    finally:
        lane6_agents_tasks_graph_context.reset(token)


def test_lane6_agents_tasks_bridge_is_canonical_owner(lane6_agents_tasks_owner_fixture):
    graph = lane6_agents_tasks_owner_fixture
    owner = lane6_agents_tasks_native_owner()
    assert isinstance(owner, AgentTaskTools)
    assert isinstance(owner._agent_manager, AgentManager)
    assert isinstance(owner._tool_loop, ToolLoopRunner)
    assert owner is graph.engine.deps.native_owners["agents"]
    assert owner._tool_loop is graph.engine.runner
    assert owner._agent_manager is graph.work.agents
    assert owner._work_service.requests is graph.requests
    assert graph.requests.engine is graph.engine
    assert graph.engine.requests is graph.requests
    assert owner._agent_generate.__func__ is AgentTaskTools._agent_generate


def test_lane6_agents_tasks_whole_suite_case_binding():
    assert (
        sum(
            path.startswith("tests/test_agents_tasks_provider_paths.py::")
            for path in lane6_agents_tasks_case_map
        )
        == 9
    )


load(globals())
