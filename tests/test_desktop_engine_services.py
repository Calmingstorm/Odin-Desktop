"""Actual composed upstream runner and durable local publication."""
import asyncio

import pytest

from src.config.schema import Config
from src.desktop.artifacts import ArtifactStore
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationError, ConversationStore
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
