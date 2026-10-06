"""Ported real-loop characterizations, not the retired Discord bot fixture.

Names retain the upstream behavior IDs from characterization/test_chat_tool_loop,
test_p1_carve_semantics and test_pipeline_persistence. Each turn enters through
RequestService's durable worker and authenticated owner binding. Only provider
responses and explicitly stubbed external tool effects are synthetic.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from src.config.schema import Config
from src.desktop.attachments import AttachmentService
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.discord.response_guards import (
    _CODE_HEDGING_RETRY_MSG,
    _FABRICATION_RETRY_MSG,
    _FAILURE_RETRY_MSG,
    _HEDGING_RETRY_MSG,
    _PROMISE_RETRY_MSG,
    _TOOL_UNAVAIL_RETRY_MSG,
)
from src.discord.tool_loop import ToolLoopRunner
from src.llm.types import LLMResponse, ToolCall
from src.permissions.manager import PermissionManager
from src.sessions.manager import summarize_tool_response
from src.tools.result_validator import ToolResult

pytestmark = pytest.mark.asyncio
INNOCENT = "Paris is the capital of France."
FABRICATION = "I ran the command and everything looks fine."
HEDGING = "Shall I proceed with the deployment now?"
GUARDS = [
    ("fabrication", FABRICATION, _FABRICATION_RETRY_MSG),
    ("promise", "I'll do that now for you right away.", _PROMISE_RETRY_MSG),
    ("tool_unavailable", "That tool is not available in this environment.",
     _TOOL_UNAVAIL_RETRY_MSG),
    ("hedging", HEDGING, _HEDGING_RETRY_MSG),
    ("code_hedging", "You can run this:\n```bash\npwd\n```", _CODE_HEDGING_RETRY_MSG),
]


def text(value):
    return LLMResponse(text=value)


def tools(*calls, preface=""):
    return LLMResponse(text=preface, tool_calls=[
        ToolCall(f"call-{i + 1}", name, args) for i, (name, args) in enumerate(calls)
    ], stop_reason="tool_use")


def parse(expression="in 1 hour"):
    return tools(("parse_time", {"expression": expression}))


class ScriptedProvider:
    model = "characterization"
    provider_name = "compat"

    def __init__(self):
        self.responses = []
        self.judgments = []
        self.calls = []
        self.chat_calls = []

    async def chat_with_tools(self, **kwargs):
        # Snapshot: the real runner appends to its working list after returning.
        self.calls.append(copy.deepcopy(kwargs))
        assert self.responses, "real runner consumed an unexpected generation"
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def chat(self, **kwargs):
        self.chat_calls.append(copy.deepcopy(kwargs))
        judgment = self.judgments.pop(0) if self.judgments else "COMPLETE"
        if isinstance(judgment, Exception):
            raise judgment
        return judgment

    async def drain_and_close(self):
        pass


@pytest_asyncio.fixture
async def graph(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = ProfilePaths.from_xdg("runner-characterization", home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    permissions = PermissionManager(authority)
    owner_token = permissions.set_request_owner(
        authority.authenticate_local(peer_uid=authority.owner_uid))
    store = JournalStore(paths.data_dir / "transport.sqlite3", paths.profile_id)
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    attachments = AttachmentService(store, lambda _db, cid: conversations.get(cid))
    cfg = Config()
    cfg.openai_codex.enabled = False
    cfg.llm_provider.model = "compat:characterization"
    cfg.openai_compatible.enabled = True
    cfg.context.directory = str(paths.data_dir / "context")
    cfg.attachments.temp_directory = str(paths.cache_dir / "attachments")
    cfg.learning.enabled = False
    cfg.browser.enabled = False
    provider = ScriptedProvider()
    engine = build_engine_services(cfg, paths, permissions, delivery=delivery,
                                   compatible_client=provider)
    requests = RequestService(store, conversations, transcript, engine=engine,
        permissions=permissions, authority=authority, delivery=delivery, attachments=attachments)
    engine.bind_requests(requests)
    cid = conversations.create()["conversation"]["id"]
    assert isinstance(engine.runner, ToolLoopRunner)
    g = SimpleNamespace(paths=paths, store=store, engine=engine, requests=requests,
        provider=provider, transcript=transcript, cid=cid, cfg=cfg, attachments=attachments)
    try:
        yield g
    finally:
        await requests.close()
        await engine.close()
        store.close()
        permissions.reset_request_owner(owner_token)
        authority.release_runtime()


async def run(
    g, responses, *, judgments=(), content="Convert in 1 hour to a timestamp", attachments=None
):
    g.provider.responses = list(responses)
    g.provider.judgments = list(judgments)
    result = g.requests.submit({"client_submission_id": f"submit-{len(g.provider.calls)}",
        "conversation_id": g.cid, "text": content, "attachments": attachments or []})
    await g.requests.after_commit()
    await asyncio.gather(*g.requests._tasks)
    return g.requests.get_request(result["request_id"])


def messages(g, index):
    return g.provider.calls[index]["messages"]


def answer(g):
    return g.transcript.read_conversation(g.cid)[-1]["text"]


@pytest.mark.parametrize("name,trigger,retry", GUARDS, ids=[c[0] for c in GUARDS])
async def test_guard_fires_once_then_accepts(graph, name, trigger, retry):
    row = await run(graph, [text(trigger), text(trigger)])
    assert row["state"] == "completed"
    assert len(graph.provider.calls) == 2
    assert messages(graph, 1)[-1] == retry
    assert answer(graph) == trigger
    assert not graph.provider.chat_calls


async def test_cascade_order_fabrication_before_hedging(graph):
    both = FABRICATION + " " + HEDGING
    await run(graph, [text(both), text(both), text(INNOCENT)])
    assert messages(graph, 1)[-1] == _FABRICATION_RETRY_MSG
    assert messages(graph, 2)[-1] == _HEDGING_RETRY_MSG
    assert answer(graph) == INNOCENT


async def test_guards_do_not_fire_after_tools_used(graph):
    await run(graph, [parse(), text(HEDGING)])
    assert answer(graph) == HEDGING
    assert len(graph.provider.calls) == 2
    assert len(graph.provider.chat_calls) == 1


async def test_premature_failure_fires_only_with_tools(graph):
    failure = "I couldn't get the data from the server, it appears to be down."
    await run(graph, [parse(), text(failure), text("Recovered: here is the real answer.")])
    assert messages(graph, 2)[-1] == _FAILURE_RETRY_MSG
    assert answer(graph) == "Recovered: here is the real answer."
    assert len(graph.provider.chat_calls) == 1


async def test_plain_text_reply_no_tools_and_classifier_not_called_without_tools(graph):
    row = await run(graph, [text(INNOCENT)], judgments=["INCOMPLETE: unused"], content="hi")
    assert row["state"] == "completed"
    assert answer(graph) == INNOCENT
    assert len(graph.provider.calls) == 1
    assert not graph.provider.chat_calls


async def test_tool_iteration_message_shape(graph):
    await run(graph, [tools(("parse_time", {"expression": "in 1 hour"}), preface="Checking."),
                      text("Parsed it.")])
    assert [m["role"] for m in messages(graph, 1)] == ["developer", "user", "assistant", "user"]
    assistant = messages(graph, 1)[2]["content"]
    assert assistant[0] == {"type": "text", "text": "Checking."}
    assert assistant[1]["name"] == "parse_time"
    results = messages(graph, 1)[3]["content"]
    assert len(results) == 1
    assert results[0]["type"] == "tool_result"
    assert results[0]["tool_use_id"] == assistant[1]["id"]
    assert re.search(r"\d{4}-\d{2}-\d{2}T", results[0]["content"])  # real native conversion


async def test_with_history_preamble_before_last_user(graph):
    await run(graph, [text(INNOCENT)], content="earlier request")
    await run(graph, [text("A second answer.")], content="new request")
    observed = messages(graph, 1)
    # The actual session pipeline adds the upstream history read-only fence;
    # the original runner-only fixture passed an unfenced history directly.
    assert [m["role"] for m in observed] == ["developer", "user", "assistant", "developer", "user"]
    assert observed[0]["content"].startswith("[HISTORY_READ_ONLY]")
    assert "=== CURRENT REQUEST [req-" in observed[-2]["content"]
    assert "HISTORY ABOVE | REQUEST BELOW" in observed[-2]["content"]


async def test_incomplete_injects_continuation_with_reason(graph):
    row = await run(graph, [parse(), text("partial answer"), text("full answer")],
        judgments=["INCOMPLETE: verification step missing", "COMPLETE"])
    assert row["state"] == "completed"
    assert answer(graph) == "full answer"
    assert messages(graph, 2)[-1] == {"role": "developer", "content":
        "You are not done. verification step missing. Continue with tool calls now."}
    assert all("partial answer" not in str(m["content"]) for m in messages(graph, 2))
    assert all(row["text"] != "partial answer"
               for row in graph.transcript.read_conversation(graph.cid))
    judge_input = graph.provider.chat_calls[0]["messages"][0]["content"]
    assert "Convert in 1 hour" in judge_input and "Tools called: parse_time" in judge_input


async def test_continuation_budget_is_three(graph):
    await run(graph, [parse(), *[text(f"t{i}") for i in range(1, 5)]],
        judgments=["INCOMPLETE: a", "INCOMPLETE: b", "INCOMPLETE: c", "INCOMPLETE: unused"])
    assert answer(graph) == "t4"
    assert len(graph.provider.calls) == 5
    assert len(graph.provider.chat_calls) == 3
    assert graph.provider.judgments == ["INCOMPLETE: unused"]


@pytest.mark.parametrize("judgment", [RuntimeError("judge unavailable"), "ambiguous", ""])
async def test_completion_judge_failure_and_ambiguity_fail_open(graph, judgment):
    row = await run(graph, [parse(), text("A finished answer.")], judgments=[judgment])
    assert row["state"] == "completed"
    assert answer(graph) == "A finished answer."
    assert len(graph.provider.calls) == 2
    assert len(graph.provider.chat_calls) == 1


async def test_mutation_injects_auto_validate_then_forces_continuation(graph, monkeypatch):
    # No mutation occurs: only the external effect boundary is stubbed. The
    # runner receives the original requires_validation ToolResult contract.
    effect = AsyncMock(return_value=ToolResult(output="fixture result", tool_name="run_command",
        requires_validation=True, validation_reason="fixture requires post-action validation"))
    monkeypatch.setattr(graph.engine.deps.tool_executor, "execute", effect)
    await run(graph, [tools(("run_command", {"host": "localhost", "command": "pwd"})),
        text("done early"), text("done again"), text("final after retries")])
    assert messages(graph, 1)[-1]["content"].startswith("[AUTO-VALIDATE]")
    assert "fixture requires" in messages(graph, 1)[-1]["content"]
    assert "[VALIDATION REQUIRED]" in messages(graph, 2)[-1]["content"]
    assert "[VALIDATION REQUIRED]" in messages(graph, 3)[-1]["content"]
    assert answer(graph) == "final after retries"
    assert effect.await_count == 1


async def test_validate_action_call_clears_requirement(graph, monkeypatch):
    effect = AsyncMock(side_effect=[
        ToolResult(output="fixture result", tool_name="run_command", requires_validation=True),
        ToolResult(output="fixture validation passed", tool_name="validate_action")])
    monkeypatch.setattr(graph.engine.deps.tool_executor, "execute", effect)
    await run(graph, [tools(("run_command", {"host": "localhost", "command": "pwd"})),
        tools(("validate_action", {"checks": [{"type": "command", "target": "pwd"}]})),
        text("validated and done")])
    assert answer(graph) == "validated and done"
    assert effect.await_count == 2
    assert not any("[VALIDATION REQUIRED]" in str(m) for call in graph.provider.calls
                   for m in call["messages"])


async def test_stuck_loop_warns_then_terminates(graph):
    row = await run(graph, [parse() for _ in range(8)])
    assert row["state"] == "failed"
    assert "stuck tool-call cycle" in answer(graph)
    assert any("repeating the same tool-call sequence" in str(m) for call in graph.provider.calls
               for m in call["messages"] if m["role"] == "developer")


async def test_iteration_cap_exit_is_error(graph):
    graph.cfg.tools.max_tool_iterations_chat = 2
    row = await run(graph, [parse("in 1 hour"), parse("in 2 hours")])
    assert row["state"] == "failed"
    assert "iteration" in answer(graph).lower()
    assert len(graph.provider.calls) == 2


async def test_caller_history_list_not_mutated(graph, monkeypatch):
    history = [{"role": "user", "content": "earlier request"},
               {"role": "assistant", "content": "earlier answer"},
               {"role": "user", "content": "parse the time"}]
    snapshot = copy.deepcopy(history)
    monkeypatch.setattr(graph.engine.deps.sessions, "get_task_history",
                        AsyncMock(return_value=history))
    await run(graph, [parse(), text("done")])
    assert history == snapshot
    assert len(messages(graph, 1)) > len(snapshot)


async def test_gather_results_keep_call_order_under_reversed_completion(graph, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    completed = []
    scheduling = graph.engine.deps.native_tools.owners["scheduling"]

    async def slower(inp):
        if inp["expression"] == "in 1 hour":
            started.set()
            await release.wait()
            completed.append("slow")
            return "slow-result"
        await started.wait()
        completed.append("fast")
        release.set()
        return "fast-result"

    monkeypatch.setattr(scheduling, "_handle_parse_time", slower)
    await run(graph, [tools(("parse_time", {"expression": "in 1 hour"}),
                           ("parse_time", {"expression": "in 2 hours"})), text("both done")])
    assert completed == ["fast", "slow"]
    results = messages(graph, 1)[-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["call-1", "call-2"]
    assert [r["content"] for r in results] == ["slow-result", "fast-result"]


async def test_op_details_accumulate_in_order_across_iterations(graph, monkeypatch):
    observed, reflected = {}, asyncio.Event()

    async def reflection(*args, **kwargs):
        observed.update(kwargs)
        reflected.set()

    monkeypatch.setattr(graph.engine.deps.turn_recorder, "_operational_reflection", reflection)
    await run(graph, [parse("in 1 hour"), parse("in 2 hours"), text("done")])
    await asyncio.wait_for(reflected.wait(), 2)
    details = observed["tool_details"]
    assert [d["tool"] for d in details] == ["parse_time", "parse_time"]
    assert [d["input"]["expression"] for d in details] == ["in 1 hour", "in 2 hours"]
    assert all(set(d) >= {"tool", "input", "result", "error"} for d in details)
    assert graph.cid not in graph.engine.deps.channel_state.last_op_details


async def test_success_persists_tagged_user_and_assistant_turns_and_summarizes_tools(graph):
    detailed = "Detailed multi-tool response " + "x" * 400
    await run(graph, [parse(), text(detailed)])
    history = graph.engine.deps.sessions.get_history(graph.cid)
    assert history[0]["role"] == "user" and "Convert in 1 hour" in history[0]["content"]
    assert history[0]["content"].startswith("[")
    assert history[-1] == {
        "role": "assistant", "content": summarize_tool_response(detailed, ["parse_time"])}
    assert answer(graph) == detailed  # transcript has full delivery, not session summary


async def test_ok_false_result_gets_error_prefix_and_marks_recent_actions_error(graph, monkeypatch):
    monkeypatch.setattr(graph.engine.deps.tool_executor, "execute", AsyncMock(return_value=
        ToolResult(output="fixture denied", ok=False, tool_name="run_command")))
    await run(graph, [tools(("run_command", {"host": "localhost", "command": "pwd"})),
                      text("noted")])
    result = messages(graph, 1)[-1]["content"][0]["content"]
    assert result == "Error (tool reported failure):\nfixture denied"
    assert any("`run_command`" in entry and "→ ERROR" in entry
               for entry in graph.engine.deps.channel_state.recent_entries(graph.cid))


async def test_parse_error_call_is_not_executed(graph, monkeypatch):
    external = AsyncMock()
    monkeypatch.setattr(graph.engine.deps.tool_executor, "execute", external)
    bad = LLMResponse(tool_calls=[ToolCall("bad", "run_command", {}, parse_error="invalid JSON")])
    await run(graph, [bad, text("noted")])
    external.assert_not_awaited()
    assert "NOT executed" in messages(graph, 1)[-1]["content"][0]["content"]


@pytest.mark.parametrize("after_tools", [False, True], ids=["before_tools", "after_tools"])
async def test_error_persists_sanitized_marker_not_raw_error_and_names_tools(graph, after_tools):
    responses = [parse()] if after_tools else []
    responses.append(RuntimeError("fixture provider failure"))
    row = await run(graph, responses)
    assert row["state"] == "failed"
    assert "fixture provider failure" in answer(graph)
    saved = graph.engine.deps.sessions.get_history(graph.cid)[-1]["content"]
    if after_tools:
        assert saved == ("[Previous request used tools (parse_time) but encountered an error. "
                         "The user may ask to retry.]")
    else:
        assert saved == "[Previous request encountered an error before tool execution.]"
    assert "fixture provider failure" not in saved


async def test_image_only_input_is_admitted_and_injected_into_real_runner(graph):
    # Real upload journal/adoption/processor, no image processing or runner mock.
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/"
        "x8AAwMCAO+jBz0AAAAASUVORK5CYII=")
    begun = graph.attachments.handle("attachments.begin", {"client_attachment_id": "image",
        "conversation_id": graph.cid, "name": "pixel.png", "mime": "image/png", "size": len(data)})
    assert begun["ok"]
    upload_id = begun["result"]["upload_id"]
    assert graph.attachments.handle("attachments.chunk", {"upload_id": upload_id, "offset": 0,
        "data_b64": base64.b64encode(data).decode()})["ok"]
    committed = graph.attachments.handle("attachments.commit", {"upload_id": upload_id,
        "sha256": hashlib.sha256(data).hexdigest()})
    assert committed["ok"]
    ref = committed["result"]["attachment"]["ref"]
    row = await run(graph, [text("A one-pixel image.")], content="", attachments=[{"ref": ref}])
    assert row["state"] == "completed"
    current = messages(graph, 0)[-1]["content"]
    image = next(block for block in current if block["type"] == "image")
    assert image["source"]["media_type"] == "image/png"
    assert base64.b64decode(image["source"]["data"]) == data
    assert any("pixel.png" in b.get("text", "") for b in current)
    assert answer(graph) == "A one-pixel image."
