"""Real SQLite command admission, identity, retention, and failure barriers."""
import json
import os
import sqlite3
import subprocess
import sys
import time

import pytest

from src.desktop.commands import (
    CommandJournal,
    JournalStorageError,
    JournalStore,
    canonical_json,
    response_error,
)
from src.desktop.events import EventJournal


@pytest.fixture
def store(tmp_path):
    journal = JournalStore(tmp_path / "private" / "journal.sqlite", "testing")
    yield journal
    journal.close()


def test_private_full_sync_profile_and_owner_binding(store, tmp_path):
    assert store.connection.execute("PRAGMA synchronous").fetchone()[0] == 2
    assert store.connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    path = tmp_path / "private" / "journal.sqlite"
    assert path.stat().st_mode & 0o777 == 0o600
    store.close()
    for profile, identity in [("other-profile", None), ("testing", "other-installation")]:
        with pytest.raises(JournalStorageError, match="^Durable journal storage is unavailable$"):
            JournalStore(path, profile, identity=identity)


@pytest.mark.parametrize("kind", ["symlink", "sidecar", "public", "hardlink", "directory"])
def test_unsafe_database_and_sidecar_files_refused(tmp_path, kind):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "journal.sqlite"
    target = tmp_path / "untouched"
    target.write_text("private original")
    target.chmod(0o600)
    if kind == "symlink":
        path.symlink_to(target)
    elif kind == "sidecar":
        path.with_name(path.name + "-journal").symlink_to(target)
    elif kind == "public":
        path.touch(mode=0o644)
    elif kind == "hardlink":
        os.link(target, path)
    else:
        path.mkdir(mode=0o700)
    with pytest.raises(JournalStorageError) as exc:
        JournalStore(path, "testing")
    assert str(path) not in str(exc.value)
    assert target.read_text() == "private original"


def test_success_reopens_canonical_keys_and_conflicts(store, tmp_path):
    commands = CommandJournal(store)
    calls = []
    params = {"a": {"y": 2, "x": 1}, "b": [True, None]}

    def handler():
        calls.append(1)
        return {"ok": True, "result": {"count": len(calls)}}

    answer = commands.execute("one", "conversations.create", params, handler)
    answer["result"]["count"] = 999
    store.close()
    reopened = JournalStore(tmp_path / "private" / "journal.sqlite", "testing")
    try:
        journal = CommandJournal(reopened)
        response = journal.execute("one", "conversations.create",
                                   {"b": [True, None], "a": {"x": 1, "y": 2}}, handler)
        assert response == {"ok": True, "result": {"count": 1}}
        for method, other in [("control.stop", params), ("conversations.create", {"a": 3})]:
            assert journal.execute("one", method, other, handler)["error"]["code"] == "id_conflict"
        assert journal.check("one", "status.get", {})["error"]["code"] == "id_conflict"
        assert journal.check("fresh-read", "status.get", {}) is None
        assert journal.check("fresh-read", "control.stop", {}) is None
        assert calls == [1]
    finally:
        reopened.close()


@pytest.mark.parametrize("code", ["busy", "stale_binding", "bad_request", "capability_unavailable"])
def test_refusals_final_same_id_new_id_required(store, tmp_path, code):
    first = response_error(code, "Not admitted")
    calls = []
    assert CommandJournal(store).execute("first", "control.stop", {}, lambda: first) == first
    store.close()
    reopened = JournalStore(tmp_path / "private" / "journal.sqlite", "testing")
    commands = CommandJournal(reopened)

    def admitted():
        calls.append(1)
        return {"ok": True, "result": {}}

    try:
        assert commands.execute("first", "control.stop", {}, admitted) == first
        assert calls == []
        assert commands.execute("retry", "control.stop", {}, admitted)["ok"]
        assert calls == [1]
    finally:
        reopened.close()


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), (1,), {2: 3}])
def test_non_json_params_validation_is_durable(store, invalid):
    commands = CommandJournal(store)

    def never():
        pytest.fail("Invalid parameters dispatched")

    answer = commands.execute("invalid", "conversations.create", {"value": invalid}, never)
    assert answer["error"]["code"] == "bad_request"
    assert commands.execute("invalid", "conversations.create", {"value": invalid}, never) == answer
    assert commands.execute("invalid", "conversations.create", {}, never)["error"][
        "code"] == "id_conflict"


def test_expiry_tombstone_survives_restart_unknowns_not_pruned(store, tmp_path):
    commands = CommandJournal(store)
    good = {"ok": True, "result": {}}
    unknown = response_error("internal", "Unresolved effects", "outcome_unknown")
    commands.execute("known", "control.stop", {}, lambda: good)
    commands.execute("unknown", "control.stop", {}, lambda: unknown)
    assert commands.prune(time.time() + 10) == 1
    assert commands.prune(time.time() + 10) == 0
    store.close()
    reopened = JournalStore(tmp_path / "private" / "journal.sqlite", "testing")
    try:
        commands = CommandJournal(reopened)

        def never():
            pytest.fail("Expired/unknown command dispatched")

        expired = commands.execute("known", "control.stop", {}, never)
        assert expired["error"]["code"] == "receipt_expired"
        assert expired["error"]["disposition"] == "outcome_unknown"
        assert commands.execute("unknown", "control.stop", {}, never) == unknown
        assert commands.execute("known", "control.stop", {"other": True}, never)["error"][
            "code"] == "id_conflict"
    finally:
        reopened.close()


def test_handler_receipt_and_event_commit_atomically(store):
    events = EventJournal(store)
    commands = CommandJournal(store)

    def handler():
        assert store.connection.in_transaction
        event = events.append("runtime.status", {}, {"phase": "ready"})
        return {"ok": True, "result": {"event": event["cursor"]}}

    assert commands.execute("one", "conversations.create", {}, handler) == {
        "ok": True, "result": {"event": "1"}}
    assert len(events.between(0)) == 1
    commands.execute("one", "conversations.create", {}, handler)
    assert events.high == "1"


def test_rollback_never_dispatches_pending_command_again(store, tmp_path):
    calls = []
    events = EventJournal(store)

    def fails():
        calls.append(1)
        events.append("runtime.status", {}, {})
        raise RuntimeError("sensitive diagnostic")

    answer = CommandJournal(store).execute("one", "control.stop", {}, fails)
    assert answer["error"]["disposition"] == "outcome_unknown"
    assert "sensitive" not in json.dumps(answer)
    assert events.high == "0"
    store.close()
    reopened = JournalStore(tmp_path / "private" / "journal.sqlite", "testing")
    try:
        answer = CommandJournal(reopened).execute("one", "control.stop", {}, fails)
        assert answer["error"]["disposition"] == "outcome_unknown"
        assert CommandJournal(reopened).prune(time.time() + 100) == 0
        assert calls == [1]
    finally:
        reopened.close()


class CommitFault:
    def __init__(self, connection, fail_at, after_commit=False):
        self.connection = connection
        self.fail_at = fail_at
        self.after_commit = after_commit
        self.commits = 0

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def commit(self):
        self.commits += 1
        if self.commits == self.fail_at:
            if self.after_commit:
                self.connection.commit()
            raise sqlite3.OperationalError("sensitive storage diagnostic")
        self.connection.commit()


@pytest.mark.parametrize("after_commit", [False, True])
def test_final_commit_failure_never_reexecutes(store, after_commit):
    store._connection = CommitFault(store.connection, 2, after_commit)
    calls = []
    events = EventJournal(store)

    def handler():
        calls.append(1)
        events.append("runtime.status", {}, {})
        return {"ok": True, "result": {}}

    commands = CommandJournal(store)
    answer = commands.execute("one", "control.stop", {}, handler)
    assert answer["error"]["code"] == "storage_unavailable"
    assert "sensitive" not in json.dumps(answer)
    replay = commands.execute("one", "control.stop", {}, handler)
    if after_commit:
        assert replay == {"ok": True, "result": {}}
    else:
        assert replay["error"]["disposition"] == "outcome_unknown"
    assert events.high == ("1" if after_commit else "0")
    assert calls == [1]


def test_admission_commit_failure_calls_no_handler(store):
    store._connection = CommitFault(store.connection, 1)

    def never():
        pytest.fail("Work ran before admission commit")

    response = CommandJournal(store).execute("one", "control.stop", {}, never)
    assert response["error"]["code"] == "storage_unavailable"


def test_nested_failure_cannot_be_caught_into_success(store):
    with pytest.raises(JournalStorageError):
        with store.transaction() as connection:
            try:
                with store.transaction():
                    connection.execute("UPDATE journal_meta SET event_high=100")
                    raise ValueError("harmless test failure")
            except ValueError:
                pass
    assert EventJournal(store).high == "0"


def test_canonical_json_rejects_surrogates_and_nonstring_keys():
    for value in ["\ud800", {1: "value"}, float("nan")]:
        with pytest.raises((ValueError, UnicodeError)):
            canonical_json(value)


def test_crash_during_handler_pending_survives_actual_process_exit(tmp_path):
    path = tmp_path / "private" / "journal.sqlite"
    program = """
import os, sys
from pathlib import Path
from src.desktop.commands import JournalStore, CommandJournal
from src.desktop.events import EventJournal
store = JournalStore(Path(sys.argv[1]), 'testing')
def handler():
    EventJournal(store).append('runtime.status', {}, {})
    os._exit(0)
CommandJournal(store).execute('crash-id', 'control.stop', {}, handler)
"""
    child = subprocess.run([sys.executable, "-c", program, str(path)], timeout=10)
    assert child.returncode == 0
    reopened = JournalStore(path, "testing")
    try:
        def never():
            pytest.fail("Crash-interrupted work replayed")
        response = CommandJournal(reopened).execute("crash-id", "control.stop", {}, never)
        assert response["error"]["disposition"] == "outcome_unknown"
        assert EventJournal(reopened).high == "0"
        assert CommandJournal(reopened).prune(time.time() + 100) == 0
    finally:
        reopened.close()


def test_admission_visible_before_handler_final_receipt_event_hidden_until_commit(store, tmp_path):
    observer = sqlite3.connect(tmp_path / "private" / "journal.sqlite")
    try:
        def handler():
            row = observer.execute("SELECT state FROM command_receipts").fetchone()
            assert row == ("pending",)
            EventJournal(store).append("runtime.status", {}, {})
            assert observer.execute("SELECT COUNT(*) FROM journal_events").fetchone() == (0,)
            assert observer.execute("SELECT state FROM command_receipts").fetchone() == ("pending",)
            return {"ok": True, "result": {}}
        assert CommandJournal(store).execute("one", "control.stop", {}, handler)["ok"]
        assert observer.execute("SELECT state FROM command_receipts").fetchone() == ("final",)
        assert observer.execute("SELECT COUNT(*) FROM journal_events").fetchone() == (1,)
    finally:
        observer.close()


def test_foreign_identity_does_not_mutate_database_journal_mode(tmp_path):
    path = tmp_path / "private" / "journal.sqlite"
    original = JournalStore(path, "testing", identity="installation-one:owner")
    original.connection.execute("PRAGMA journal_mode=WAL")
    original.close()
    before = path.read_bytes()
    with pytest.raises(JournalStorageError):
        JournalStore(path, "testing", identity="installation-two:owner")
    assert path.read_bytes() == before
    observer = sqlite3.connect(path)
    try:
        assert observer.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    finally:
        observer.close()


def test_existing_empty_foreign_schema_not_adopted(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "journal.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE other_state (value TEXT)")
    connection.close()
    path.chmod(0o600)
    before = path.read_bytes()
    with pytest.raises(JournalStorageError):
        JournalStore(path, "testing")
    assert path.read_bytes() == before


@pytest.mark.parametrize("answer", [{"ok": True}, {"ok": "yes"}, {"ok": False, "error": None},
                                    {"ok": False, "error": {"code": "bad_request"}},
                                    {"ok": True, "result": float("nan")}])
def test_invalid_handler_result_never_leaks_or_reexecutes(store, answer):
    journal = CommandJournal(store)
    first = journal.execute("one", "control.stop", {}, lambda: answer)
    assert first["error"]["disposition"] == "outcome_unknown"
    def never():
        pytest.fail("Invalid handler result caused replay")
    assert journal.execute("one", "control.stop", {}, never)["error"][
        "disposition"] == "outcome_unknown"


def test_execute_inside_uncommitted_transaction_never_invokes_handler(store):
    with store.transaction():
        def never():
            pytest.fail("Handler admission was not durably reserved")
        assert CommandJournal(store).execute("one", "control.stop", {}, never)["error"][
            "code"] == "storage_unavailable"
    assert CommandJournal(store).check("one", "control.stop", {}) is None


def test_fsync_failure_is_scrubbed_before_any_admission(tmp_path, monkeypatch):
    def unavailable(_):
        raise OSError("sensitive storage diagnostic")
    monkeypatch.setattr(os, "fsync", unavailable)
    with pytest.raises(JournalStorageError) as error:
        JournalStore(tmp_path / "private" / "journal.sqlite", "testing")
    assert "sensitive" not in str(error.value)


def test_closed_store_never_dispatches(store):
    store.close()
    def never():
        pytest.fail("Unavailable store admitted work")
    commands = CommandJournal(store)
    assert commands.execute("one", "control.stop", {}, never)["error"][
        "code"] == "storage_unavailable"
    assert commands.check("one", "status.get", {})["error"]["code"] == "storage_unavailable"
