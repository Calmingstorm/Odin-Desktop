"""Actual composed upstream runner and durable local publication."""
import asyncio

import pytest

from src.config.schema import Config
from src.desktop.artifacts import ArtifactStore
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import ArtifactPublisher, DurableDelivery, PublicationEventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
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
