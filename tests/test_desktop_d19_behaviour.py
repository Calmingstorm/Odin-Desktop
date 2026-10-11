"""D19 runtime evidence, not an assertion that every Phase-1 fence is restored.

Every test starts the real profile core, authenticates over its Unix transport,
and retains the real admission, executor, runner, authorization and delivery.
Only the LLM and OS keyring are boundaries replaced here. No readiness override,
bot/facade, native display, provider network or live profile is involved.

History, file publication, output retention and restored scheduling/background
owners have bounded positive runtime proofs. Computer and skill delivery remain
explicitly incomplete: their actual refusals are not inferred catalog parity.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.desktop.core import CoreService, profile_config
from src.desktop.delivery import DurableDelivery
from src.discord.tool_loop import ToolLoopRunner
from src.llm.types import LLMResponse, ToolCall
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_management_core import TemporaryKeyring


class ScriptedProvider:
    """A provider boundary, never a replacement execution or delivery owner."""

    model = "test"
    provider_name = "compat"

    def __init__(self):
        self.responses = []
        self.calls = []
        self.closed = False

    async def chat_with_tools(self, **kwargs):
        # RankedOutput is a str subclass with required constructor metadata;
        # deepcopy would try reconstructing it and change provider behaviour.
        self.calls.append(json.loads(json.dumps(kwargs, default=str)))
        assert self.responses, "Unexpected additional provider generation"
        return self.responses.pop(0)

    async def chat(self, **_kwargs):
        return "COMPLETE"

    async def drain_and_close(self):
        self.closed = True


@pytest.fixture
async def composed(tmp_path, monkeypatch):
    import aiohttp

    def no_network(*_args, **_kwargs):
        raise AssertionError("D19 proofs must not create a provider/network session")

    monkeypatch.setattr(aiohttp, "ClientSession", no_network)
    paths, socket_path, token_file = profile(tmp_path)
    config = profile_config(paths)
    config.openai_codex.enabled = False
    config.llm_provider.model = "compat:test"
    config.openai_compatible.enabled = True
    config.learning.enabled = False
    config.browser.enabled = False
    # Only this private fixture workspace is ever read by the real file tool.
    from src.config.schema import ToolHost

    config.tools.hosts = {"localhost": ToolHost(address="127.0.0.1")}
    provider = ScriptedProvider()
    core = CoreService(paths, socket_path, token_file,
        config_provider=lambda _: config,
        runtime_provider=lambda *_: SimpleNamespace(compatible_client=provider),
        secret_backend=TemporaryKeyring())
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, welcome = await connect(socket_path)
        assert welcome["t"] == "welcome"
        assert isinstance(core.engine.runner, ToolLoopRunner)
        assert isinstance(core.delivery, DurableDelivery)
        assert core.management.executor is core.engine.deps.tool_executor
        assert core.management.providers is core.engine.deps.llm_gateway
        assert core.requests.engine is core.engine
        assert core.engine.requests is core.requests
        yield SimpleNamespace(core=core, provider=provider, reader=reader,
                              writer=writer, paths=paths, write_fd=write_fd,
                              welcome=welcome, tmp_path=tmp_path)
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


async def rpc(graph, method, params=None, *, command_id=None):
    response = await request(graph.reader, graph.writer, method, params, command_id)
    assert response["ok"], response
    return response["result"]


async def conversation(graph, title="D19 proof"):
    return (await rpc(graph, "conversations.create", {"title": title}))["conversation"]["id"]


async def turn(graph, cid, tool=None, arguments=None, *, text="Run the requested proof",
               expected_state="completed", background_replies=0):
    graph.provider.calls.clear()
    graph.provider.responses = (
        [LLMResponse(tool_calls=[ToolCall("d19-call", tool, arguments or {})],
                     stop_reason="tool_use")] if tool else []
    ) + [LLMResponse(text="The bounded proof has settled.")
         for _ in range(1 + background_replies)]
    receipt = await rpc(graph, "submission.send", {
        "client_submission_id": uuid4().hex, "conversation_id": cid, "text": text,
    })
    await asyncio.wait_for(asyncio.gather(*graph.core.requests._tasks), timeout=20)
    row = graph.core.requests.get_request(receipt["request_id"])
    assert row["state"] == expected_state, row
    rows = graph.core.transcript.read_conversation(cid)
    if expected_state == "completed":
        assert rows[-1]["text"] == "The bounded proof has settled."
        assert rows[-1]["role"] == "assistant"
    else:
        assert "Tool execution failed:" in rows[-1]["text"]
        assert "The bounded proof has settled." not in str(rows)
    return receipt


def tool_results(graph):
    return [block["content"] for call in graph.provider.calls
            for message in call["messages"] if isinstance(message.get("content"), list)
            for block in message["content"] if block.get("type") == "tool_result"]


@pytest.mark.parametrize("tool,arguments", [
    pytest.param("read_conversation", {"limit": 10}, id="read_conversation"),
])
async def test_authenticated_history_reads_current_durable_transcript(composed, tool, arguments):
    graph = composed
    cid = await conversation(graph)
    foreign = await conversation(graph, "Not this request")
    graph.core.transcript.commit(cid, "assistant", "D19 visible transcript marker")
    graph.core.transcript.commit(foreign, "assistant", "D19 foreign private marker")
    receipt = await turn(graph, cid, tool, arguments)
    results = tool_results(graph)
    assert results and "D19 visible transcript marker" in str(results)
    assert "D19 foreign private marker" not in str(results)
    assert tool in {item["name"] for item in graph.provider.calls[0]["tools"]}
    assert graph.core.requests.get_request(receipt["request_id"])["ledger_generation"] is not None
    # A genuine stored request envelope is still not authority outside its task.
    message = graph.core.requests.fetch_request(cid, receipt["request_id"])
    reader = graph.core.engine.deps.native_tools.owners["channel_ops"]
    denied = await reader._handle_read_conversation(message, {"limit": 10})
    assert denied == "Permission denied — cannot read this conversation."


async def test_search_history_spans_every_conversation_in_the_profile(composed):
    # Contract (core-contracts.md) and approved wording: profile-scoped search
    # across conversations, as Odin searches every channel; reading stays current.
    graph = composed
    cid = await conversation(graph)
    other = await conversation(graph, "Another conversation")
    graph.core.transcript.commit(cid, "assistant", "D19 shared history marker here")
    graph.core.transcript.commit(other, "assistant", "D19 shared history marker there")
    await turn(graph, cid, "search_history", {"query": "D19 shared history marker", "limit": 10})
    results = str(tool_results(graph))
    assert "marker here" in results and "marker there" in results
    assert "search_history" in {item["name"] for item in graph.provider.calls[0]["tools"]}


async def test_history_rejects_foreign_selector_before_any_transcript_read(composed):
    cid = await conversation(composed)
    foreign = await conversation(composed, "Foreign")
    composed.core.transcript.commit(foreign, "assistant", "foreign selector marker")
    await turn(composed, cid, "read_conversation", {"conversation_id": foreign, "limit": 10})
    results = str(tool_results(composed))
    assert "Only 'limit' is accepted" in results
    assert "foreign selector marker" not in results


@pytest.mark.parametrize("tool", ["generate_file", "post_file"])
async def test_admitted_file_tool_publishes_real_durable_bytes(composed, tool):
    graph = composed
    cid = await conversation(graph)
    content = b"D19 artifact bytes\n"
    if tool == "generate_file":
        arguments = {"filename": "d19.txt", "content": content.decode()}
    else:
        path = graph.tmp_path / "d19.txt"
        path.write_bytes(content)
        arguments = {"host": "localhost", "path": str(path)}
    receipt = await turn(graph, cid, tool, arguments)
    files = [item for item in graph.core.transcript.list(cid)["items"] if item.get("artifacts")]
    assert len(files) == 1
    assert files[0]["request_id"] == receipt["request_id"]
    ref = files[0]["artifacts"][0]["ref"]
    page = await rpc(graph, "artifacts.read", {"ref": ref, "offset": 0, "length": 100})
    assert base64.b64decode(page["data_b64"]) == content
    assert page["eof"]
    assert tool in {item["name"] for item in graph.provider.calls[0]["tools"]}
    detail = await rpc(graph, "tool.detail", {
        "request_id": receipt["request_id"], "invocation_id": "d19-call"})
    assert detail["tool"] == tool
    assert "Phase 2" not in str(detail["previews"])
    # Publication is stored content; subsequent tool revocation is not erasure.
    await rpc(graph, "tools.set_enabled", {"name": tool, "enabled": False})
    again = await rpc(graph, "artifacts.read", {"ref": ref, "offset": 0, "length": 100})
    assert again == page


async def test_executor_retains_full_output_and_rechecks_live_capability(composed):
    graph = composed
    cid = await conversation(graph)
    long_value = ("D19-retained-line\n" * 3000).rstrip()
    await rpc(graph, "memory.set", {"scope": "global", "key": "d19_large", "value": long_value})
    receipt = await turn(graph, cid, "memory_manage", {
        "action": "get", "scope": "global", "key": "d19_large"})
    detail = await rpc(graph, "tool.detail", {
        "request_id": receipt["request_id"], "invocation_id": "d19-call"})
    cursor = detail["output"]["cursor"]
    pages = []
    for _ in range(20):
        page = await rpc(graph, "tool.output", {"cursor": cursor, "limit": 8000})
        pages.append(page["text"])
        if page["eof"]:
            break
        cursor = page["next_cursor"]
    else:
        pytest.fail("Retained output did not terminate within the bounded page budget")
    assert "".join(pages) == "**d19_large** (global): " + long_value
    await rpc(graph, "tools.set_enabled", {"name": "memory_manage", "enabled": False})
    denied = await request(graph.reader, graph.writer, "tool.output", {
        "cursor": detail["output"]["cursor"], "limit": 8000})
    assert not denied["ok"] and denied["error"]["code"] == "unauthorized"
    historical = await rpc(graph, "tool.detail", {
        "request_id": receipt["request_id"], "invocation_id": "d19-call"})
    assert historical["previews"] == detail["previews"]
    assert historical["output"] == {}


async def test_identity_string_cannot_admit_or_execute_without_authenticated_owner(composed):
    from src.desktop.conversations import ConversationError

    graph = composed
    cid = await conversation(graph)
    before = len(graph.core.transcript.list(cid)["items"])
    with pytest.raises(ConversationError, match="Authenticated profile owner required"):
        graph.core.requests.submit({"client_submission_id": "untrusted", "conversation_id": cid,
                                    "text": "No owner context",
                                    "owner_id": graph.core.authority.owner_id})
    rejected = await graph.core.engine.deps.tool_executor.execute("memory_manage", {
        "action": "save", "scope": "global", "key": "untrusted", "value": "never saved"},
        user_id=graph.core.authority.owner_id)
    assert not rejected.ok and rejected.error == "permission_denied"
    assert "untrusted" not in graph.core.management.executor._load_all_memory().get("global", {})
    assert len(graph.core.transcript.list(cid)["items"]) == before
    assert graph.provider.calls == []


@pytest.mark.parametrize("tool", ["schedule_task", "update_schedule"])
async def test_restored_scheduling_binds_real_owner_and_destination(composed, tool):
    graph = composed
    cid = await conversation(graph)
    await turn(graph, cid, "schedule_task", {
        "description": "Private reminder", "action": "reminder",
        "run_at": "2099-01-01T00:00:00Z", "message": "D19 scheduled fixture"})
    schedules = graph.core.engine.deps.scheduler.list_all()
    assert len(schedules) == 1
    saved = schedules[0]
    assert saved["channel_id"] == cid
    assert saved["requester_id"] == graph.core.authority.owner_id
    assert "Scheduled one-time task" in str(tool_results(graph))
    if tool == "update_schedule":
        await turn(graph, cid, tool, {"schedule_id": saved["id"], "paused": True})
        updated = graph.core.engine.deps.scheduler.list_all()
        assert len(updated) == 1 and updated[0]["paused"] is True
        assert updated[0]["channel_id"] == cid
        assert updated[0]["requester_id"] == graph.core.authority.owner_id
        assert "Updated" in str(tool_results(graph))
    assert tool in {row["name"] for row in graph.provider.calls[0]["tools"]}
    owner = graph.core.engine.deps.native_tools.owners["scheduling"]
    with pytest.raises(PermissionError, match="No current admitted request"):
        await owner._handle_update_schedule({"schedule_id": saved["id"], "paused": False})
    assert graph.core.engine.deps.scheduler.list_all() == (updated if tool == "update_schedule"
                                                         else schedules)


async def test_schedule_tools_report_a_missing_id_as_not_found(composed):
    # Odin's delete/update_schedule say "Schedule <id> not found." for a missing id.
    graph = composed
    cid = await conversation(graph)
    await turn(graph, cid, "schedule_task", {
        "description": "Private reminder", "action": "reminder",
        "run_at": "2099-01-01T00:00:00Z", "message": "D19 scheduled fixture"})
    saved, = graph.core.engine.deps.scheduler.list_all()
    await turn(graph, cid, "delete_schedule", {"schedule_id": saved["id"]})
    assert f"Deleted schedule {saved['id']}." in str(tool_results(graph))
    assert not graph.core.engine.deps.scheduler.list_all()
    for tool, arguments in (("delete_schedule", {"schedule_id": saved["id"]}),
                            ("update_schedule", {"schedule_id": saved["id"], "paused": True})):
        await turn(graph, cid, tool, arguments)
        assert f"Schedule {saved['id']} not found." in str(tool_results(graph)), tool
    # The management protocol refuses a missing id instead of reporting a deletion.
    response = await request(graph.reader, graph.writer, "schedules.delete", {"id": saved["id"]})
    assert not response["ok"] and response["error"]["code"] == "not_found", response


async def test_restored_delegate_task_executes_and_settles_owned_background(composed):
    graph = composed
    cid = await conversation(graph)
    receipt = await turn(graph, cid, "delegate_task", {
        "description": "Bounded D19 memory effect", "steps": [{
            "tool_name": "memory_manage", "tool_input": {
                "action": "save", "scope": "global", "key": "d19_background", "value": "run"}}]})
    tasks = graph.core.engine.deps.channel_state.background_tasks
    assert len(tasks) == 1
    async with asyncio.timeout(5):
        while any(task.status in {"pending", "running"} for task in tasks.values()):
            await asyncio.sleep(.01)
    task = next(iter(tasks.values()))
    assert task.status == "completed", task.results
    assert task.requester_id == graph.core.authority.owner_id
    assert task.conversation_id == cid
    assert graph.core.management.executor._load_all_memory()["global"]["d19_background"] == "run"
    work = (await rpc(graph, "work.list", {"kind": "task"}))["items"]
    assert len(work) == 1 and work[0]["state"] == "completed"
    assert work[0]["conversation_id"] == cid
    assert work[0]["request_id"] != receipt["request_id"]
    assert graph.core.requests.get_request(work[0]["request_id"])["state"] == "completed"
    assert any(row["request_id"] == work[0]["request_id"]
               for row in graph.core.transcript.list(cid)["items"])
    assert "delegate_task" in {row["name"] for row in graph.provider.calls[0]["tools"]}


async def test_restored_loop_executes_one_sealed_iteration_and_settles(composed):
    graph = composed
    cid = await conversation(graph)
    await turn(graph, cid, "start_loop", {"goal": "Bounded D19 iteration", "mode": "silent",
                                         "max_iterations": 1, "interval_seconds": 10},
               background_replies=1)
    loops = graph.core.engine.deps.loop_manager._loops
    assert len(loops) == 1
    await asyncio.wait_for(next(iter(loops.values()))._task, 5)
    work = (await rpc(graph, "work.list", {"kind": "loop"}))["items"]
    assert len(work) == 1 and work[0]["state"] == "completed"
    assert work[0]["settlement"]["state"] == "settled"
    assert work[0]["conversation_id"] == cid
    rows = list(graph.core.store.connection.execute(
        "SELECT r.state,r.owner,r.conversation_id FROM desktop_requests r "
        "JOIN desktop_background_requests b ON b.request_id=r.request_id "
        "WHERE b.kind='loop_iteration'"))
    assert len(rows) == 1 and tuple(rows[0]) == (
        "completed", graph.core.authority.owner_id, cid)
    assert "start_loop" in {row["name"] for row in graph.provider.calls[0]["tools"]}


def configure_agent_fixture(graph):
    from src.config.schema import OpenAICompatibleModelProfile

    # A declared compatible-model budget is required, not a readiness override.
    graph.core.config.agents.model = "compat:test"
    graph.core.config.openai_compatible.model_profiles["test"] = OpenAICompatibleModelProfile(
        total_window_tokens=200000, max_output_tokens=10000, supports_thinking_mode=True)
    graph.core.config.agents.max_iterations = 4


@pytest.mark.parametrize("tool", ["spawn_agent", "get_agent_results"])
async def test_restored_agent_admission_and_owner_scoped_result_read(composed, tool):
    graph = composed
    configure_agent_fixture(graph)
    cid = await conversation(graph)
    await turn(graph, cid, "spawn_agent", {"label": "d19_fixture", "goal": "Bounded D19 result"},
               background_replies=1)
    agents = graph.core.engine.deps.agent_manager._agents
    assert len(agents) == 1, tool_results(graph)
    agent = next(iter(agents.values()))
    await asyncio.wait_for(agent._task, 5)
    work = (await rpc(graph, "work.list", {"kind": "agent"}))["items"]
    assert len(work) == 1 and work[0]["state"] == "completed"
    assert work[0]["settlement"]["state"] == "settled"
    assert agent.requester_id == graph.core.authority.owner_id
    assert agent.iteration_count <= 4
    assert graph.core.requests.get_request(work[0]["request_id"])["state"] == "completed"
    if tool == "get_agent_results":
        agent_id = next(iter(agents))
        await turn(graph, cid, tool, {"agent_id": agent_id})
        page = json.loads(tool_results(graph)[-1])
        assert page["id"] == agent_id and page["status"] == "completed"
        assert page["preview"] == "The bounded proof has settled."
        assert page["truncated"] is False
        assert tool in {row["name"] for row in graph.provider.calls[0]["tools"]}
        await turn(graph, await conversation(graph, "Foreign result scope"), tool,
                   {"agent_id": agent_id})
        assert tool_results(graph)[-1] == f"Agent '{agent_id}' not found."
    else:
        assert tool in {row["name"] for row in graph.provider.calls[0]["tools"]}


@pytest.mark.parametrize("tool,arguments", [
    pytest.param("computer_session", {"operation": "start"}, id="computer_session"),
])
async def test_unwired_features_are_hidden_and_stale_calls_refused_not_restored(
        composed, tool, arguments):
    graph = composed
    cid = await conversation(graph)
    deps = graph.core.engine.deps
    before = (deepcopy(deps.scheduler.list_all()), set(deps.agent_manager._agents),
              set(deps.loop_manager._loops))
    receipt = await turn(graph, cid, tool, arguments, expected_state="failed")
    assert tool not in {item["name"] for item in graph.provider.calls[0]["tools"]}
    # The real readiness rejection cannot itself claim output capability. The
    # retained runtime sink refuses it before a tool-detail/model result exists.
    notice = graph.core.transcript.read_conversation(cid)[-1]["text"]
    assert "Output capability unavailable" in notice
    detail = await request(graph.reader, graph.writer, "tool.detail", {
        "request_id": receipt["request_id"], "invocation_id": "d19-call"})
    assert not detail["ok"] and detail["error"]["code"] == "not_found"
    assert len(graph.provider.calls) == 1
    assert before == (deps.scheduler.list_all(), set(deps.agent_manager._agents),
                      set(deps.loop_manager._loops))
    assert not [item for item in graph.core.transcript.list(cid)["items"] if item.get("artifacts")]


# Message and file posting are restored by skill delivery (D19-020/021); the
# composed-core proofs live in test_desktop_skill_delivery.py. History and
# scheduling (D19-022/023) use the request-bound transcript search and the
# admitted schedule service, as the native tools do.
async def save_skill(graph, name, lines):
    definition = {"name": name, "description": "Private bounded D19 proof",
                  "input_schema": {"type": "object", "properties": {}}}
    code = (f"SKILL_DEFINITION = {definition!r}\n"
            "async def execute(inp, context):\n" + "".join(f"    {line}\n" for line in lines))
    saved = await rpc(graph, "skills.save", {"name": name, "code": code})
    assert "created" in saved["result"]


async def test_restored_skill_history_searches_the_request_transcript(composed):
    graph = composed
    cid = await conversation(graph)
    graph.core.transcript.commit(cid, "assistant", "D19 skill history marker")
    await save_skill(graph, "d19_history", [
        "hits = await context.search_history('D19 skill history marker')",
        "return ' | '.join(f\"{hit['type']}: {hit['content']}\" for hit in hits)",
    ])
    await turn(graph, cid, "d19_history")
    results = [str(content) for content in tool_results(graph)]
    assert any("assistant: D19 skill history marker" in content for content in results), results


async def test_restored_skill_scheduling_binds_owner_and_destination(composed):
    from datetime import UTC, datetime, timedelta

    graph = composed
    scheduler = graph.core.engine.deps.scheduler
    cid = await conversation(graph)
    run_at = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    await save_skill(graph, "d19_schedule", [
        f"created = await context.schedule_task('D19 skill reminder', 'reminder', {cid!r}, "
        f"message='Skill reminder', run_at={run_at!r})",
        "listed = [item['id'] for item in context.list_schedules()]",
        "updated = await context.update_schedule(created['id'], paused=True)",
        # Odin's Scheduler.update: None fields are unchanged, a missing id is None.
        "kept = await context.update_schedule(created['id'], message='Skill reminder 2', "
        "run_at=None, paused=None, max_retries=None, conversation_id=None)",
        "missing = await context.update_schedule('missing', paused=True)",
        "return f\"created={created['id']} listed={created['id'] in listed} "
        "paused={updated['paused']} kept={kept['paused']} "
        "run_at_kept={kept['run_at'] == created['run_at']} missing={missing}\"",
    ])
    await turn(graph, cid, "d19_schedule")
    results = " ".join(str(content) for content in tool_results(graph))
    assert "listed=True paused=True kept=True run_at_kept=True missing=None" in results, results
    stored, = scheduler.list_all()
    assert stored["channel_id"] == cid and stored["paused"] is True
    assert stored["message"] == "Skill reminder 2"
    assert stored["requester_id"] == graph.core.authority.owner_id
    assert stored["description"] == "D19 skill reminder"
    await save_skill(graph, "d19_unschedule", [
        f"first = await context.delete_schedule({stored['id']!r})",
        f"second = await context.delete_schedule({stored['id']!r})",
        "return f'deleted={first} again={second}'",
    ])
    await turn(graph, cid, "d19_unschedule")
    assert "deleted=True again=False" in " ".join(str(c) for c in tool_results(graph))
    assert not scheduler.list_all()


async def test_restored_skill_scheduling_refuses_an_unknown_destination(composed):
    from datetime import UTC, datetime, timedelta

    graph = composed
    cid = await conversation(graph)
    run_at = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    await save_skill(graph, "d19_foreign_destination", [
        "await context.schedule_task('D19 foreign', 'reminder', 'c_not_a_conversation', "
        f"message='Never scheduled', run_at={run_at!r})",
        "return 'unexpected success'",
    ])
    await turn(graph, cid, "d19_foreign_destination")
    results = [str(content) for content in tool_results(graph)]
    assert results and not any("unexpected success" in content for content in results)
    assert not graph.core.engine.deps.scheduler.list_all()


async def test_skill_history_and_scheduling_require_an_admitted_request(composed):
    graph = composed
    deps = graph.core.engine.deps
    manager = deps.skill_manager
    # Skills never receive the unscoped stores, only the request-bound surfaces.
    assert manager._session_manager is not deps.sessions
    assert manager._scheduler is not deps.scheduler
    # Outside an executing request there is no ambient owner or destination.
    with pytest.raises(PermissionError, match="No current admitted request"):
        await manager._session_manager.search_history("anything")
    with pytest.raises(PermissionError, match="No current admitted request"):
        manager._scheduler.list_all()
    with pytest.raises(PermissionError, match="No current admitted request"):
        await manager._scheduler.delete("missing")


async def test_shared_settings_change_governs_next_real_request(composed):
    graph = composed
    cid = await conversation(graph)
    await rpc(graph, "tools.set_enabled", {"name": "generate_file", "enabled": False})
    await turn(graph, cid, "generate_file", {"filename": "denied.txt",
                                           "content": "never published"},
               expected_state="failed")
    assert "generate_file" not in {item["name"] for item in graph.provider.calls[0]["tools"]}
    notice = graph.core.transcript.read_conversation(cid)[-1]["text"]
    assert "Output capability unavailable" in notice
    assert not [item for item in graph.core.transcript.list(cid)["items"] if item.get("artifacts")]
    assert graph.core.management.executor is graph.core.engine.deps.tool_executor


async def test_core_supervisor_shutdown_closes_real_owners_without_desktop_input(composed):
    graph = composed
    computer = await rpc(graph, "computer.status")
    readiness = computer["readiness"]
    assert readiness["dispatch"] == "none"
    assert not readiness["foreground_available"]
    assert not readiness["native_qualified"]
    assert not readiness["input_supported"]
    await turn(graph, await conversation(graph))
    result = await rpc(graph, "runtime.shutdown", {"reason": "D19 private fixture complete"})
    assert result["disposition"] == "accepted"
    assert not graph.core.lifetime.admitting
    await graph.core.close()
    assert graph.provider.closed
    assert graph.core.engine.producers_quiesced
    assert graph.core.engine.cleanup_outcome["state"] == "released"
    assert not graph.core.engine.deps.turn_store.available


async def test_health_delivery_ready_after_real_publication(composed):
    graph = composed
    await turn(graph, await conversation(graph))
    health = await rpc(graph, "health.get")
    delivery = next(item for item in health["components"] if item["name"] == "delivery")
    assert delivery == {"name": "delivery", "healthy": True, "status": "ok",
                        "detail": "Delivery ready"}
    assert health["unavailable_count"] == sum(
        item["status"] == "unavailable" for item in health["components"])
    # #69 projects the actual durable owner; retained uncomposed diagnostics
    # remain legitimate but no longer describe this successfully composed core.
    assert graph.core.delivery is graph.core.requests.delivery


async def test_real_mcp_management_composes_and_persists_disabled_server_without_launch(composed):
    graph = composed
    from src.tools.mcp.manager import MCPManager

    assert isinstance(graph.core.management.mcp.manager, MCPManager)
    status = await rpc(graph, "mcp.status")
    assert status["started"] and not status["closed"]
    assert status["configured_server_count"] == 0
    await rpc(graph, "mcp.save", {"name": "d19_disabled", "transport": "stdio",
                                  "command": "fixture-never-launched", "enabled": False})
    status = await rpc(graph, "mcp.list")
    assert status["configured_servers"] == ["d19_disabled"]
    assert status["enabled_server_count"] == 0
    assert graph.core.settings.config.mcp.servers["d19_disabled"].enabled is False
    assert graph.core.management.mcp.manager.get_tool_definitions() == []
    assert "fixture-never-launched" in graph.paths.config_file.read_text()
    await rpc(graph, "mcp.delete", {"name": "d19_disabled"})
    assert (await rpc(graph, "mcp.status"))["configured_server_count"] == 0


async def test_uploaded_attachment_intake_is_admitted_and_duplicate_submission_not_reexecuted(
        composed):
    graph = composed
    cid = await conversation(graph)
    data = b"D19 uploaded attachment marker\n"
    begun = await rpc(graph, "attachments.begin", {
        "client_attachment_id": "d19_upload", "conversation_id": cid,
        "name": "d19.txt", "mime": "text/plain", "size": len(data)})
    await rpc(graph, "attachments.chunk", {"upload_id": begun["upload_id"], "offset": 0,
                                            "data_b64": base64.b64encode(data).decode()})
    attachment = await rpc(graph, "attachments.commit", {"upload_id": begun["upload_id"],
                         "sha256": hashlib.sha256(data).hexdigest()})
    graph.provider.responses = [LLMResponse(text="The uploaded attachment was read.")]
    params = {"client_submission_id": "d19_attachment_submission", "conversation_id": cid,
              "text": "Read this attachment",
              "attachments": [{"ref": attachment["attachment"]["ref"]}]}
    receipt = await rpc(graph, "submission.send", params)
    await asyncio.wait_for(asyncio.gather(*graph.core.requests._tasks), timeout=20)
    assert graph.core.requests.get_request(receipt["request_id"])["state"] == "completed"
    assert "D19 uploaded attachment marker" in str(graph.provider.calls[0]["messages"])
    assert graph.core.transcript.read_conversation(cid)[-1]["text"] == (
        "The uploaded attachment was read.")
    calls = len(graph.provider.calls)
    assert await rpc(graph, "submission.send", params) == receipt
    await asyncio.wait_for(asyncio.gather(*graph.core.requests._tasks), timeout=20)
    assert len(graph.provider.calls) == calls


async def test_computer_foreground_is_unsupported_and_unknown_cleanup_cannot_start_native_input(
        composed):
    graph = composed
    denied = await request(graph.reader, graph.writer, "computer.start", {})
    assert not denied["ok"]
    assert denied["error"]["code"] == "capability_unavailable"
    unknown = await request(graph.reader, graph.writer, "computer.stop", {
        "session_id": "not-a-real-session", "generation": 1})
    assert not unknown["ok"]
    assert unknown["error"]["code"] == "not_found"
    status = await rpc(graph, "computer.status")
    assert status["session"] is None
    assert status["readiness"]["dispatch"] == "none"
    assert status["readiness"]["input_supported"] is False


async def test_real_main_entry_and_local_client_complete_supervised_shutdown(tmp_path):
    """Real child entry/containment/finalization, not a patched CoreService."""
    from src.desktop.local_client import LocalClient

    paths, socket_path, token_file = profile(tmp_path)
    process = subprocess.Popen([sys.executable, "-m", "src", "--socket", str(socket_path),
        "--token-file", str(token_file), "--profile", paths.profile_id,
        "--data-dir", str(paths.data_dir)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    client = None
    try:
        for _ in range(200):
            if socket_path.exists():
                break
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=5)
                pytest.fail(f"Private core exited at startup: {process.returncode}: "
                            f"{stdout!r} {stderr!r}")
            await asyncio.sleep(.1)
        else:
            pytest.fail("Private core did not start within its bounded startup wait")
        client = await LocalClient.connect(socket_path, token_file, paths.profile_id)
        identity = await client.request("status.get")
        response = await asyncio.wait_for(client.read(), 5)
        assert response["id"] == identity and response["ok"]
        assert response["result"]["phase"] == "ready"
        await client.request("runtime.shutdown", {"reason": "D19 child entry proof complete"})
        response = await asyncio.wait_for(client.read(), 5)
        assert response["ok"]
        await client.close()
        client = None
        _stdout, stderr = await asyncio.to_thread(process.communicate, timeout=20)
        assert process.returncode == 0, stderr.decode(errors="replace")
        assert not socket_path.exists()
    finally:
        if client is not None:
            await client.close()
        if process.poll() is None:
            process.kill()  # exact test-owned child, namespace isolated
            await asyncio.to_thread(process.communicate, timeout=5)


async def test_real_cli_entry_authenticates_to_composed_core(composed):
    graph = composed
    result = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "src.cli",
        "--socket", str(graph.core.socket_path), "--token-file", str(graph.core.token_file),
        "--profile", graph.paths.profile_id, "status.get"],
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["ok"]
    assert response["result"]["phase"] == "ready"
    assert response["result"]["core_instance_id"] == graph.core.authority.runtime_id
    assert graph.provider.calls == []


@pytest.mark.parametrize("dependency,pip_status", [
    pytest.param("packaging", None, id="preinstalled_packaging"),
    pytest.param("d19-fixture-not-an-installed-distribution", 0, id="missing_installer_success"),
    pytest.param("d19-fixture-not-an-installed-distribution", 1, id="missing_installer_failure"),
])
async def test_composed_skill_dependency_resolution_and_actual_admitted_execution(
        composed, monkeypatch, dependency, pip_status):
    """Real OS package metadata; only missing-dependency pip I/O is stubbed.

    Trusted loading/publication preserves upstream diagnostics, and the skill's
    result reaches the model as in v4.13.0.
    """
    import src.tools.skill_manager as skills_module

    calls = []
    # A skill's packages go to the profile's own folder: the packaged runtime is read-only.
    packages = composed.core.engine.deps.skill_manager._packages_dir

    def pip_boundary(argv, **kwargs):
        calls.append((argv, kwargs))
        assert pip_status is not None, "Preinstalled packaging must never invoke pip"
        assert argv == [sys.executable, "-m", "pip", "install", "--quiet",
                        "--disable-pip-version-check", "--target", str(packages), "--upgrade",
                        dependency]
        return subprocess.CompletedProcess(
            argv, pip_status, "", "fixture pip failure" if pip_status else "")

    monkeypatch.setattr(skills_module.subprocess, "run", pip_boundary)
    graph = composed
    definition = {"name": "d19_dependency", "description": "Private dependency proof",
                  "input_schema": {"type": "object", "properties": {}},
                  "dependencies": [dependency]}
    code = (f"SKILL_DEFINITION = {definition!r}\n"
            "from packaging.version import Version\n"
            "EXECUTIONS = 0\n"
            "async def execute(inp, context):\n"
            "    global EXECUTIONS\n"
            "    EXECUTIONS += 1\n"
            "    return 'dependency execution marker ' + str(Version('1.2.3'))\n")
    saved = await rpc(graph, "skills.save", {"name": "d19_dependency", "code": code})
    assert "created and loaded successfully" in saved["result"]
    manager = graph.core.engine.deps.skill_manager
    assert manager is graph.core.management.skills.skill_manager
    info = await rpc(graph, "skills.get", {"name": "d19_dependency"})
    assert info["status"] == "loaded"
    skill = manager._skills["d19_dependency"]
    assert sys.modules[skill.module_name].EXECUTIONS == 0
    if pip_status is None:
        assert calls == []
        assert skill.diagnostics == []
    else:
        assert len(calls) == 1
        assert calls[0][1] == {"capture_output": True, "text": True,
                               "timeout": skills_module._PIP_INSTALL_TIMEOUT}
        diagnostics = str(skill.diagnostics)
        assert ("Auto-installed dependencies" if pip_status == 0 else
                "Failed to install dependencies") in diagnostics
    await turn(graph, await conversation(graph), "d19_dependency")
    results = [str(content) for content in tool_results(graph)]
    assert any("dependency execution marker 1.2.3" in content for content in results)
    assert sys.modules[skill.module_name].EXECUTIONS == 1
    assert "d19_dependency" in {item["name"] for item in graph.provider.calls[0]["tools"]}
    assert len(calls) == (0 if pip_status is None else 1)
