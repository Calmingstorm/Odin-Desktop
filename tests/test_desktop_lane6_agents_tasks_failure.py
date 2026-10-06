"""Exact retained failure cases with actual published MCP fixture ownership."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest_asyncio

from src.desktop.controls import ControlService
from src.desktop.services import build_engine_services
from src.tools.mcp.client import DiscoveryResult, ToolRecord
from src.tools.mcp.manager import MCPManager, _ServerRuntime
from tests.desktop_adapters.lane6_agents_lineage_owner import lane6_agents_lineage_graph
from tests.desktop_adapters.lane6_agents_tasks import lane6_agents_tasks_graph_context
from tests.desktop_adapters.lane6_agents_tasks_recovery import load
from tests.desktop_adapters.tools_cases import owner_fixture


@pytest_asyncio.fixture(autouse=True)
async def lane6_agents_tasks_failure_graph(tmp_path):
    mcp = MCPManager()
    mcp._global_enabled = True
    mcp._servers["srv"] = _ServerRuntime(config={"enabled": True}, generation=1)
    connection = SimpleNamespace(connected=True)
    discovery = DiscoveryResult(tools=[ToolRecord("write", "hermetic metadata seam",
        {"type": "object", "properties": {"password": {"type": "string"}}})])
    assert await mcp._publish("srv", 1, connection, discovery)
    assert mcp.has_tool("mcp_srv_write")
    with owner_fixture(tmp_path / "owner") as owner:
        def compose(*args, **kwargs):
            return build_engine_services(*args, **kwargs,
                runtime_context=SimpleNamespace(mcp_manager=mcp))
        with patch(
            "tests.desktop_adapters.lane6_agents_lineage_owner.build_engine_services", compose
        ):
            graph = lane6_agents_lineage_graph(owner)
        graph.cid = graph.message.conversation_id
        graph.lane6_agents_tasks_messages = {}
        controls = ControlService(graph.store, graph.work.events, graph.requests,
            graph.engine.deps.channel_state, authority=owner.authority, permissions=owner.manager)
        controls.work = graph.work
        graph.work.controls = controls
        token = lane6_agents_tasks_graph_context.set(graph)
        try:
            assert graph.engine.deps.readiness()["mcp_srv_write"]
            yield graph
        finally:
            tasks = [
                t._asyncio_task for t in graph.engine.deps.channel_state.background_tasks.values()
                     if t._asyncio_task is not None and not t._asyncio_task.done()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await graph.requests.close()
            # The fixture connection is an inert metadata seam, not a transport.
            mcp._servers["srv"].connection = None
            await graph.engine.close()
            graph.store.close()
            lane6_agents_tasks_graph_context.reset(token)


load(globals(), "test_background_task_failure_visibility")
