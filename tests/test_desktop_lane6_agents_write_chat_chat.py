"""Execute the complete retained frozen chat corpus on canonical owners."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from src.desktop.requests import EngineRequest
from src.tools.result_validator import ToolResult
from tests.desktop_adapters.lane6_agents_write_chat_chat import (
    CORPUS_EXCLUSIONS,
    lane6_agents_write_chat_chat_cases,
    lane6_agents_write_chat_chat_current,
    lane6_agents_write_chat_chat_make_bot,
    lane6_agents_write_chat_chat_message,
    lane6_agents_write_chat_chat_run_loop,
    load,
)
from tests.desktop_adapters.tools_cases import owner_fixture
from tests.fakes import FakeLLM, text_response, tool_call_response

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def lane6_agents_write_chat_chat_owner(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with owner_fixture(tmp_path) as owner:
        state = SimpleNamespace(owner=owner, root=tmp_path / "graphs", graphs=[])
        token = lane6_agents_write_chat_chat_current.set(state)
        try:
            yield state
        finally:
            lane6_agents_write_chat_chat_current.reset(token)
            for graph in state.graphs:
                await graph.requests.close()
                await graph.engine.close()
                graph.store.close()


async def test_lane6_agents_write_chat_chat_shared_canonical_graph(
        lane6_agents_write_chat_chat_owner):
    bot = lane6_agents_write_chat_chat_make_bot(fake_llm=FakeLLM([text_response("done")]))
    message = lane6_agents_write_chat_chat_message("hello")
    graph = lane6_agents_write_chat_chat_owner.graph
    assert isinstance(message, EngineRequest)
    assert graph.requests.engine is graph.engine
    assert graph.engine.requests is graph.requests
    assert graph.requests.store is graph.work.store is graph.store
    assert graph.requests.transcript.store is graph.store
    assert graph.requests.events.store is graph.store
    assert graph.engine.deps.turn_store is graph.ledger
    assert bot.tool_loop is graph.engine.runner
    assert message.author.id == graph.requests.authority.owner_id
    assert graph.requests.fetch_request(graph.cid, message.request_id) == message
    result = await lane6_agents_write_chat_chat_run_loop(bot, message)
    assert result[0] == "done"
    assert graph.requests.get_request(message.request_id)["state"] == "running"


async def test_lane6_agents_write_chat_chat_partition():
    assert len(lane6_agents_write_chat_chat_cases) == 38
    assert len(CORPUS_EXCLUSIONS["test_chat_tool_loop"]) == 2
    from tests.desktop_adapters.lane6_agents_write_chat_chat import PROPOSED_CASES
    assert PROPOSED_CASES == {}


async def test_lane6_agents_write_chat_chat_source_identity_is_observation_only(
        lane6_agents_write_chat_chat_owner):
    from tests.desktop_adapters.lane6_agents_write_chat_chat import (
        lane6_agents_write_chat_chat_source_kill_observer,
    )

    bot = lane6_agents_write_chat_chat_make_bot(fake_llm=FakeLLM([
        text_response("done")]))
    source = lane6_agents_write_chat_chat_message("source mapping", id=987654)
    graph = lane6_agents_write_chat_chat_owner.graph
    canonical = graph.source_messages[id(source)][1]
    assert canonical.request_id != str(source.id)
    assert canonical.conversation_id != str(source.channel.id)
    assert isinstance(canonical, EngineRequest)
    assert graph.requests.fetch_request(graph.cid, canonical.request_id) == canonical
    async with graph.requests.background_execution(canonical, settle=False):
        event = bot.channel_state.set_active_request(graph.cid, canonical.request_id)
        assert bot.channel_state.cancel_events["99"] is event
        assert bot.channel_state.cancel_events[graph.cid] is event
        observer = lane6_agents_write_chat_chat_source_kill_observer(return_value=[])
        assert observer(canonical.request_id) == []
        observer.assert_called_once_with("987654")
        with pytest.raises(AssertionError):
            observer("987654")
    assert "99" not in bot.channel_state.active_requests
    assert bot.channel_state.active_requests[graph.cid] == canonical.request_id


async def test_lane6_agents_write_chat_chat_stop_during_generation(
        lane6_agents_write_chat_chat_owner):
    def lane6_agents_write_chat_chat_cancel_generation():
        graph.engine.deps.channel_state.cancel_events[graph.cid].set()
        return tool_call_response(("parse_time", {"text": "now"}))

    fake = FakeLLM([lane6_agents_write_chat_chat_cancel_generation])
    bot = lane6_agents_write_chat_chat_make_bot(fake_llm=fake)
    graph = lane6_agents_write_chat_chat_owner.graph
    msg = lane6_agents_write_chat_chat_message("stop during generation")
    bot.tool_executor.execute = AsyncMock()
    result = await lane6_agents_write_chat_chat_run_loop(bot, msg)
    assert result == ("Task stopped by user.", False, False, [], False)
    bot.tool_executor.execute.assert_not_awaited()
    assert graph.cid not in bot.channel_state.active_requests
    assert not bot.channel_state.cancel_events[graph.cid].is_set()


async def test_lane6_agents_write_chat_chat_stop_kills_real_turn_agents(
        lane6_agents_write_chat_chat_owner):
    bot = lane6_agents_write_chat_chat_make_bot(fake_llm=FakeLLM([
        tool_call_response(("read_file", {"host": "h", "path": "/x"}))]))
    graph = lane6_agents_write_chat_chat_owner.graph
    msg = lane6_agents_write_chat_chat_message("stop only this turn")
    other = lane6_agents_write_chat_chat_message("unrelated turn")
    manager = graph.engine.deps.agent_manager
    started = [asyncio.Event(), asyncio.Event()]

    async def lane6_agents_write_chat_chat_iteration(messages, system_prompt, tools, **kwargs):
        index = 0 if "linked" in str(messages) else 1
        started[index].set()
        await asyncio.Event().wait()

    async def lane6_agents_write_chat_chat_execute(name, inp):
        raise AssertionError("Agent fixture must not execute effects")

    ids = [manager.spawn(label, label, graph.cid, msg.owner_id, "Owner",
        lane6_agents_write_chat_chat_iteration, lane6_agents_write_chat_chat_execute,
        turn_id=request.id) for label, request in [("linked", msg), ("unrelated", other)]]
    tasks = [manager._agents[aid]._task for aid in ids]
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started)), 10)

        async def lane6_agents_write_chat_chat_stop_tool(name, inp, user_id=None):
            graph.requests.assert_bound_request(msg)
            bot.channel_state.cancel_events[graph.cid].set()
            return ToolResult(output="done", tool_name=name)

        bot.tool_executor.execute = lane6_agents_write_chat_chat_stop_tool
        result = await lane6_agents_write_chat_chat_run_loop(bot, msg)
        await asyncio.sleep(0)
        assert "Sent cancellation to 1 agent(s) spawned by this turn" in result[0]
        assert tasks[0].done()
        assert not tasks[1].done()
        assert manager._agents[ids[0]]._cancel_event.is_set()
        assert not manager._agents[ids[1]]._cancel_event.is_set()
    finally:
        manager.kill(ids[1])
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_lane6_agents_write_chat_chat_persisted_redelivery(
        lane6_agents_write_chat_chat_owner):
    fake = FakeLLM([tool_call_response(("read_file", {"host": "h", "path": "/x"})),
                   text_response("done")])
    bot = lane6_agents_write_chat_chat_make_bot(fake_llm=fake)
    graph = lane6_agents_write_chat_chat_owner.graph
    msg = lane6_agents_write_chat_chat_message("read once")
    bot.tool_executor.execute = AsyncMock(return_value=ToolResult(
        output="read", tool_name="read_file"))
    first = await lane6_agents_write_chat_chat_run_loop(bot, msg)
    persisted = graph.requests.fetch_request(graph.cid, msg.request_id)
    second = await lane6_agents_write_chat_chat_run_loop(bot, persisted)
    assert first[0] == "done"
    assert "already processed" in second[0]
    assert persisted.id == msg.id
    assert persisted.turn_key == msg.turn_key
    assert graph.ledger.turn_status_sync(msg.turn_key) == "TERMINAL_COMPLETED"
    assert len(fake.calls) == 2
    bot.tool_executor.execute.assert_awaited_once()


load(globals())
