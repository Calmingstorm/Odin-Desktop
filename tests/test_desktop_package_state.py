"""Real stores and harmless storage faults; run in the isolated PID namespace."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import uuid
from pathlib import Path

import pytest

from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.package_state import (
    BACKUPS_NAME,
    STATE_NAME,
    PackageStateError,
    PackageUpgrade,
    compatibility,
    inspect_profile,
    main,
)
from src.desktop.paths import ProfilePaths
from src.turn_state.store import TurnKey, TurnStateStore


def snapshot(paths):
    return {str(p): (p.read_bytes(), p.stat().st_mode) for root in (
        paths.config_dir, paths.data_dir, paths.cache_dir) if root.exists()
        for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def profile(tmp_path):
    paths = ProfilePaths.from_xdg("upgrade", environ={}, home=tmp_path)
    authority = OwnerAuthority(paths)
    authority.acquire_runtime()
    try:
        yield paths, authority
    finally:
        authority.release_runtime()


def journal(paths, authority):
    return JournalStore(paths.data_dir / "transport.sqlite3", paths.profile_id,
                        identity=f"{authority.installation_id}:{authority.owner_id}")


def marker(paths, authority, **updates):
    value = {"record_version": 1, "profile_id": paths.profile_id,
             "identity": f"{authority.installation_id}:{authority.owner_id}",
             "package_version": "previous", "compatibility": compatibility(),
             "state": "committed", "backup": str(uuid.uuid4())}
    value.update(updates)
    (paths.data_dir / STATE_NAME).write_text(json.dumps(value))
    (paths.data_dir / STATE_NAME).chmod(0o600)


def test_fresh_inspection_creates_nothing(tmp_path):
    paths = ProfilePaths.from_xdg("new", environ={}, home=tmp_path / "empty")
    assert inspect_profile(paths) is None
    assert not (tmp_path / "empty").exists()


@pytest.mark.parametrize("key", list(compatibility()))
def test_newer_independent_versions_refuse_without_writes(profile, key):
    paths, authority = profile
    versions = compatibility()
    versions[key] += 1
    marker(paths, authority, compatibility=versions)
    before = snapshot(paths)
    with pytest.raises(PackageStateError, match="incompatible"):
        inspect_profile(paths)
    assert snapshot(paths) == before


def test_transport_unknown_receipts_survive_compatible_upgrade(profile):
    paths, authority = profile
    store = journal(paths, authority)
    with store.transaction() as db:
        db.execute("INSERT INTO command_receipts VALUES (?,?,?,?,?,?,?)",
                   ("receipt", "binding", "pending", None, 1.0, None, 1))
    store.close()
    before = (paths.data_dir / "transport.sqlite3").read_bytes()
    upgrade = PackageUpgrade(paths, authority, "new-candidate")
    upgrade.prepare()
    record = inspect_profile(paths)
    assert record["state"] == "pending"
    backup = paths.data_dir / BACKUPS_NAME / record["backup"]
    assert (backup / "data/transport.sqlite3").read_bytes() == before
    upgrade.commit()
    assert inspect_profile(paths)["state"] == "committed"
    assert (paths.data_dir / "transport.sqlite3").read_bytes() == before
    with sqlite3.connect(paths.data_dir / "transport.sqlite3") as db:
        assert db.execute("SELECT state,unknown_outcome FROM command_receipts").fetchone() == (
            "pending", 1)


def test_unsupported_transport_shape_refuses_before_backup(profile):
    paths, authority = profile
    store = journal(paths, authority)
    store.connection.execute("CREATE TABLE future_contract (fence TEXT)")
    store.close()
    before = snapshot(paths)
    with pytest.raises(PackageStateError):
        PackageUpgrade(paths, authority, "new").prepare()
    assert snapshot(paths) == before
    assert not (paths.data_dir / BACKUPS_NAME).exists()


@pytest.mark.parametrize("name", ["turns.db", "turns.sqlite3"])
@pytest.mark.parametrize("future", ["schema", "codec", "columns"])
def test_future_actual_turn_store_refuses_without_rejection_or_sweep(profile, name, future):
    paths, _authority = profile
    db_path = paths.data_dir / "turn_state" / name
    store = TurnStateStore(db_path)
    assert store.available
    key = TurnKey("desktop", "conversation", "message")
    store._conn.execute("INSERT INTO turns (source,channel_id,message_id,turn_generation,revision,"
                        "lease_token,status,last_progress_at,created_at,schema_version,payload) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (key.source, key.channel_id, key.message_id, "generation", 19,
                         "fence", "SUSPENDED", 1, 1, 999 if future == "schema" else 1,
                         json.dumps({"codec_version": 999 if future == "codec"
                                     else compatibility()["checkpoint"]})))
    if future == "columns":
        store._conn.execute("ALTER TABLE turns ADD COLUMN future_fence TEXT")
    store._conn.commit()
    store._conn.close()
    before = snapshot(paths)
    with pytest.raises(PackageStateError):
        inspect_profile(paths)
    assert snapshot(paths) == before


def test_preflight_sees_future_version_committed_only_in_wal(profile):
    paths, authority = profile
    store = journal(paths, authority)
    store.close()
    db_path = paths.data_dir / "transport.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("PRAGMA user_version=999")
        db.commit()
        before = snapshot(paths)
        with pytest.raises(PackageStateError, match="Newer transport"):
            inspect_profile(paths)
        assert snapshot(paths) == before


def test_unknown_files_and_fences_retained_in_backup_and_recovery(profile, monkeypatch):
    paths, authority = profile
    (paths.data_dir / "unknown-owner-record.json").write_text('{"unknown":true,"generation":91}')
    (paths.data_dir / "unknown-owner-record.json").chmod(0o600)
    upgrade = PackageUpgrade(paths, authority, "new")
    upgrade.prepare()
    pending = inspect_profile(paths)
    original = (paths.data_dir / "unknown-owner-record.json").read_bytes()
    # A harmless failure after migration but before durable package completion.
    import src.desktop.package_state as package_state

    original_publish = package_state._publish
    def fail_commit(path, value):
        if value.get("state") == "committed":
            raise OSError("temporary storage failure")
        original_publish(path, value)

    monkeypatch.setattr(package_state, "_publish", fail_commit)
    with pytest.raises(OSError):
        upgrade.commit()
    assert inspect_profile(paths) == pending
    assert (paths.data_dir / "unknown-owner-record.json").read_bytes() == original
    monkeypatch.setattr(package_state, "_publish", original_publish)
    recovered = PackageUpgrade(paths, authority, "new")
    recovered.prepare()
    recovered.commit()
    assert inspect_profile(paths)["backup"] == pending["backup"]
    assert inspect_profile(paths)["state"] == "committed"
    assert (paths.data_dir / "unknown-owner-record.json").read_bytes() == original


def test_backup_failure_is_not_completion_or_source_rollback(profile, monkeypatch):
    paths, authority = profile
    (paths.config_file).write_text("timezone: UTC\n")
    paths.config_file.chmod(0o600)
    before = paths.config_file.read_bytes()
    import src.desktop.package_state as package_state

    def unavailable(_fd):
        raise OSError("temporary fsync failure")

    monkeypatch.setattr(package_state.os, "fsync", unavailable)
    with pytest.raises(OSError):
        PackageUpgrade(paths, authority, "new").prepare()
    assert not (paths.data_dir / STATE_NAME).exists()
    assert paths.config_file.read_bytes() == before


def test_interrupted_upgrade_cannot_be_claimed_by_other_candidate(profile):
    paths, authority = profile
    PackageUpgrade(paths, authority, "new").prepare()
    before = snapshot(paths)
    with pytest.raises(PackageStateError, match="Interrupted"):
        PackageUpgrade(paths, authority, "older").prepare()
    assert snapshot(paths) == before


def test_corrupt_backup_never_restores_or_erases_state(profile):
    paths, authority = profile
    paths.config_file.write_text("timezone: UTC\n")
    paths.config_file.chmod(0o600)
    upgrade = PackageUpgrade(paths, authority, "new")
    upgrade.prepare()
    record = inspect_profile(paths)
    backup_file = paths.data_dir / BACKUPS_NAME / record["backup"] / "config/config.yml"
    backup_file.write_text("incomplete copy")
    before = snapshot(paths)
    with pytest.raises(PackageStateError, match="integrity"):
        PackageUpgrade(paths, authority, "new").prepare()
    assert snapshot(paths) == before


def test_runtime_lock_required_before_backup(profile):
    paths, authority = profile
    authority.release_runtime()
    before = snapshot(paths)
    with pytest.raises(PackageStateError, match="ownership"):
        PackageUpgrade(paths, authority, "new").prepare()
    assert snapshot(paths) == before


def test_symlink_refusal_does_not_read_or_modify_other_installation(profile, tmp_path):
    paths, _ = profile
    external = tmp_path / "sentinel"
    external.write_text("independent installation")
    (paths.data_dir / STATE_NAME).symlink_to(external)
    before = external.read_bytes()
    with pytest.raises(PackageStateError):
        inspect_profile(paths)
    assert external.read_bytes() == before


def test_standalone_readonly_cli_refuses_newer_state(profile, capsys):
    paths, authority = profile
    versions = compatibility()
    versions["storage"] = 999
    marker(paths, authority, compatibility=versions)
    before = snapshot(paths)
    assert main(["--profile", paths.profile_id, "--token-file", str(paths.config_dir / "ipc.token"),
                 "--data-dir", str(paths.data_dir)]) == 1
    assert "original state preserved" in capsys.readouterr().out
    assert snapshot(paths) == before


@pytest.mark.asyncio
async def test_core_refuses_future_storage_before_identity_permissions_and_settings(profile):
    from src.desktop.core import CoreService

    paths, authority = profile
    versions = compatibility()
    versions["checkpoint"] = 999
    marker(paths, authority, compatibility=versions)
    authority.release_runtime()
    before = snapshot(paths)
    service = CoreService(paths, paths.cache_dir / "core.sock", paths.config_dir / "ipc.token")
    with pytest.raises(PackageStateError):
        await service.start()
    assert service.authority is None
    assert snapshot(paths) == before


@pytest.mark.asyncio
async def test_previous_candidate_real_stores_upgrade_with_seeded_data(tmp_path):
    """Opt-in candidate proof, not a fabricated historical format fixture.

    Parent qualification supplies the exact previous candidate resources. The
    bundled interpreter imports its own frozen source and constructs its stores.
    """
    resources = os.environ.get("ODIN_TEST_PREVIOUS_CANDIDATE_RESOURCES")
    if not resources:
        pytest.skip("exact previous candidate resources required for candidate upgrade proof")
    root = Path(resources) / "runtime"
    python = root / "python/bin/python3"
    paths = ProfilePaths.from_xdg("upgrade", environ={}, home=tmp_path)
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG"}}
    env.update(HOME=str(tmp_path), ODIN_DESKTOP_PROFILE=paths.profile_id,
               ODIN_DESKTOP_TOKEN_FILE=str(paths.config_dir / "ipc.token"),
               ODIN_DESKTOP_DATA_DIR=str(paths.data_dir), ODIN_DESKTOP_BUNDLE_ROOT=str(root))
    seed = '''
import asyncio,json
from src.desktop.paths import ProfilePaths
from src.desktop.authority import OwnerAuthority
from src.desktop.provisioning import ensure_profile
from src.desktop.commands import JournalStore
from src.desktop.events import EventJournal
from src.desktop.conversations import ConversationStore
from src.desktop.artifacts import ArtifactStore
from src.scheduler import Scheduler
from src.computer.store import ComputerStore
from src.computer.models import RequestContext
from src.turn_state.store import TurnStateStore,TurnKey
p=ProfilePaths.from_xdg("upgrade")
a=OwnerAuthority(p);a.acquire_runtime()
c=ensure_profile(p,authority=a)
j=JournalStore(p.data_dir/"transport.sqlite3",p.profile_id,
               identity=f"{a.installation_id}:{a.owner_id}")
e=EventJournal(j); conversations=ConversationStore(j,e)
cid=conversations.create("previous candidate conversation")["conversation"]["id"]
artifacts=ArtifactStore(j,authorize=lambda *args:True)
artifacts.publish(b"previous artifact",owner=a.owner_id,conversation_id=cid,
                  request_id="preserved-request",name="artifact.txt",mime="text/plain")
with j.transaction() as db:
    db.execute("INSERT INTO command_receipts VALUES (?,?,?,?,?,?,?)",
               ("preserved-unknown","binding","pending",None,1.0,None,1))
j.close()
s=Scheduler(str(p.data_dir/"schedules.json"))
asyncio.run(s.add("preserved reminder","reminder",cid,cron="0 9 * * *",
                  message="preserved",requester_id=a.owner_id))
t=TurnStateStore(p.data_dir/"turn_state/turns.db")
lease,disposition=t.admit_turn_sync(TurnKey("desktop",cid,"preserved-message"),
    guild_id=None,user_id=a.owner_id,content_digest="original",code_version="previous",
    prompt_policy_hash="policy",tool_catalog_hash="tools",session_snapshot={})
t._conn.execute("UPDATE turns SET status='SUSPENDED',revision=19")
t._conn.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("desktop",cid,"preserved-message",lease.generation,7,"unknown-invocation",
     "OUTCOME_UNKNOWN","run_command","EXTERNAL_EFFECT_CAPABLE",3,
     "fingerprint",None,1.0,1.0))
t._conn.commit();t._conn.close()
computer=ComputerStore(p.data_dir/"computer/state.sqlite3",p.data_dir/"computer/evidence")
grant=computer.create_session(RequestContext(a.owner_id,cid,"preserved-turn","localhost"),
                              "drawing")
computer.set_state(grant.session_id,"quarantined",revoke=True)
computer.record_cleanup(grant.session_id,{"stopped":False,"released":False},clean=False)
computer.close()
(p.data_dir/"unknown-extension.json").write_text('{"unknown":true,"generation":73}')
(p.data_dir/"unknown-extension.json").chmod(0o600)
a.release_runtime()
'''
    result = subprocess.run([str(python), "-I", "-B", "-c", seed], env=env,
                            text=True, capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr
    originals = {str(p.relative_to(paths.data_dir)): p.read_bytes()
                 for p in paths.data_dir.rglob("*") if p.is_file()}
    original_config = paths.config_file.read_bytes()
    authority = OwnerAuthority(paths)
    authority.acquire_runtime()
    try:
        upgrade = PackageUpgrade(paths, authority, "next-candidate")
        upgrade.prepare()
        record = inspect_profile(paths)
        # Existing transport migration owners open the real previous journal.
        store = journal(paths, authority)
        from src.desktop.artifacts import ArtifactStore
        from src.desktop.conversations import ConversationStore
        from src.desktop.events import EventJournal

        conversations = ConversationStore(store, EventJournal(store))
        ArtifactStore(store, authorize=lambda *args: True)
        assert conversations.list()["items"][0]["title"] == "previous candidate conversation"
        assert store.connection.execute("SELECT data FROM desktop_artifacts").fetchone()[0] == (
            b"previous artifact")
        assert tuple(store.connection.execute(
            "SELECT state,unknown_outcome FROM command_receipts").fetchone()) == ("pending", 1)
        store.close()
        upgrade.commit()
        backup = paths.data_dir / BACKUPS_NAME / record["backup"] / "data"
        for name, data in originals.items():
            assert (backup / name).read_bytes() == data
        assert paths.config_file.read_bytes() == original_config
        for name in ("schedules.json", "unknown-extension.json", "turn_state/turns.db",
                     "computer/state.sqlite3"):
            assert (paths.data_dir / name).read_bytes() == originals[name]
        with sqlite3.connect(paths.data_dir / "turn_state/turns.db") as db:
            assert db.execute("SELECT revision FROM turns").fetchone()[0] == 19
            assert db.execute("SELECT state FROM operations").fetchone()[0] == "OUTCOME_UNKNOWN"
        with sqlite3.connect(paths.data_dir / "computer/state.sqlite3") as db:
            assert db.execute("SELECT state,generation FROM sessions").fetchone() == (
                "quarantined", 2)
        # Simulate rollback to a reader whose independent storage support is
        # older, using the actual upgraded state and authoritative receipts.
        committed = inspect_profile(paths)
        committed["compatibility"]["storage"] += 1
        (paths.data_dir / STATE_NAME).write_text(json.dumps(committed))
        before_rollback = snapshot(paths)
        with pytest.raises(PackageStateError, match="incompatible"):
            PackageUpgrade(paths, authority, "previous-candidate").prepare()
        assert snapshot(paths) == before_rollback
    finally:
        authority.release_runtime()
