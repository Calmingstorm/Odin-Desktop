"""D19 runtime evidence, not an assertion that every Phase-1 fence is restored.

Every test starts the real profile core, authenticates over its Unix transport,
and retains the real admission, executor, runner, authorization and delivery.
Only the LLM and OS keyring are boundaries replaced here. No readiness override,
bot/facade, native display, provider network or live profile is involved.

History, file publication and output retention have positive runtime proofs.
Background/scheduling/computer and skill delivery remain explicitly incomplete:
the tests prove the actual refusal, not parity inferred from a hidden catalog.
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
               expected_state="completed"):
    graph.provider.calls.clear()
    graph.provider.responses = (
        [LLMResponse(tool_calls=[ToolCall("d19-call", tool, arguments or {})],
                     stop_reason="tool_use")] if tool else []
    ) + [LLMResponse(text="The bounded proof has settled.")]
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
    pytest.param("search_history", {"query": "D19 visible transcript marker", "limit": 10},
                 id="search_history"),
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


@pytest.mark.parametrize("tool,arguments", [
    pytest.param("schedule_task", {"description": "Private reminder", "action": "reminder",
                                  "run_at": "2099-01-01T00:00:00Z", "message": "fixture"},
                 id="schedule_task"),
    pytest.param("update_schedule", {"schedule_id": "fixture", "paused": True},
                 id="update_schedule"),
    pytest.param("delegate_task", {"description": "No background effect", "steps": []},
                 id="delegate_task"),
    pytest.param("start_loop", {"goal": "No autonomous effect", "max_iterations": 1},
                 id="start_loop"),
    pytest.param("spawn_agent", {"label": "fixture", "goal": "No agent effect",
                                "model": "compat:test"},
                 id="spawn_agent"),
    pytest.param("get_agent_results", {"agent_id": "fixture"}, id="get_agent_results"),
    pytest.param("export_skill", {"name": "fixture"}, id="export_skill"),
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


@pytest.mark.parametrize("body,diagnostic", [
    pytest.param("await context.post_message('fixture message')",
                 "Conversation skill delivery is unavailable until Phase 2.", id="post_message"),
    pytest.param("await context.post_file(b'fixture', 'fixture.txt')",
                 "Conversation skill delivery is unavailable until Phase 2.", id="post_file"),
    pytest.param("await context.search_history('fixture')",
                 "Owner-scoped conversation history is unavailable until Phase 2 wiring.",
                 id="search_history"),
    pytest.param("await context.schedule_task(description='fixture', action='reminder', "
                 "conversation_id='fixture')",
                 "Validated conversation scheduling is unavailable until Phase 2 wiring.",
                 id="schedule_task"),
    pytest.param("await context.update_schedule('fixture', paused=True)",
                 "Validated conversation scheduling is unavailable until Phase 2 wiring.",
                 id="update_schedule"),
    pytest.param("await context.delete_schedule('fixture')",
                 "Validated conversation scheduling is unavailable until Phase 2 wiring.",
                 id="delete_schedule"),
])
async def test_dynamic_skill_context_fences_remain_reachable(composed, caplog, body, diagnostic):
    graph = composed
    definition = {"name": "d19_fixture", "description": "Private bounded D19 proof",
                  "input_schema": {"type": "object", "properties": {}}}
    code = (f"SKILL_DEFINITION = {definition!r}\n"
            f"async def execute(inp, context):\n    {body}\n    return 'unexpected success'\n")
    saved = await rpc(graph, "skills.save", {"name": "d19_fixture", "code": code})
    assert "created" in saved["result"]
    assert graph.core.management.skills.skill_manager is graph.core.engine.deps.skill_manager
    cid = await conversation(graph)
    receipt = await turn(graph, cid, "d19_fixture", expected_state="failed")
    assert "d19_fixture" in {item["name"] for item in graph.provider.calls[0]["tools"]}
    # The real trusted skill runs and reaches the legacy context/callback fence.
    # Failure output is then blocked by the dynamic tool's output readiness:
    # this is a still-reachable fence, NOT a successful model-visible delivery.
    assert diagnostic in caplog.text
    detail = await request(graph.reader, graph.writer, "tool.detail", {
        "request_id": receipt["request_id"], "invocation_id": "d19-call"})
    assert not detail["ok"] and detail["error"]["code"] == "not_found"
    notice = graph.core.transcript.read_conversation(cid)[-1]["text"]
    assert "Output capability unavailable" in notice
    assert not graph.core.engine.deps.scheduler.list_all()
    assert not [item for item in graph.core.transcript.list(cid)["items"] if item.get("artifacts")]


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

    Trusted loading/publication preserves upstream diagnostics. Dynamic result
    delivery still fails closed and is explicitly not claimed restored here.
    """
    import src.tools.skill_manager as skills_module

    calls = []

    def pip_boundary(argv, **kwargs):
        calls.append((argv, kwargs))
        assert pip_status is not None, "Preinstalled packaging must never invoke pip"
        assert argv == [sys.executable, "-m", "pip", "install", "--quiet",
                        "--disable-pip-version-check", dependency]
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
    await turn(graph, await conversation(graph), "d19_dependency", expected_state="failed")
    assert sys.modules[skill.module_name].EXECUTIONS == 1
    assert "d19_dependency" in {item["name"] for item in graph.provider.calls[0]["tools"]}
    assert len(calls) == (0 if pip_status is None else 1)
