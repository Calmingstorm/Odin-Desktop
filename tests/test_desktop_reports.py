"""Harmless stored-output and stub delivery tests, no live managers/effects."""
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from src.desktop.artifacts import ArtifactStore, ResultReadError
from src.desktop.commands import JournalStorageError, JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.reports import (
    ERROR_TEXT,
    MAX_PAGE_BYTES,
    MAX_REPORT_BYTES,
    ReportBinding,
    ReportDelivery,
    ReportService,
)
from src.desktop.transcript import TranscriptStore

BINDING = ReportBinding("owner", "conversation", "request", "run", 1, "schedule")


@pytest.fixture
def service(tmp_path):
    store = JournalStore(tmp_path / "journal.sqlite3", "profile")
    policy, admissions = [True], []

    def admit(binding):
        admissions.append(binding)
        return binding == BINDING

    reports = ReportService(store, authorize=lambda *_: policy[0], assert_binding=admit)
    yield store, reports, policy, admissions
    store.close()


def publish(reports, pages=None, **kwargs):
    return reports.publish(pages if pages is not None else ["first", "second"],
        binding=kwargs.pop("binding", BINDING), tool="run_command", hosts=("test-host",), **kwargs)


def test_bound_snapshot_is_immutable_and_reads_do_not_admit_or_execute(service):
    store, reports, _, admissions = service
    pages = ["first", "second"]
    descriptor = publish(reports, pages)
    pages[0] = "changed"
    admissions.clear()
    for _ in range(3):
        assert reports.page(descriptor["report_id"], 2, owner="owner") == {
            "page": 2, "pages": 2, "text": "second"}
    assert admissions == []
    saved = json.loads(store.connection.execute("SELECT pages FROM desktop_reports").fetchone()[0])
    assert saved["binding"]["run_id"] == "run"
    assert saved["binding"]["generation"] == 1
    with pytest.raises(FrozenInstanceError):
        BINDING.run_id = "other"


def test_identical_publication_deduplicates_and_conflicting_content_refused(service):
    store, reports, _, _ = service
    first = publish(reports)
    assert publish(reports) == first
    with pytest.raises(ResultReadError, match="already bound") as error:
        publish(reports, ["changed"])
    assert error.value.code == "id_conflict"
    assert store.connection.execute("SELECT COUNT(*) FROM desktop_reports").fetchone()[0] == 1


@pytest.mark.parametrize("field,value", [
    ("owner_id", "other"), ("conversation_id", "other"), ("request_id", "other"),
    ("run_id", "other"), ("generation", 2), ("producer_id", "other"),
])
def test_every_immutable_binding_component_is_validated(service, field, value):
    _, reports, _, _ = service
    with pytest.raises(ResultReadError) as error:
        publish(reports, binding=replace(BINDING, **{field: value}))
    assert error.value.code == "unauthorized"


def test_reference_possession_not_authority_and_policy_rechecked(service):
    _, reports, policy, _ = service
    report = publish(reports)
    for owner, conversation in [("other", None), ("owner", "other")]:
        with pytest.raises(ResultReadError) as error:
            reports.page(report["report_id"], 1, owner=owner, conversation_id=conversation)
        assert error.value.code == "not_found"
    policy[0] = False
    with pytest.raises(ResultReadError) as error:
        reports.page(report["report_id"], 1, owner="owner")
    assert error.value.code == "unauthorized"


def test_explicit_report_id_cannot_rebind_run_owner_scope_or_tool(service):
    store, reports, _, _ = service
    # Validator accepts both runs; a stored report ID still cannot move.
    reports.assert_binding = lambda _: True
    publish(reports, report_id="fixed")
    for field, value in [("run_id", "new-run"), ("owner_id", "new-owner"),
                         ("conversation_id", "new-conversation"), ("generation", 2)]:
        with pytest.raises(ResultReadError) as error:
            publish(reports, binding=replace(BINDING, **{field: value}), report_id="fixed")
        assert error.value.code == "id_conflict"
    with pytest.raises(ResultReadError) as error:
        reports.publish(["first", "second"], binding=BINDING, tool="different", report_id="fixed")
    assert error.value.code == "id_conflict"
    row = store.connection.execute("SELECT owner,conversation_id FROM desktop_reports").fetchone()
    assert tuple(row) == ("owner", "conversation")


def test_policy_and_admission_exceptions_do_not_leak_diagnostics(service):
    _, reports, _, _ = service
    report = publish(reports)

    def unavailable(*_):
        raise RuntimeError("private stub diagnostic")

    reports.authorize = unavailable
    with pytest.raises(ResultReadError) as error:
        reports.page(report["report_id"], 1, owner="owner")
    assert error.value.code == "unavailable" and "private" not in str(error.value)
    reports.assert_binding = unavailable
    with pytest.raises(ResultReadError) as error:
        publish(reports)
    assert error.value.code == "unauthorized" and "private" not in str(error.value)


def test_publish_event_failure_rolls_back_snapshot(service):
    store, reports, _, _ = service

    class BrokenEvents:
        def append(self, *_):
            raise RuntimeError("Harmless publication failure")

    reports.events = BrokenEvents()
    with pytest.raises(RuntimeError):
        publish(reports)
    assert store.connection.execute("SELECT COUNT(*) FROM desktop_reports").fetchone()[0] == 0


@pytest.mark.parametrize("page", [True, False, 0, -1, 1.5, "1", 3])
def test_pages_are_strict_one_based_bounded(service, page):
    _, reports, _, _ = service
    descriptor = publish(reports)
    with pytest.raises(ResultReadError) as error:
        reports.page(descriptor["report_id"], page, owner="owner")
    assert error.value.code == "bad_request"


@pytest.mark.parametrize("pages", [[], [1], ["x"] * 11,
    ["x" * (MAX_PAGE_BYTES + 1)], ["x" * MAX_PAGE_BYTES] * 9,
    ["\ud800"], ["\U0001f600" * (MAX_PAGE_BYTES // 4 + 1)]])
def test_count_utf8_page_and_aggregate_limits(service, pages):
    store, reports, _, _ = service
    with pytest.raises(ResultReadError):
        publish(reports, pages)
    assert store.connection.execute("SELECT COUNT(*) FROM desktop_reports").fetchone()[0] == 0


def test_maximum_bytes_roundtrip(service):
    _, reports, _, _ = service
    report = publish(reports, ["x" * MAX_PAGE_BYTES] * (MAX_REPORT_BYTES // MAX_PAGE_BYTES))
    assert report["size"] == MAX_REPORT_BYTES
    assert len(reports.page(report["report_id"], 8, owner="owner")["text"]) == MAX_PAGE_BYTES


def test_output_reuses_registered_renderer_and_scrubs_before_persistence(service):
    store, reports, _, _ = service
    # Synthetic value, never a real credential.
    secret = "ghp_" + "a" * 36
    raw = json.dumps({"format": "paginated_embed_v1", "pages": [
        {"title": "Status", "description": secret,
         "fields": [{"name": "Result", "value": "saved"}],
         "links": [{"label": "Docs", "url": "https://example.com/docs"}]}]})
    report = reports.publish_output(raw, report_format="paginated_embed_v1",
                                    binding=BINDING, tool="run_command")
    assert report["status"] == "available"
    text = reports.page(report["report_id"], 1, owner="owner")["text"]
    assert "Status" in text and "Result: saved" in text and "https://example.com/docs" in text
    assert secret not in text
    assert secret not in store.connection.execute("SELECT pages FROM desktop_reports").fetchone()[0]


@pytest.mark.parametrize("output,fmt", [
    ("not JSON", "paginated_embed_v1"), ("{}", "unavailable-format"),
    ("x" * (MAX_REPORT_BYTES + 1), "paginated_embed_v1"),
    (json.dumps({"format": "paginated_embed_v1", "pages": [{"unknown": "private"}]}),
     "paginated_embed_v1"),
])
def test_rejected_output_persists_honest_generic_error(service, output, fmt):
    _, reports, _, _ = service
    report = reports.publish_output(output, report_format=fmt, binding=BINDING, tool="run_command")
    assert report["status"] == "error"
    assert reports.page(report["report_id"], 1, owner="owner")["text"] == ERROR_TEXT


def test_unavailable_is_persisted_not_recomputed(service):
    store, reports, _, _ = service
    report = publish(reports, ["should not persist"], status="unavailable")
    assert report["available"] is False
    saved = store.connection.execute("SELECT pages FROM desktop_reports").fetchone()[0]
    assert "should not persist" not in saved
    with pytest.raises(ResultReadError) as error:
        reports.page(report["report_id"], 1, owner="owner")
    assert error.value.code == "unavailable"


def test_corrupt_stored_projection_has_safe_failure(service):
    store, reports, _, _ = service
    report = publish(reports)
    with store.transaction() as db:
        db.execute("UPDATE desktop_reports SET pages=?", ("private malformed data",))
    with pytest.raises(ResultReadError) as error:
        reports.page(report["report_id"], 1, owner="owner")
    assert error.value.code == "unavailable"
    assert "private" not in str(error.value)


def test_closed_store_honest_storage_failure(service):
    store, reports, _, _ = service
    report = publish(reports)
    store.close()
    with pytest.raises(JournalStorageError):
        reports.page(report["report_id"], 1, owner="owner")


def test_legacy_and_bound_reports_survive_actual_reopen(tmp_path):
    path = tmp_path / "journal.sqlite3"
    store = JournalStore(path, "profile")
    artifacts = ArtifactStore(store, authorize=lambda *_: True)
    legacy = artifacts.publish_report(["legacy saved"], owner="owner",
        conversation_id="conversation", request_id="old", tool="run_command")
    reports = ReportService(store, authorize=lambda *_: True, assert_binding=lambda _: True)
    bound = publish(reports)
    store.close()
    store = JournalStore(path, "profile")
    try:
        reports = ReportService(store, authorize=lambda *_: True)
        assert reports.page(bound["report_id"], 2, owner="owner")["text"] == "second"
        assert reports.page(legacy["report_id"], 1, owner="owner")["text"] == "legacy saved"
        reports.delete_conversation("conversation")
        with pytest.raises(ResultReadError) as error:
            reports.page(bound["report_id"], 1, owner="owner")
        assert error.value.code == "not_found"
    finally:
        store.close()


def test_missing_binding_validator_fails_closed(service):
    store, _, _, _ = service
    reports = ReportService(store, authorize=lambda *_: True)
    with pytest.raises(ResultReadError) as error:
        publish(reports)
    assert error.value.code == "unauthorized"


def test_handle_no_rerun_operation(service):
    _, reports, _, _ = service
    report = publish(reports)
    assert reports.handle("reports.page", {"report_id": report["report_id"], "page": 1},
                          owner="owner")["text"] == "first"
    for method, params in [("schedules.run", {}), ("reports.page", {"report_id": "x"}),
                           ("reports.page", {"report_id": "x", "page": 1, "run": True})]:
        with pytest.raises(ResultReadError):
            reports.handle(method, params, owner="owner")


class Sink:
    def __init__(self):
        self.available = False
        self.accepted = {}

    async def deliver(self, delivery_id, frame):
        if not self.available:
            raise RuntimeError("Harmless stub disconnected")
        self.accepted[delivery_id] = frame
        return True


def graph(store, sink):
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit, sink=sink)
    reports = ReportService(store, authorize=lambda *_: True,
                            assert_binding=lambda binding: binding == BINDING, events=events)
    return conversations, ReportDelivery(reports, delivery), delivery


@pytest.mark.asyncio
async def test_atomic_delivery_dedup_and_reconnect_no_producer_replay(tmp_path):
    path = tmp_path / "journal.sqlite3"
    store = JournalStore(path, "profile")
    sink = Sink()
    conversations, publisher, delivery = graph(store, sink)
    binding = replace(BINDING, conversation_id=conversations.create()["conversation"]["id"])
    publisher.reports.assert_binding = lambda value: value == binding
    report = await publisher.publish(["saved"], binding=binding, tool="run_command")
    assert await publisher.publish(["saved"], binding=binding, tool="run_command") == report
    assert store.connection.execute("SELECT COUNT(*) FROM desktop_messages").fetchone()[0] == 1
    assert store.connection.execute("SELECT COUNT(*) FROM desktop_notifications").fetchone()[0] == 1
    record = store.connection.execute("SELECT record FROM desktop_messages").fetchone()[0]
    payload = json.loads(record)
    assert payload["artifacts"][0]["ref"] == report["report_id"]
    assert payload["artifacts"][0]["size"] == len("saved")
    pending = store.connection.execute("SELECT COUNT(*) FROM desktop_delivery_outbox "
                                       "WHERE state='pending'").fetchone()[0]
    assert pending > 0 and not sink.accepted
    store.close()
    store = JournalStore(path, "profile")
    try:
        _, publisher, delivery = graph(store, sink)
        sink.available = True
        await delivery.recover()
        assert sink.accepted
        assert publisher.reports.page(report["report_id"], 1, owner="owner")["text"] == "saved"
        assert store.connection.execute("SELECT COUNT(*) FROM desktop_messages").fetchone()[0] == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_delivery_failure_rolls_back_report_and_event(service):
    store, _, _, _ = service
    _, publisher, delivery = graph(store, Sink())
    # No destination exists. Publication cannot claim success before its notice commits.
    with pytest.raises(Exception):
        await publisher.publish(["saved"], binding=BINDING, tool="run_command")
    assert store.connection.execute("SELECT COUNT(*) FROM desktop_reports").fetchone()[0] == 0
    assert store.connection.execute("SELECT COUNT(*) FROM journal_events").fetchone()[0] == 0
    count = store.connection.execute("SELECT COUNT(*) FROM desktop_delivery_outbox").fetchone()[0]
    assert count == 0
