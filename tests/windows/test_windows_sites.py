"""The routed storage functions on Windows: identity, journal, packages, audit, saves."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.desktop.platform import win32, windows_files
from src.desktop.platform.windows import windows_profile_paths
from src.desktop.platform.windows_files import dacl_is_private, held, tombstones


@pytest.fixture
def paths(tmp_path):
    profile = windows_profile_paths("test", environ={"LOCALAPPDATA": str(tmp_path)})
    profile.create_private()
    return profile


def _private(path, *, directory=False):
    with held(path if directory else path.parent) as chain:
        if directory:
            return dacl_is_private(win32.object_security(chain.handle))
        handle = windows_files.open_file(chain, path.name, links=False)
        try:
            return dacl_is_private(win32.object_security(handle))
        finally:
            win32.close(handle)


# --- identity, locks and the IPC credential ---------------------------------------------------


def test_owner_identity_is_the_user_sid_and_survives_a_reload(paths):
    from src.desktop.authority import OwnerAuthority

    first = OwnerAuthority(paths)
    record = json.loads(paths.identity_file.read_text())
    assert record["owner_sid"] == windows_files.user_sid() and "owner_uid" not in record
    assert _private(paths.identity_file)
    second = OwnerAuthority(paths)
    assert (second.installation_id, second.owner_id) == (first.installation_id, first.owner_id)
    context = second.authenticate_local(peer_uid=windows_files.user_sid())
    assert second.accepts(context)
    for wrong in (os.getpid(), "S-1-5-21-1-2-3-500"):
        with pytest.raises(PermissionError, match="not the profile owner"):
            second.authenticate_local(peer_uid=wrong)
    second.release_runtime()


def test_runtime_lock_admits_one_core_per_profile(paths):
    from src.desktop.authority import OwnerAuthority

    first, second = OwnerAuthority(paths), OwnerAuthority(paths)
    first.acquire_runtime()
    assert first._runtime_current()
    with pytest.raises(BlockingIOError):
        second.acquire_runtime()
    # The held lock file can't be swapped out from under its owner.
    with pytest.raises(PermissionError):
        os.replace(paths.config_dir / ".identity.lock", paths.config_dir / ".core.lock")
    first.release_runtime()
    second.acquire_runtime()
    second.release_runtime()


def test_a_foreign_identity_record_is_refused(paths):
    from src.desktop.authority import OwnerAuthority

    OwnerAuthority(paths)
    record = json.loads(paths.identity_file.read_text())
    record["owner_sid"] = "S-1-5-21-1-2-3-1001"
    from src.permissions.persistence import write_private_atomic

    write_private_atomic(paths.identity_file, json.dumps(record))
    with pytest.raises(ValueError, match="foreign or invalid profile identity"):
        OwnerAuthority(paths)


def test_ipc_token_must_be_private_exact_and_hex(paths, sddl):
    from src.desktop.ipc_auth import load_token

    token = paths.config_dir / "ipc.token"
    token.write_text("ab" * 32)
    assert load_token(token) == "ab" * 32
    token.write_text("ab" * 31)
    with pytest.raises(PermissionError, match="unsafe IPC credential file"):
        load_token(token)
    token.write_text("zz" * 32)
    with pytest.raises(PermissionError, match="invalid IPC credential"):
        load_token(token)
    token.write_text("ab" * 32)
    sddl(token, "D:PAI(A;;FA;;;WD)(A;;FA;;;OW)", directory=False)
    with pytest.raises(PermissionError, match="unsafe IPC credential file"):
        load_token(token)


# --- the conversation journal ---------------------------------------------------------------


def test_journal_opens_creates_reopens_and_releases_its_folder(paths):
    from src.desktop.commands import JournalStorageError, JournalStore

    database = paths.data_dir / "journal" / "transport.sqlite3"
    store = JournalStore(database, "test", identity="install:owner")
    tables = {row[0] for row in store.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"journal_meta", "command_receipts", "journal_events"} <= tables
    with pytest.raises(PermissionError):
        os.rename(database.parent, database.parent.with_name("moved"))
    store.close()
    os.rename(database.parent, database.parent.with_name("moved"))
    os.rename(database.parent.with_name("moved"), database.parent)
    again = JournalStore(database, "test", identity="install:owner")
    again.close()
    with pytest.raises(JournalStorageError):
        JournalStore(database, "test", identity="someone:else")
    assert _private(database)


def test_binding_key_is_created_once_and_read_back(paths):
    from src.desktop.management import _binding_key

    first = _binding_key(paths)
    assert len(first) == 32 and _binding_key(paths) == first
    assert _private(paths.data_dir / "command-binding.key")


# --- a fresh profile and the package records a core start writes ----------------------------


def test_fresh_profile_provisioning_and_package_records(paths):
    from src.desktop.authority import OwnerAuthority
    from src.desktop.package_state import PackageUpgrade, inspect_profile
    from src.desktop.provisioning import ensure_profile

    authority = OwnerAuthority(paths)
    config = ensure_profile(paths, authority=authority)
    assert paths.config_file.is_file() and _private(paths.config_file)
    assert config.timezone == "UTC"
    key = paths.secrets_dir / "id_ed25519"
    assert key.is_file() and _private(key)
    assert config.tools.ssh_pool.socket_dir == str(paths.cache_dir / "ssh")
    assert inspect_profile(paths) is None
    authority.acquire_runtime()
    upgrade = PackageUpgrade(paths, authority, "9.9.9")
    upgrade.prepare()
    assert upgrade.record["state"] == "pending"
    upgrade.commit()
    record = inspect_profile(paths, package_version="9.9.9")
    assert record["state"] == "committed"
    backup = paths.data_dir / "package-backups" / record["backup"]
    assert (backup / "manifest.json").is_file()
    authority.release_runtime()


def test_owner_display_name_reads_only_a_private_folder(paths, sddl):
    from src.desktop.requests import OWNER_NAME, owner_display_name

    folder = paths.config_dir / "display-profile"
    folder.mkdir()
    (folder / "profile.json").write_text(json.dumps({"name": "Aaron"}))
    assert owner_display_name(paths.config_dir) == "Aaron"
    sddl(folder, "D:P(A;OICI;FA;;;WD)(A;OICI;FA;;;OW)", directory=True)
    assert owner_display_name(paths.config_dir) == OWNER_NAME


def test_boot_id_comes_from_the_kernel():
    from src.desktop.resource_cleanup import current_boot_id

    value = current_boot_id()
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value)
    assert current_boot_id() == value


def test_workspace_usage_counts_without_following_junctions(tmp_path):
    import _winapi

    from src.desktop.workspace_diagnostics import _usage

    root = tmp_path / "work"
    (root / "nested").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"12345")
    (root / "nested" / "b.txt").write_bytes(b"123")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"x" * 1000)
    _winapi.CreateJunction(str(outside), str(root / "link"))
    import time

    result = _usage(root, time.monotonic() + 30)
    assert (result["bytes"], result["files"], result["symlinks_skipped"]) == (8, 2, 1)
    assert result["complete"]


# --- saves with strict, degraded and best-effort outcomes ------------------------------------


def _fail_final_flush(monkeypatch):
    """Let the temp file's flush pass, then fail the flush after the rename."""
    real, calls = win32.flush, []

    def flush(handle):
        calls.append(handle)
        if len(calls) == 2:
            raise OSError("flush failed")
        real(handle)

    monkeypatch.setattr(win32, "flush", flush)


def test_write_private_atomic_proves_or_degrades(paths, monkeypatch):
    from src.permissions.persistence import write_private_atomic

    target = paths.data_dir / "state.json"
    assert write_private_atomic(target, "{}") is True
    _fail_final_flush(monkeypatch)
    assert write_private_atomic(target, '{"a": 1}') is False
    monkeypatch.undo()
    assert target.read_text() == '{"a": 1}'


def test_session_publication_after_a_failed_flush_is_published_but_unsynced(paths, monkeypatch):
    from src.sessions.manager import _atomic_json, _PublishedButUnsyncedError

    target = paths.data_dir / "sessions" / "channel.json"
    target.parent.mkdir()
    _atomic_json(target, {"epoch": 1})
    _fail_final_flush(monkeypatch)
    with pytest.raises(_PublishedButUnsyncedError):
        _atomic_json(target, {"epoch": 2})
    monkeypatch.undo()
    assert json.loads(target.read_text()) == {"epoch": 2}


def test_agent_result_publication_is_strict(paths, monkeypatch):
    from src.agents.results import publish_result, result_path

    publish_result(paths.data_dir, {"id": "agent-1", "status": "done"})
    assert json.loads(result_path(paths.data_dir, "agent-1").read_text())["status"] == "done"
    _fail_final_flush(monkeypatch)
    with pytest.raises(OSError):
        publish_result(paths.data_dir, {"id": "agent-1", "status": "again"})


async def test_interrupted_history_recovery_is_strict_and_pruning_works(paths, monkeypatch):
    from src.scheduler.history import ScheduleHistory

    history = ScheduleHistory(str(paths.data_dir / "schedule_history.jsonl"))
    pending = {"schedule_id": "s1", "status": "unknown", "run_binding": "r1", "error": "lost"}
    await history.record_interrupted(pending)
    await history.record_interrupted(pending)
    lines = (paths.data_dir / "schedule_history.jsonl").read_text().splitlines()
    assert len(lines) == 1
    real = windows_files.flush_path

    def failing(path):
        raise OSError("flush failed")

    import src.desktop.platform.windows_engine as engine

    monkeypatch.setattr(engine, "flush_path", failing)
    with pytest.raises(OSError):
        await history.record_interrupted({**pending, "run_binding": "r2"})
    monkeypatch.setattr(engine, "flush_path", real)


async def test_audit_append_retires_its_marker_without_leftovers(paths):
    from src.audit.logger import AuditLogger

    logger = AuditLogger(str(paths.data_dir / "audit.jsonl"))
    await logger.initialize_chain()
    await logger._append_durable('{"event": 1}\n')
    marker = logger._repair_marker
    assert not marker.exists()
    with held(marker.parent) as chain:
        assert tombstones(chain, marker.name) == []
    assert not logger.repair_required


async def test_failed_retirement_keeps_the_fence_for_the_next_process(paths, monkeypatch):
    import src.audit.logger as audit_module
    import src.desktop.platform.windows_engine as engine
    from src.audit.logger import AuditLogger

    path = paths.data_dir / "audit.jsonl"
    logger = AuditLogger(str(path))
    await logger.initialize_chain()
    real_retire = windows_files.retire

    def rename_then_fail(chain, name):
        # The rename commits, then its flush fails; the quarantine's marker
        # re-publication fails too, so only the tombstone remains on disk.
        monkeypatch.setattr(win32, "flush", lambda handle: (_ for _ in ()).throw(
            OSError("flush failed")))
        monkeypatch.setattr(audit_module, "write_private_atomic", lambda *a, **k: (
            _ for _ in ()).throw(OSError("marker failed")))
        return real_retire(chain, name)

    monkeypatch.setattr(engine, "retire", rename_then_fail)
    with pytest.raises(OSError):
        await logger._append_durable('{"event": 1}\n')
    monkeypatch.undo()
    assert logger.repair_required
    assert not logger._repair_marker.exists()
    with held(path.parent) as chain:
        assert len(tombstones(chain, logger._repair_marker.name)) == 1
    successor = AuditLogger(str(path))
    assert successor.repair_required and successor.durability_degraded
    await successor.initialize_chain()
    assert not successor.repair_required
    with held(path.parent) as chain:
        assert tombstones(chain, successor._repair_marker.name) == []
    assert not successor._repair_marker.exists()


@pytest.mark.parametrize("step", ["publish", "retire", "flush_other"])
async def test_a_failed_settlement_step_keeps_every_fence(paths, monkeypatch, step):
    import src.desktop.platform.windows_engine as engine
    from src.audit.logger import AuditLogger

    path = paths.data_dir / "audit.jsonl"
    path.write_text('{"event": 1}\n')
    marker = path.with_name(path.name + ".repair-required")
    for suffix in ("a" * 32, "b" * 32):
        Path(f"{marker}.retiring-{suffix}").write_bytes(b"")
    if step != "publish":
        marker.write_text("pending\n")
    failing = {"publish": "publish", "retire": "retire", "flush_other": "flush_object"}[step]
    monkeypatch.setattr(engine, failing, lambda *a, **k: (_ for _ in ()).throw(OSError(step)))
    logger = AuditLogger(str(path))
    assert logger.repair_required
    await logger.initialize_chain()
    assert logger.repair_required
    monkeypatch.undo()
    with held(path.parent) as chain:
        assert len(tombstones(chain, marker.name)) >= 2
    restarted = AuditLogger(str(path))
    assert restarted.repair_required
    await restarted.initialize_chain()
    assert not restarted.repair_required
    with held(path.parent) as chain:
        assert tombstones(chain, marker.name) == []


# --- keys, stores, markers and the config file ------------------------------------------------


def test_account_key_has_one_winner(tmp_path):
    from src.llm.account_key import _create_key, _read_established_key

    key = tmp_path / "keys" / "account_key.secret"
    material = _create_key(key)
    assert len(material) == 32 and _read_established_key(key).material == material
    assert _create_key(key) == material
    assert _read_established_key(tmp_path / "missing" / "k").missing


def test_window_store_round_trip(tmp_path):
    from src.llm.window_observer import _read_store_bytes

    path = tmp_path / "context_windows.json"
    assert _read_store_bytes(path) is None
    path.write_text('{"a": 1}')
    assert _read_store_bytes(path) == b'{"a": 1}'


def test_migration_marker_and_legacy_claim(tmp_path):
    from src.config.migrations import _atomic_write_marker, _claim_legacy_marker

    marker = tmp_path / "migrations" / "marker.json"
    _atomic_write_marker(marker, {"done": True})
    assert json.loads(marker.read_text()) == {"done": True}
    legacy = tmp_path / "migrations" / "legacy.json"
    assert _claim_legacy_marker(legacy, "a" * 64) is True
    assert _claim_legacy_marker(legacy, "a" * 64) is True
    assert _claim_legacy_marker(legacy, "b" * 64) is False


def test_config_lock_and_atomic_dump(paths):
    from src.config.persistence import _config_file_lock, _dump_atomic

    paths.config_file.write_text("timezone: UTC\n")
    with _config_file_lock(paths.config_file):
        _dump_atomic(None, paths.config_file, 0o600, raw_text="timezone: Europe/Paris\n")
    assert paths.config_file.read_text() == "timezone: Europe/Paris\n"


def test_turn_state_store_is_private_before_it_opens(paths, sddl):
    from src.turn_state.store import TurnStateStore

    folder = paths.data_dir / "turn_state"
    folder.mkdir()
    database = folder / "turns.sqlite3"
    sqlite3.connect(database).close()
    sddl(database, "D:PAI(A;;FA;;;WD)(A;;FA;;;OW)", directory=False)
    store = TurnStateStore(database)
    assert store._conn is not None
    assert _private(database) and _private(folder, directory=True)
    store._conn.close()


def test_turn_state_store_stays_off_when_privacy_fails(paths, monkeypatch):
    import src.desktop.platform.windows_engine as engine
    from src.turn_state.store import TurnStateStore

    monkeypatch.setattr(engine, "ensure_private",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError("refused")))
    store = TurnStateStore(paths.data_dir / "turn_state" / "turns.sqlite3")
    assert store._conn is None
    assert not (paths.data_dir / "turn_state" / "turns.sqlite3").exists()


def test_startup_workspace_check_uses_the_windows_resolver(paths):
    from src.health.startup import check_local_workspace

    workspace = paths.data_dir / "workspace"
    result = check_local_workspace(SimpleNamespace(local_working_dir=str(workspace)))
    assert result.passed, result.detail
    assert _private(workspace, directory=True)


def test_asyncio_runs_on_windows():
    assert asyncio.run(asyncio.sleep(0, result=7)) == 7
