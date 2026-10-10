"""The storage contract at its consumer sites, against links, wide ACLs and moved folders.

Phase 2 plan A2's native adversarial exits, at the functions that hold private
state: the audit log, schedule history, the turn-state store, the runtime lock,
the workspace, and every place a path could reach a network share.
"""
from __future__ import annotations

import _winapi
import ctypes
import json
import os
from pathlib import Path

import pytest

from src.desktop.platform import win32, windows_files
from src.desktop.platform.windows import windows_profile_paths
from src.desktop.platform.windows_files import dacl_is_private

EVERYONE_FILE = "D:P(A;;FA;;;WD)"


@pytest.fixture
def paths(tmp_path):
    profile = windows_profile_paths("test", environ={"LOCALAPPDATA": str(tmp_path)})
    profile.create_private()
    return profile


def security_of(path, *, directory=False):
    flags = win32.FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= win32.FILE_FLAG_BACKUP_SEMANTICS
    handle = win32.create_file(
        path, win32.READ_CONTROL | win32.FILE_READ_ATTRIBUTES,
        win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE | win32.FILE_SHARE_DELETE,
        win32.OPEN_EXISTING, flags)
    try:
        return win32.object_security(handle)
    finally:
        win32.close(handle)


def handle_count() -> int:
    count = win32.DWORD()
    assert ctypes.WinDLL("kernel32").GetProcessHandleCount(
        ctypes.c_void_p(win32.GetCurrentProcess()), ctypes.byref(count))
    return count.value


def symlink_or_skip(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link)
    except OSError as exc:
        if exc.winerror == 1314:  # ERROR_PRIVILEGE_NOT_HELD
            pytest.skip("creating a symbolic link needs the privilege or developer mode")
        raise


def audit(path):
    from src.audit.logger import AuditLogger

    acks = []
    logger = AuditLogger(path=str(path), hmac_key="k" * 32)

    async def acknowledged(entry):
        acks.append(entry.get("audit_durability", "durable"))

    logger.set_event_callback(acknowledged)
    return logger, acks


async def record(logger, n=1):
    await logger.log_execution(user_id="u", user_name="u", channel_id="c", tool_name="t",
                               tool_input={"n": n}, approved=True, result_summary="ok",
                               execution_time_ms=1)


# --- B1: the audit log and schedule history ----------------------------------------------------


@pytest.mark.parametrize("kind", ["hard link", "symbolic link"])
async def test_an_audit_log_that_is_a_link_is_never_written_through(paths, kind):
    victim = paths.data_dir / "victim.txt"
    victim.write_text("unchanged\n")
    log = paths.data_dir / "audit.jsonl"
    if kind == "hard link":
        os.link(victim, log)
    else:
        symlink_or_skip(victim, log)
    logger, acks = audit(log)
    await record(logger)
    assert acks == ["not_persisted"] and logger.durability_degraded
    assert victim.read_text() == "unchanged\n"


async def test_an_audit_log_shared_with_everyone_receives_no_entry(paths, sddl):
    log = paths.data_dir / "audit.jsonl"
    log.write_text("", newline="")
    sddl(log, EVERYONE_FILE, directory=False)
    logger, acks = audit(log)
    await record(logger)
    assert acks == ["not_persisted"]
    assert log.read_bytes() == b""
    await logger.initialize_chain()
    assert not logger._chain_initialized  # retried before the next persist, as on Linux


async def test_rotation_renames_names_and_never_writes_through_a_link(paths):
    log = paths.data_dir / "audit.jsonl"
    victim = paths.data_dir / "victim.txt"
    victim.write_text("unchanged\n")
    logger, acks = audit(log)
    logger._max_bytes = 10
    await record(logger, 1)
    os.link(victim, log.with_name("audit.jsonl.1"))
    await record(logger, 2)  # rotation moves names only; nothing is written through the link
    assert victim.read_text() == "unchanged\n"
    assert acks[0] == "durable"


async def test_integrity_verification_reports_linked_and_shared_generations(paths, sddl):
    log = paths.data_dir / "audit.jsonl"
    logger, _ = audit(log)
    await record(logger, 1)
    outside = paths.data_dir / "elsewhere.jsonl"
    outside.write_bytes(log.read_bytes())  # a valid signed segment, copied out of the store
    os.link(outside, log.with_name("audit.jsonl.1"))
    shared = log.with_name("audit.jsonl.2")
    shared.write_bytes(log.read_bytes())
    sddl(shared, EVERYONE_FILE, directory=False)
    result = await logger.verify_integrity()
    status = {segment["file"]: segment["status"] for segment in result["segments"]}
    assert status["audit.jsonl"] == "verified"
    assert status["audit.jsonl.1"] == "unreadable" and status["audit.jsonl.2"] == "unreadable"
    assert result["valid"] is False


async def test_integrity_verification_refuses_a_symlinked_generation(paths):
    log = paths.data_dir / "audit.jsonl"
    logger, _ = audit(log)
    await record(logger, 1)
    outside = paths.data_dir / "elsewhere.jsonl"
    outside.write_bytes(log.read_bytes())
    symlink_or_skip(outside, log.with_name("audit.jsonl.1"))
    result = await logger.verify_integrity()
    status = {segment["file"]: segment["status"] for segment in result["segments"]}
    assert status["audit.jsonl.1"] == "unreadable"


async def test_the_audit_snapshot_skips_a_linked_generation(paths):
    log = paths.data_dir / "audit.jsonl"
    logger, _ = audit(log)
    await record(logger)
    victim = paths.data_dir / "victim.txt"
    victim.write_text("secret\n")
    os.link(victim, log.with_name("audit.jsonl.1"))
    opened = await logger.open_read_snapshot()
    try:
        assert len(opened) == 1  # only the private current file
    finally:
        for handle, _ in opened:
            handle.close()


async def test_history_never_writes_through_a_link_or_into_a_shared_file(paths, sddl):
    from src.scheduler.history import ScheduleHistory

    victim = paths.data_dir / "victim.txt"
    victim.write_text("unchanged\n")
    path = paths.data_dir / "schedule_history.jsonl"
    os.link(victim, path)
    history = ScheduleHistory(str(path))
    entry = dict(schedule_id="s1", description="d", action="reminder", status="success",
                 duration_ms=1)
    await history.record(**entry)  # best effort: logged, nothing written
    assert victim.read_text() == "unchanged\n"
    assert await history.query() == []
    pending = {"schedule_id": "s1", "status": "unknown", "run_binding": "r1", "error": "lost"}
    with pytest.raises(OSError):
        await history.record_interrupted(pending)  # strict: the outbox stays
    assert victim.read_text() == "unchanged\n"
    path.unlink()
    path.write_text("", newline="")
    sddl(path, EVERYONE_FILE, directory=False)
    with pytest.raises(PermissionError):
        await history.record_interrupted(pending)
    assert path.read_bytes() == b""


async def test_pruning_publishes_through_its_own_temporary_and_leaves_old_names_alone(
        paths, monkeypatch):
    import src.scheduler.history as module
    from src.scheduler.history import ScheduleHistory

    path = paths.data_dir / "schedule_history.jsonl"
    victim = paths.data_dir / "victim.txt"
    victim.write_text("unchanged\n")
    os.link(victim, path.with_suffix(".tmp"))  # Linux's temporary name, pre-planted
    history = ScheduleHistory(str(path), max_entries_per_schedule=1)
    lines = "".join(json.dumps({"schedule_id": "s", "n": n, "timestamp": f"{n:04}"}) + "\n"
                    for n in range(5))
    path.write_text(lines, newline="")
    monkeypatch.setattr(module, "MAX_TOTAL_ENTRIES", 1)
    assert await history._prune_locked() == 4
    assert victim.read_text() == "unchanged\n"
    assert [json.loads(line)["n"] for line in path.read_text().splitlines()] == [4]


# --- B2: the turn-state store keeps its anchors ------------------------------------------------


def test_turn_state_uses_its_held_path_after_an_ancestor_alias_moves(paths, monkeypatch):
    from src.turn_state.store import TurnStateStore

    first, second = paths.data_dir / "first", paths.data_dir / "second"
    for folder in (first, second):
        folder.mkdir()
    alias = paths.data_dir / "alias"
    _winapi.CreateJunction(str(first), str(alias))
    import src.desktop.platform.windows_engine as engine

    original = engine.turn_state_linux_init

    def rebind_then_open(self, *args, **kwargs):
        os.rmdir(alias)  # removes the junction itself, not its target
        _winapi.CreateJunction(str(second), str(alias))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(engine, "turn_state_linux_init", rebind_then_open)
    store = TurnStateStore(alias / "turn_state" / "turns.sqlite3")
    try:
        assert store.available
        assert Path(store.db_path).parent == first / "turn_state"
        assert (first / "turn_state" / "turns.sqlite3").exists()
        assert not (second / "turn_state").exists()
    finally:
        store.close()


def test_the_blob_folder_cannot_be_rebound_while_the_store_is_open(paths):
    from src.turn_state.store import TurnStateStore

    store = TurnStateStore(paths.data_dir / "turn_state" / "turns.sqlite3")
    blobs = paths.data_dir / "turn_state" / "blobs"
    try:
        reference = store.store_blob_sync(b"transcript")
        with pytest.raises(PermissionError):
            os.rename(blobs, blobs.with_name("moved"))
        assert store.load_blob_sync(reference) == b"transcript"
        assert dacl_is_private(security_of(blobs / reference.split(":")[1]))
        with pytest.raises(Exception, match="blob read failed"):
            store.load_blob_sync("blob:..\\turns.sqlite3")
    finally:
        store.close()
    os.rename(blobs, blobs.with_name("moved"))  # B4: nothing is held after close


def test_a_tampered_blob_is_refused(paths):
    from src.turn_state.store import TurnStateStore, TurnStateUnavailableError

    store = TurnStateStore(paths.data_dir / "turn_state" / "turns.sqlite3")
    try:
        reference = store.store_blob_sync(b"transcript")
        assert store.store_blob_sync(b"transcript") == reference  # already present
        digest = reference.split(":")[1]
        blob = paths.data_dir / "turn_state" / "blobs" / digest
        blob.write_bytes(b"changed")
        with pytest.raises(TurnStateUnavailableError, match="digest mismatch"):
            store.load_blob_sync(reference)
    finally:
        store.close()
    with pytest.raises(TurnStateUnavailableError, match="blob write failed"):
        store.store_blob_sync(b"after close")


# --- B3: what new files inherit is private before SQLite creates them ------------------------


def test_inherit_only_wide_grants_are_repaired_before_sqlite_creates_files(paths, sddl):
    from src.turn_state.store import TurnStateStore

    folder = paths.data_dir / "turn_state"
    folder.mkdir()
    sddl(folder, "D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICIIO;FA;;;WD)", directory=True)
    assert dacl_is_private(security_of(folder, directory=True))
    assert not dacl_is_private(security_of(folder, directory=True), children=True)
    store = TurnStateStore(folder / "turns.sqlite3")
    try:
        assert store.available
        assert dacl_is_private(security_of(folder, directory=True), children=True)
        for name in ("turns.sqlite3", "turns.sqlite3-wal", "turns.sqlite3-shm"):
            if (folder / name).exists():
                assert dacl_is_private(security_of(folder / name)), name
    finally:
        store.close()


BROAD_TARGET = "D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;0x1200a9;;;WD)"


def test_a_store_folder_resolving_outside_the_profile_is_private_before_sqlite(
        paths, tmp_path, sddl, monkeypatch):
    import src.desktop.platform.windows_engine as engine
    from src.turn_state.store import TurnStateStore

    target = tmp_path / "TurnStateTarget"
    target.mkdir()
    sddl(target, BROAD_TARGET, directory=True)  # the owner, plus everyone may read, inherited
    _winapi.CreateJunction(str(target), str(paths.data_dir / "turn_state"))
    at_connect = []
    original = engine.turn_state_linux_init

    def checked(self, *args, **kwargs):
        at_connect.append(dacl_is_private(security_of(target, directory=True), children=True))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(engine, "turn_state_linux_init", checked)
    store = TurnStateStore(paths.data_dir / "turn_state" / "turns.sqlite3")
    try:
        assert store.available and at_connect == [True]
        for name in ("turns.sqlite3", "turns.sqlite3-wal", "turns.sqlite3-shm"):
            if (target / name).exists():
                assert dacl_is_private(security_of(target / name)), name
    finally:
        store.close()


def test_a_journal_folder_resolving_outside_the_profile_is_private_before_sqlite(
        paths, tmp_path, sddl, monkeypatch):
    import src.desktop.platform.windows_desktop as desktop
    from src.desktop.commands import JournalStore

    target = tmp_path / "JournalTarget"
    target.mkdir()
    sddl(target, BROAD_TARGET, directory=True)
    _winapi.CreateJunction(str(target), str(paths.data_dir / "journal"))
    at_connect = []
    connect = desktop.sqlite3.connect

    def checked(*args, **kwargs):
        at_connect.append(dacl_is_private(security_of(target, directory=True), children=True))
        return connect(*args, **kwargs)

    monkeypatch.setattr(desktop.sqlite3, "connect", checked)
    store = JournalStore(paths.data_dir / "journal" / "transport.sqlite3", "test")
    try:
        assert at_connect == [True]
        assert dacl_is_private(security_of(target / "transport.sqlite3"))
    finally:
        store.close()


def ace(flags, sid, mask=0x1F01FF, kind=win32.ACCESS_ALLOWED_ACE_TYPE):
    return (kind, flags, mask, sid)


OI_CI = win32.OBJECT_INHERIT_ACE | win32.CONTAINER_INHERIT_ACE
IO = win32.INHERIT_ONLY_ACE


@pytest.mark.parametrize("entries, private_itself, private_for_children", [
    ([ace(OI_CI | IO, "S-1-1-0")], True, False),
    ([ace(win32.OBJECT_INHERIT_ACE | IO, "S-1-1-0")], True, False),
    ([ace(OI_CI | IO, win32.CREATOR_OWNER_SID)], True, True),
    ([ace(IO, "S-1-1-0")], True, True),  # inherited by nothing
    ([ace(OI_CI, win32.SYSTEM_SID), ace(OI_CI | IO, win32.OWNER_RIGHTS_SID)], True, True),
    ([ace(OI_CI | IO, "S-1-3-1")], True, False),  # CREATOR GROUP is not the creator
])
def test_what_children_inherit_counts_for_a_folder(entries, private_itself, private_for_children):
    security = win32.ObjectSecurity(win32.SYSTEM_SID, True, True, tuple(entries))
    assert dacl_is_private(security) is private_itself
    assert dacl_is_private(security, children=True) is private_for_children


@pytest.mark.parametrize("owner", [win32.SYSTEM_SID, win32.ADMINISTRATORS_SID])
@pytest.mark.parametrize("entries, accepted", [
    ([ace(OI_CI, win32.SYSTEM_SID), ace(OI_CI, win32.ADMINISTRATORS_SID)], True),
    ([ace(OI_CI, "S-1-1-0")], False),
    ([ace(OI_CI, win32.SYSTEM_SID), ace(OI_CI | IO, "S-1-5-11")], False),
])
def test_a_privileged_namespace_folder_must_already_be_private(monkeypatch, tmp_path, owner,
                                                               entries, accepted):
    if owner in windows_files.own_sids():
        pytest.skip("this token owns it, so it would be repaired instead")
    security = win32.ObjectSecurity(owner, True, True, tuple(entries))
    tag = type("Tag", (), {"FileAttributes": win32.FILE_ATTRIBUTE_DIRECTORY})()
    monkeypatch.setattr(win32, "attribute_tag", lambda handle: tag)
    monkeypatch.setattr(win32, "object_security", lambda handle: security)
    repairs = []
    monkeypatch.setattr(windows_files, "_repair_dacl", lambda *a, **k: repairs.append(a))
    verify = windows_files._verify_directory
    if accepted:
        verify(0, tmp_path, namespace=True, kind="profile")
    else:
        with pytest.raises(PermissionError, match="not ours to repair"):
            verify(0, tmp_path, namespace=True, kind="profile")
    assert repairs == []  # never ours to change


# --- B4: no handle outlives its use ----------------------------------------------------------


def test_repeated_refusals_and_closed_stores_leak_no_handles(paths):
    from src.desktop.requests import owner_display_name
    from src.llm.account_key import _read_established_key
    from src.permissions.host_access import HostAccessManager
    from src.permissions.persistence import write_private_atomic
    from src.turn_state.store import TurnStateStore

    folder = paths.config_dir / "display-profile"
    windows_files.private_directory(folder)
    write_private_atomic(folder / "profile.json", json.dumps({"name": "x" * 5000}))
    preferences = paths.config_dir / "host-preferences.json"
    write_private_atomic(preferences, json.dumps({"default_host": "x" * 70000}))
    key = paths.data_dir / "account.key"
    write_private_atomic(key, "short")
    manager = HostAccessManager(preferences)

    def refusals():
        assert owner_display_name(paths.config_dir) == "Owner"
        assert manager.default_host == ""
        assert _read_established_key(key).material is None
        TurnStateStore(paths.data_dir / "turn_state" / "turns.sqlite3").close()

    refusals()  # warm caches and imports
    before = handle_count()
    for _ in range(50):
        refusals()
    assert handle_count() - before < 10


# --- B5: a lock widened after acquisition is no longer authority -----------------------------


def test_a_runtime_lock_shared_after_acquisition_revokes_authentication(paths, sddl):
    from src.desktop.authority import OwnerAuthority

    authority = OwnerAuthority(paths)
    owner = windows_files.user_sid()
    authority.authenticate_local(peer_uid=owner)
    lock = paths.config_dir / ".core.lock"
    sddl(lock, EVERYONE_FILE, directory=False)
    try:
        assert not authority._runtime_current()
        with pytest.raises(PermissionError):
            authority.authenticate_local(peer_uid=owner)
    finally:
        sddl(lock, f"D:P(A;;FA;;;{owner})", directory=False)
    assert authority._runtime_current()
    authority.release_runtime()


# --- B6: usable means the DACL lets the user create and delete entries -----------------------


def test_a_private_read_only_workspace_is_not_usable(tmp_path, sddl):
    from src.desktop.platform.windows_workspace import resolve_workspace
    from src.tools.workspace import WorkspaceError

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    owner = windows_files.user_sid()
    resolve_workspace(str(workspace), create_if_missing=False)  # usable as created
    sddl(workspace, f"D:P(A;;0x1200a1;;;{owner})", directory=True)
    try:
        with pytest.raises(WorkspaceError, match="not fully usable"):
            resolve_workspace(str(workspace), create_if_missing=False)
    finally:
        sddl(workspace, f"D:P(A;OICI;FA;;;{owner})", directory=True)


# --- B7: a network location is refused before anything resolves it --------------------------


@pytest.fixture
def remote_z(monkeypatch):
    """Drive Z: is a mapped network drive; resolving anything is a test failure."""
    real = win32.drive_type
    monkeypatch.setattr(win32, "drive_type",
                        lambda root: 4 if root.upper().startswith("Z:") else real(root))

    def resolved(*args, **kwargs):
        raise AssertionError("a network path was resolved")

    monkeypatch.setattr(os.path, "realpath", resolved)
    monkeypatch.setattr(Path, "resolve", resolved)


@pytest.mark.parametrize("path", ["Z:\\odin\\state", "\\\\server\\share\\state",
                                  "\\\\?\\UNC\\server\\share\\state"])
def test_private_state_on_a_network_location_is_refused_unresolved(remote_z, path):
    with pytest.raises(PermissionError, match="local fixed NTFS volume"):
        windows_files.canonical(path)
    with pytest.raises(PermissionError):
        windows_files.private_directory(path)


@pytest.mark.parametrize("path", ["Z:\\odin\\package.json", "\\\\server\\share\\package.json"])
def test_the_package_reader_refuses_a_network_location_unresolved(remote_z, path):
    from src.desktop.platform.windows_desktop import _package_reader

    with pytest.raises(PermissionError), _package_reader(path):
        pass


@pytest.mark.parametrize("path", ["Z:\\workspace", "\\\\server\\share\\workspace"])
def test_the_workspace_refuses_a_network_location_unresolved(remote_z, monkeypatch, path):
    import src.tools.workspace as pinned
    from src.desktop.platform.windows_workspace import resolve_workspace
    from src.tools.workspace import WorkspaceError

    def probed(*args, **kwargs):
        raise AssertionError("a network path was probed")

    monkeypatch.setattr(pinned, "_canonical", probed)
    monkeypatch.setattr(Path, "is_symlink", probed)
    with pytest.raises(WorkspaceError, match="local fixed drive"):
        resolve_workspace(path)
