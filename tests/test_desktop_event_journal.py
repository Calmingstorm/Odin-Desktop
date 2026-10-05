"""Persistent monotonic event cursors and exact retention boundaries."""
import pytest

from src.desktop.commands import JournalStorageError, JournalStore
from src.desktop.events import EventJournal


@pytest.fixture
def store(tmp_path):
    journal = JournalStore(tmp_path / "private" / "journal.sqlite", "testing")
    yield journal
    journal.close()


def append(events, number):
    return events.append("runtime.status", {"kind": "runtime", "id": "testing"},
                         {"number": number}, at="2026-10-05T14:00:00Z")


def test_frame_payload_snapshot(store):
    events = EventJournal(store)
    frame = append(events, 1)
    assert frame == {"t": "evt", "seq": 1, "cursor": "1", "type": "runtime.status",
                     "entity": {"kind": "runtime", "id": "testing"},
                     "at": "2026-10-05T14:00:00Z", "payload": {"number": 1}}
    frame["payload"]["number"] = 999
    assert events.between(0)[0]["payload"] == {"number": 1}
    assert events.high == "1"


def test_catchup_and_between_ordered_bounded(store):
    events = EventJournal(store)
    frames = [append(events, i) for i in range(5)]
    assert events.catchup("0") == (False, "5", frames)
    assert events.catchup("3") == (False, "5", frames[3:])
    assert events.catchup("5") == (False, "5", [])
    assert events.catchup(None) == (False, "5", [])
    assert events.between("1", "3") == frames[1:3]


@pytest.mark.parametrize("cursor", ["6", "-1", "01", "1.0", "", "abc", "9" * 100, 0, True])
def test_unknown_cursor_requires_reset_not_empty_interval(store, cursor):
    events = EventJournal(store)
    append(events, 1)
    assert events.catchup(cursor) == (True, "1", [])


def test_retention_boundary_and_high_after_restart(store, tmp_path):
    events = EventJournal(store, max_events=2)
    frames = [append(events, i) for i in range(4)]
    assert events.catchup("1") == (True, "4", [])
    assert events.catchup("2") == (False, "4", frames[2:])
    store.close()
    reopened = JournalStore(tmp_path / "private" / "journal.sqlite", "testing")
    try:
        events = EventJournal(reopened, max_events=2)
        assert events.high == "4"
        assert append(events, 5)["seq"] == 5
        assert events.catchup("2") == (True, "5", [])
        assert [event["seq"] for event in events.between(0)] == [4, 5]
    finally:
        reopened.close()


def test_empty_retention_keeps_high_and_reset_floor(store, tmp_path):
    events = EventJournal(store, max_events=0)
    append(events, 1)
    append(events, 2)
    assert events.between(0) == []
    assert events.catchup("0") == (True, "2", [])
    assert events.catchup("2") == (False, "2", [])
    store.close()
    reopened = JournalStore(tmp_path / "private" / "journal.sqlite", "testing")
    try:
        events = EventJournal(reopened)
        assert append(events, 3)["seq"] == 3
        assert events.catchup("2")[0] is False
    finally:
        reopened.close()


def test_transaction_rollback_preserves_history_and_floor(store):
    events = EventJournal(store, max_events=1)
    original = append(events, 1)
    with pytest.raises(ValueError):
        with store.transaction():
            append(events, 2)
            raise ValueError("harmless transaction interruption")
    assert events.high == "1"
    assert events.catchup("0") == (False, "1", [original])
    assert append(events, 3)["seq"] == 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {1: "bad"}, (1, 2)])
def test_non_json_rejected_without_sequence_retention_change(store, value):
    events = EventJournal(store, max_events=1)
    original = append(events, 1)
    with pytest.raises(ValueError):
        events.append("runtime.status", {}, {"invalid": value})
    assert events.catchup("0") == (False, "1", [original])


@pytest.mark.parametrize("at", ["yesterday", "2026-10-05T14:00:00", "2026-10-05T14:00:00+01:00"])
def test_requires_utc_time(store, at):
    with pytest.raises(ValueError):
        EventJournal(store).append("runtime.status", {}, {}, at)


def test_closed_store_errors_scrubbed(store):
    store.close()
    with pytest.raises(JournalStorageError, match="^Durable journal storage is unavailable$"):
        EventJournal(store).append("runtime.status", {}, {})


def test_caught_validation_failure_marks_outer_transaction_rollback_only(store):
    events = EventJournal(store)
    with pytest.raises(JournalStorageError):
        with store.transaction():
            append(events, 1)
            try:
                events.append("runtime.status", {}, {}, at="not-a-timestamp")
            except ValueError:
                pass
    assert events.high == "0"
    assert events.between(0) == []


def test_sequence_exhaustion_is_scrubbed_not_overflow(store):
    with store.transaction() as connection:
        connection.execute("UPDATE journal_meta SET event_high=9223372036854775807")
    with pytest.raises(JournalStorageError, match="^Durable journal storage is unavailable$"):
        append(EventJournal(store), 1)
    assert EventJournal(store).high == "9223372036854775807"
