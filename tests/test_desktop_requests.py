"""Durable request identity and task-owned execution admission."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.events import EventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.transcript import TranscriptStore
from src.discord.channel_state import ChannelStateRegistry
from src.permissions.manager import PermissionManager
from src.turn_state import TurnStateStore


class Engine:
    def __init__(self, ledger):
        self.deps = SimpleNamespace(turn_store=ledger, channel_state=ChannelStateRegistry())
        self.calls = []

    async def run(self, message, **_kwargs):
        self.requests.assert_request(message)
        self.calls.append(message.request_id)
        return ("committed answer", False, False, [], False)

    async def record_result(self, _message, _result):
        pass


class Delivery:
    def __init__(self):
        self.replies = []

    def guarded_reply(self, context, text):
        return (context, text)

    async def send_reply(self, context, text, *, guarded):
        assert guarded == (context, text)
        self.replies.append((context, text))


@pytest.fixture
def service(tmp_path):
    paths = ProfilePaths.from_xdg("test", home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    owner = authority.authenticate_local(peer_uid=authority.owner_uid)
    permissions = PermissionManager(authority)
    token = permissions.set_request_owner(owner)
    store = JournalStore(paths.data_dir / "transport.sqlite3", "test")
    events = EventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    ledger = TurnStateStore(paths.data_dir / "turn-state" / "turns.sqlite3")
    engine, delivery = Engine(ledger), Delivery()
    requests = RequestService(store, conversations, transcript, engine=engine,
                              permissions=permissions, authority=authority, delivery=delivery)
    engine.requests = requests
    cid = conversations.create()["conversation"]["id"]
    yield requests, cid, engine, delivery, store
    ledger.close()
    store.close()
    permissions.reset_request_owner(token)
    authority.release_runtime()


def params(cid, **changes):
    return {"client_submission_id": "submission", "conversation_id": cid,
            "text": "Show a harmless result", **changes}


def test_submission_deduplicates_before_any_execution(service):
    requests, cid, engine, _delivery, _store = service
    first = requests.handle("submission.send", params(cid))
    assert first["ok"] and first["result"]["disposition"] == "accepted"
    assert requests.handle("submission.send", params(cid)) == first
    assert len(requests.snapshot(cid)["queued"]) == 1
    assert engine.calls == []
    conflict = requests.handle("submission.send", params(cid, text="Different"))
    assert conflict["error"]["code"] == "id_conflict"


def test_rollback_admits_no_work_or_transcript(service):
    requests, cid, engine, _delivery, store = service
    with pytest.raises(RuntimeError), store.transaction():
        requests.submit(params(cid))
        raise RuntimeError("rollback")
    assert requests.snapshot(cid)["queued"] == []
    assert requests.transcript.list(cid)["items"] == []
    assert engine.calls == []


def test_validation_and_attachment_only_admission(service):
    requests, cid, _engine, _delivery, _store = service
    empty = requests.handle("submission.send", params(cid, text=""))
    assert empty["error"]["code"] == "bad_request"
    assert requests.handle("submission.send", params("absent"))["error"]["code"] == "not_found"
    result = requests.handle("submission.send", params(
        cid, text="", attachments=[{"ref": "opaque"}]))
    assert result["error"]["code"] == "capability_unavailable"


@pytest.mark.asyncio
async def test_followups_execute_once_in_admission_order(service):
    requests, cid, engine, delivery, _store = service
    first = requests.submit(params(cid))
    second = requests.submit(params(cid, client_submission_id="second", text="Second result"))
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert engine.calls == [first["request_id"], second["request_id"]]
    assert [item[0].request_id for item in delivery.replies] == engine.calls
    state = requests.snapshot(cid)
    assert state["running"] is None and state["queued"] == []
    assert [item["outcome"] for item in state["recent"]] == ["completed", "completed"]


@pytest.mark.asyncio
async def test_cancelled_queued_work_never_starts(service):
    requests, cid, engine, _delivery, store = service
    admitted = requests.submit(params(cid))
    with store.transaction() as db:
        db.execute("UPDATE desktop_requests SET state='cancelled' WHERE request_id=?",
                   (admitted["request_id"],))
    await requests.after_commit()
    assert engine.calls == [] and not requests._tasks


@pytest.mark.asyncio
async def test_neutral_envelope_is_not_an_execution_grant(service):
    requests, cid, engine, _delivery, store = service
    admitted = requests.submit(params(cid))
    with store.transaction() as db:
        db.execute("UPDATE desktop_requests SET state='running' WHERE request_id=?",
                   (admitted["request_id"],))
    message = requests.fetch_request(cid, admitted["request_id"])
    assert message.id == admitted["request_id"] and message.channel.id == cid
    assert message.author.id == requests.authority.owner_id
    with pytest.raises(PermissionError):
        await engine.run(message)
    assert requests.binding(cid, message.id, 2) is None
    assert requests.binding(cid, message.id, True) is None


def test_admission_has_no_arbitrary_text_cap(service):
    requests, cid, _engine, _delivery, _store = service
    text = "ordinary text " * 6000
    admitted = requests.submit(params(cid, text=text))
    assert requests.get_request(admitted["request_id"])["text"] == text
    assert requests.transcript.list(cid)["items"][0]["text"] == text


@pytest.mark.asyncio
async def test_delivery_failure_never_reopens_execution(service):
    requests, cid, engine, delivery, _store = service
    async def fail(*_args, **_kwargs):
        raise OSError("Temporary publication failure")
    delivery.send_reply = fail
    admitted = requests.submit(params(cid))
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert requests.get_request(admitted["request_id"])["state"] == "completed"
    await requests.after_commit()
    assert engine.calls == [admitted["request_id"]]


@pytest.mark.asyncio
async def test_branch_seed_reset_and_compaction_preservation(service, tmp_path):
    from src.sessions.manager import SessionManager

    requests, parent, engine, _delivery, _store = service
    sessions = SessionManager(max_history=160, max_age_hours=24,
                              persist_dir=str(tmp_path / "model-sessions"))
    engine.deps.sessions = sessions
    requests.transcript.commit(parent, "user", "inherited question")
    requests.transcript.commit(parent, "assistant", "inherited answer")
    child = requests.conversations.create(parent_id=parent)["conversation"]["id"]
    requests.transcript.commit(parent, "assistant", "later parent answer")
    observed = []
    async def run(message, **kwargs):
        requests.assert_request(message)
        observed.append(sessions.get_history(message.conversation_id))
        sessions.add_message(message.conversation_id, "user", kwargs["content"])
        return ("answer", False, False, [], False)
    engine.run = run
    requests.submit(params(child))
    requests.submit(params(child, client_submission_id="followup", text="queued later"))
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert [item["content"] for item in observed[0]] == ["inherited question", "inherited answer"]
    assert "queued later" not in str(observed[0])
    assert "later parent answer" not in str(observed)
    # Simulate the retained manager's compacted cache. Next admission must not
    # replace it with the visible transcript.
    sessions.reset(child)
    sessions.add_message(child, "assistant", "compacted history")
    requests.submit(params(child, client_submission_id="third"))
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert observed[-1] == [{"role": "assistant", "content": "compacted history"}]
    requests.conversations.reset_context(child, requests.conversations.get(child)["rev"])
    requests.submit(params(child, client_submission_id="after-reset"))
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert observed[-1] == []


def test_all_unknown_effects_preserved_as_wire_count(service):
    requests, cid, engine, _delivery, store = service
    admitted = requests.submit(params(cid))
    rid = admitted["request_id"]
    with store.transaction() as db:
        db.execute("UPDATE desktop_requests SET state='running' WHERE request_id=?", (rid,))
    ledger = engine.deps.turn_store
    with ledger._write_lock:
        db = ledger._require()
        db.executemany("""INSERT INTO operations
            (source,channel_id,message_id,turn_generation,generation_seq,tool_call_id,state,
             tool_name,effect_class,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [("conversation", cid, rid, "ledger-gen", 1, f"call-{i}", "OUTCOME_UNKNOWN",
              "harmless_fake", "EXTERNAL_EFFECT_CAPABLE", 0, 0) for i in range(1100)])
        db.commit()
    requests._finish(requests.fetch_request(cid, rid), "interrupted")
    state = requests.snapshot(cid)
    assert state["recent"][0]["unknown_effects"] == 1100
    assert state["unresolved"] == state["recent"]
    assert len(json.loads(requests.get_request(rid)["unknown_effects"])) == 1100


@pytest.mark.asyncio
async def test_tool_outbox_projection_survives_retention_and_pairs_invocations(service):
    from src.desktop.delivery import DurableDelivery

    requests, cid, engine, _delivery, store = service
    delivery = DurableDelivery(store, requests.events, transcript_commit=requests.transcript.commit)
    requests.delivery = delivery
    rid = requests.submit(params(cid))["request_id"]
    with store.transaction() as db:
        db.execute("UPDATE desktop_requests SET state='running' WHERE request_id=?", (rid,))
    requests.events.max_events = 0
    async def event(kind, call, **metadata):
        await requests.observe_tool_event({"type": kind, "action": "harmless_fake",
            "channel_id": cid, "metadata": {"turn_id": rid, "call_id": call, **metadata}})
    await event("tool_start", "first")
    await event("tool_start", "second")
    await event("tool_end", "second", elapsed_ms=8, error="failed")
    await event("tool_end", "first", elapsed_ms=12, uncertain_outcome=True)
    assert not list(store.connection.execute("SELECT * FROM journal_events"))
    tools = requests.snapshot(cid)["tools"][rid]
    assert [item["invocation_id"] for item in tools] == ["first", "second"]
    assert [item["outcome"] for item in tools] == ["unknown", "failure"]
    assert [item["duration_ms"] for item in tools] == [12, 8]
    assert requests.transcript.snapshot(cid)["tools"][rid] == tools


@pytest.mark.asyncio
async def test_tool_child_has_bound_read_not_execution_authority(service):
    requests, cid, engine, _delivery, _store = service
    async def run(message, **_kwargs):
        async def child():
            requests.assert_bound_request(message)
            with pytest.raises(PermissionError):
                requests.assert_request(message)
        await asyncio.create_task(child())
        return ("answer", False, False, [], False)
    engine.run = run
    requests.submit(params(cid))
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert requests.snapshot(cid)["recent"][0]["outcome"] == "completed"


@pytest.mark.asyncio
async def test_close_reports_unsettled_execution_without_unbounded_gather(service, monkeypatch):
    requests, _cid, _engine, _delivery, store = service
    release, started = asyncio.Event(), asyncio.Event()
    async def resistant():
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
    task = asyncio.create_task(resistant())
    requests._tasks.add(task)
    await started.wait()
    wait = asyncio.wait
    async def bounded(tasks, **kwargs):
        return await wait(tasks, timeout=0.01)
    monkeypatch.setattr(asyncio, "wait", bounded)
    try:
        with pytest.raises(RuntimeError, match="still settling"):
            await requests.close()
        assert not task.done()
        assert store.connection.execute("SELECT 1").fetchone()[0] == 1
    finally:
        release.set()
        await task
        requests._tasks.discard(task)


@pytest.mark.asyncio
async def test_real_runner_tool_detail_preserves_sink_output_and_live_authorization(service):
    from src.config.schema import Config
    from src.desktop.artifacts import ArtifactStore
    from src.desktop.delivery import DurableDelivery, PublicationEventJournal
    from src.desktop.services import build_engine_services
    from src.desktop.tool_details import ToolDetailsStore
    from src.llm.types import LLMResponse, ToolCall

    requests, cid, old_engine, _delivery, store = service
    class Provider:
        model, provider_name = "test", "compat"
        def __init__(self):
            self.responses = [LLMResponse(tool_calls=[ToolCall("time-call", "parse_time",
                {"expression": "in 2 hours"})]), LLMResponse(text="Conversion complete.")]
        async def chat_with_tools(self, **_kwargs):
            return self.responses.pop(0)
        async def chat(self, **_kwargs):
            return "COMPLETE"
        async def drain_and_close(self):
            pass
    cfg = Config()
    cfg.openai_codex.enabled = False
    cfg.llm_provider.model = "compat:test"
    cfg.openai_compatible.enabled = True
    cfg.context.directory = str(requests.authority.paths.data_dir / "context")
    cfg.learning.enabled = False
    cfg.browser.enabled = False
    events = PublicationEventJournal(store)
    requests.events = requests.transcript.events = requests.conversations.events = events
    delivery = DurableDelivery(store, events, transcript_commit=requests.transcript.commit,
                               assert_context=requests.assert_delivery_context)
    engine = build_engine_services(cfg, requests.authority.paths, requests.permissions,
                                   delivery=delivery, compatible_client=Provider())
    requests.engine, requests.delivery = engine, delivery
    engine.bind_requests(requests)
    engine.runner._record_tool_detail = requests.record_tool_detail
    engine.deps.audit.set_event_callback(requests.observe_tool_event)
    executor = engine.deps.tool_executor
    artifacts = ArtifactStore(store, output_store=executor._ensure_output_store(),
                              authorize=executor._authorize_output)
    delivery.tool_details = ToolDetailsStore(
        store, output_store=executor._ensure_output_store(),
        artifacts=artifacts, authorize=executor._authorize_output)
    try:
        admitted = requests.submit(params(cid))
        await requests.after_commit()
        await asyncio.gather(*requests._tasks)
        rid = admitted["request_id"]
        detail = delivery.tool_details.detail(rid, "time-call", owner=requests.authority.owner_id,
                                              conversation_id=cid)
        assert detail["tool"] == "parse_time"
        assert detail["arguments"] == {"expression": "in 2 hours"}
        assert "T" in detail["previews"][0]["text"]
        assert requests.snapshot(cid)["tools"][rid][0]["outcome"] == "success"
        executor._builtin_policy._get_readiness = lambda: {}
        with pytest.raises(Exception, match="no longer authorized"):
            delivery.tool_details.detail(rid, "time-call", owner=requests.authority.owner_id)
    finally:
        await requests.close()
        await engine.close()
        requests.engine = old_engine
