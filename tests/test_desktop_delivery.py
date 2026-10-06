"""D9 commit/rollback and restart publication using real durable domain stores."""
import io
import json
from dataclasses import replace

import pytest

from src.desktop.commands import JournalStorageError, JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import (
    DELIVERY_SCHEMA,
    ArtifactPost,
    ArtifactPublisher,
    DurableDelivery,
    LocalDestination,
    PublicationEventJournal,
    RequestContext,
)
from src.desktop.schema import DOMAIN_COLUMNS
from src.desktop.transcript import TranscriptStore

# Match the parent's explicit registry composition, never a permissive table
# matcher. Restart tests below exercise the real store's validation unchanged.
DOMAIN_COLUMNS.update(DELIVERY_SCHEMA)


class Sink:
    def __init__(self, store):
        self.store = store
        self.accepted = {}
        self.disconnected = False
        self.fail_after_accept = False
        self.calls = 0

    async def deliver(self, delivery_id, frame):
        assert self.store._depth == 0
        self.calls += 1
        if self.disconnected:
            raise ConnectionError("Local display disconnected")
        self.accepted.setdefault(delivery_id, frame)
        if self.fail_after_accept:
            self.fail_after_accept = False
            raise ConnectionError("Acknowledgement unavailable")
        return True


def build(path, *, max_events=10000):
    store = JournalStore(path, "test")
    events = PublicationEventJournal(store, max_events=max_events)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    sink = Sink(store)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit, sink=sink)
    return store, events, conversations, transcript, sink, delivery


def context(conversations):
    cid = conversations.create("Delivery")["conversation"]["id"]
    # Setup events are not the request under test, but are durably captured too.
    with conversations.store.transaction() as db:
        db.execute("DELETE FROM desktop_delivery_outbox")
    return RequestContext(cid, "request-one", 1, "owner")


@pytest.mark.asyncio
async def test_unguarded_candidates_never_become_reply_preview(tmp_path):
    store, events, conversations, transcript, sink, delivery = build(tmp_path / "journal.db")
    ctx = context(conversations)
    before = events.high
    with pytest.raises(PermissionError):
        await delivery.send_reply(ctx, "Candidate model text")
    await delivery.set_status("Candidate model text", task_start=True)
    await delivery.set_status(task_end=True)
    assert events.high == before
    assert transcript.list(ctx.conversation_id)["items"] == []
    assert sink.accepted == {}
    assert delivery.notifications.pending() == []
    store.close()


@pytest.mark.asyncio
async def test_capability_binds_service_request_generation_and_exact_text(tmp_path):
    store, events, conversations, transcript, sink, delivery = build(tmp_path / "journal.db")
    ctx = context(conversations)
    guarded = delivery.guarded_reply(ctx, "Guarded final")
    for wrong, text in [(ctx, "Changed"), (replace(ctx, generation=2), "Guarded final"),
                        (replace(ctx, request_id="other"), "Guarded final")]:
        with pytest.raises(PermissionError):
            await delivery.send_reply(wrong, text, guarded=guarded)
    other = DurableDelivery(store, events, transcript_commit=transcript.commit)
    with pytest.raises(PermissionError):
        await other.send_reply(ctx, "Guarded final", guarded=guarded)
    assert transcript.list(ctx.conversation_id)["items"] == []
    message = await delivery.send_reply(ctx, "Guarded final", guarded=guarded)
    assert message["role"] == "assistant"
    assert {row[0] for row in store.connection.execute(
        "SELECT request_id FROM desktop_delivery_outbox")} == {ctx.request_id}
    assert [frame["type"] for frame in sink.accepted.values()] == [
        "message.committed", "conversation.updated", "notification.intent"]
    assert delivery.notifications.pending()[0]["message_id"] == message["id"]
    assert await delivery.send_reply(ctx, "Guarded final", guarded=guarded) == message
    assert len(transcript.list(ctx.conversation_id)["items"]) == 1
    store.close()


@pytest.mark.asyncio
async def test_scrubbed_committed_reply_only_and_no_discord_length_rewrite(tmp_path):
    store, events, conversations, transcript, sink, delivery = build(tmp_path / "journal.db")
    ctx = context(conversations)
    text = "api_key=synthetic-credential\n" + "Guarded content\n" * 2000
    message = await delivery.send_reply(ctx, text, guarded=delivery.guarded_reply(ctx, text))
    assert "synthetic-credential" not in json.dumps(events.between("0"))
    assert len(message["text"]) > 8000
    assert message["text"].endswith("Guarded content\n")
    assert "synthetic-credential" not in delivery.notifications.pending()[0]["preview"]
    store.close()


@pytest.mark.asyncio
async def test_parent_rollback_cannot_send_message_or_notification(tmp_path):
    store, events, conversations, transcript, sink, delivery = build(tmp_path / "journal.db")
    ctx = context(conversations)
    before = events.high
    with pytest.raises(RuntimeError, match="Harmless rollback"):
        with store.transaction():
            await delivery.send_reply(ctx, "Guarded final",
                guarded=delivery.guarded_reply(ctx, "Guarded final"))
            assert sink.calls == 0
            raise RuntimeError("Harmless rollback")
    assert events.high == before
    assert delivery.notifications.pending() == []
    assert transcript.list(ctx.conversation_id)["items"] == []
    assert await delivery.drain() == 0
    assert sink.calls == 0
    store.close()


@pytest.mark.asyncio
async def test_nested_failure_rolls_back_reply_outbox_and_notification(tmp_path):
    store, events, conversations, transcript, sink, delivery = build(tmp_path / "journal.db")
    ctx = context(conversations)
    before = events.high
    original = delivery.notifications.intent

    def failure(**kwargs):
        original(**kwargs)
        raise JournalStorageError()

    delivery.notifications.intent = failure
    with pytest.raises(JournalStorageError):
        await delivery.send_reply(ctx, "Guarded final",
            guarded=delivery.guarded_reply(ctx, "Guarded final"))
    assert events.high == before
    assert transcript.list(ctx.conversation_id)["items"] == []
    assert sink.calls == 0
    count = store.connection.execute("SELECT COUNT(*) FROM desktop_delivery_outbox").fetchone()[0]
    assert count == 0
    assert delivery.notifications.pending() == []
    store.close()


@pytest.mark.asyncio
async def test_disconnect_restart_and_unknown_accept_repair_never_rerun(tmp_path):
    path = tmp_path / "journal.db"
    store, events, conversations, transcript, sink, delivery = build(path)
    ctx = context(conversations)
    sink.disconnected = True
    message = await delivery.send_reply(ctx, "Guarded final",
        guarded=delivery.guarded_reply(ctx, "Guarded final"))
    assert len(delivery.notifications.pending()) == 1
    assert len(transcript.list(ctx.conversation_id)["items"]) == 1
    store.close()
    store, events, conversations, transcript, sink, delivery = build(path)
    sink.fail_after_accept = True
    assert await delivery.drain() == 0
    assert len(sink.accepted) == 1
    assert await delivery.drain() == 3
    assert len(sink.accepted) == 3
    assert transcript.list(ctx.conversation_id)["items"][0] == message
    assert delivery.notifications.ack(f"reply:{message['id']}", "shown")["ok"]
    store.close()
    store, events, conversations, transcript, sink, delivery = build(path)
    assert await delivery.drain() == 0
    assert delivery.notifications.pending() == []
    assert delivery.notifications.ack(f"reply:{message['id']}", "shown")["ok"]
    assert not delivery.notifications.ack(f"reply:{message['id']}", "failed")["ok"]
    store.close()


@pytest.mark.asyncio
async def test_artifact_only_notice_and_no_fabricated_artifact_success(tmp_path):
    store, events, conversations, transcript, sink, delivery = build(tmp_path / "journal.db")
    ctx = context(conversations)
    destination = LocalDestination(ctx, delivery)
    with pytest.raises(RuntimeError, match="publication unavailable"):
        await destination.send("", files=[object()])
    assert transcript.list(ctx.conversation_id)["items"] == []
    descriptor = {"ref": "artifact-one", "name": "result.txt", "mime": "text/plain",
                  "size": 6, "kind": "file", "available": True}

    def publish(bound_context, files):
        assert bound_context == ctx
        events.append("artifact.published", {"kind": "artifact", "id": "artifact-one"}, descriptor)
        return [descriptor]

    delivery.artifact_converter = publish
    message = await destination.send("", files=[object()])
    assert message["role"] == "notice"
    assert message["artifacts"] == [descriptor]
    assert next(iter(sink.accepted.values()))["type"] == "artifact.published"
    assert delivery.notifications.pending() == []
    assert await delivery.send_reply(ctx, "", guarded=delivery.guarded_reply(ctx, "")) is None
    store.close()


@pytest.mark.asyncio
async def test_tool_unknown_settlement_is_retained_and_not_promoted(tmp_path):
    path = tmp_path / "journal.db"
    store, events, conversations, transcript, sink, delivery = build(path)
    ctx = context(conversations)
    start = delivery.tool_started(ctx, invocation_id="inv-one", tool="read_file",
        summary="api_key=synthetic-credential", target="local")
    settled = delivery.tool_settled(ctx, invocation_id="inv-one", outcome="unknown", duration_ms=12)
    assert settled["payload"]["outcome"] == "unknown"
    assert "synthetic-credential" not in start["payload"]["summary"]
    with pytest.raises(ValueError):
        delivery.tool_settled(ctx, invocation_id="inv-one", outcome="completed", duration_ms=12)
    store.close()
    store, events, conversations, transcript, sink, delivery = build(path)
    assert events.between(start["seq"])[0] == settled
    assert await delivery.drain() == 2
    assert [frame["type"] for frame in sink.accepted.values()] == ["tool.started", "tool.settled"]
    store.close()


def test_pending_notification_recovery_survives_retention_and_acks(tmp_path):
    path = tmp_path / "journal.db"
    store, events, conversations, transcript, sink, delivery = build(path, max_events=1)
    notifications = delivery.notifications
    intent = notifications.intent(conversation_id="conversation", message_id="message",
        category="reply", preview="Guarded final", dedupe_key="reply-one")
    notifications.intent(**intent)
    events.append("test.padding", {"kind": "test", "id": "padding"}, {})
    store.close()
    store, events, conversations, transcript, sink, delivery = build(path, max_events=1)
    assert delivery.notifications.recover() == 1
    assert events.between(int(events.high) - 1)[0]["payload"] == intent
    assert delivery.notifications.ack("reply-one", "suppressed")["ok"]
    assert delivery.notifications.recover() == 0
    assert not delivery.notifications.ack("missing", "shown")["ok"]
    response = delivery.notifications.handle("notifications.ack",
        {"dedupe_key": "reply-one", "outcome": "invalid"})
    assert response["error"]["code"] == "bad_request"
    store.close()


@pytest.mark.asyncio
async def test_outbox_capture_survives_zero_journal_retention(tmp_path):
    store, events, conversations, transcript, sink, delivery = build(
        tmp_path / "journal.db", max_events=0)
    ctx = context(conversations)
    sink.disconnected = True
    message = await delivery.send_reply(ctx, "Guarded final",
        guarded=delivery.guarded_reply(ctx, "Guarded final"))
    assert events.between("0") == []
    count = store.connection.execute("SELECT COUNT(*) FROM desktop_delivery_outbox").fetchone()[0]
    assert count == 3
    sink.disconnected = False
    assert await delivery.recover() == 4
    assert any(frame["type"] == "message.committed" for frame in sink.accepted.values())
    intents = [frame for frame in sink.accepted.values() if frame["type"] == "notification.intent"]
    assert {frame["payload"]["dedupe_key"] for frame in intents} == {f"reply:{message['id']}"}
    store.close()


@pytest.mark.asyncio
async def test_deletion_cleanup_rolls_back_and_prevents_recovery(tmp_path):
    path = tmp_path / "journal.db"
    store, events, conversations, transcript, sink, delivery = build(path)
    ctx = context(conversations)
    sink.disconnected = True
    await delivery.send_reply(ctx, "Guarded final",
        guarded=delivery.guarded_reply(ctx, "Guarded final"))
    with pytest.raises(RuntimeError):
        with store.transaction():
            delivery.delete_conversation(ctx.conversation_id)
            raise RuntimeError("Harmless rollback")
    assert len(delivery.notifications.pending()) == 1
    with store.transaction():
        delivery.delete_conversation(ctx.conversation_id)
        conversations.delete(ctx.conversation_id, conversations.get(ctx.conversation_id)["rev"])
    store.close()
    store, events, conversations, transcript, sink, delivery = build(path)
    assert await delivery.recover() == 1
    assert [frame["type"] for frame in sink.accepted.values()] == ["conversation.deleted"]
    assert delivery.notifications.pending() == []
    store.close()


@pytest.mark.asyncio
async def test_tool_event_identity_prevents_unknown_promotion(tmp_path):
    store, events, conversations, transcript, sink, delivery = build(tmp_path / "journal.db")
    ctx = context(conversations)
    first = delivery.tool_settled(ctx, invocation_id="inv-one", outcome="unknown", duration_ms=12)
    high = events.high
    repeat = delivery.tool_settled(ctx, invocation_id="inv-one", outcome="unknown", duration_ms=12)
    assert repeat == first
    assert events.high == high
    with pytest.raises(ValueError, match="identity conflict"):
        delivery.tool_settled(ctx, invocation_id="inv-one", outcome="success", duration_ms=12)
    assert events.high == high
    store.close()


@pytest.mark.asyncio
async def test_transport_file_snapshot_preserves_stream_and_origin(tmp_path):
    from types import SimpleNamespace

    store, events, conversations, transcript, sink, delivery = build(tmp_path / "journal.db")
    ctx = context(conversations)
    received = []

    class Artifacts:
        def publish(self, data, **kwargs):
            received.append((data, kwargs))
            return {"ref": "artifact-one", "name": kwargs["name"], "mime": kwargs["mime"],
                    "size": len(data), "kind": kwargs["kind"], "available": True}

    artifacts = Artifacts()
    artifacts.store = store
    delivery.artifact_converter = ArtifactPublisher(artifacts, events)
    stream = io.BytesIO(b"prefix\x00exact-producer-bytes")
    stream.seek(6)
    file = SimpleNamespace(fp=stream, filename="result.png", tool="generate_image", hosts=())
    message = await delivery.send(ctx, files=[file])
    assert stream.tell() == 6 and not stream.closed
    assert received[0][0] == b"\x00exact-producer-bytes"
    assert received[0][1]["owner"] == ctx.owner_id
    assert received[0][1]["tool"] == "generate_image"
    assert message["artifacts"][0]["mime"] == "image/png"
    assert message["artifacts"][0]["kind"] == "image"
    store.close()


def test_artifact_post_type_and_no_path_reopen(tmp_path):
    from types import SimpleNamespace

    store, events, conversations, transcript, sink, delivery = build(tmp_path / "journal.db")
    ctx = context(conversations)
    artifacts = SimpleNamespace(store=store)
    publisher = ArtifactPublisher(artifacts, events)
    with pytest.raises(TypeError):
        publisher(ctx, [SimpleNamespace(filename="not-a-stream", path="unused")])
    assert ArtifactPost(b"exact", "result.txt", "text/plain").data == b"exact"
    store.close()


@pytest.mark.asyncio
async def test_actual_outbox_write_failure_rolls_back_all_publication(tmp_path):
    store, events, conversations, transcript, sink, delivery = build(tmp_path / "journal.db")
    ctx = context(conversations)
    before = events.high
    with store.transaction() as db:
        db.execute("""CREATE TEMP TRIGGER fail_outbox BEFORE INSERT
            ON desktop_delivery_outbox BEGIN SELECT RAISE(ABORT,'Harmless test failure'); END""")
    with pytest.raises(JournalStorageError):
        await delivery.send_reply(ctx, "Guarded final",
            guarded=delivery.guarded_reply(ctx, "Guarded final"))
    assert events.high == before
    assert transcript.list(ctx.conversation_id)["items"] == []
    assert delivery.notifications.pending() == []
    assert sink.calls == 0
    with store.transaction() as db:
        db.execute("DROP TRIGGER fail_outbox")
    message = await delivery.send_reply(ctx, "Guarded final",
        guarded=delivery.guarded_reply(ctx, "Guarded final"))
    assert message["text"] == "Guarded final"
    assert len(sink.accepted) == 3
    store.close()


@pytest.mark.asyncio
async def test_worker_events_captured_before_retention_and_survive_restart(tmp_path):
    path = tmp_path / "journal.db"
    store, events, conversations, transcript, sink, delivery = build(path, max_events=0)
    ctx = context(conversations)
    with store.transaction():
        events.append("request.started", {"kind": "request", "id": ctx.request_id},
            {"conversation_id": ctx.conversation_id, "request_id": ctx.request_id,
             "generation": ctx.generation})
    assert events.between("0") == []
    with pytest.raises(RuntimeError):
        with store.transaction():
            events.append("request.completed", {"kind": "request", "id": ctx.request_id},
                {"conversation_id": ctx.conversation_id, "request_id": ctx.request_id})
            raise RuntimeError("Harmless rollback")
    store.close()
    store, events, conversations, transcript, sink, delivery = build(path, max_events=0)
    assert await delivery.drain() == 1
    assert [frame["type"] for frame in sink.accepted.values()] == ["request.started"]
    store.close()
