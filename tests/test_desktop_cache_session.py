"""Odin 4.18 carry-over: one prompt-cache conversation ID per Desktop conversation.

Desktop's real core (IPC, request service, engine and tool loop) with a scripted
model that records the conversation ID bound to each model call. The Codex
client turns that ID into the ``session_id`` header and ``prompt_cache_key``
(tests/test_codex_cache_session.py checks the wire).
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from src.config.schema import OpenAICompatibleModelProfile
from src.llm.cache_session import current_session_id
from src.llm.types import LLMResponse, ToolCall
from tests.test_desktop_agent_vision import _first_text, _tool_results
from tests.test_desktop_background_core import cleanup, session
from tests.test_desktop_core_lifecycle import request
from tests.test_desktop_request_core import Provider, settled

AGENT = "CACHE-AGENT"
LOOP = "CACHE-LOOP"


class RecordingProvider(Provider):
    def __init__(self):
        super().__init__()
        self.seen: list[str | None] = []

    async def chat_with_tools(self, **kwargs):
        self.seen.append(current_session_id())
        return await super().chat_with_tools(**kwargs)


async def _send(reader, writer, core, cid, text):
    sent = await request(reader, writer, "submission.send", {
        "client_submission_id": str(uuid.uuid4()), "conversation_id": cid, "text": text})
    assert "result" in sent, sent
    await settled(core)


async def _rev(reader, writer, cid):
    listed = (await request(reader, writer, "conversations.list", {}))["result"]
    items = listed if isinstance(listed, list) else listed.get("items", listed.get("conversations"))
    return next(c["rev"] for c in items if c["id"] == cid)


@pytest.mark.asyncio
async def test_a_conversation_keeps_one_id_until_its_context_is_reset(tmp_path):
    provider = RecordingProvider()
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    try:
        await _send(reader, writer, core, cid, "First")
        await _send(reader, writer, core, cid, "Second")
        created = await request(reader, writer, "conversations.create", {})
        other = created["result"]["conversation"]["id"]
        await _send(reader, writer, core, other, "Elsewhere")
        reset = await request(reader, writer, "conversations.reset_context",
                              {"id": cid, "expected_rev": await _rev(reader, writer, cid)})
        assert "result" in reset, reset
        await _send(reader, writer, core, cid, "After the reset")
    finally:
        await cleanup(core, writer, rfd, wfd)
    first, second, elsewhere, after_reset = provider.seen
    for seen in provider.seen:
        assert uuid.UUID(seen).version == 4
    assert first == second  # one conversation, one ID across its turns
    assert elsewhere != first  # another conversation has its own
    assert after_reset not in (first, elsewhere)  # a context reset starts a new one
    assert current_session_id() is None


def _last_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        content = message.get("content")
        if message.get("role") == "user" and isinstance(content, str):
            return content
        if message.get("role") == "user" and isinstance(content, list):
            texts = [b.get("text", "") for b in content if b.get("type") == "text"]
            if texts:
                return " ".join(texts)
    return ""


class WorkProvider(Provider):
    """Main chat starts an agent, then a loop; each work request calls one tool, then answers."""

    def __init__(self):
        super().__init__()
        self.seen: list[tuple[str, str | None]] = []

    async def chat_with_tools(self, **kwargs):
        self.calls += 1
        messages = kwargs.get("messages", [])
        first = _first_text(messages)
        kind = "agent" if AGENT in first else "loop" if LOOP in first else "chat"
        self.seen.append((kind, current_session_id()))
        if kind != "chat":
            if not _tool_results(messages):
                return LLMResponse(tool_calls=[ToolCall(
                    "probe", "parse_time", {"expression": "tomorrow at 9am"})],
                    stop_reason="tool_use")
            return LLMResponse(text="work done")
        if _tool_results(messages):
            return LLMResponse(text="Started.")
        start = (("spawn_agent", {"label": "cache", "goal": f"{AGENT} check the time"})
                 if "agent work" in _last_user_text(messages) else
                 ("start_loop", {"goal": f"{LOOP} check the time", "mode": "silent",
                                 "max_iterations": 1, "interval_seconds": 10}))
        return LLMResponse(tool_calls=[ToolCall("start", *start)], stop_reason="tool_use")


@pytest.mark.asyncio
async def test_agents_and_loops_each_keep_their_own_id(tmp_path):
    provider = WorkProvider()
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    core.config.agents.model = "compat:test"
    core.config.openai_compatible.model_profiles["test"] = OpenAICompatibleModelProfile(
        total_window_tokens=200000, max_output_tokens=10000, supports_thinking_mode=True)
    try:
        await _send(reader, writer, core, cid, "Start the agent work")
        agents = list(core.engine.deps.agent_manager._agents.values())
        assert len(agents) == 1
        await asyncio.wait_for(agents[0]._task, 5)
        await _send(reader, writer, core, cid, "Start the loop work")
        started = list(core.engine.deps.loop_manager._loops.values())
        assert len(started) == 1
        await asyncio.wait_for(started[0]._task, 5)
    finally:
        await cleanup(core, writer, rfd, wfd)
    kinds = ("chat", "agent", "loop")
    ids = {kind: {sid for k, sid in provider.seen if k == kind} for kind in kinds}
    counts = {kind: sum(k == kind for k, _ in provider.seen) for kind in ids}
    assert counts["agent"] == 2 and counts["loop"] == 2, provider.seen  # 2 requests per run
    assert all(len(found) == 1 and None not in found for found in ids.values()), provider.seen
    chat, agent, loop = (next(iter(ids[k])) for k in ("chat", "agent", "loop"))
    assert len({chat, agent, loop}) == 3  # the agent and the loop never use the chat's ID


class IngressProvider(Provider):
    """Records the bound ID for tool-loop calls and plain chat calls (hand-off, follow-ups)."""

    def __init__(self, first_call=None):
        super().__init__()
        self.first_call = first_call
        self.seen: list[tuple[str, str | None]] = []

    async def chat_with_tools(self, **kwargs):
        self.calls += 1
        self.seen.append(("tools", current_session_id()))
        if self.first_call is not None and not _tool_results(kwargs.get("messages", [])):
            return LLMResponse(tool_calls=[ToolCall("first", *self.first_call)],
                               stop_reason="tool_use")
        return LLMResponse(text="Done.")

    async def chat(self, **kwargs):
        if "INCOMPLETE" in str(kwargs.get("system", "")):  # the completion judge
            self.seen.append(("judge", current_session_id()))
            return "COMPLETE"
        self.seen.append(("chat", current_session_id()))
        return "Conversational reply."


@pytest.mark.asyncio
async def test_compaction_before_a_turn_uses_the_conversation_id(tmp_path):
    provider = IngressProvider()
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    compactions: list[str | None] = []

    async def compact(messages, system):
        compactions.append(current_session_id())
        return "Summary of the earlier conversation."

    # The engine rebuilds a conversation's session from its transcript, so earlier
    # turns are real turns; with a one-token budget the second turn compacts.
    sessions = core.engine.deps.sessions
    sessions.token_budget = 1
    sessions.set_compaction_fn(compact)
    try:
        await _send(reader, writer, core, cid, "Hello")
        await _send(reader, writer, core, cid, "Hello again")
    finally:
        await cleanup(core, writer, rfd, wfd)
    turn_ids = [sid for kind, sid in provider.seen if kind == "tools"]
    assert compactions and len(turn_ids) == 2, (compactions, provider.seen)
    assert compactions[0] is not None and set(compactions) | set(turn_ids) == {compactions[0]}


@pytest.mark.asyncio
async def test_a_hand_off_reply_uses_the_conversation_id_and_reflection_its_own(tmp_path):
    provider = IngressProvider(("parse_time", {"expression": "tomorrow at 9am"}))
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    core.engine.runner._skill_manager.should_handoff_to_codex = lambda name: name == "parse_time"
    reflected: list[str | None] = []
    reflection_done = asyncio.Event()

    async def reflection(*args, **kwargs):
        reflected.append(current_session_id())
        reflection_done.set()

    core.engine.deps.turn_recorder._operational_reflection = reflection
    try:
        await _send(reader, writer, core, cid, "What time is tomorrow at 9am?")
        await asyncio.wait_for(reflection_done.wait(), 5)
    finally:
        await cleanup(core, writer, rfd, wfd)
    kinds = [kind for kind, _ in provider.seen]
    assert kinds == ["tools", "chat"], provider.seen  # one tool round, then the hand-off reply
    turn_id = provider.seen[0][1]
    assert turn_id is not None and provider.seen[1][1] == turn_id
    assert reflected[0] not in (None, turn_id)  # background learning has its own ID


@pytest.mark.asyncio
async def test_a_delegated_task_follow_up_has_its_own_id(tmp_path):
    provider = IngressProvider(("delegate_task", {
        "description": "check the time", "steps": [
            {"tool_name": "parse_time", "tool_input": {"expression": "tomorrow at 9am"}}]}))
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    try:
        await _send(reader, writer, core, cid, "Check the time in the background")
        tasks = list(core.engine.deps.channel_state.background_tasks.values())
        assert len(tasks) == 1
        await asyncio.wait_for(tasks[0]._asyncio_task, 5)
    finally:
        await cleanup(core, writer, rfd, wfd)
    turn_ids = {sid for kind, sid in provider.seen if kind in ("tools", "judge")}
    follow_ups = [sid for kind, sid in provider.seen if kind == "chat"]
    assert len(turn_ids) == 1 and None not in turn_ids, provider.seen
    assert len(follow_ups) == 1 and follow_ups[0] not in (None, *turn_ids), provider.seen
