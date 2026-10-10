"""The routed engine variants' own edges: refusals, parse failures and fail-open stores."""
from __future__ import annotations

import json
import os

import pytest

import src.desktop.platform.windows_engine as engine
from src.desktop.platform import win32
from src.desktop.platform.windows import windows_profile_paths

EVERYONE_FILE = "D:P(A;;FA;;;WD)"


@pytest.fixture
def paths(tmp_path):
    profile = windows_profile_paths("test", environ={"LOCALAPPDATA": str(tmp_path)})
    profile.create_private()
    return profile


def refused(*args, **kwargs):
    raise OSError("refused")


# --- schedule history --------------------------------------------------------------------------


async def test_history_queries_filter_skip_damage_and_stop_at_the_limit(paths):
    from src.scheduler.history import ScheduleHistory

    path = paths.data_dir / "schedule_history.jsonl"
    history = ScheduleHistory(str(path))
    assert await history.query() == []  # no file yet
    rows = [{"schedule_id": "a", "status": "success", "n": 1}, "not json",
            {"schedule_id": "b", "status": "success", "n": 2},
            {"schedule_id": "a", "status": "failure", "n": 3},
            {"schedule_id": "a", "status": "success", "n": 4}]
    path.write_text("\n".join(row if isinstance(row, str) else json.dumps(row)
                              for row in rows) + "\n\n", newline="")
    assert [row["n"] for row in await history.query("a", status="success")] == [4, 1]
    assert [row["n"] for row in await history.query(limit=2)] == [4, 3]


async def test_history_pruning_edges(paths, monkeypatch, sddl):
    import src.scheduler.history as module
    from src.scheduler.history import ScheduleHistory

    path = paths.data_dir / "schedule_history.jsonl"
    history = ScheduleHistory(str(path), max_entries_per_schedule=1)
    assert await history._prune_locked() == 0  # no file
    path.write_text(json.dumps({"schedule_id": "s", "timestamp": "1"}) + "\n\nnot json\n",
                    newline="")
    assert await history._prune_locked() == 0  # under the cap
    monkeypatch.setattr(module, "MAX_TOTAL_ENTRIES", 0)
    monkeypatch.setattr(engine, "_publish_path", lambda path, data: False)
    path.write_text("".join(json.dumps({"schedule_id": "s", "timestamp": str(n)}) + "\n"
                            for n in range(3)), newline="")
    assert await history._prune_locked() == 0  # committed, flush unproven: logged
    monkeypatch.setattr(engine, "_publish_path", refused)
    assert await history._prune_locked() == 0  # could not write: logged
    sddl(path, EVERYONE_FILE, directory=False)
    assert await history._prune_locked() == 0  # not private: unread, logged


async def test_history_appends_trigger_their_periodic_prune(paths):
    from src.scheduler.history import ScheduleHistory

    history = ScheduleHistory(str(paths.data_dir / "schedule_history.jsonl"))
    history._auto_prune_interval = 1
    pruned = []

    async def prune():
        pruned.append(True)
        return 0

    history._prune_locked = prune
    await history.record(schedule_id="s", description="d", action="reminder",
                         status="success", duration_ms=1)
    assert pruned == [True] and history._records_since_prune == 0


# --- audit -------------------------------------------------------------------------------------


def logger_at(path):
    from src.audit.logger import AuditLogger

    return AuditLogger(path=str(path), hmac_key="k" * 32)


async def test_an_unproven_intent_marker_fences_before_any_byte(paths, monkeypatch):
    import src.audit.logger as audit_module

    path = paths.data_dir / "audit.jsonl"
    logger = logger_at(path)
    await logger.initialize_chain()
    monkeypatch.setattr(audit_module, "write_private_atomic", lambda *args, **kwargs: False)
    with pytest.raises(OSError, match="intent durability unproven"):
        await logger._append_durable('{"event": 1}\n')
    assert logger.repair_required and not path.read_bytes()


async def test_a_refused_log_with_a_marker_present_keeps_the_fence(paths, sddl):
    path = paths.data_dir / "audit.jsonl"
    logger = logger_at(path)
    path.write_text("", newline="")
    sddl(path, EVERYONE_FILE, directory=False)
    logger._repair_marker.write_text("pending\n")
    with pytest.raises(PermissionError):
        await logger._append_durable('{"event": 1}\n')
    assert logger.repair_required


async def test_rotation_and_snapshots_report_what_they_cannot_open(paths, monkeypatch, sddl):
    path = paths.data_dir / "audit.jsonl"
    logger = logger_at(path)
    logger._max_bytes = 1
    await logger.initialize_chain()
    await logger._persist({"event": 1})
    rotated = path.with_name("audit.jsonl.2")
    rotated.write_text("{}\n", newline="")
    sddl(rotated, EVERYONE_FILE, directory=False)
    path.with_name("audit.jsonl.1").write_text("{}\n", newline="")
    logger._maybe_rotate()  # the shared generation can't move: logged, nothing lost
    assert rotated.exists() and path.exists()
    snapshot = await logger.open_read_snapshot()
    try:
        assert len(snapshot) == 2  # current and .1; the shared .2 is refused
    finally:
        for handle, _ in snapshot:
            handle.close()
    monkeypatch.setattr(engine, "HeldChain", lambda *args, **kwargs: refused())
    logger._maybe_rotate()
    assert await logger.open_read_snapshot() == []


async def test_snapshot_reports_a_failed_stat(paths, monkeypatch):
    path = paths.data_dir / "audit.jsonl"
    logger = logger_at(path)
    await logger.initialize_chain()
    await logger._persist({"event": 1})
    monkeypatch.setattr(engine.os, "fstat", refused)
    assert await logger.open_read_snapshot() == []


def test_chain_verification_without_a_file_or_with_an_unreadable_one(paths, sddl):
    path = paths.data_dir / "audit.jsonl"
    assert engine._verify_audit(path, "k" * 32)["valid"] is True
    path.write_text("{}\n", newline="")
    sddl(path, EVERYONE_FILE, directory=False)
    result = engine._verify_audit(path, "k" * 32)
    assert result["valid"] is False and result["error"]


async def test_an_initialized_chain_is_not_read_twice(paths):
    logger = logger_at(paths.data_dir / "audit.jsonl")
    await logger.initialize_chain()
    await logger.initialize_chain()
    assert logger._chain_initialized


# --- turn state --------------------------------------------------------------------------------


def test_turn_state_reopens_existing_blobs_and_reports_a_closed_store(paths):
    from src.turn_state.store import TurnStateStore, TurnStateUnavailableError

    database = paths.data_dir / "turn_state" / "turns.sqlite3"
    store = TurnStateStore(database)
    reference = store.store_blob_sync(b"kept")
    store.close()
    reopened = TurnStateStore(database)  # the existing blobs are checked first
    try:
        assert reopened.load_blob_sync(reference) == b"kept"
    finally:
        reopened.close()
    with pytest.raises(TurnStateUnavailableError, match="blob read failed"):
        reopened.load_blob_sync(reference)


def test_a_damaged_database_leaves_the_store_off_and_releases_its_folders(paths):
    from src.turn_state.store import TurnStateStore

    folder = paths.data_dir / "turn_state"
    folder.mkdir()
    (folder / "turns.sqlite3").write_bytes(b"not a database" * 100)
    store = TurnStateStore(folder / "turns.sqlite3")
    assert not store.available
    # Our chains are released. (Linux's constructor leaves its failed connection to
    # garbage collection, which pytest's captured log record delays, so the database
    # folder itself is not renamed here.)
    assert store._windows_chain is None and store._windows_blob_chain is None
    os.rename(folder / "blobs", folder / "blobs-moved")


def test_a_constructor_that_raises_releases_its_folders(paths, monkeypatch):
    from src.turn_state.store import TurnStateStore

    def broken(self, *args, **kwargs):
        raise RuntimeError("constructor failed")

    monkeypatch.setattr(TurnStateStore.__init__, "linux_original", broken)
    folder = paths.data_dir / "turn_state"
    with pytest.raises(RuntimeError):
        TurnStateStore(folder / "turns.sqlite3")
    os.rename(folder, folder.with_name("moved"))


def test_restricting_modes_stays_best_effort(paths, monkeypatch):
    from src.turn_state.store import TurnStateStore

    store = TurnStateStore(paths.data_dir / "turn_state" / "turns.sqlite3")
    try:
        monkeypatch.setattr(engine, "held", refused)
        store._restrict_db_modes()  # no raise, as on Linux
    finally:
        monkeypatch.undo()
        store.close()


# --- handles stay owned when a size check itself fails ---------------------------------------


def test_a_failing_size_check_closes_the_handle(paths, monkeypatch):
    from src.llm.account_key import _read_established_key
    from src.permissions.host_access import HostAccessManager
    from src.permissions.persistence import write_private_atomic

    preferences = paths.config_dir / "host-preferences.json"
    write_private_atomic(preferences, json.dumps({"default_host": "server"}))
    key = paths.data_dir / "account.key"
    write_private_atomic(key, "x" * 32)
    store = paths.data_dir / "windows.json"
    store.write_text("{}")
    closed = []
    real_close = win32.close
    monkeypatch.setattr(win32, "close", lambda handle: (closed.append(handle),
                                                       real_close(handle)))
    monkeypatch.setattr(engine, "file_size", refused)
    assert HostAccessManager(preferences).default_host == ""
    assert _read_established_key(key).material is None
    with pytest.raises(OSError):
        engine.read_store_bytes(store)
    assert len(closed) >= 3
