"""Whole frozen cancellation suite with persisted control/publication receipts."""
import asyncio
import pytest_asyncio
from src.desktop.controls import ControlService
from tests.desktop_adapters.tools_cases import owner_fixture
from tests.desktop_adapters.lane6_agents_lineage_owner import lane6_agents_lineage_graph
from tests.desktop_adapters.lane6_agents_tasks import lane6_agents_tasks_graph_context
from tests.desktop_adapters.lane6_agents_tasks_recovery import load


@pytest_asyncio.fixture(autouse=True)
async def lane6_agents_tasks_cancel_graph(tmp_path):
    with owner_fixture(tmp_path / "owner") as owner:
        graph = lane6_agents_lineage_graph(owner)
        graph.cid = graph.message.conversation_id
        graph.lane6_agents_tasks_messages = {}
        controls = ControlService(graph.store, graph.work.events, graph.requests,
            graph.engine.deps.channel_state, authority=owner.authority, permissions=owner.manager)
        controls.work = graph.work
        graph.work.controls = controls
        token = lane6_agents_tasks_graph_context.set(graph)
        try:
            yield graph
        finally:
            tasks = [t._asyncio_task for t in graph.engine.deps.channel_state.background_tasks.values()
                     if t._asyncio_task is not None and not t._asyncio_task.done()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await graph.requests.close()
            await graph.engine.close()
            graph.store.close()
            lane6_agents_tasks_graph_context.reset(token)


load(globals())
