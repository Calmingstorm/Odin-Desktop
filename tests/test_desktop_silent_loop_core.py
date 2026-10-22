"""Odin 4.21.0 carry-over (PR #672): a silent loop's quiet iteration is its answer.

Desktop's real core (IPC, request service, engine, start_loop, the loop manager and the
tool loop) with a scripted model. These replace the cases of Odin's
``tests/test_silent_loop_empty_reply.py`` that build Odin's Discord bot (``build_loop``),
which Desktop doesn't have; the providers' own acceptance of a settled empty reply is
tested in tests/test_desktop_silent_loop_empty_reply.py.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from src.llm.types import LLMResponse, ToolCall
from tests.test_desktop_agent_vision import _tool_results
from tests.test_desktop_background_core import cleanup, notified, session
from tests.test_desktop_core_lifecycle import request
from tests.test_desktop_request_core import Provider, settled

LOOP = "SILENT-LOOP-CARRY"


def _is_loop_request(messages: list[dict]) -> bool:
    """A loop iteration's prompt names the loop and its goal (after any earlier context)."""
    texts = [str(m.get("content")) for m in messages if m.get("role") == "user"]
    return any("AUTONOMOUS LOOP" in text and LOOP in text for text in texts)


class LoopProvider(Provider):
    """Main chat starts one loop, once; each loop request answers from a script."""

    def __init__(self, start: dict, loop_replies: list[LLMResponse]):
        super().__init__()
        self.start, self.loop_replies = start, list(loop_replies)
        self.loop_calls: list[dict] = []
        self.started = False

    async def chat_with_tools(self, **kwargs):
        self.calls += 1
        messages = kwargs.get("messages", [])
        if _is_loop_request(messages):
            self.loop_calls.append(kwargs)
            return self.loop_replies.pop(0) if self.loop_replies else LLMResponse(text="")
        if self.started or _tool_results(messages):
            return LLMResponse(text="Started.")
        self.started = True  # later chat turns (the loop's end notice) start nothing
        return LLMResponse(tool_calls=[ToolCall("start", "start_loop", self.start)],
                           stop_reason="tool_use")


async def _run_loop(tmp_path, provider, *, no_wait=False):
    """Start the provider's loop from a chat turn and wait for it to end."""
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    if no_wait:
        async def _no_wait(*_args):
            return False

        core.engine.deps.loop_manager._interruptible_wait = _no_wait
    try:
        sent = await request(reader, writer, "submission.send", {
            "client_submission_id": str(uuid.uuid4()), "conversation_id": cid,
            "text": "Start the loop"})
        assert sent["ok"], sent
        await settled(core)
        (info,) = core.engine.deps.loop_manager._loops.values()
        await asyncio.wait_for(info._task, 5)
        return info, notified(core, "loop")
    finally:
        await cleanup(core, writer, rfd, wfd)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["silent", "notify", "act"])
async def test_only_a_silent_loop_asks_for_the_opt_in(tmp_path, mode):
    provider = LoopProvider(
        {"goal": f"{LOOP} watch the queue", "mode": mode, "max_iterations": 1,
         "interval_seconds": 10},
        [LLMResponse(text="nothing new")])
    await _run_loop(tmp_path, provider)
    assert provider.loop_calls
    assert provider.loop_calls[0].get("allow_empty_reply") is (True if mode == "silent" else None)


@pytest.mark.asyncio
async def test_quiet_silent_iterations_post_nothing_count_no_error_and_alerts_still_work(tmp_path):
    quiet = [LLMResponse(text="") for _ in range(4)]
    provider = LoopProvider(
        {"goal": f"{LOOP} watch the disk", "mode": "silent", "max_iterations": 10,
         "interval_seconds": 10},
        [*quiet, LLMResponse(text="[ALERT] disk full\nLOOP_STOP")])
    info, posts = await _run_loop(tmp_path, provider, no_wait=True)
    assert info.status == "completed"
    assert info.interval_seconds == 10  # no identical-output backoff
    assert len(provider.loop_calls) == 5
    assert all(call.get("allow_empty_reply") is True for call in provider.loop_calls)
    # The four quiet iterations posted nothing; the alert did, then the loop's end.
    assert posts[0] == "[ALERT] disk full", posts
    assert all("disk full" not in post for post in posts[1:]), posts
    assert len(posts) <= 2, posts


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["silent", "notify"])
async def test_earlier_narration_never_becomes_a_silent_iterations_answer(tmp_path, mode):
    script = [
        LLMResponse(text="[NOTIFY] checking now",
                    tool_calls=[ToolCall("probe", "parse_time", {"expression": "tomorrow at 9am"})],
                    stop_reason="tool_use"),
        LLMResponse(text=""),
    ]
    provider = LoopProvider(
        {"goal": f"{LOOP} do the loop work", "mode": mode, "max_iterations": 1,
         "interval_seconds": 10},
        script)
    _info, posts = await _run_loop(tmp_path, provider)
    assert len(provider.loop_calls) == 2
    # The narration stays in the conversation the model saw.
    second = provider.loop_calls[1]["messages"]
    assert any(
        message.get("role") == "assistant"
        and "[NOTIFY] checking now" in str(message.get("content"))
        for message in second
    )
    narrated = [post for post in posts if "[NOTIFY] checking now" in post]
    if mode == "silent":
        assert narrated == [], posts  # the empty final is the answer
    else:
        assert narrated, posts  # other modes keep today's behavior
