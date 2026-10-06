"""Retained frozen native cases, real admission and manager-wrap observations."""
import asyncio

import pytest_asyncio

from src.desktop.controls import ControlService
from tests.desktop_adapters.lane6_agents_lineage_owner import lane6_agents_lineage_graph
from tests.desktop_adapters.lane6_agents_tasks import lane6_agents_tasks_graph_context
from tests.desktop_adapters.lane6_agents_tasks_native import (
    lane6_agents_tasks_native_task,
    load,
)
from tests.desktop_adapters.tools_cases import owner_fixture


@pytest_asyncio.fixture(autouse=True)
async def lane6_agents_tasks_native_graph(tmp_path):
    with owner_fixture(tmp_path / "owner") as owner:
        graph = lane6_agents_lineage_graph(owner)
        graph.cid = graph.message.conversation_id
        controls = ControlService(graph.store, graph.work.events, graph.requests,
            graph.engine.deps.channel_state, authority=owner.authority, permissions=owner.manager)
        controls.work = graph.work
        graph.work.controls = controls
        async def publish(message, text, kind=None):
            return await graph.requests.delivery.send(message.channel, text)
        graph.engine.deps.native_owners["agents"]._publish_background = publish
        token = lane6_agents_tasks_graph_context.set(graph)
        try:
            yield graph
        finally:
            tasks = [a._task for a in graph.engine.deps.agent_manager._agents.values()
                     if getattr(a, "_task", None) is not None and not a._task.done()]
            tasks.extend(
                t._asyncio_task for t in graph.engine.deps.channel_state.background_tasks.values()
                if getattr(t, "_asyncio_task", None) is not None and not t._asyncio_task.done()
            )
            tasks.extend(loop._task for loop in graph.engine.deps.loop_manager._loops.values()
                         if loop._task is not None and not loop._task.done())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await graph.requests.close()
            await graph.engine.close()
            graph.store.close()
            lane6_agents_tasks_graph_context.reset(token)


load(globals())


async def test_lane6_native_retained_task_privacy_without_multiuser_tiers(
    lane6_agents_tasks_native_graph,
):
    graph = lane6_agents_tasks_native_graph
    native = graph.engine.deps.native_owners["agents"]
    task = lane6_agents_tasks_native_task(desc="owner-private-output")
    graph.engine.deps.channel_state.background_tasks[task.task_id] = task
    owner = graph.owner.authority.owner_id
    assert "owner-private-output" in native._handle_list_tasks(
        {}, user_id=owner, channel_id=graph.cid
    )
    assert "owner-private-output" in native._handle_list_tasks(
        {"task_id": task.task_id}, user_id=owner, channel_id=graph.cid
    )
    for reader, destination in (("unissued-reader", graph.cid), (owner, "other"), ("", graph.cid)):
        assert "owner-private-output" not in native._handle_list_tasks(
            {}, user_id=reader, channel_id=destination
        )
        actual = native._handle_list_tasks(
            {"task_id": task.task_id}, user_id=reader, channel_id=destination
        )
        absent = native._handle_list_tasks(
            {"task_id": "absent"}, user_id=reader, channel_id=destination
        )
        assert actual.replace(task.task_id, "absent") == absent
