"""Whole inherited write invariant through isolated canonical service owners."""
import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio

from tests.desktop_adapters.lane6_agents_write_chat_write import (
    lane6_agents_write_chat_write_build,
    lane6_agents_write_chat_write_context,
    load,
)
from tests.desktop_adapters.tools_cases import owner_fixture


@pytest_asyncio.fixture(autouse=True)
async def lane6_agents_write_chat_write_owner(tmp_path, request):
    with owner_fixture(tmp_path / "owner") as owner:
        state = SimpleNamespace(owner=owner, graphs=[])
        token = lane6_agents_write_chat_write_context.set(state)
        try:
            if "ttl_sweep" in request.node.name:
                lane6_agents_write_chat_write_build([], tmp_path)
            yield state
        finally:
            for graph in state.graphs:
                for context in graph.contexts.values():
                    await context.__aexit__(None, None, None)
                tasks = [a._task for a in graph.engine.deps.agent_manager._agents.values()
                         if a._task is not None and not a._task.done()]
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await graph.requests.close()
                await graph.engine.close()
                graph.ledger.close()
                graph.store.close()
            lane6_agents_write_chat_write_context.reset(token)


load(globals())


@pytest.mark.asyncio
async def test_lane6_agents_write_chat_write_canonical_graph_and_redelivery():
    """One durable identity and one real graph, including feature-off ownership."""
    from tests.desktop_adapters.lane6_agents_write_chat_write import (
        lane6_agents_write_chat_write_disable_durability,
        lane6_agents_write_chat_write_message,
        lane6_agents_write_chat_write_run_loop,
    )
    from tests.fakes import text_response

    state = lane6_agents_write_chat_write_context.get()
    bot, fake, ledger = lane6_agents_write_chat_write_build(
        [text_response("settled")], state.owner.paths.data_dir)
    graph = state.graph
    assert graph.requests.store is graph.work.store is graph.store
    assert graph.requests.conversations.store is graph.requests.transcript.store is graph.store
    assert graph.engine.requests is graph.requests
    assert graph.engine.deps.turn_store is bot.tool_loop._turn_store is ledger
    assert graph.work.agents is graph.engine.deps.agent_manager
    message = lane6_agents_write_chat_write_message("harmless identity check")
    first = await lane6_agents_write_chat_write_run_loop(bot, message)
    assert first[0] == "settled"
    fetched = graph.requests.fetch_request(graph.cid, message.request_id)
    assert fetched.id == message.id
    assert fetched.turn_key == message.turn_key
    second = await lane6_agents_write_chat_write_run_loop(bot, fetched)
    assert "already processed" in second[0]
    assert len(fake.calls) == 1
    assert ledger._conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1
    lane6_agents_write_chat_write_disable_durability(bot)
    assert bot.tool_loop._turn_store is graph.engine.deps.turn_store is None
    fake.responses.append(text_response("legacy check"))
    fresh = lane6_agents_write_chat_write_message("harmless feature-off check")
    assert (await lane6_agents_write_chat_write_run_loop(bot, fresh))[0] == "legacy check"
    assert ledger._conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1
