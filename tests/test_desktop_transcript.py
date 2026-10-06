import pytest

from src.desktop.commands import JournalStorageError, JournalStore
from src.desktop.conversations import ConversationError, ConversationStore
from src.desktop.events import EventJournal
from src.desktop.transcript import TranscriptStore


@pytest.fixture
def graph(tmp_path):
    store = JournalStore(tmp_path / "journal.sqlite3", "test-profile")
    events = EventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    cid = conversations.create()["conversation"]["id"]
    yield store, events, conversations, transcript, cid
    store.close()


def test_paging_snapshot_then_tail_watermark(graph):
    _, events, _, transcript, cid = graph
    messages = [transcript.commit(cid, "user", str(i)) for i in range(6)]
    snapshot = transcript.snapshot(cid, 2)
    assert [item["text"] for item in snapshot["messages"]["items"]] == ["4", "5"]
    assert snapshot["messages"]["has_more"]
    page = transcript.list(cid, before=messages[4]["id"], limit=2)
    assert [item["text"] for item in page["items"]] == ["2", "3"]
    older = transcript.list(cid, before=messages[2]["id"], limit=2)
    assert [item["text"] for item in older["items"]] == ["0", "1"]
    assert not older["has_more"]
    committed = transcript.commit(cid, "assistant", "Tail")
    reset, high, tail = events.catchup(snapshot["watermark"])
    assert not reset and high == events.high
    assert tail[0]["payload"]["message"] == committed
    assert len(snapshot["messages"]["items"]) == 2
    assert tail[0]["seq"] > int(snapshot["watermark"])


def test_snapshot_complete_unresolved_controls_tool_scope_activity(graph):
    store, events, conversations, transcript, cid = graph
    transcript.commit(cid, "user", "Shown", request_id="shown")
    outcomes = [{"request_id": str(i), "generation": 1, "outcome": "interrupted",
                 "unknown_effects": 1, "at": "2026-10-05T00:00:00Z"} for i in range(30)]
    state = {"running": {"request_id": "run", "generation": 2, "started_at": "now"},
             "queued": [{"request_id": "queue", "generation": 1, "message_id": "m"}],
             "recent": list(outcomes), "unresolved": list(outcomes),
             "tools": {name: [{"invocation_id": name, "tool": "check", "summary": "Done"}]
                       for name in ("shown", "run", "queue", "old")},
             "controls": [{"control_command_id": name, "kind": "stop", "request_id": name,
                           "generation": 1, "disposition": "requested"}
                          for name in ("run", "queue", "old")]}
    def provider(id):
        assert id == cid and store._depth > 0
        return state
    conversations.state_provider = provider
    snapshot = transcript.snapshot(cid)
    assert snapshot["watermark"] == events.high
    assert len(snapshot["recent"]) == 20 and len(snapshot["unresolved"]) == 30
    assert set(snapshot["tools"]) == {"shown", "run"}
    assert {item["request_id"] for item in snapshot["controls"]} == {"run", "queue"}
    assert conversations.list()["items"][0]["activity"] == {
        "running": {"request_id": "run", "generation": 2},
        "queued": [{"request_id": "queue", "generation": 1}]}
    state["recent"].append({"request_id": "success", "generation": 1,
                           "outcome": "completed", "unknown_effects": 0, "at": "later"})
    assert len(transcript.snapshot(cid)["unresolved"]) == 30
    snapshot["unresolved"][0]["request_id"] = "tampered"
    assert transcript.snapshot(cid)["unresolved"][0]["request_id"] == "0"


def test_transcript_independent_of_context_and_persists_restart(graph, tmp_path):
    store, _, conversations, transcript, cid = graph
    first = transcript.commit(cid, "assistant", "Visible", request_id="request",
                              artifacts=[{"ref": "artifact", "name": "result.txt",
                                          "available": True}])
    conversations.reset_context(cid, conversations.get(cid)["rev"])
    assert transcript.model_context(cid) == []
    store.close()
    reopened = JournalStore(tmp_path / "journal.sqlite3", "test-profile")
    try:
        events = EventJournal(reopened)
        conv = ConversationStore(reopened, events)
        restored = TranscriptStore(reopened, events, conv)
        assert restored.list(cid)["items"][0] == first
        assert restored.model_context(cid) == []
        assert restored.snapshot(cid)["conversation"]["unread"] == 1
    finally:
        reopened.close()


def test_delivery_idempotence_and_conflict(graph):
    _, events, _, transcript, cid = graph
    metadata = {"id": "fixed", "created_at": "2026-10-05T00:00:00Z"}
    message = transcript.commit(cid, "assistant", "Original", **metadata)
    high = events.high
    assert transcript.commit(cid, "assistant", "Original", **metadata) == message
    assert events.high == high
    with pytest.raises(ConversationError) as caught:
        transcript.commit(cid, "assistant", "Conflict", **metadata)
    assert caught.value.code == "id_conflict"
    assert transcript.list(cid)["items"] == [message]


def test_execution_lineage_survives_reload_repeat_resets_and_cascades_delete(graph, tmp_path):
    store, _, conversations, transcript, cid = graph
    transcript.commit(cid, "user", "original", request_id="preserved")
    with store.transaction() as db:
        db.execute("INSERT INTO desktop_request_context VALUES ('preserved',?,0)", (cid,))
    conversations.reset_context(cid, conversations.get(cid)["rev"])
    first_epoch = conversations._row(cid)["context_position"]
    transcript.commit(cid, "user", "between", request_id="between")
    with store.transaction() as db:
        db.execute("INSERT INTO desktop_request_context VALUES ('between',?,?)", (cid, first_epoch))
    conversations.reset_context(cid, conversations.get(cid)["rev"])
    old_output = transcript.commit(cid, "assistant", "resumed late", request_id="preserved")
    transcript.commit(cid, "assistant", "between late", request_id="between")
    transcript.commit(cid, "user", "fresh")
    assert [item["text"] for item in transcript.model_context(cid)] == ["fresh"]
    # A historical child at the late-output anchor uses the reset at that
    # anchor, not the lineage of the output it happens to be anchored to.
    child = conversations.create(parent_id=cid, from_message_id=old_output["id"])
    assert transcript.model_context(child["conversation"]["id"]) == []
    store.close()
    reopened = JournalStore(tmp_path / "journal.sqlite3", "test-profile")
    try:
        events = EventJournal(reopened)
        restored_conversations = ConversationStore(reopened, events)
        restored = TranscriptStore(reopened, events, restored_conversations)
        assert [item["text"] for item in restored.model_context(cid)] == ["fresh"]
        assert "resumed late" in str(restored.list(cid))
        restored_conversations.delete(cid, restored_conversations.get(cid)["rev"])
        assert reopened.connection.execute(
            "SELECT COUNT(*) FROM desktop_request_context WHERE conversation_id=?", (cid,)
        ).fetchone()[0] == 0
    finally:
        reopened.close()


def test_failed_message_event_rolls_back_transcript_and_revision(graph, monkeypatch):
    _, events, conversations, transcript, cid = graph
    original, high = conversations.get(cid), events.high
    def unavailable(*args, **kwargs):
        raise JournalStorageError()
    monkeypatch.setattr(events, "append", unavailable)
    with pytest.raises(JournalStorageError):
        transcript.commit(cid, "assistant", "Not committed")
    assert transcript.list(cid)["items"] == []
    assert conversations.get(cid) == original and events.high == high


@pytest.mark.parametrize("limit", [0, 101, True, "10", None])
def test_invalid_limits_are_rejected(graph, limit):
    _, _, _, transcript, cid = graph
    with pytest.raises(ConversationError) as caught:
        transcript.snapshot(cid, limit)
    assert caught.value.code == "bad_request"


def test_foreign_paging_cutoff_is_not_silently_latest_page(graph):
    _, _, conversations, transcript, cid = graph
    other = conversations.create()["conversation"]["id"]
    foreign = transcript.commit(other, "user", "Foreign")
    with pytest.raises(ConversationError, match="Message not found"):
        transcript.list(cid, before=foreign["id"])


def test_delivery_reuses_original_timestamp_when_not_supplied(graph):
    _, events, _, transcript, cid = graph
    original = transcript.commit(cid, "assistant", "Original", id="stable")
    high = events.high
    assert transcript.commit(cid, "assistant", "Original", id="stable") == original
    assert events.high == high


def test_snapshot_blocks_concurrent_writer_until_watermark(graph, tmp_path):
    import sqlite3
    _, _, conversations, transcript, cid = graph
    message = transcript.commit(cid, "user", "Before snapshot")
    def provider(id):
        writer = sqlite3.connect(tmp_path / "journal.sqlite3", timeout=0, isolation_level=None)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                writer.execute("BEGIN IMMEDIATE")
        finally:
            writer.close()
        return {"running": None, "queued": [], "recent": [], "unresolved": [],
                "tools": {}, "controls": []}
    conversations.state_provider = provider
    snapshot = transcript.snapshot(cid)
    assert snapshot["messages"]["items"] == [message]


@pytest.mark.parametrize("metadata", [{"request_id": []}, {"attachments": "not-list"},
                                       {"artifacts": ["not-object"]}, {"context_reset": True}])
def test_invalid_committed_metadata_rejected_without_change(graph, metadata):
    _, events, conversations, transcript, cid = graph
    before, high = conversations.get(cid), events.high
    with pytest.raises(ConversationError):
        transcript.commit(cid, "user", "Invalid", **metadata)
    assert conversations.get(cid) == before and events.high == high
