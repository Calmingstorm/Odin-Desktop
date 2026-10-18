"""Odin 4.19 carry-over: spawned agents queue interim reports for their spawner.

Odin's own report tests (test_agent_reports*.py) run here where Desktop has
their harness; the cases that need Odin's Discord bot or Odin's unwired
background path are covered below instead: the spawn binding with Desktop's
durable background admission, and a real-core conversation in which a spawned
agent reports while the turn waits for it.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.execution_context import agent_dispatch
from src.agents.manager import AgentInfo
from src.agents.reports import REPORT_HEADER, ReportTarget
from src.audit.tool_context import _pending_observers
from src.config.schema import OpenAICompatibleModelProfile
from src.llm.types import LLMResponse, ToolCall
from tests.test_desktop_background_core import cleanup, session
from tests.test_desktop_core_lifecycle import request
from tests.test_desktop_request_core import Provider, settled
from tests.test_native_agents_tasks import _tools

AGENT = "REPORTING-AGENT"
SPAWN_SENTENCE = (
    "When you want interim reports, tell spawned agents to use their agent-only "
    "report_to_parent tool, not send_to_agent."
)
SEND_SENTENCE = "For interim reports to your spawner, use report_to_parent, not this tool."


class _Admission:
    """Desktop's durable background admission, reduced to what spawning uses."""

    def __init__(self, background: set[str] = frozenset()):
        self.background = set(background)

    def register_background(self, message, kind, run_id, text, **kwargs):
        return SimpleNamespace(id=f"bg-{run_id}", request_id=f"bg-{run_id}",
                               channel=getattr(message, "channel", None),
                               author=getattr(message, "author", None))

    def is_background(self, message):
        return getattr(message, "request_id", None) in self.background

    @contextlib.asynccontextmanager
    async def background_execution(self, message, *, settle=True):
        yield


class TestBindingAtSpawn:
    async def _spawn(self, message, inp, *, background=(), dispatching=None, agents=None):
        t = _tools()
        t._background_admission = _Admission(set(background))
        t._work_service = MagicMock()
        t._publish_background = AsyncMock()
        t._agent_manager.spawn.return_value = "child-1"
        t._agent_manager._agents = {**(agents or {}), "child-1": MagicMock()}
        if dispatching is None:
            await t._handle_spawn_agent(message, inp)
        else:
            with agent_dispatch(dispatching, {"id": "spawn-call"}):
                await t._handle_spawn_agent(message, inp)
        return t._agent_manager.spawn.call_args.kwargs

    @staticmethod
    def _request(request_id: str):
        return SimpleNamespace(id=request_id, request_id=request_id, conversation_id="conv-1",
                               owner_id="owner", owner_name="owner",
                               channel=SimpleNamespace(id="conv-1"),
                               author=SimpleNamespace(id="owner"))

    async def test_a_conversation_turn_receives_by_its_request(self):
        kwargs = await self._spawn(self._request("req-1"), {"label": "c", "goal": "g"})
        assert kwargs["report_target"] == ReportTarget.for_turn("conv-1", "req-1")

    async def test_a_chosen_parent_changes_tree_accounting_not_the_receiver(self):
        parent = SimpleNamespace(depth=0, max_depth=2)
        kwargs = await self._spawn(self._request("req-2"),
                                   {"label": "c", "goal": "g", "parent_id": "other"},
                                   agents={"other": parent})
        assert kwargs["parent_id"] == "other"
        assert kwargs["report_target"] == ReportTarget.for_turn("conv-1", "req-2")

    async def test_background_roots_have_no_receiver(self):
        # A schedule's or loop's durable request has an id, but no turn to report to.
        kwargs = await self._spawn(self._request("bg-loop"), {"label": "c", "goal": "g"},
                                   background={"bg-loop"})
        assert kwargs["report_target"] is None

    async def test_an_agents_own_tool_cycle_binds_to_that_agent(self):
        invoker = AgentInfo(id="invoker", label="invoker", goal="g", channel_id="conv-1",
                            requester_id="owner", requester_name="owner")
        kwargs = await self._spawn(self._request("bg-agent"),
                                   {"label": "c", "goal": "g", "parent_id": "forged"},
                                   background={"bg-agent"}, dispatching=invoker,
                                   agents={"forged": SimpleNamespace(depth=0, max_depth=2)})
        assert kwargs["report_target"] == ReportTarget.for_agent("invoker")


def _first_text(messages: list[dict]) -> str:
    content = messages[0].get("content") if messages else ""
    return content if isinstance(content, str) else str(content)


def _tool_results(messages: list[dict]) -> list[dict]:
    return [b for m in messages if isinstance(m.get("content"), list)
            for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]


def _reports(messages: list[dict]) -> list[dict]:
    return [m for m in messages if m.get("provenance") == "agent_report"]


class ReportProvider(Provider):
    """The conversation spawns one agent and waits for it. The agent reports only
    once the conversation is inside its wait, then answers when released."""

    def __init__(self):
        super().__init__()
        self.main: list[dict] = []
        self.agent: list[dict] = []
        self.waiting, self.reported = asyncio.Event(), asyncio.Event()
        self.release_agent = asyncio.Event()

    async def chat_with_tools(self, **kwargs):
        self.calls += 1
        messages = kwargs.get("messages", [])
        tools = {t["name"]: t.get("description", "") for t in kwargs.get("tools") or []}
        seen = {"messages": copy.deepcopy(messages), "tools": tools}
        if AGENT in _first_text(messages):
            self.agent.append(seen)
            if not _tool_results(messages):
                await self.waiting.wait()
                return LLMResponse(tool_calls=[ToolCall(
                    "report-1", "report_to_parent", {"message": "found a blocker"})],
                    stop_reason="tool_use")
            self.reported.set()
            await self.release_agent.wait()
            return LLMResponse(text="agent done")
        self.main.append(seen)
        done = len(_tool_results(messages))
        if done == 0:
            return LLMResponse(tool_calls=[ToolCall(
                "spawn", "spawn_agent", {"label": "reporter", "goal": f"{AGENT} inspect"})],
                stop_reason="tool_use")
        if done == 1:
            ids = list(self.core.engine.deps.agent_manager._agents)
            self.waiting.set()
            return LLMResponse(tool_calls=[ToolCall(
                "wait", "wait_for_agents", {"agent_ids": ids, "timeout": 30})],
                stop_reason="tool_use")
        return LLMResponse(text="summary")


@pytest.mark.asyncio
async def test_an_agents_report_reaches_the_conversation_without_waking_its_wait(tmp_path):
    provider = ReportProvider()
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    provider.core = core
    core.config.agents.model = "compat:test"
    core.config.openai_compatible.model_profiles["test"] = OpenAICompatibleModelProfile(
        total_window_tokens=200000, max_output_tokens=10000, supports_thinking_mode=True)
    try:
        accepted = await request(reader, writer, "submission.send", {
            "client_submission_id": "reports", "conversation_id": cid,
            "text": "Spawn a reporter"})
        assert accepted["ok"]
        await asyncio.wait_for(provider.reported.wait(), 10)
        await asyncio.sleep(0.3)
        # The report is queued, yet the conversation is still inside its wait.
        assert len(provider.main) == 2
        provider.release_agent.set()
        await settled(core)
        (agent,) = core.engine.deps.agent_manager._agents.values()
        await asyncio.wait_for(agent._task, 5)

        assert len(provider.main) == 3
        (delivered,) = _reports(provider.main[2]["messages"])
        header, line = delivered["content"].split("\n")[:2]
        assert header == REPORT_HEADER
        assert json.loads(line) == {"agent_id": agent.id, "label": "reporter",
                                    "report_sequence": 1, "report": "found a blocker"}
        assert delivered["report_items"][0]["recipient"].startswith("turn:")
        (receipt,) = _tool_results(provider.agent[1]["messages"])
        assert receipt["content"].startswith(
            "Report queued for the conversation that spawned you (report sequence 1;")
        # Agent-only: every agent request has the tool, no conversation request does.
        assert all("report_to_parent" not in seen["tools"] for seen in provider.main)
        assert all("report_to_parent" in seen["tools"] for seen in provider.agent)
        assert SPAWN_SENTENCE in provider.main[0]["tools"]["spawn_agent"]
        assert SEND_SENTENCE in provider.main[0]["tools"]["send_to_agent"]
        if _pending_observers:
            await asyncio.gather(*list(_pending_observers), return_exceptions=True)
    finally:
        provider.release_agent.set()
        await cleanup(core, writer, rfd, wfd)
    audits = [json.loads(line) for path in tmp_path.rglob("audit.jsonl")
              for line in path.read_text().splitlines() if line.strip()]
    queued = [e for e in audits if e.get("tool_name") == "report_to_parent"
              and (e.get("audit_metadata") or {}).get("report_outcome") == "queued"]
    assert len(queued) == 1


@pytest.mark.asyncio
async def test_the_tools_settings_list_it_and_can_switch_it_off(tmp_path):
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, Provider())
    try:
        listed = (await request(reader, writer, "tools.list", {}))["result"]["tools"]
        (row,) = [t for t in listed if t["name"] == "report_to_parent"]
        assert row["enabled"] and row["state"] == "available"
        changed = await request(reader, writer, "tools.set_enabled",
                                {"name": "report_to_parent", "enabled": False})
        assert changed["ok"], changed
        listed = (await request(reader, writer, "tools.list", {}))["result"]["tools"]
        (row,) = [t for t in listed if t["name"] == "report_to_parent"]
        assert not row["enabled"] and row["state"] == "disabled"
        assert "report_to_parent" in core.config.tools.disabled_tools
    finally:
        await cleanup(core, writer, rfd, wfd)


def test_the_tool_reference_links_report_to_parent_where_it_was_carried_from():
    """Desktop's reference baseline predates agent_only.py, so a baseline link would 404."""
    import hashlib
    import re
    from pathlib import Path

    from scripts.docs._reference import SOURCE_COMMIT
    from scripts.docs.generate_tool_reference import AGENT_ONLY_SOURCE_COMMIT, generate
    from src.tools.defs import agent_only

    static, carried = generate().split("\n## agent_only\n", 1)
    linked = r"\(https://github\.com/Calmingstorm/Odin/blob/([0-9a-f]{40})/"
    assert set(re.findall(linked, static)) == {SOURCE_COMMIT}
    assert re.findall(linked, carried) == [AGENT_ONLY_SOURCE_COMMIT]
    assert (f"https://github.com/Calmingstorm/Odin/blob/{AGENT_ONLY_SOURCE_COMMIT}"
            "/src/tools/defs/agent_only.py") in carried
    # The link claims the carried bytes: these are agent_only.py's at that Odin revision.
    assert hashlib.sha256(Path(agent_only.__file__).read_bytes()).hexdigest() == (
        "ffdec4da8cf66c488a972a8163eeca45cf53a545e3f2190e6eac19c7846703eb")
