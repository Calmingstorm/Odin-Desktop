"""Refusals and the remaining routed paths on Windows: each keeps its Linux decision."""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.desktop.platform.windows_engine as engine
from src.desktop.platform import win32, windows_files
from src.desktop.platform.windows import windows_profile_paths
from src.desktop.platform.windows_files import dacl_is_private, held

EVERYONE_FILE = "D:PAI(A;;FA;;;WD)(A;;FA;;;OW)"
EVERYONE_FOLDER = "D:P(A;OICI;FA;;;WD)(A;OICI;FA;;;OW)"


@pytest.fixture
def paths(tmp_path):
    profile = windows_profile_paths("test", environ={"LOCALAPPDATA": str(tmp_path)})
    profile.create_private()
    return profile


# --- authority ---------------------------------------------------------------------------------


def test_app_bootstrap_files_are_adopted_and_strays_refused(paths):
    from src.desktop.authority import OwnerAuthority

    (paths.config_dir / "ipc.token").write_text("ab" * 32)
    (paths.config_dir / "app-state.json").write_text("{}")
    (paths.data_dir / "drafts.json").write_text("{}")
    (paths.data_dir / "logs").mkdir()
    (paths.data_dir / "logs" / "core.log").write_text("started\n")
    authority = OwnerAuthority(paths, app_bootstrap=True)
    assert authority.installation_id


def test_unexpected_engine_logs_have_no_identity(paths):
    from src.desktop.authority import OwnerAuthority

    (paths.data_dir / "logs").mkdir()
    (paths.data_dir / "logs" / "other.log").write_text("x")
    with pytest.raises(ValueError, match="engine logs have no identity"):
        OwnerAuthority(paths, app_bootstrap=True)


def test_a_shared_bootstrap_file_is_refused(paths, sddl):
    from src.desktop.authority import OwnerAuthority

    token = paths.config_dir / "ipc.token"
    token.write_text("ab" * 32)
    sddl(token, EVERYONE_FILE, directory=False)
    with pytest.raises(PermissionError, match="unsafe app bootstrap file"):
        OwnerAuthority(paths, app_bootstrap=True)


def test_existing_state_without_identity_needs_explicit_recovery(paths):
    from src.desktop.authority import OwnerAuthority

    (paths.config_dir / "config.yml").write_text("{}")
    with pytest.raises(ValueError, match="existing state has no identity"):
        OwnerAuthority(paths)


def test_an_oversized_or_duplicate_identity_record_is_refused(paths):
    from src.desktop.authority import OwnerAuthority
    from src.permissions.persistence import write_private_atomic

    OwnerAuthority(paths)
    write_private_atomic(paths.identity_file, "{" + " " * 4100 + "}")
    with pytest.raises(PermissionError, match="unsafe profile identity record"):
        OwnerAuthority(paths)
    write_private_atomic(paths.identity_file, '{"version": 1, "version": 1}')
    with pytest.raises(ValueError):
        OwnerAuthority(paths)


def test_runtime_reacquisition_and_degraded_identity(paths):
    from src.desktop.authority import OwnerAuthority

    authority = OwnerAuthority(paths)
    authority.acquire_runtime()
    authority.acquire_runtime()  # already held: just rechecked
    assert authority._identity_current()
    authority.durability_degraded = True
    with pytest.raises(PermissionError, match="durability unproven"):
        authority.authenticate_local(peer_uid=windows_files.user_sid())
    authority.release_runtime()
    assert not authority._runtime_current()


# --- journal, binding key, display name, diagnostics -------------------------------------------


def test_a_shared_journal_sidecar_is_refused(paths, sddl):
    from src.desktop.commands import JournalStorageError, JournalStore

    folder = paths.data_dir / "journal"
    folder.mkdir()
    sidecar = folder / "transport.sqlite3-journal"
    sidecar.write_bytes(b"")
    sddl(sidecar, EVERYONE_FILE, directory=False)
    with pytest.raises(JournalStorageError):
        JournalStore(folder / "transport.sqlite3", "test")


@pytest.mark.parametrize("content", ["ab" * 31, "zz" * 32])
def test_a_malformed_binding_key_is_refused(paths, content):
    from src.desktop.commands import JournalStorageError
    from src.desktop.management import _binding_key
    from src.permissions.persistence import write_private_atomic

    write_private_atomic(paths.data_dir / "command-binding.key", content)
    with pytest.raises(JournalStorageError):
        _binding_key(paths)


def test_display_name_defaults(paths):
    from src.desktop.requests import OWNER_NAME, owner_display_name

    assert owner_display_name(None) == OWNER_NAME
    folder = paths.config_dir / "display-profile"
    folder.mkdir()
    (folder / "profile.json").write_text(json.dumps({"name": "x" * 41}))
    assert owner_display_name(paths.config_dir) == OWNER_NAME
    (folder / "profile.json").write_text(json.dumps({"name": "ok"}) + " " * 5000)
    assert owner_display_name(paths.config_dir) == OWNER_NAME


def test_workspace_diagnostics_collect(paths):
    from src.desktop.workspace_diagnostics import WorkspaceDiagnostics

    workspace = paths.data_dir / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("hello")
    executor = SimpleNamespace(_ensure_local_workspace=lambda: str(workspace))
    diagnostics = object.__new__(WorkspaceDiagnostics)
    diagnostics._executor_provider = lambda: executor
    report = diagnostics._collect()
    assert report["status"] == "ok" and report["usage"]["bytes"] == 5
    assert report["disk"]["free_bytes"] > 0 and "free_inodes" not in report["disk"]
    diagnostics._executor_provider = lambda: (_ for _ in ()).throw(RuntimeError("no executor"))
    assert diagnostics._collect()["reason"] == "workspace_unusable"


def test_prepare_socket_directory_creates_it_privately(paths):
    from src.desktop.ssh_sockets import prepare_socket_directory, socket_directory

    target = socket_directory(paths)
    prepare_socket_directory(target)
    with held(target) as chain:
        assert dacl_is_private(win32.object_security(chain.handle))


# --- package state ----------------------------------------------------------------------------


def test_package_upgrade_to_a_new_version_reuses_the_backup_folder(paths):
    from src.desktop.authority import OwnerAuthority
    from src.desktop.package_state import PackageStateError, PackageUpgrade, inspect_profile
    from src.desktop.provisioning import ensure_profile

    authority = OwnerAuthority(paths)
    ensure_profile(paths, authority=authority)
    authority.acquire_runtime()
    first = PackageUpgrade(paths, authority, "1.0.0")
    first.prepare()
    first.commit()
    second = PackageUpgrade(paths, authority, "2.0.0")
    second.prepare()
    assert second.record["state"] == "pending"
    with pytest.raises(PackageStateError, match="compatible candidate"):
        inspect_profile(paths, package_version="1.0.0")
    second.commit()
    assert len(list((paths.data_dir / "package-backups").iterdir())) == 2
    authority.release_runtime()


def test_a_failed_package_record_flush_is_an_error(paths, monkeypatch):
    from src.desktop.package_state import _publish

    monkeypatch.setattr("src.desktop.platform.windows_desktop.publish", lambda *a, **k: False)
    with pytest.raises(OSError, match="durability is unproven"):
        _publish(paths.data_dir / "package-state.json", {"a": 1})


# --- host preference, window store, account key ------------------------------------------------


def test_default_host_preference(paths, sddl):
    from src.permissions.host_access import HostAccessManager
    from src.permissions.persistence import write_private_atomic

    path = paths.config_dir / "host-preferences.json"
    manager = HostAccessManager(path)
    assert manager.default_host == ""
    write_private_atomic(path, json.dumps({"default_host": "server"}))
    assert manager.default_host == "server"
    write_private_atomic(path, json.dumps({"default_host": "x" * 70000}))
    assert manager.default_host == ""
    write_private_atomic(path, json.dumps({"default_host": "server"}))
    sddl(path, EVERYONE_FILE, directory=False)
    assert manager.default_host == ""


def test_window_store_persistence_and_refusals(tmp_path, monkeypatch):
    from src.llm.window_observer import _read_store_bytes

    observer = SimpleNamespace(_state={"windows": {}}, _path=tmp_path / "observer" / "store.json")
    engine.window_persist_locked(observer)
    assert json.loads(observer._path.read_text()) == {"windows": {}}
    (tmp_path / "folder.json").mkdir()
    with pytest.raises(ValueError, match="unreadable"):
        _read_store_bytes(tmp_path / "folder.json")
    monkeypatch.setattr("src.llm.window_observer._MAX_STORE_BYTES", 2)
    with pytest.raises(ValueError, match="too large"):
        _read_store_bytes(observer._path)
    monkeypatch.setattr(engine, "_publish_path", lambda *a, **k: False)
    with pytest.raises(OSError, match="durability"):
        engine.window_persist_locked(observer)


def test_account_key_refusals(tmp_path, sddl):
    from src.llm.account_key import _create_key, _fsync_parent, _read_established_key

    key = tmp_path / "account_key.secret"
    key.write_bytes(b"short")
    assert _read_established_key(key).material is None
    key.write_bytes(b"k" * 32)
    sddl(key, EVERYONE_FILE, directory=False)
    assert _read_established_key(key).material is None
    _fsync_parent(key)
    blocked = tmp_path / "file-not-folder"
    blocked.write_bytes(b"")
    assert _create_key(blocked / "account_key.secret") is None


# --- config persistence and migrations ---------------------------------------------------------


def test_config_lock_refuses_a_shared_lock_folder(paths, sddl, monkeypatch, tmp_path):
    import hashlib
    import tempfile

    from src.config.persistence import ConfigPersistError, _config_file_lock

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    owner = hashlib.sha256(windows_files.user_sid().encode()).hexdigest()[:16]
    folder = tmp_path / f"odin-config-locks-{owner}"
    folder.mkdir()
    sddl(folder, EVERYONE_FOLDER, directory=True)
    with pytest.raises(ConfigPersistError, match="unsafe config lock directory"):
        with _config_file_lock(paths.config_file):
            pass


def test_dump_atomic_serializes_a_document(paths):
    from ruamel.yaml import YAML

    from src.config.persistence import _dump_atomic

    paths.config_file.write_text("a: 1\n")
    document = YAML().load("a: 1\nlist:\n- x\n")
    document["a"] = 2
    _dump_atomic(document, paths.config_file, 0o600, sequence_indent=2)
    assert "a: 2" in paths.config_file.read_text()


def test_dump_atomic_refuses_a_shared_config(paths, sddl):
    from src.config.persistence import _dump_atomic

    paths.config_file.write_text("a: 1\n")
    sddl(paths.config_file, EVERYONE_FILE, directory=False)
    with pytest.raises(PermissionError):
        _dump_atomic(None, paths.config_file, 0o600, raw_text="a: 2\n")


def test_legacy_claim_failure_is_a_migration_error(tmp_path):
    from src.config.migrations import MigrationCompletionError, _claim_legacy_marker

    blocked = tmp_path / "not-a-folder"
    blocked.write_bytes(b"")
    with pytest.raises(MigrationCompletionError):
        _claim_legacy_marker(blocked / "legacy.json", "a" * 64)


# --- history, audit, turn state, workspace -----------------------------------------------------


async def test_history_pruning_keeps_the_latest_entries(paths):
    from src.scheduler.history import MAX_TOTAL_ENTRIES, ScheduleHistory

    path = paths.data_dir / "schedule_history.jsonl"
    entries = [{"schedule_id": "s1", "timestamp": f"2026-10-10T00:00:{i:05d}", "n": i}
               for i in range(MAX_TOTAL_ENTRIES + 50)]
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
    history = ScheduleHistory(str(path))
    removed = await history._prune_locked()
    assert removed == len(entries) - history._max_per_schedule
    kept = [json.loads(line) for line in path.read_text().splitlines()]
    assert kept[-1]["n"] == len(entries) - 1


async def test_interrupted_history_rejects_a_settled_status(paths):
    from src.scheduler.history import ScheduleHistory

    history = ScheduleHistory(str(paths.data_dir / "schedule_history.jsonl"))
    with pytest.raises(ValueError, match="unknown status"):
        await history.record_interrupted({"schedule_id": "s", "status": "ok"})


async def test_audit_unsettled_tail_is_quarantined_and_signed_chains_resume(paths):
    from src.audit.logger import AuditLogger

    path = paths.data_dir / "audit.jsonl"
    path.write_text('{"event": 1}')  # no trailing newline: an unsettled append
    logger = AuditLogger(str(path))
    await logger.initialize_chain()
    assert logger.repair_required
    signed = AuditLogger(str(paths.data_dir / "signed.jsonl"), hmac_key="k" * 32)
    await signed.initialize_chain()
    await signed._append_durable('{"event": 1}\n')
    assert engine._marker_tombstones(paths.data_dir / "missing" / "marker") == []


def test_turn_state_restricts_its_sidecars(paths):
    from src.turn_state.store import TurnStateStore

    store = TurnStateStore(paths.data_dir / "turn_state" / "turns.sqlite3")
    assert store._conn is not None
    store._restrict_db_modes()
    store._conn.close()


def test_executor_and_startup_workspace_paths(paths, monkeypatch):
    from src.health.startup import check_local_workspace

    workspace = paths.data_dir / "workspace"
    executor = SimpleNamespace(config=SimpleNamespace(local_working_dir=str(workspace)),
                               _protected_roots=lambda: [str(paths.config_dir)])
    assert Path(engine.ensure_local_workspace(executor)) == workspace.resolve()
    assert executor._local_workspace_resolved
    result = check_local_workspace(SimpleNamespace(local_working_dir="relative"))
    assert not result.passed and "unusable" in result.detail


def test_ssh_key_failures_and_existing_keys(paths, monkeypatch):
    import subprocess

    from src.desktop.authority import OwnerAuthority
    from src.desktop.provisioning import _ensure_ssh_key, fresh_config

    authority = OwnerAuthority(paths)
    config = fresh_config(paths)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        subprocess.SubprocessError("no ssh-keygen")))
    with pytest.raises(RuntimeError, match="SSH key"):
        _ensure_ssh_key(paths, authority, config)
    monkeypatch.undo()
    _ensure_ssh_key(paths, authority, config)
    key = paths.secrets_dir / "id_ed25519"
    before = key.read_bytes()
    _ensure_ssh_key(paths, authority, config)
    assert key.read_bytes() == before


def test_boot_id_failure_is_unknown(monkeypatch):
    from src.desktop.resource_cleanup import current_boot_id

    monkeypatch.setattr(win32, "boot_identifier", lambda: (_ for _ in ()).throw(OSError("no")))
    assert current_boot_id() is None


def test_journal_close_tolerates_a_closed_connection(paths):
    from src.desktop.commands import JournalStore

    store = JournalStore(paths.data_dir / "journal" / "transport.sqlite3", "test")
    store._connection.close()
    store.close()
    store.close()
    assert time.monotonic() > 0
