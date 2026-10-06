"""Execute complete retained loop and workflow projections in isolated profiles."""
from types import SimpleNamespace

import pytest_asyncio

from tests.desktop_adapters.lane6_schedules_core import graph as graph
from tests.desktop_adapters.lane6_schedules_core import (
    lane6_schedules_core_graph as lane6_schedules_core_graph,
)
from tests.desktop_adapters.lane6_schedules_finish import CURRENT, bind_work, load
from tests.desktop_adapters.lane6_schedules_loops_bridge import CURRENT as LOOP_CURRENT


def test_native_skill_readiness_requires_actual_owner_and_bound_requests(graph):
    deps = graph.engine.deps
    names = ("create_skill", "edit_skill", "delete_skill", "enable_skill",
             "disable_skill", "install_skill", "skill_status", "list_skills", "invoke_skill")
    assert all(deps.readiness()[name] for name in names)
    assert "export_skill" not in {tool["name"] for tool in
                                  deps.tool_catalog.merged_definitions()}
    actual = deps.native_tools.skills.skill_manager
    deps.native_tools.skills.skill_manager = None
    try:
        assert all(not deps.readiness()[name] for name in names)
    finally:
        deps.native_tools.skills.skill_manager = actual
    graph.engine.requests = None
    try:
        assert all(not deps.readiness()[name] for name in names)
    finally:
        graph.engine.requests = graph.requests
    assert not deps.readiness().get("export_skill", False)


@pytest_asyncio.fixture(autouse=True)
async def finish_graphs(graph, tmp_path):
    bind_work(graph)
    graph.finish_schedulers = []
    state = SimpleNamespace(root=tmp_path / "loop-graphs", graphs=[], latest=None)
    token = CURRENT.set(graph)
    loop_token = LOOP_CURRENT.set(state)
    try:
        yield
    finally:
        for scheduler in graph.finish_schedulers:
            await scheduler.stop()
        for loop_graph in reversed(state.graphs):
            await loop_graph.close()
        LOOP_CURRENT.reset(loop_token)
        CURRENT.reset(token)


load(globals())
