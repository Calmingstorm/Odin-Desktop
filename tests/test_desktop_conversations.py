from uuid import uuid4

import pytest

from src.desktop.commands import CommandJournal, JournalStorageError, JournalStore
from src.desktop.conversations import ConversationError, ConversationStore
from src.desktop.events import EventJournal
from src.desktop.transcript import TranscriptStore


@pytest.fixture
def graph(tmp_path):
    store = JournalStore(tmp_path / "journal.sqlite3", "test-profile")
    events = EventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    yield store, events, conversations, transcript
    store.close()


def command(graph, method, params, command_id=None):
    store, _, conversations, _ = graph
    def execute():
        try:
            return {"ok": True, "result": conversations.handle(method, params)}
        except ConversationError as error:
            return error.response()
    return CommandJournal(store).execute(command_id or str(uuid4()), method, params, execute)


def test_two_conversations_revisioned_update_and_durable_replay(graph):
    _, events, conversations, _ = graph
    id = str(uuid4())
    result = command(graph, "conversations.create", {"title": "First"}, id)
    first = result["result"]["conversation"]
    assert command(graph, "conversations.create", {"title": "First"}, id) == result
    assert len(events.between("0")) == 1
    second = conversations.create("Second")["conversation"]
    assert {item["id"] for item in conversations.list()["items"]} == {first["id"], second["id"]}
    update = conversations.update(
        first["id"], first["rev"], title="Changed", archived=True)["conversation"]
    assert update["rev"] == 2 and update["archived"]
    stale_id = str(uuid4())
    params = {"id": first["id"], "expected_rev": 1, "title": "Bad"}
    stale = command(graph, "conversations.update", params, stale_id)
    assert stale["error"]["code"] == "stale_binding"
    assert command(graph, "conversations.update", params, stale_id) == stale
    assert conversations.get(first["id"])["title"] == "Changed"


def test_child_cutoff_immutable_labeled_context_survives_parent_delete(graph):
    _, _, conversations, transcript = graph
    parent = conversations.create("Original")["conversation"]["id"]
    first = transcript.commit(parent, "user", "First", request_id="r1")
    transcript.commit(parent, "assistant", "Second", request_id="r1")
    child = conversations.create("Child", parent, first["id"])["conversation"]
    assert child["inherited_from"] == {
        "conversation_id": parent, "message_id": first["id"], "title": "Original"}
    inherited = transcript.model_context(child["id"])
    assert [item["text"] for item in inherited] == ["First"]
    assert inherited[0]["inherited_from"]["conversation_id"] == parent
    assert "request_id" not in inherited[0]
    assert transcript.list(child["id"])["items"] == []
    inherited[0]["text"] = "Mutation"
    transcript.commit(parent, "assistant", "Later")
    conversations.update(parent, conversations.get(parent)["rev"], title="Renamed")
    conversations.delete(parent, conversations.get(parent)["rev"])
    assert transcript.model_context(child["id"])[0]["text"] == "First"
    assert conversations.get(child["id"])["inherited_from"]["title"] == "Original"


def test_reset_context_visible_notice_and_child_reset(graph):
    _, events, conversations, transcript = graph
    parent = conversations.create()["conversation"]["id"]
    transcript.commit(parent, "user", "Before")
    child = conversations.create(parent_id=parent)["conversation"]["id"]
    revision = conversations.get(child)["rev"]
    reset = conversations.reset_context(child, revision)["conversation"]
    assert reset["rev"] == revision + 1
    assert transcript.model_context(child) == []
    assert transcript.list(child)["items"][0]["role"] == "notice"
    transcript.commit(child, "user", "After")
    assert [item["text"] for item in transcript.model_context(child)] == ["After"]
    assert events.between("0")[-1]["type"] == "conversation.updated"


@pytest.mark.parametrize("busy_key", ["running", "queued"])
@pytest.mark.parametrize("method", ["conversations.delete", "conversations.reset_context"])
def test_busy_final_refusal_not_retargeted_after_work_clears(graph, busy_key, method):
    _, events, conversations, transcript = graph
    cid = conversations.create()["conversation"]["id"]
    transcript.commit(cid, "user", "Retained")
    state = {"running": None, "queued": [], "recent": [], "unresolved": [],
             "tools": {}, "controls": []}
    state[busy_key] = ({"request_id": "r", "generation": 1}
                       if busy_key == "running" else [{"request_id": "r"}])
    conversations.state_provider = lambda _: state
    params = {"id": cid, "expected_rev": conversations.get(cid)["rev"]}
    high, command_id = events.high, str(uuid4())
    refusal = command(graph, method, params, command_id)
    assert refusal["error"]["code"] == "busy"
    assert refusal["error"]["disposition"] == "not_dispatched"
    assert events.high == high
    state[busy_key] = None if busy_key == "running" else []
    assert command(graph, method, params, command_id) == refusal
    assert command(graph, method, params)["ok"]


def test_unread_watermark_monotonic_and_foreign_message_refused(graph):
    _, _, conversations, transcript = graph
    cid = conversations.create()["conversation"]["id"]
    first = transcript.commit(cid, "assistant", "First")
    transcript.commit(cid, "user", "Mine")
    latest = transcript.commit(cid, "assistant", "Latest")
    assert conversations.get(cid)["unread"] == 2
    assert conversations.mark_read(cid, first["id"])["conversation"]["unread"] == 1
    assert conversations.mark_read(cid, latest["id"])["conversation"]["unread"] == 0
    assert conversations.mark_read(cid, first["id"])["conversation"]["unread"] == 0
    other = conversations.create()["conversation"]["id"]
    foreign = transcript.commit(other, "assistant", "Foreign")
    with pytest.raises(ConversationError, match="Message not found"):
        conversations.mark_read(cid, foreign["id"])
    assert conversations.get(cid)["unread"] == 0


def test_delete_preserves_command_identity(graph):
    store, _, conversations, transcript = graph
    creation_id = str(uuid4())
    created = command(graph, "conversations.create", {}, creation_id)
    cid = created["result"]["conversation"]["id"]
    transcript.commit(cid, "user", "Visible")
    conversations.delete(cid, conversations.get(cid)["rev"])
    assert transcript.all_messages() == []
    assert command(graph, "conversations.create", {}, creation_id) == created
    assert store.connection.execute("SELECT COUNT(*) FROM desktop_conversations").fetchone()[0] == 0


def test_delete_unknown_terminal_is_not_extra_admission_restriction(graph):
    _, _, conversations, transcript = graph
    cid = conversations.create()["conversation"]["id"]
    transcript.commit(cid, "user", "Retained")
    tombstones = [{"request_id": "unknown", "unknown_effects": 1}]
    conversations.state_provider = lambda _: {
        "running": None, "queued": [], "recent": [], "unresolved": tombstones,
        "tools": {}, "controls": []}
    called = []
    conversations.delete_hooks = (lambda id: called.append(id),)
    assert conversations.delete(cid, conversations.get(cid)["rev"]) == {"disposition": "deleted"}
    assert called == [cid] and tombstones[0]["unknown_effects"] == 1


def test_branch_before_later_reset_uses_context_at_cutoff(graph):
    _, _, conversations, transcript = graph
    cid = conversations.create()["conversation"]["id"]
    old = transcript.commit(cid, "user", "Old context")
    conversations.reset_context(cid, conversations.get(cid)["rev"])
    new = transcript.commit(cid, "user", "New context")
    old_child = conversations.create(parent_id=cid, from_message_id=old["id"])["conversation"]["id"]
    new_child = conversations.create(parent_id=cid, from_message_id=new["id"])["conversation"]["id"]
    assert [item["text"] for item in transcript.model_context(old_child)] == ["Old context"]
    assert [item["text"] for item in transcript.model_context(new_child)] == ["New context"]


def test_child_inheritance_reopens_without_parent_and_keeps_metadata(graph, tmp_path):
    store, _, conversations, transcript = graph
    parent = conversations.create("Parent")["conversation"]["id"]
    original = transcript.commit(
        parent, "assistant", "Result", artifacts=[{"ref": "ref", "name": "file.txt"}])
    child = conversations.create(parent_id=parent)["conversation"]
    assert child["inherited_from"]["message_id"] == original["id"]
    conversations.delete(parent, conversations.get(parent)["rev"])
    store.close()
    reopened = JournalStore(tmp_path / "journal.sqlite3", "test-profile")
    try:
        events = EventJournal(reopened)
        restored_conversations = ConversationStore(reopened, events)
        restored = TranscriptStore(reopened, events, restored_conversations)
        context = restored.model_context(child["id"])
        assert context[0]["artifacts"] == original["artifacts"]
        assert restored_conversations.get(child["id"])["inherited_from"] == child["inherited_from"]
        assert restored.list(child["id"])["items"] == []
    finally:
        reopened.close()


def test_mark_read_updates_revision_and_reset_stale_has_no_notice(graph):
    _, events, conversations, transcript = graph
    cid = conversations.create()["conversation"]["id"]
    message = transcript.commit(cid, "assistant", "Unread")
    before = conversations.get(cid)
    read = conversations.mark_read(cid, message["id"])["conversation"]
    assert read["rev"] == before["rev"] + 1
    watermark = events.high
    stale = command(graph, "conversations.reset_context",
                    {"id": cid, "expected_rev": before["rev"]})
    assert stale["error"]["code"] == "stale_binding"
    assert events.high == watermark and transcript.list(cid)["items"] == [message]


def test_atomic_event_failure_rolls_back_domain_and_receipt(graph, monkeypatch):
    store, events, conversations, _ = graph
    def unavailable(*args, **kwargs):
        raise JournalStorageError()
    monkeypatch.setattr(events, "append", unavailable)
    result = command(graph, "conversations.create", {"title": "Lost"}, "failed-create")
    assert result["error"]["code"] == "storage_unavailable"
    assert conversations.list()["items"] == []
    receipt = store.connection.execute(
        "SELECT state FROM command_receipts WHERE command_id='failed-create'").fetchone()
    assert receipt[0] == "pending"


@pytest.mark.parametrize("method,params", [
    ("conversations.create", {"title": 12}),
    ("conversations.create", {"from_message_id": "foreign"}),
    ("conversations.update", {"id": "x", "expected_rev": True}),
    ("conversations.delete", {}),
])
def test_validation_refusals_are_durable(graph, method, params):
    identity = str(uuid4())
    result = command(graph, method, params, identity)
    assert result["error"]["code"] == "bad_request"
    assert command(graph, method, params, identity) == result
