"""Actual composed upstream runner and durable local publication."""
import asyncio
import json
import os
import subprocess
import sys

import pytest

from src.config.schema import Config
from src.desktop.artifacts import ArtifactStore
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationError, ConversationStore
from src.desktop.delivery import ArtifactPublisher, DurableDelivery, PublicationEventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService, owner_display_name
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.discord.tool_loop import ToolLoopRunner
from src.llm.types import LLMResponse, ToolCall
from src.permissions.manager import PermissionManager


class Provider:
    model = "test"
    provider_name = "compat"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.judges = 0

    async def chat_with_tools(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)

    async def chat(self, **_kwargs):
        self.judges += 1
        return "COMPLETE"

    async def drain_and_close(self):
        self.closed = True



@pytest.mark.asyncio
async def test_packaged_core_offers_and_dispatches_management_mcp_tools(tmp_path):
    """L14 (1.0.5): with no runtime MCP manager (the packaged core), management built its
    own, but requests and agents dispatched to none and the catalog published nothing, so
    a connected server's tools never reached the model. A real stdio server end to end."""
    import os
    from pathlib import Path
    from types import SimpleNamespace

    from src.desktop.core import CoreService, profile_config
    from src.desktop.mcp import MCPDispatchBinding
    from tests.test_desktop_core_lifecycle import profile
    from tests.test_desktop_management_core import TemporaryKeyring

    fixture = Path(__file__).parents[1] / "app" / "test" / "harmless-mcp-stdio.py"
    paths, socket_path, token_file = profile(tmp_path)
    config = profile_config(paths)
    config.openai_codex.enabled = False
    config.llm_provider.model = "compat:test"
    config.openai_compatible.enabled = True
    config.learning.enabled = False
    config.browser.enabled = False
    config.mcp.enabled = True
    provider = Provider([
        LLMResponse(tool_calls=[ToolCall("m1", "mcp_fixture_constant", {})], stop_reason="tool_use"),
        LLMResponse(text="The fixture returned its constant."),
    ])
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file, config_provider=lambda _: config,
        runtime_provider=lambda *_: SimpleNamespace(compatible_client=provider),
        secret_backend=TemporaryKeyring())
    try:
        await core.start(read_fd)
        binding = core.engine.deps.mcp_dispatch
        assert isinstance(binding, MCPDispatchBinding)
        assert binding.target is core.management.mcp.manager
        # The engine awaits the dispatched-to service before declaring producers quiesced.
        assert core.engine.deps.management_mcp_service is core.management.mcp
        saved = await core.management.invoke("mcp.save", {
            "name": "fixture", "command": sys.executable, "args": [str(fixture)]})
        assert saved["ok"], saved
        catalog = core.engine.deps.tool_catalog
        assert "mcp_fixture_constant" in {tool["name"] for tool in catalog.merged_definitions()}
        cid = core.conversations.create()["conversation"]["id"]
        owner = core.authority.authenticate_local(peer_uid=core.authority.owner_uid)
        token = PermissionManager.set_request_owner(owner)
        try:
            receipt = core.requests.submit({"client_submission_id": "mcp",
                "conversation_id": cid, "text": "Call the fixture tool"})
        finally:
            PermissionManager.reset_request_owner(token)
        await core.requests.after_commit()
        await asyncio.gather(*core.requests._tasks)
        assert core.requests.get_request(receipt["request_id"])["state"] == "completed"
        assert "mcp_fixture_constant" in {tool["name"] for tool in provider.calls[0]["tools"]}
        assert "harmless constant" in json.dumps(provider.calls[1]["messages"])
        assert core.transcript.read_conversation(cid)[-1]["text"] == (
            "The fixture returned its constant.")
    finally:
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
@pytest.mark.parametrize("mcp_shutdown_fails", [False, True])
async def test_management_mutation_governs_retained_request_runner(tmp_path, mcp_shutdown_fails):
    import os
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from src.desktop.core import CoreService, profile_config
    from tests.test_desktop_core_lifecycle import profile
    from tests.test_desktop_management_core import TemporaryKeyring

    paths, socket_path, token_file = profile(tmp_path)
    config = profile_config(paths)
    config.openai_codex.enabled = False
    config.llm_provider.model = "compat:test"
    config.openai_compatible.enabled = True
    config.learning.enabled = False
    config.browser.enabled = False
    provider = Provider([LLMResponse(text="The request used the shared runtime.")])
    mcp_manager = SimpleNamespace(
        get_tool_definitions=Mock(return_value=[]), set_on_catalog_changed=Mock(),
        load_desired_state=AsyncMock(), start=AsyncMock(), shutdown=AsyncMock(),
    )
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file,
        config_provider=lambda _: config,
        runtime_provider=lambda *_: SimpleNamespace(
            compatible_client=provider, mcp_manager=mcp_manager),
        secret_backend=TemporaryKeyring())
    try:
        await core.start(read_fd)
        assert isinstance(core.engine.runner, ToolLoopRunner)
        gateway = core.engine.deps.llm_gateway
        assert gateway is core.management.providers
        assert core.management.mcp.manager is mcp_manager
        assert core.engine.deps.management_mcp_service is core.management.mcp
        assert gateway.capture_serving_identity().client is provider
        changed = await core.management.invoke("tools.set_enabled", {
            "name": "parse_time", "enabled": False,
        })
        assert changed["ok"], changed
        cid = core.conversations.create()["conversation"]["id"]
        owner = core.authority.authenticate_local(peer_uid=core.authority.owner_uid)
        token = PermissionManager.set_request_owner(owner)
        try:
            receipt = core.requests.submit({"client_submission_id": "managed",
                "conversation_id": cid, "text": "Give a short factual response"})
        finally:
            PermissionManager.reset_request_owner(token)
        await core.requests.after_commit()
        await asyncio.gather(*core.requests._tasks)
        assert core.requests.get_request(receipt["request_id"])["state"] == "completed"
        offered = {t["name"] for t in provider.calls[0]["tools"]}
        assert "parse_time" not in offered
        assert "read_file" in offered
        assert core.transcript.read_conversation(cid)[-1]["text"] == (
            "The request used the shared runtime.")

        async def shutdown_shared_mcp():
            assert core.management.mcp._closed
            assert not core.engine.producers_quiesced
            assert core.engine.execution_cleanup_results is None
            if mcp_shutdown_fails:
                raise RuntimeError("private MCP error")

        mcp_manager.shutdown.side_effect = shutdown_shared_mcp
        if mcp_shutdown_fails:
            gateway_close = AsyncMock()
            gateway.close = gateway_close
            with pytest.raises(RuntimeError, match="producers"):
                await core.close()
            gateway_close.assert_not_called()
            assert core.engine.deps.turn_store.available
            assert core.engine.cleanup_outcome["state"] == "unknown"
            assert core.resource_cleanup.current["state"] == "unknown"
    finally:
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
        if mcp_shutdown_fails:
            # Failed cleanup intentionally retains graph ownership. Dispose
            # only this test's private stores after checking the barrier.
            if core.engine is not None:
                core.engine.deps.turn_store.close()
            if core.store is not None:
                core.store.close()
            core.release_runtime()
    mcp_manager.shutdown.assert_awaited_once()


@pytest.fixture
def graph(tmp_path):
    paths = ProfilePaths.from_xdg("test", home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    owner = authority.authenticate_local(peer_uid=authority.owner_uid)
    permissions = PermissionManager(authority)
    token = permissions.set_request_owner(owner)
    store = JournalStore(paths.data_dir / "transport.sqlite3", "test")
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    cfg = Config()
    cfg.openai_codex.enabled = False
    cfg.llm_provider.model = "compat:test"
    cfg.openai_compatible.enabled = True
    cfg.context.directory = str(paths.data_dir / "context")
    cfg.learning.enabled = False
    cfg.browser.enabled = False
    provider = Provider([LLMResponse(text="An actual guarded answer.")])
    engine = build_engine_services(cfg, paths, permissions, delivery=delivery,
                                   compatible_client=provider)
    requests = RequestService(store, conversations, transcript, engine=engine,
                              permissions=permissions, authority=authority, delivery=delivery)
    engine.bind_requests(requests)
    cid = conversations.create()["conversation"]["id"]
    yield requests, engine, provider, transcript, cid
    engine.deps.turn_store.close()
    store.close()
    permissions.reset_request_owner(token)
    authority.release_runtime()


@pytest.mark.asyncio
async def test_real_runner_guarded_delivery_and_accounting(graph):
    requests, engine, provider, transcript, cid = graph
    assert isinstance(engine.runner, ToolLoopRunner)
    result = requests.submit({"client_submission_id": "first", "conversation_id": cid,
                              "text": "Say something brief"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert requests.get_request(result["request_id"])["state"] == "completed"
    rows = transcript.read_conversation(cid)
    assert rows[-1]["text"] == "An actual guarded answer."
    assert rows[-1]["role"] == "assistant"
    assert engine.deps.sessions.get_history(cid)[-1]["role"] == "assistant"
    assert len(provider.calls) == 1
    tools = {tool["name"] for tool in provider.calls[0]["tools"]}
    assert "read_file" in tools
    assert "spawn_agent" not in tools and "schedule_task" not in tools


@pytest.mark.asyncio
async def test_actual_native_dispatch_and_completion_judge(graph):
    requests, _engine, provider, transcript, cid = graph
    provider.responses = [LLMResponse(tool_calls=[ToolCall("t1", "parse_time", {
        "expression": "in 2 hours"})], stop_reason="tool_use"),
        LLMResponse(text="The time conversion is complete.")]
    requests.submit({"client_submission_id": "tool", "conversation_id": cid,
                     "text": "Convert in 2 hours to a timestamp"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert len(provider.calls) == 2
    assert transcript.read_conversation(cid)[-1]["text"] == "The time conversion is complete."
    assert provider.judges == 1


@pytest.mark.asyncio
async def test_actual_generate_file_posts_durable_binary_artifact(graph):
    import base64

    requests, engine, provider, transcript, cid = graph
    artifacts = ArtifactStore(requests.store,
                              authorize=engine.deps.tool_executor._authorize_output)
    requests.delivery.artifact_converter = ArtifactPublisher(artifacts, requests.events)
    provider.responses = [LLMResponse(tool_calls=[ToolCall("file", "generate_file", {
        "filename": "result.txt", "content": "durable text"})], stop_reason="tool_use"),
        LLMResponse(text="The file has been created.")]
    requests.submit({"client_submission_id": "file", "conversation_id": cid,
                     "text": "Create a text file"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    files = [item for item in transcript.list(cid)["items"] if item.get("artifacts")]
    assert len(files) == 1
    assert files[0]["author"] == "odin" and files[0]["role"] == "notice"
    ref = files[0]["artifacts"][0]["ref"]
    page = artifacts.read(ref, 0, 100, owner=requests.authority.owner_id)
    assert base64.b64decode(page["data_b64"]) == b"durable text"
    assert "generate_file" in {tool["name"] for tool in provider.calls[0]["tools"]}


@pytest.mark.asyncio
async def test_retained_promise_guard_does_not_publish_unexecuted_promise(graph):
    requests, _engine, provider, transcript, cid = graph
    provider.responses = [LLMResponse(text="I'll run that command now for you."),
        LLMResponse(tool_calls=[ToolCall("t1", "parse_time", {"expression": "in 1 hour"})]),
        LLMResponse(text="The conversion has finished.")]
    requests.submit({"client_submission_id": "guard", "conversation_id": cid,
                     "text": "Convert in 1 hour to a timestamp"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert len(provider.calls) == 3
    rows = transcript.read_conversation(cid)
    assert rows[-1]["text"] == "The conversion has finished."
    assert all("I'll run" not in row["text"] for row in rows)


@pytest.mark.asyncio
async def test_readiness_revocation_denies_stale_native_call(graph):
    requests, engine, _provider, _transcript, cid = graph
    policy = engine.deps.native_tools.builtin_policy
    policy._get_readiness = lambda: {}
    offered = {tool["name"] for tool in engine.deps.tool_catalog.merged_definitions()}
    assert "parse_time" not in offered
    result = requests.submit({"client_submission_id": "identity", "conversation_id": cid,
                              "text": "Readiness identity"})
    message = requests.fetch_request(cid, result["request_id"])
    rejected, _effects = await engine.deps.native_tools.dispatch(
        "parse_time", {"expression": "in 1 hour"}, message=message,
        user_id=message.owner_id, skill_file_delivery="stage")
    assert rejected.error == "tool_unavailable"


@pytest.mark.asyncio
async def test_composed_shutdown_drains_real_owners_once(graph):
    requests, engine, _provider, _transcript, _cid = graph
    await requests.close()
    await engine.close()
    await engine.close()
    assert engine.deps.turn_store.available is False


def cleanup_engine(*, computer=None, registry=None):
    """Harmless owner graph for lifecycle failure injection."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from src.desktop.services import EngineServices

    deps = SimpleNamespace(
        channel_state=SimpleNamespace(shutdown_steering=AsyncMock()),
        loop_manager=SimpleNamespace(shutdown=AsyncMock(), _loops={}),
        scheduler=SimpleNamespace(stop=AsyncMock(), _task=None),
        runtime_context=SimpleNamespace(),
        agent_manager=SimpleNamespace(_agents={}, cleanup=AsyncMock()),
        tool_executor=SimpleNamespace(_process_registry=registry),
        native_tools=SimpleNamespace(owners={"computer": computer} if computer else {}),
        browser_manager=None, llm_gateway=SimpleNamespace(close=AsyncMock()),
        sessions=SimpleNamespace(save=Mock()), turn_store=SimpleNamespace(close=Mock()),
    )
    return EngineServices(deps, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown_fails", [False, True])
async def test_management_mcp_is_early_single_engine_producer_barrier(tmp_path, shutdown_fails):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.desktop.management import ManagementService
    from src.desktop.mcp import MCPService
    from src.desktop.resource_cleanup import ResourceCleanupError, ResourceCleanupJournal

    calls = []
    engine = cleanup_engine()

    async def mcp_shutdown():
        assert not engine.producers_quiesced
        assert engine.execution_cleanup_results is None
        assert mcp._closed
        calls.append("mcp")
        if shutdown_fails:
            raise RuntimeError("private MCP error")

    async def computer_close():
        assert engine.producers_quiesced and mcp._closed
        calls.append("computer")

    async def process_shutdown():
        assert engine.producers_quiesced and mcp._closed
        calls.append("processes")

    manager = SimpleNamespace(shutdown=AsyncMock(side_effect=mcp_shutdown))
    mcp = MCPService(SimpleNamespace(config=Config()), manager=manager)
    d = engine.deps
    d.runtime_context.mcp_manager = manager
    d.management_owned_mcp = True
    d.management_mcp_service = mcp
    d.channel_state.shutdown_steering.side_effect = lambda: calls.append("steering")
    d.loop_manager.shutdown.side_effect = lambda: calls.append("loops")
    d.scheduler.stop.side_effect = lambda: calls.append("scheduler")
    d.agent_manager.cleanup.side_effect = lambda: calls.append("agents")
    computer = SimpleNamespace(close=AsyncMock(side_effect=computer_close))
    registry = SimpleNamespace(shutdown=AsyncMock(side_effect=process_shutdown))
    d.native_tools.owners["computer"] = computer
    d.tool_executor._process_registry = registry
    d.tool_executor.ssh_pool = SimpleNamespace(
        close_all=AsyncMock(side_effect=lambda: calls.append("ssh")))
    d.browser_manager = SimpleNamespace(
        close=AsyncMock(side_effect=lambda: calls.append("browser")))
    d.llm_gateway.close.side_effect = lambda: calls.append("providers")
    d.runtime_context.outbound_webhook_dispatcher = SimpleNamespace(
        close=AsyncMock(side_effect=lambda: calls.append("outbound")))
    d.runtime_context.knowledge_store = SimpleNamespace(
        close=AsyncMock(side_effect=lambda: calls.append("knowledge")))
    d.sessions.save.side_effect = lambda: calls.append("sessions")
    d.turn_store.close.side_effect = lambda: calls.append("turn_store")
    late_owner = SimpleNamespace(METHODS=(), READ_METHODS=(),
        close=AsyncMock(side_effect=lambda: calls.append("management")))
    journal = ResourceCleanupJournal(tmp_path / "cleanup.json")
    core = SimpleNamespace(engine=engine, resource_cleanup=journal)
    management = ManagementService(core, services=(late_owner, mcp), identity_key=b"x" * 32)
    management._engine_owned = True

    if shutdown_fails:
        for _ in range(2):
            with pytest.raises(RuntimeError, match="producers"):
                await engine.close()
            with pytest.raises(ResourceCleanupError):
                await management.close()
        assert calls == ["steering", "loops", "scheduler", "mcp", "agents"]
        assert not engine.producers_quiesced
        assert engine.cleanup_outcome["state"] == "unknown"
        assert journal.current["state"] == "unknown"
        assert journal.current["resources"]["services"] == {
            "state": "unknown", "reason": "producers_not_quiesced"}
        for owner in (computer.close, registry.shutdown, d.tool_executor.ssh_pool.close_all,
                      d.browser_manager.close, d.llm_gateway.close,
                      d.runtime_context.outbound_webhook_dispatcher.close,
                      d.runtime_context.knowledge_store.close, d.sessions.save,
                      d.turn_store.close, late_owner.close):
            owner.assert_not_called()
        # Even a later direct wrapper traversal must retain the first failure.
        with pytest.raises(RuntimeError, match="private MCP error"):
            await mcp.shutdown()
    else:
        await asyncio.gather(engine.close(), engine.close())
        await management.close()
        await mcp.shutdown()
        assert calls == ["steering", "loops", "scheduler", "mcp", "agents",
                         "computer", "processes", "ssh", "browser", "providers",
                         "outbound", "sessions", "knowledge", "turn_store", "management"]
        assert engine.cleanup_outcome["state"] == "released"
        assert journal.current["state"] == "complete"
    manager.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_shared_injected_owner_barriers_once_after_producers_quiesce(graph):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.desktop.resource_cleanup import close_existing_execution_owners

    requests, engine, _provider, _transcript, _cid = graph
    calls = []

    async def computer_close():
        assert requests._closed and not requests._tasks
        assert engine.producers_quiesced
        calls.append("computer")

    async def process_shutdown():
        assert engine.producers_quiesced
        calls.append("processes")

    computer = SimpleNamespace(close=AsyncMock(side_effect=computer_close))
    registry = SimpleNamespace(shutdown=AsyncMock(side_effect=process_shutdown))
    engine.deps.native_tools.owners["computer"] = computer
    engine.deps.tool_executor._process_registry = registry
    await requests.close()
    await asyncio.gather(engine.close(), engine.close())
    results = await close_existing_execution_owners(
        SimpleNamespace(engine=engine), SimpleNamespace(executor=engine.deps.tool_executor))
    assert calls == ["computer", "processes"]
    assert all(row["state"] == "released" for row in results.values())
    computer.close.assert_awaited_once()
    registry.shutdown.assert_awaited_once()
    assert engine.deps.native_tools.owners["computer"] is computer
    results["processes"]["state"] = "unknown"
    assert engine.execution_cleanup_results["processes"]["state"] == "released"


@pytest.mark.asyncio
async def test_original_process_failure_durable_unknown_and_never_retried(tmp_path):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.desktop.resource_cleanup import (
        ResourceCleanupError,
        ResourceCleanupJournal,
        close_existing_execution_owners,
    )

    registry = SimpleNamespace(shutdown=AsyncMock(side_effect=RuntimeError("private detail")))
    computer = SimpleNamespace(close=AsyncMock())
    engine = cleanup_engine(computer=computer, registry=registry)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="cleanup did not fully complete"):
            await engine.close()
    assert engine.producers_quiesced
    computer.close.assert_awaited_once()
    registry.shutdown.assert_awaited_once()
    engine.deps.llm_gateway.close.assert_not_called()
    engine.deps.turn_store.close.assert_not_called()
    result = await close_existing_execution_owners(SimpleNamespace(engine=engine), None)
    assert result["processes"] == {"state": "unknown", "error_type": "RuntimeError"}
    assert result["computer"]["state"] == "released"
    assert result["engine"]["state"] == "unknown"
    assert {"stage": "execution_owners", "error_type": "ResourceCleanupError"} in (
        result["engine"]["failures"])
    assert "private detail" not in json.dumps(result)
    journal = ResourceCleanupJournal(tmp_path / "cleanup.json")
    with pytest.raises(ResourceCleanupError):
        journal.finish(result)
    assert json.loads(journal.path.read_text())["resources"] == result


@pytest.mark.asyncio
async def test_provider_failure_preserves_successful_original_owner_evidence():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.desktop.resource_cleanup import close_existing_execution_owners

    registry = SimpleNamespace(shutdown=AsyncMock())
    engine = cleanup_engine(registry=registry)
    engine.deps.llm_gateway.close.side_effect = ValueError("private provider error")
    with pytest.raises(RuntimeError):
        await engine.close()
    result = await close_existing_execution_owners(SimpleNamespace(engine=engine), None)
    assert result["processes"]["state"] == "released"
    assert result["computer"]["state"] == "not_started"
    assert result["engine"]["state"] == "unknown"
    assert {"stage": "providers", "error_type": "ValueError"} in result["engine"]["failures"]
    registry.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_injected_native_quarantine_keeps_original_durable_unknown(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.computer.models import RequestContext
    from src.computer.store import ComputerStore
    from src.desktop.resource_cleanup import close_existing_execution_owners

    store = ComputerStore(tmp_path / "computer.sqlite3", tmp_path / "evidence")
    grant = store.create_session(
        RequestContext("owner", "channel", "turn", "localhost", surface="webui"),
        environment="existing_session")
    store.set_state(grant.session_id, "quarantined", revoke=True)

    async def close_original_store():
        store.close()

    owner = SimpleNamespace(controller=SimpleNamespace(store=store),
                            close=AsyncMock(side_effect=close_original_store))
    engine = cleanup_engine(computer=owner)
    try:
        with pytest.raises(RuntimeError):
            await engine.close()
        result = await close_existing_execution_owners(SimpleNamespace(engine=engine), None)
        assert result["computer"]["state"] == "unknown"
        assert result["computer"]["unresolved_sessions"] == [grant.session_id]
        owner.close.assert_awaited_once()
        assert engine.deps.native_tools.owners["computer"] is owner
        engine.deps.turn_store.close.assert_not_called()
    finally:
        if owner.close.await_count == 0:
            store.close()


@pytest.mark.asyncio
async def test_producer_failure_preserves_execution_owners_and_persistence():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.desktop.resource_cleanup import close_existing_execution_owners

    owner = SimpleNamespace(close=AsyncMock())
    registry = SimpleNamespace(shutdown=AsyncMock())
    engine = cleanup_engine(computer=owner, registry=registry)
    engine.deps.loop_manager.shutdown.side_effect = RuntimeError("producer failure")
    with pytest.raises(RuntimeError, match="producers"):
        await engine.close()
    owner.close.assert_not_called()
    registry.shutdown.assert_not_called()
    engine.deps.llm_gateway.close.assert_not_called()
    engine.deps.turn_store.close.assert_not_called()
    assert not engine.producers_quiesced
    result = await close_existing_execution_owners(SimpleNamespace(engine=engine), None)
    assert all(row["state"] == "unknown" for row in result.values())


@pytest.mark.asyncio
async def test_request_not_quiesced_refuses_any_engine_owner_teardown():
    from types import SimpleNamespace

    engine = cleanup_engine()
    engine.bind_requests(SimpleNamespace(_closed=False, _tasks=set()))
    with pytest.raises(RuntimeError, match="request producers"):
        await engine.close()
    engine.deps.channel_state.shutdown_steering.assert_not_called()
    engine.deps.turn_store.close.assert_not_called()


@pytest.mark.asyncio
async def test_engine_barrier_cancellation_keeps_partial_results_and_propagates():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.desktop.resource_cleanup import close_existing_execution_owners

    owner = SimpleNamespace(close=AsyncMock())
    registry = SimpleNamespace(shutdown=AsyncMock(side_effect=asyncio.CancelledError()))
    engine = cleanup_engine(computer=owner, registry=registry)
    for _ in range(2):
        with pytest.raises(asyncio.CancelledError):
            await engine.close()
    result = await close_existing_execution_owners(SimpleNamespace(engine=engine), None)
    assert result["computer"]["state"] == "released"
    assert result["processes"] == {"state": "unknown", "error_type": "CancelledError"}
    assert result["engine"]["state"] == "unknown"
    owner.close.assert_awaited_once()
    registry.shutdown.assert_awaited_once()
    engine.deps.turn_store.close.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("repeat_reset", [False, True])
async def test_reset_running_retains_real_context_but_fences_next_turn(graph, repeat_reset):
    """Exercise runner/native file delivery, retained history, prompt and save paths."""
    import copy

    from src.sessions.manager import SessionManager

    requests, engine, provider, transcript, cid = graph
    transcript.commit(cid, "user", "OLD QUESTION")
    transcript.commit(cid, "assistant", "OLD ANSWER")
    started, release = asyncio.Event(), asyncio.Event()
    original = provider.chat_with_tools
    admitted_session = []
    observations = []

    async def blocked(**kwargs):
        # Snapshot the real physical provider context before the runner mutates it.
        observations.append(copy.deepcopy(kwargs))
        if len(observations) == 1:
            admitted_session.append(engine.deps.sessions.get(cid))
            started.set()
            await release.wait()
            assert engine.deps.sessions.get(cid) is admitted_session[0]
            assert "OLD ANSWER" in str(engine.deps.sessions.get_history(cid))
        return await original(**kwargs)

    provider.chat_with_tools = blocked
    provider.responses = [LLMResponse(tool_calls=[ToolCall("late-file", "generate_file", {
        "filename": "old-result.txt", "content": "OLD FILE"})], stop_reason="tool_use"),
        LLMResponse(text="OLD LATE ANSWER"), LLMResponse(text="NEW ANSWER"),
        LLMResponse(text="AFTER RELOAD ANSWER")]
    artifacts = ArtifactStore(requests.store, authorize=engine.deps.tool_executor._authorize_output)
    requests.delivery.artifact_converter = ArtifactPublisher(artifacts, requests.events)
    first = requests.submit({"client_submission_id": "running", "conversation_id": cid,
                             "text": "OLD RUNNING INPUT"})
    await requests.after_commit()
    try:
        await asyncio.wait_for(started.wait(), 5)
        queued = requests.submit({"client_submission_id": "queued-before-reset",
                                  "conversation_id": cid, "text": "NEW QUEUED INPUT"})
        revision = requests.conversations.get(cid)["rev"]
        with pytest.raises(ConversationError, match="active work"):
            requests.conversations.delete(cid, revision)
        reset = requests.conversations.reset_context(cid, revision)
        assert reset["conversation"]["rev"] == revision + 1
        if repeat_reset:
            transcript.commit(cid, "user", "BETWEEN RESETS")
            requests.conversations.reset_context(cid, requests.conversations.get(cid)["rev"])
        assert transcript.model_context(cid) == []
        assert engine.deps.sessions.get(cid) is admitted_session[0]
        transcript.commit(cid, "user", "NEW CONTEXT MARKER")
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(*requests._tasks), 15)

    assert requests.get_request(first["request_id"])["state"] == "completed"
    assert requests.get_request(queued["request_id"])["state"] == "completed"
    assert len(observations) == 3
    assert "OLD ANSWER" in str(observations[0]["messages"])
    assert "OLD ANSWER" in str(observations[1]["messages"])
    fresh = str(observations[2])
    assert "NEW QUEUED INPUT" in fresh and "NEW CONTEXT MARKER" in fresh
    assert "OLD" not in str(observations[2]["messages"])
    assert "BETWEEN RESETS" not in fresh
    assert "## Recent Actions" not in observations[2]["system"]
    visible = transcript.list(cid)["items"]
    assert any(item.get("artifacts") for item in visible)
    assert any(item["text"] == "OLD LATE ANSWER" for item in visible)
    context = transcript.model_context(cid)
    assert {item["text"] for item in context} == {
        "NEW CONTEXT MARKER", "NEW QUEUED INPUT", "NEW ANSWER"}
    assert all("context_position" not in item for item in visible)
    assert "OLD" not in str(engine.deps.sessions.get_history(cid))

    # Reload both durable transcript storage and real SessionManager cache. The
    # request lineage is durable, not an in-memory exclusion list.
    paths = requests.authority.paths
    reloaded_sessions = SessionManager(160, 24, str(paths.data_dir / "sessions"))
    reloaded_sessions.load()
    assert "OLD" not in str(reloaded_sessions.get_history(cid))
    reopened = JournalStore(paths.data_dir / "transport.sqlite3", "test")
    try:
        events = PublicationEventJournal(reopened)
        conversations = ConversationStore(reopened, events)
        restored = TranscriptStore(reopened, events, conversations)
        assert restored.model_context(cid) == context
        engine.deps.sessions = reloaded_sessions
        reloaded = RequestService(reopened, conversations, restored, engine=engine,
            permissions=requests.permissions, authority=requests.authority,
            delivery=requests.delivery)
        engine.requests = reloaded
        reloaded.submit({"client_submission_id": "after-reload", "conversation_id": cid,
                         "text": "RELOAD INPUT"})
        await reloaded.after_commit()
        await asyncio.wait_for(asyncio.gather(*reloaded._tasks), 15)
        assert "OLD" not in str(observations[-1]["messages"])
        assert "NEW ANSWER" in str(observations[-1]["messages"])
        assert "RELOAD INPUT" in str(observations[-1]["messages"])
    finally:
        engine.requests = requests
        reopened.close()


@pytest.mark.asyncio
async def test_reset_real_handoff_retains_history_and_retires_cache(graph, monkeypatch):
    requests, engine, provider, transcript, cid = graph
    transcript.commit(cid, "assistant", "ADMITTED HANDOFF CONTEXT")
    entered, release = asyncio.Event(), asyncio.Event()
    observed = []

    async def handoff(**kwargs):
        observed.append(kwargs)
        entered.set()
        await release.wait()
        assert "ADMITTED HANDOFF CONTEXT" in str(engine.deps.sessions.get_history(cid))
        return "LATE HANDOFF RESPONSE"

    monkeypatch.setattr(engine.deps.skill_manager, "should_handoff_to_codex", lambda _: True)
    provider.chat = handoff
    provider.responses = [LLMResponse(tool_calls=[ToolCall("time", "parse_time", {
        "expression": "in 1 hour"})], stop_reason="tool_use")]
    requests.submit({"client_submission_id": "handoff", "conversation_id": cid,
                     "text": "Convert one hour"})
    await requests.after_commit()
    try:
        await asyncio.wait_for(entered.wait(), 5)
        session = engine.deps.sessions.get(cid)
        requests.conversations.reset_context(cid, requests.conversations.get(cid)["rev"])
        assert engine.deps.sessions.get(cid) is session
        assert "ADMITTED HANDOFF CONTEXT" in str(observed[0]["messages"])
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(*requests._tasks), 10)
    assert transcript.list(cid)["items"][-1]["text"] == "LATE HANDOFF RESPONSE"
    assert transcript.model_context(cid) == []
    assert engine.deps.sessions.get(cid) is None
    assert cid not in engine.deps.channel_state.recent_actions
    from src.sessions.manager import SessionManager

    loaded = SessionManager(160, 24, str(requests.authority.paths.data_dir / "sessions"))
    loaded.load()
    assert loaded.get_history(cid) == []


@pytest.mark.asyncio
async def test_preserved_generation_two_stays_fenced_after_new_lineage_turn(graph, monkeypatch):
    """Restore a real retained checkpoint, not a fake resume runner."""
    import copy

    from src.discord.response_guards import StuckLoopTracker
    from src.discord.tool_loop import CHAT_POLICY, _ChatTurn
    from src.llm.errors import LLMCapacityError
    from src.llm.model_breaker import ModelBreakerRegistry
    from src.llm.recovery import RecoveryPolicy
    from src.turn_state.codec import restore_field_values
    from src.turn_state.durability import TurnDurability

    requests, engine, provider, transcript, cid = graph
    original = provider.chat_with_tools

    async def overloaded(**kwargs):
        if not provider.responses:
            raise LLMCapacityError("scripted capacity", provider="compat", model="test")
        return await original(**kwargs)

    provider.chat_with_tools = overloaded
    monkeypatch.setattr(engine.deps.llm_gateway, "_recovery_policy_source", lambda: RecoveryPolicy(
        deadline_seconds=0.05, backoff_base=0.005, backoff_cap=0.01, retry_after_cap=0.01))
    provider.responses = [LLMResponse(tool_calls=[ToolCall("parse", "parse_time", {
        "expression": "in 1 hour"})], stop_reason="tool_use")]
    first = requests.submit({"client_submission_id": "preserved", "conversation_id": cid,
                             "text": "OLD PRESERVED INPUT"})
    await requests.after_commit()
    await asyncio.wait_for(asyncio.gather(*requests._tasks), 10)
    assert requests.get_request(first["request_id"])["state"] == "suspended"
    old_message = requests.fetch_request(cid, first["request_id"])
    ledger = engine.deps.turn_store
    row = ledger.load_resumable_sync(old_message.turn_key)
    assert row is not None
    fields = restore_field_values(row["payload"], load_blob=ledger.load_blob_sync,
                                  stuck_tracker_cls=StuckLoopTracker)
    monkeypatch.setattr(engine.deps.llm_gateway, "model_breakers", ModelBreakerRegistry())
    requests.conversations.reset_context(cid, requests.conversations.get(cid)["rev"])
    provider.responses = [LLMResponse(text="NEW LINEAGE ANSWER")]
    requests.submit({"client_submission_id": "new", "conversation_id": cid,
                     "text": "NEW LINEAGE INPUT"})
    await requests.after_commit()
    await asyncio.wait_for(asyncio.gather(*requests._tasks), 10)
    session = engine.deps.sessions.get(cid)
    before_resume = copy.deepcopy(engine.deps.sessions.get_history(cid))
    lease = ledger.acquire_resume_lease_sync(old_message.turn_key, row["generation"])
    assert lease is not None
    with requests.store.transaction() as db:
        db.execute("UPDATE desktop_requests SET state='running',generation=2 WHERE request_id=?",
                   (first["request_id"],))
    st = _ChatTurn(message=requests.fetch_request(cid, first["request_id"]), policy=CHAT_POLICY,
        trace=None, tools=engine.deps.tool_catalog.merged_definitions(), _cancel=asyncio.Event(),
        durability=TurnDurability.resumed(ledger, lease, 1), **fields)
    provider.responses = [LLMResponse(text="OLD RESUMED ANSWER")]
    await requests.launch_resume(requests.get_request(first["request_id"]), st)
    await asyncio.wait_for(asyncio.gather(*requests._tasks), 10)
    assert requests.get_request(first["request_id"])["state"] == "completed"
    assert "OLD RESUMED ANSWER" in str(transcript.list(cid))
    assert "OLD" not in str(transcript.model_context(cid))
    assert engine.deps.sessions.get(cid) is session
    assert engine.deps.sessions.get_history(cid) == before_resume
    provider.responses = [LLMResponse(text="NEXT ANSWER")]
    requests.submit({"client_submission_id": "next", "conversation_id": cid, "text": "NEXT INPUT"})
    await requests.after_commit()
    await asyncio.wait_for(asyncio.gather(*requests._tasks), 10)
    assert "NEW LINEAGE ANSWER" in str(provider.calls[-1]["messages"])
    assert "OLD" not in str(provider.calls[-1]["messages"])


def _saved_name(config_dir, content, *, mode=0o700):
    """The app's display profile, as Settings, General, Your profile saves it."""
    folder = config_dir / "display-profile"
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(mode)
    (folder / "profile.json").write_text(content)
    (folder / "profile.json").chmod(0o600)
    return folder


@pytest.mark.asyncio
@pytest.mark.parametrize(("saved", "called"), [(None, "Owner"), ("Intolerance", "Intolerance")])
async def test_odin_calls_you_by_the_name_set_in_settings(graph, saved, called):
    """As Odin knows your Discord display name: the message tag and the request preamble."""
    requests, engine, provider, transcript, cid = graph
    if saved:
        _saved_name(requests.authority.paths.config_dir, json.dumps({"name": saved}))
    requests.submit({"client_submission_id": "named", "conversation_id": cid, "text": "Who am I?"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    sent = json.dumps(provider.calls[0]["messages"])
    assert f"[{called}]: Who am I?" in sent
    assert engine.deps.sessions.get_history(cid)[0]["content"] == f"[{called}]: Who am I?"
    other = "Owner" if saved else "Intolerance"
    assert f"[{other}]" not in sent


@pytest.mark.parametrize("content", [
    "{not json", json.dumps({"name": ""}), json.dumps({"name": "   "}),
    json.dumps({"name": "x" * 41}),
    json.dumps({"name": "two\nlines"}), json.dumps({"name": 7}), json.dumps(["Intolerance"]),
    json.dumps({"name": "Intolerance", "pad": "x" * 5000}),
])
def test_an_unusable_saved_name_means_owner(tmp_path, content):
    _saved_name(tmp_path, content)
    assert owner_display_name(tmp_path) == "Owner"


def test_the_saved_name_is_read_only_under_the_apps_own_rules(tmp_path):
    assert owner_display_name(None) == "Owner"
    assert owner_display_name(tmp_path) == "Owner"  # nothing saved
    folder = _saved_name(tmp_path, json.dumps({"name": "Intolerance"}))
    assert owner_display_name(tmp_path) == "Intolerance"
    folder.chmod(0o755)  # a folder others can read is not the app's private profile
    assert owner_display_name(tmp_path) == "Owner"
    folder.chmod(0o700)
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps({"name": "Someone else"}))
    (folder / "profile.json").unlink()
    (folder / "profile.json").symlink_to(elsewhere)  # never through a link
    assert owner_display_name(tmp_path) == "Owner"


def test_a_saved_name_that_is_a_fifo_is_refused_at_once(tmp_path):
    """A FIFO opened for reading waits for a writer unless opened non-blocking. The read runs in a
    child process with a time limit, so a regression fails here instead of hanging the suite."""
    folder = tmp_path / "display-profile"
    folder.mkdir(mode=0o700)
    os.mkfifo(folder / "profile.json", 0o600)
    code = ("import sys; from src.desktop.requests import owner_display_name; "
            "print(owner_display_name(sys.argv[1]))")
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True,
                            text=True, timeout=30, cwd=os.path.dirname(os.path.dirname(__file__)))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Owner"
