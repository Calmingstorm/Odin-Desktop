"""Real scoped upload/admission behaviour, disposable profile journals only."""
from __future__ import annotations

import base64
import hashlib
import sqlite3
import time
from dataclasses import dataclass

import pytest

from src.desktop.attachments import AttachmentError, AttachmentService
from src.desktop.commands import CommandJournal, JournalStorageError, JournalStore
from src.desktop.events import EventJournal


@dataclass
class Clock:
    now: float = 1000

    def __call__(self):
        return self.now


def require_conversation(connection, conversation_id):
    if conversation_id not in {"conversation-a", "conversation-b"}:
        raise AttachmentError("not_found", "Conversation is unavailable")
    assert connection.in_transaction


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    store = JournalStore(tmp_path / "journal.sqlite3", "profile-a", identity="owner-a")
    service = AttachmentService(store, require_conversation, clock=clock,
                                chunk_bytes=8, attachment_bytes=64, ttl_seconds=60)
    yield store, service, clock
    store.close()


def begin(service, data=b"hello", **overrides):
    params = {"client_attachment_id": "client-a", "conversation_id": "conversation-a",
              "name": "notes.txt", "mime": "text/plain", "size": len(data), **overrides}
    result = service.handle("attachments.begin", params)
    assert result["ok"], result
    return result["result"]["upload_id"], params


def chunk(service, upload_id, data, offset=0):
    return service.handle("attachments.chunk", {"upload_id": upload_id, "offset": offset,
                          "data_b64": base64.b64encode(data).decode()})


def commit(service, upload_id, data):
    return service.handle("attachments.commit", {"upload_id": upload_id,
                          "sha256": hashlib.sha256(data).hexdigest()})


def upload(service, data=b"hello", **overrides):
    upload_id, _ = begin(service, data, **overrides)
    for offset in range(0, len(data), service.chunk_bytes):
        assert chunk(service, upload_id, data[offset:offset + service.chunk_bytes], offset)["ok"]
    result = commit(service, upload_id, data)
    assert result["ok"], result
    return result["result"]["attachment"], upload_id


def error(result, code):
    assert result["ok"] is False, result
    assert result["error"]["code"] == code, result


def adopt(store, service, items, request="request-a", message="message-a", cid="conversation-a"):
    with store.transaction() as connection:
        return service.adopt_for_submission(connection, cid, request, message, items)


def test_empty_file_and_idempotent_begin_commit(env):
    store, service, _ = env
    upload_id, params = begin(service, b"")
    assert service.handle("attachments.begin", params)["result"]["upload_id"] == upload_id
    result = commit(service, upload_id, b"")
    assert result["ok"]
    assert commit(service, upload_id, b"") == result
    metadata = result["result"]["attachment"]
    assert set(metadata) == {"ref", "name", "mime", "size"}
    assert metadata["size"] == 0
    assert metadata["ref"].startswith("a_")
    assert store.connection.execute("SELECT count(*) FROM desktop_uploads").fetchone()[0] == 1


def test_offset_retries_not_command_receipts(env):
    store, service, _ = env
    upload_id, _ = begin(service, b"abcdefghijk")
    assert chunk(service, upload_id, b"abcdefgh") == {"ok": True, "result": {"received": 8}}
    assert chunk(service, upload_id, b"def", 3)["result"]["received"] == 8
    assert chunk(service, upload_id, b"ijk", 8)["result"]["received"] == 11
    assert chunk(service, upload_id, b"fghij", 5)["result"]["received"] == 11
    assert chunk(service, upload_id, b"", 11)["result"]["received"] == 11
    assert store.connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0] == 0
    assert store.connection.execute("SELECT count(*) FROM desktop_upload_chunks").fetchone()[0] == 2
    assert commit(service, upload_id, b"abcdefghijk")["ok"]


@pytest.mark.parametrize("offset,data,code", [
    (4, b"x", "bad_request"), (1, b"XX", "bad_request"), (2, b"cdef", "bad_request"),
    (0, b"123456789", "too_large"), (-1, b"x", "bad_request"),
    (True, b"x", "bad_request"), (10, b"x", "too_large"),
])
def test_chunk_failure_changes_nothing(env, offset, data, code):
    store, service, _ = env
    upload_id, _ = begin(service, b"abcdefghij")
    assert chunk(service, upload_id, b"abc")["ok"]
    error(chunk(service, upload_id, data, offset), code)
    assert store.connection.execute("SELECT received FROM desktop_uploads").fetchone()[0] == 3
    saved = store.connection.execute("SELECT data FROM desktop_upload_chunks").fetchone()[0]
    assert saved == b"abc"


@pytest.mark.parametrize("encoded", [None, 3, "%%%", "é", "x" * 13])
def test_invalid_base64_and_encoded_bound(env, encoded):
    _, service, _ = env
    upload_id, _ = begin(service)
    result = service.handle("attachments.chunk", {"upload_id": upload_id, "offset": 0,
                           "data_b64": encoded})
    error(result, "too_large" if encoded == "x" * 13 else "bad_request")
    assert chunk(service, upload_id, b"hello")["ok"]


@pytest.mark.parametrize("override,code", [
    ({"size": -1}, "bad_request"), ({"size": True}, "bad_request"),
    ({"size": 65}, "too_large"), ({"name": None}, "bad_request"),
    ({"mime": 3}, "bad_request"), ({"conversation_id": "absent"}, "not_found"),
    ({"client_attachment_id": ""}, "bad_request"), ({"name": "\ud800"}, "bad_request"),
])
def test_begin_refuses_before_bytes(env, override, code):
    store, service, _ = env
    params = {"client_attachment_id": "client-a", "conversation_id": "conversation-a",
              "name": "file.txt", "mime": "text/plain", "size": 5, **override}
    error(service.handle("attachments.begin", params), code)
    assert store.connection.execute("SELECT count(*) FROM desktop_uploads").fetchone()[0] == 0
    assert store.connection.execute("SELECT count(*) FROM desktop_upload_chunks").fetchone()[0] == 0


def test_identity_binds_all_semantic_fields(env):
    _, service, _ = env
    upload_id, params = begin(service)
    for key, value in {"conversation_id": "conversation-b", "name": "other",
                       "mime": "image/png", "size": 4}.items():
        error(service.handle("attachments.begin", {**params, key: value}), "id_conflict")
    assert service.handle("attachments.begin", params)["result"]["upload_id"] == upload_id


@pytest.mark.parametrize("incomplete", [False, True])
def test_bad_digest_or_size_destroys_bytes_durably(env, incomplete):
    store, service, _ = env
    journal = CommandJournal(store)
    upload_id, params = begin(service, b"hello")
    assert chunk(service, upload_id, b"hell" if incomplete else b"hello")["ok"]
    wrong = {"upload_id": upload_id, "sha256": hashlib.sha256(b"other").hexdigest()}
    result = journal.execute("commit-a", "attachments.commit", wrong,
                             lambda: service.handle("attachments.commit", wrong))
    error(result, "bad_request")
    assert journal.check("commit-a", "attachments.commit", wrong) == result
    assert store.connection.execute("SELECT count(*) FROM desktop_upload_chunks").fetchone()[0] == 0
    error(commit(service, upload_id, b"hello"), "expired")
    error(service.handle("attachments.begin", params), "expired")


def test_cancel_idempotent_removes_unadopted_bytes(env):
    store, service, _ = env
    _, upload_id = upload(service)
    params = {"upload_id": upload_id}
    expected = {"ok": True, "result": {"disposition": "cancelled"}}
    assert service.handle("attachments.cancel", params) == expected
    assert service.handle("attachments.cancel", params) == expected
    assert service.handle("attachments.cancel", {"upload_id": "absent"}) == expected
    assert store.connection.execute("SELECT count(*) FROM desktop_upload_chunks").fetchone()[0] == 0
    error(chunk(service, upload_id, b"hello"), "expired")


@pytest.mark.parametrize("digest", [None, 123, "", "invalid", "0" * 63])
def test_malformed_digest_keeps_nothing(env, digest):
    store, service, _ = env
    upload_id, _ = begin(service)
    assert chunk(service, upload_id, b"hello")["ok"]
    error(service.handle("attachments.commit", {"upload_id": upload_id, "sha256": digest}),
          "bad_request")
    assert store.connection.execute("SELECT count(*) FROM desktop_upload_chunks").fetchone()[0] == 0
    error(commit(service, upload_id, b"hello"), "expired")


def test_committed_digest_conflict_does_not_destroy_admitted_content(env):
    store, service, _ = env
    attachment, upload_id = upload(service)
    adopt(store, service, [{"ref": attachment["ref"]}])
    error(commit(service, upload_id, b"other"), "id_conflict")
    error(service.handle("attachments.commit", {"upload_id": upload_id, "sha256": "invalid"}),
          "bad_request")
    assert len(service.streams_for_request("conversation-a", "request-a")) == 1


def test_committed_upload_cannot_take_more_chunks(env):
    _, service, _ = env
    _, upload_id = upload(service)
    error(chunk(service, upload_id, b"hello"), "bad_request")


def test_unknown_or_malformed_method_and_upload_are_typed_refusals(env):
    _, service, _ = env
    error(service.handle("attachments.missing", {}), "bad_request")
    error(service.handle("attachments.begin", []), "bad_request")
    error(service.handle("attachments.chunk", {"upload_id": "missing"}), "expired")
    error(service.handle("attachments.commit", {"upload_id": "missing"}), "expired")
    error(service.handle("attachments.cancel", {"upload_id": None}), "bad_request")


def test_expiry_keeps_adopted_refs_and_identity_tombstones(env):
    store, service, clock = env
    attachment, adopted_id = upload(service)
    adopt(store, service, [{"ref": attachment["ref"]}])
    _, other_params = begin(service, b"hi", client_attachment_id="client-b")
    unadopted, unadopted_id = upload(service, b"xx", client_attachment_id="client-c")
    clock.now += 60
    assert service.expire() == 2
    assert service.expire() == 0
    assert len(service.streams_for_request("conversation-a", "request-a")) == 1
    error(service.handle("attachments.begin", other_params), "expired")
    error(commit(service, unadopted_id, b"xx"), "expired")
    assert commit(service, adopted_id, b"hello")["ok"]
    with pytest.raises(AttachmentError, match="no longer"):
        adopt(store, service, [{"ref": unadopted["ref"]}])


def test_lazy_expiry_deletes_bytes(env):
    store, service, clock = env
    upload_id, _ = begin(service)
    assert chunk(service, upload_id, b"hello")["ok"]
    clock.now += 61
    error(commit(service, upload_id, b"hello"), "expired")
    assert store.connection.execute("SELECT count(*) FROM desktop_upload_chunks").fetchone()[0] == 0


def test_foreign_conversation_and_profile_refs_are_unavailable(env, tmp_path):
    store, service, _ = env
    attachment, _ = upload(service)
    with pytest.raises(AttachmentError) as exc:
        adopt(store, service, [{"ref": attachment["ref"]}], cid="conversation-b")
    assert exc.value.code == "not_found"
    other = JournalStore(tmp_path / "other.sqlite3", "profile-b", identity="owner-b")
    try:
        foreign = AttachmentService(other, require_conversation)
        with pytest.raises(AttachmentError) as exc:
            adopt(other, foreign, [{"ref": attachment["ref"]}])
        assert exc.value.code == "not_found"
        assert foreign.streams_for_request("conversation-a", "request-a") == []
    finally:
        other.close()
    assert service.streams_for_request("conversation-b", "request-a") == []


@pytest.mark.parametrize("items,code", [
    (None, "bad_request"), (["a"], "bad_request"),
    ([{"ref": "unknown", "add_to_knowledge": True}], "not_found"),
    ([{"ref": "unknown", "add_to_knowledge": 1}], "bad_request"),
    ([{"ref": "unknown"}] * 11, "too_large"),
])
def test_typed_adoption_refusals_leave_no_records(env, items, code):
    store, service, _ = env
    with pytest.raises(AttachmentError) as exc:
        adopt(store, service, items)
    assert exc.value.code == code
    count = store.connection.execute(
        "SELECT count(*) FROM desktop_attachment_adoptions").fetchone()[0]
    assert count == 0


def test_adoption_verifies_batch_before_mutating(env):
    store, service, _ = env
    attachment, _ = upload(service)
    with pytest.raises(AttachmentError):
        adopt(store, service, [{"ref": attachment["ref"]}, {"ref": "missing"}])
    count = store.connection.execute(
        "SELECT count(*) FROM desktop_attachment_adoptions").fetchone()[0]
    assert count == 0
    with pytest.raises(AttachmentError, match="Duplicate"):
        adopt(store, service, [{"ref": attachment["ref"]}] * 2)


def test_receipt_event_and_adoption_are_atomic(env):
    store, service, _ = env
    attachment, _ = upload(service)
    journal, events = CommandJournal(store), EventJournal(store)
    params = {"attachments": [{"ref": attachment["ref"]}]}

    def admit():
        public = service.adopt_for_submission(store.connection, "conversation-a", "request-a",
                                               "message-a", params["attachments"])
        events.append("message.committed", {"kind": "message", "id": "message-a"},
                      {"text": "", "attachments": public})
        return {"ok": True, "result": {"disposition": "accepted", "request_id": "request-a",
                                       "message_id": "message-a"}}

    result = journal.execute("submit-a", "submission.send", params, admit)
    assert result["ok"]
    assert journal.execute("submit-a", "submission.send", params, admit) == result
    assert events.high == "1"
    assert events.between(0)[0]["payload"]["attachments"] == [attachment]
    count = store.connection.execute(
        "SELECT count(*) FROM desktop_attachment_adoptions").fetchone()[0]
    assert count == 1


def test_post_adoption_harmless_failure_rolls_back_everything(env):
    store, service, _ = env
    attachment, _ = upload(service)
    events = EventJournal(store)
    with pytest.raises(RuntimeError, match="injected"):
        with store.transaction() as connection:
            service.adopt_for_submission(connection, "conversation-a", "request-a", "message-a",
                                          [{"ref": attachment["ref"]}])
            events.append("message.committed", {"kind": "message", "id": "message-a"}, {})
            raise RuntimeError("injected harmless admission failure")
    assert events.high == "0"
    assert service.streams_for_request("conversation-a", "request-a") == []
    assert adopt(store, service, [{"ref": attachment["ref"]}]) == [attachment]


def test_refs_reusable_same_conversation_idempotent_adoption(env):
    store, service, _ = env
    attachment, upload_id = upload(service)
    items = [{"ref": attachment["ref"]}]
    assert adopt(store, service, items) == [attachment]
    assert adopt(store, service, items) == [attachment]
    assert adopt(store, service, items, request="request-b", message="message-b") == [attachment]
    with pytest.raises(AttachmentError) as exc:
        adopt(store, service, [{"ref": attachment["ref"], "add_to_knowledge": True}])
    assert exc.value.code == "id_conflict"
    error(service.handle("attachments.cancel", {"upload_id": upload_id}), "busy")


def test_adoption_deletion_require_shared_active_transaction(env):
    store, service, _ = env
    with pytest.raises(ValueError, match="shared"):
        service.adopt_for_submission(store.connection, "conversation-a", "r", "m", [])
    with pytest.raises(ValueError, match="shared"):
        service.delete_conversation(store.connection, "conversation-a")
    foreign = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="shared"):
            service.adopt_for_submission(foreign, "conversation-a", "r", "m", [])
    finally:
        foreign.close()


def test_digest_rechecked_before_adoption_and_runner_read(env):
    store, service, _ = env
    attachment, _ = upload(service)
    adopt(store, service, [{"ref": attachment["ref"]}])
    with store.transaction() as connection:
        connection.execute("UPDATE desktop_upload_chunks SET data=?", (b"other",))
    with pytest.raises(AttachmentError, match="verified"):
        service.streams_for_request("conversation-a", "request-a")
    with pytest.raises(AttachmentError, match="verified"):
        adopt(store, service, [{"ref": attachment["ref"]}], request="request-b")


def test_delete_removes_content_not_identity_and_rollback_safe(env):
    store, service, _ = env
    attachment, upload_id = upload(service)
    adopt(store, service, [{"ref": attachment["ref"]}])
    with pytest.raises(RuntimeError):
        with store.transaction() as connection:
            service.delete_conversation(connection, "conversation-a")
            raise RuntimeError("harmless injected deletion failure")
    assert len(service.streams_for_request("conversation-a", "request-a")) == 1
    with store.transaction() as connection:
        service.delete_conversation(connection, "conversation-a")
    assert service.streams_for_request("conversation-a", "request-a") == []
    assert store.connection.execute("SELECT count(*) FROM desktop_upload_chunks").fetchone()[0] == 0
    assert store.connection.execute("SELECT state FROM desktop_uploads").fetchone()[0] == "deleted"
    error(commit(service, upload_id, b"hello"), "expired")


@pytest.mark.asyncio
async def test_image_only_explicit_knowledge_seam_existing_processor(env, tmp_path):
    from src.discord.attachments import AttachmentIntent, AttachmentProcessor

    store, service, _ = env
    png = b"\x89PNG\r\n\x1a\n" + b"content"
    image, _ = upload(service, png, name="photo.png", mime="image/png")
    text, _ = upload(service, b"notes", client_attachment_id="client-b", name="notes.txt")
    public = adopt(store, service, [{"ref": image["ref"]},
                                   {"ref": text["ref"], "add_to_knowledge": True}])
    assert public == [image, text]
    streams = service.streams_for_request("conversation-a", "request-a")
    assert [choice for _, choice in streams] == [False, True]
    processor = AttachmentProcessor(temp_dir=tmp_path / "processing")
    result = await processor.process(
        [stream for stream, _ in streams], "conversation-a", "request-a",
        intent=AttachmentIntent.CURRENT_TASK)
    assert len(result.image_blocks) == 1
    assert base64.b64decode(result.image_blocks[0]["source"]["data"]) == png
    assert "notes" in result.inline_text
    assert "requested knowledge ingestion" not in result.inline_text
    assert await streams[1][0].read() == b"notes"


@pytest.mark.asyncio
async def test_names_never_read_paths_unknown_binary_supported(env, tmp_path):
    store, service, _ = env
    attachment, _ = upload(service, b"content", name="../picked/data.bin",
                           mime="application/x-executable")
    assert attachment["name"] == "../picked/data.bin"
    adopt(store, service, [{"ref": attachment["ref"]}])
    stream, knowledge = service.streams_for_request("conversation-a", "request-a")[0]
    assert await stream.read() == b"content"
    assert not knowledge
    assert set(path.name for path in tmp_path.iterdir()) == {"journal.sqlite3"}


@pytest.mark.asyncio
async def test_image_only_submission_is_valid_current_task_context(env, tmp_path):
    from src.discord.attachments import AttachmentIntent, AttachmentProcessor

    store, service, _ = env
    png = b"\x89PNG\r\n\x1a\n" + b"content"
    image, _ = upload(service, png, name="photo.png", mime="image/png")
    assert adopt(store, service, [{"ref": image["ref"]}]) == [image]
    stream, knowledge = service.streams_for_request("conversation-a", "request-a")[0]
    result = await AttachmentProcessor(temp_dir=tmp_path / "processing").process(
        [stream], "conversation-a", "request-a", AttachmentIntent.CURRENT_TASK)
    assert not knowledge
    assert len(result.image_blocks) == 1
    assert result.inline_text == "[User shared image: photo.png]"


@pytest.mark.parametrize("option", ["chunk_bytes", "attachment_bytes", "attachments_per_turn",
                                    "ttl_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_limits_are_not_silently_adopted(env, option, value):
    store, _, _ = env
    with pytest.raises(ValueError, match="positive integers"):
        AttachmentService(store, require_conversation, **{option: value})


def test_chunk_configuration_cannot_exceed_safe_transport_bound(env):
    store, _, _ = env
    with pytest.raises(ValueError, match="bounded transport"):
        AttachmentService(store, require_conversation, chunk_bytes=512 * 1024 + 1)


def test_default_accepts_existing_50mib_archive_without_byte_allocation(tmp_path):
    store = JournalStore(tmp_path / "journal.sqlite3", "profile-a")
    try:
        service = AttachmentService(store, require_conversation)
        assert service.limits["attachment_bytes"] >= 50 * 1024 * 1024
        upload_id, _ = begin(service, size=50 * 1024 * 1024,
                             name="pack.zip", mime="application/zip")
        assert service.handle("attachments.cancel", {"upload_id": upload_id})["ok"]
    finally:
        store.close()


def test_partial_committed_adopted_and_receipts_survive_restart(tmp_path):
    path, clock = tmp_path / "journal.sqlite3", Clock()
    store = JournalStore(path, "profile-a", identity="owner-a")
    service = AttachmentService(store, require_conversation, clock=clock, chunk_bytes=8)
    partial_id, params = begin(service, b"abcdefghijk")
    assert chunk(service, partial_id, b"abcdefgh")["ok"]
    journal = CommandJournal(store)
    receipt_params = {"client_attachment_id": "client-b", "conversation_id": "conversation-a",
                      "name": "notes.txt", "mime": "text/plain", "size": 5}
    receipt = journal.execute("begin-b", "attachments.begin", receipt_params,
                              lambda: service.handle("attachments.begin", receipt_params))
    committed_id = receipt["result"]["upload_id"]
    assert chunk(service, committed_id, b"hello")["ok"]
    metadata = commit(service, committed_id, b"hello")["result"]["attachment"]
    adopt(store, service, [{"ref": metadata["ref"], "add_to_knowledge": True}])
    store.close()
    store = JournalStore(path, "profile-a", identity="owner-a")
    try:
        service = AttachmentService(store, require_conversation, clock=clock, chunk_bytes=8)
        replay = CommandJournal(store).check("begin-b", "attachments.begin", receipt_params)
        assert replay == receipt
        assert service.handle("attachments.begin", params)["result"]["upload_id"] == partial_id
        assert chunk(service, partial_id, b"abcdefgh")["result"]["received"] == 8
        assert chunk(service, partial_id, b"ijk", 8)["result"]["received"] == 11
        assert commit(service, partial_id, b"abcdefghijk")["ok"]
        assert commit(service, committed_id, b"hello")["result"]["attachment"] == metadata
        assert service.streams_for_request("conversation-a", "request-a")[0][1] is True
    finally:
        store.close()


def test_cancel_expire_failure_and_receipt_tombstones_survive_restart(tmp_path):
    path, clock = tmp_path / "journal.sqlite3", Clock()
    store = JournalStore(path, "profile-a")
    service = AttachmentService(store, require_conversation, clock=clock, chunk_bytes=8,
                                ttl_seconds=60)
    cancelled, _ = begin(service)
    params = {"upload_id": cancelled}
    journal = CommandJournal(store)
    assert journal.execute("cancel-a", "attachments.cancel", params,
                           lambda: service.handle("attachments.cancel", params))["ok"]
    expired, _ = begin(service, client_attachment_id="client-b")
    failed, _ = begin(service, client_attachment_id="client-c")
    assert chunk(service, failed, b"hello")["ok"]
    error(commit(service, failed, b"other"), "bad_request")
    clock.now += 61
    assert service.expire() == 1
    assert journal.prune(time.time() + 1) == 1
    store.close()
    store = JournalStore(path, "profile-a")
    try:
        service = AttachmentService(store, require_conversation, clock=clock, chunk_bytes=8)
        replay = CommandJournal(store).check("cancel-a", "attachments.cancel", params)
        error(replay, "receipt_expired")
        for upload_id in (cancelled, expired, failed):
            error(chunk(service, upload_id, b"hello"), "expired")
        count = store.connection.execute("SELECT count(*) FROM desktop_upload_chunks").fetchone()[0]
        assert count == 0
    finally:
        store.close()


def test_storage_failure_cannot_false_accept_upload(env, monkeypatch):
    store, service, _ = env
    journal = CommandJournal(store)
    params = {"client_attachment_id": "client-a", "conversation_id": "conversation-a",
              "name": "notes.txt", "mime": "text/plain", "size": 5}

    def fail(*_args):
        raise JournalStorageError()

    monkeypatch.setattr(service, "_begin_result", fail)
    result = journal.execute("begin-a", "attachments.begin", params,
                             lambda: service.handle("attachments.begin", params))
    error(result, "storage_unavailable")
    assert result["error"]["disposition"] == "outcome_unknown"
    assert store.connection.execute("SELECT count(*) FROM desktop_uploads").fetchone()[0] == 0
    replay = journal.check("begin-a", "attachments.begin", params)
    assert replay["error"]["disposition"] == "outcome_unknown"
