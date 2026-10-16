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
