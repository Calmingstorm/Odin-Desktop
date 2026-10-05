"""Snapshot/watermark fencing against an independent SQLite connection."""

import sqlite3

import pytest

from src.desktop.commands import JournalStorageError, JournalStore
from src.desktop.events import EventJournal


def test_snapshot_watermark_and_domain_state_share_one_committed_boundary(tmp_path):
    path = tmp_path / "private" / "journal.sqlite"
    store = JournalStore(path, "snapshot-test")
    observer = sqlite3.connect(path, isolation_level=None)
    events = EventJournal(store)
    try:
        with store.transaction() as connection:
            connection.execute("CREATE TABLE snapshot_fixture (revision INTEGER)")
            connection.execute("INSERT INTO snapshot_fixture VALUES (0)")
        with store.transaction() as connection:
            connection.execute("UPDATE snapshot_fixture SET revision=1")
            event = events.append("runtime.status", {"kind": "runtime", "id": "test"}, {})
            assert events.high == event["cursor"] == "1"
            # Independent readers see neither half of the uncommitted update.
            assert observer.execute("SELECT revision FROM snapshot_fixture").fetchone() == (0,)
            assert observer.execute("SELECT event_high FROM journal_meta").fetchone() == (0,)
        observer.execute("BEGIN")
        assert observer.execute("SELECT revision FROM snapshot_fixture").fetchone() == (1,)
        assert observer.execute("SELECT event_high FROM journal_meta").fetchone() == (1,)
        observer.commit()
        assert events.catchup("0")[2] == [event]
    finally:
        observer.close()
        store.close()


def test_snapshot_transaction_fences_second_writer_until_watermark_is_captured(tmp_path):
    path = tmp_path / "private" / "journal.sqlite"
    store = JournalStore(path, "snapshot-test")
    competitor = JournalStore(path, "snapshot-test")
    competitor.connection.execute("PRAGMA busy_timeout=0")
    events, competing_events = EventJournal(store), EventJournal(competitor)
    try:
        first = events.append("runtime.status", {}, {"phase": "ready"})
        with store.transaction():
            assert events.high == "1"
            with pytest.raises(JournalStorageError):
                competing_events.append("runtime.status", {}, {"phase": "quiescing"})
            assert events.high == "1"
            assert events.between(0) == [first]
        second = competing_events.append("runtime.status", {}, {"phase": "quiescing"})
        assert second["seq"] == 2
        assert events.catchup(first["cursor"]) == (False, "2", [second])
    finally:
        competitor.close()
        store.close()
