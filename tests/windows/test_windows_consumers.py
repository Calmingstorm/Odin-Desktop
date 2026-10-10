"""Consumers after their commit points, across real process restarts (plan A5, B3r, B3s).

Each restart is a new Python process that builds the store with the core's own
arguments (``src/desktop/services.py``). Every fixture checks the disk, the
runtime state and what the consumer acknowledges. The evidence is injected
failures and native API behaviour, not crash or power-loss recovery.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.desktop.platform import win32, windows_files
from src.desktop.platform.windows import windows_profile_paths
from src.desktop.platform.windows_files import held, tombstones

ROOT = Path(__file__).resolve().parents[2]

AUDIT = '''
import asyncio, json, os, sys
from pathlib import Path
from src.audit.logger import AuditLogger
from src.desktop.platform import win32, windows_files
import src.desktop.platform.windows_engine as engine

path = Path(sys.argv[1])
marker_name = path.name + ".repair-required"
acks, steps = [], []


def tombstones():
    with windows_files.held(path.parent) as chain:
        return windows_files.tombstones(chain, marker_name)


def make():
    # The core's construction (src/desktop/services.py).
    logger = AuditLogger(path=str(path), hmac_key="k" * 32, classify_failures=True)

    async def acknowledged(entry):
        acks.append(entry.get("audit_durability", "durable"))

    logger.set_event_callback(acknowledged)
    return logger


async def record(logger, n):
    await logger.log_execution(user_id="u", user_name="u", channel_id="c", tool_name="t",
                               tool_input={"n": n}, approved=True, result_summary="ok",
                               execution_time_ms=1)


async def report(logger, **extra):
    integrity = await logger.verify_integrity()
    print(json.dumps({"repair_required": logger.repair_required,
                      "degraded": logger.durability_degraded,
                      "marker": logger._repair_marker.exists(), "tombstones": tombstones(),
                      "acks": acks, "steps": steps, "durability": integrity["durability"],
                      **extra}))


def fail_next_flush(*, exit_code=None, then=None):
    """The next native flush fails (or the process ends there); later ones succeed."""
    real = win32.flush

    def once(handle):
        win32.flush = then or real
        if exit_code is not None:
            os._exit(exit_code)
        raise OSError("flush failed")

    win32.flush = once
'''


def child(program: str, *args, prelude: str = AUDIT, exit_code: int = 0) -> dict | None:
    """Run ``program`` as a new process (a restart); return the JSON it prints last."""
    result = subprocess.run(
        [sys.executable, "-c", prelude + textwrap.dedent(program), *map(str, args)],
        cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True,
        text=True, timeout=180)
    assert result.returncode == exit_code, result.stderr[-4000:]
    lines = result.stdout.strip().splitlines()
    return json.loads(lines[-1]) if lines else None


@pytest.fixture
def paths(tmp_path):
    profile = windows_profile_paths("test", environ={"LOCALAPPDATA": str(tmp_path)})
    profile.create_private()
    return profile


@pytest.fixture
def audit_path(paths):
    return paths.data_dir / "audit.jsonl"


def on_disk(path: Path) -> tuple[bool, list[str]]:
    marker = path.with_name(path.name + ".repair-required")
    with held(path.parent) as chain:
        return marker.exists(), tombstones(chain, marker.name)


# --- the audit repair marker -----------------------------------------------------------------


def test_a_flush_failing_after_the_rename_fences_the_next_process(audit_path):
    first = child('''
        async def main():
            logger = make()
            await record(logger, 1)
            real_retire = engine.retire

            def rename_then_fail(chain, name):
                fail_next_flush()  # the retirement's own flush; the quarantine's marker succeeds
                return real_retire(chain, name)

            engine.retire = rename_then_fail
            await record(logger, 2)
            await report(logger)
        asyncio.run(main())
    ''', audit_path)
    assert first["acks"] == ["durable", "repair_required"]
    assert first["repair_required"] and first["degraded"]
    assert first["marker"] and len(first["tombstones"]) == 1
    assert first["durability"] == "repair_required"

    restarted = child('''
        async def main():
            logger = make()
            fenced = logger.repair_required
            await logger.initialize_chain()
            await record(logger, 3)
            await report(logger, fenced_at_start=fenced)
        asyncio.run(main())
    ''', audit_path)
    assert restarted["fenced_at_start"] is True
    assert not restarted["repair_required"] and not restarted["marker"]
    assert restarted["tombstones"] == [] and restarted["acks"] == ["durable"]
    assert restarted["durability"] == "durable"


def test_a_failed_marker_recreation_then_full_settlement_in_a_new_process(audit_path):
    first = child('''
        async def main():
            logger = make()
            await record(logger, 1)
            real_retire = engine.retire

            def failing(handle):
                raise OSError("flush failed")

            def rename_then_fail(chain, name):
                fail_next_flush(then=failing)  # every later flush fails: no new marker
                return real_retire(chain, name)

            engine.retire = rename_then_fail
            await record(logger, 2)
            await report(logger)
        asyncio.run(main())
    ''', audit_path)
    assert first["acks"] == ["durable", "repair_required"]
    assert first["repair_required"] and not first["marker"]
    assert len(first["tombstones"]) == 1

    settled = child('''
        async def main():
            logger = make()

            def watched(name, function):
                def call(*args, **kwargs):
                    steps.append([name, logger.repair_required])
                    return function(*args, **kwargs)
                return call

            originals = {name: getattr(engine, name)
                         for name in ("publish", "retire", "flush_object", "remove")}
            for name, function in originals.items():
                setattr(engine, name, watched(name, function))
            await logger.initialize_chain()
            for name, function in originals.items():
                setattr(engine, name, function)
            await record(logger, 3)
            await report(logger)
        asyncio.run(main())
    ''', audit_path)
    # Steps 2-4 ran while the fence held; cleanup (step 5) came only after them.
    assert [step for step, _ in settled["steps"]] == [
        "publish", "retire", "flush_object", "remove", "remove"]
    assert all(fenced for _, fenced in settled["steps"])
    assert not settled["repair_required"] and settled["tombstones"] == []
    assert not settled["marker"] and settled["acks"] == ["durable"]


@pytest.mark.parametrize("step", ["publish", "retire", "flush_object"])
def test_each_failed_settlement_step_keeps_the_fence_across_another_restart(audit_path, step):
    audit_path.write_text('{"event": 1}\n', newline="")
    marker = audit_path.with_name(audit_path.name + ".repair-required")
    for suffix in ("a" * 32, "b" * 32):  # two, so no outcome depends on one chosen file
        Path(f"{marker}.retiring-{suffix}").write_bytes(b"")
    if step != "publish":
        marker.write_text("pending\n")
    failed = child(f'''
        async def main():
            logger = make()

            def refused(*args, **kwargs):
                raise OSError("{step} failed")

            engine.{step} = refused
            await logger.initialize_chain()
            await record(logger, 2)
            await report(logger)
        asyncio.run(main())
    ''', audit_path)
    assert failed["repair_required"] and failed["acks"] == ["repair_required"]
    assert len(failed["tombstones"]) >= 2
    assert failed["durability"] == "repair_required"

    restarted = child('''
        async def main():
            logger = make()
            fenced = logger.repair_required
            await logger.initialize_chain()
            await record(logger, 3)
            await report(logger, fenced_at_start=fenced)
        asyncio.run(main())
    ''', audit_path)
    assert restarted["fenced_at_start"] is True
    assert not restarted["repair_required"] and restarted["tombstones"] == []
    assert restarted["acks"] == ["durable"]


def test_an_interruption_between_the_rename_and_its_flush_fences_the_next_process(audit_path):
    child('''
        async def main():
            logger = make()
            await record(logger, 1)
            real_retire = engine.retire

            def rename_then_die(chain, name):
                fail_next_flush(exit_code=9)  # the process ends before the flush result
                return real_retire(chain, name)

            engine.retire = rename_then_die
            await record(logger, 2)
        asyncio.run(main())
    ''', audit_path, exit_code=9)
    marker, left = on_disk(audit_path)
    assert not marker and len(left) == 1

    restarted = child('''
        async def main():
            logger = make()
            fenced = logger.repair_required
            await logger.initialize_chain()
            await record(logger, 3)
            await report(logger, fenced_at_start=fenced)
        asyncio.run(main())
    ''', audit_path)
    assert restarted["fenced_at_start"] is True
    assert not restarted["repair_required"] and restarted["tombstones"] == []
    assert restarted["acks"] == ["durable"] and restarted["durability"] == "durable"


def test_a_failed_tombstone_cleanup_after_the_barrier_means_a_redundant_repair(audit_path):
    audit_path.write_text('{"event": 1}\n', newline="")
    marker = audit_path.with_name(audit_path.name + ".repair-required")
    marker.write_text("pending\n")
    Path(f"{marker}.retiring-{'c' * 32}").write_bytes(b"")
    settled = child('''
        async def main():
            logger = make()

            def refused(*args, **kwargs):
                raise OSError("cleanup failed")

            real_remove, engine.remove = engine.remove, refused
            await logger.initialize_chain()
            engine.remove = real_remove  # only settlement's cleanup fails
            await record(logger, 2)
            await report(logger)
        asyncio.run(main())
    ''', audit_path)
    # The barrier succeeded, so the fence cleared; only the cleanup is left over.
    assert not settled["repair_required"] and settled["acks"] == ["durable"]
    assert len(settled["tombstones"]) == 2

    redundant = child('''
        async def main():
            logger = make()
            fenced = logger.repair_required
            await logger.initialize_chain()
            await report(logger, fenced_at_start=fenced)
        asyncio.run(main())
    ''', audit_path)
    assert redundant["fenced_at_start"] is True
    assert not redundant["repair_required"] and redundant["tombstones"] == []


def test_a_tombstone_name_collision_picks_a_fresh_name(audit_path, monkeypatch):
    audit_path.write_text('{"event": 1}\n', newline="")
    marker = audit_path.with_name(audit_path.name + ".repair-required")
    marker.write_text("pending\n")
    taken = Path(f"{marker}.retiring-{'a' * 32}")
    taken.write_bytes(b"earlier")
    names = iter(["a" * 32, "d" * 32])
    monkeypatch.setattr(windows_files.secrets, "token_hex", lambda size: next(names))
    with held(audit_path.parent) as chain:
        fresh = windows_files.retire(chain, marker.name)
    assert fresh == f"{marker.name}.retiring-{'d' * 32}"
    assert taken.read_bytes() == b"earlier"  # never replaced
    monkeypatch.undo()
    restarted = child('''
        async def main():
            logger = make()
            fenced = logger.repair_required
            await logger.initialize_chain()
            await report(logger, fenced_at_start=fenced)
        asyncio.run(main())
    ''', audit_path)
    assert restarted["fenced_at_start"] is True and restarted["tombstones"] == []


def test_look_alike_files_are_never_tombstones(audit_path):
    audit_path.write_text('{"event": 1}\n', newline="")
    marker = audit_path.with_name(audit_path.name + ".repair-required")
    look_alikes = [
        Path(f"{marker}.retiring-{'A' * 32}"), Path(f"{marker}.retiring-{'a' * 31}"),
        Path(f"{marker}.retiring-{'a' * 32}.bak"), Path(f"{marker}.bak"),
        audit_path.with_name(f"other.jsonl.repair-required.retiring-{'a' * 32}"),
    ]
    for path in look_alikes:
        path.write_bytes(b"keep")
    unfenced = child('''
        async def main():
            logger = make()
            await report(logger, fenced_at_start=logger.repair_required)
        asyncio.run(main())
    ''', audit_path)
    assert unfenced["fenced_at_start"] is False and unfenced["tombstones"] == []
    marker.write_text("pending\n")
    settled = child('''
        async def main():
            logger = make()
            await logger.initialize_chain()
            await report(logger)
        asyncio.run(main())
    ''', audit_path)
    assert not settled["repair_required"] and not settled["marker"]
    assert all(path.read_bytes() == b"keep" for path in look_alikes)


# --- session reset epochs ----------------------------------------------------------------------


SESSIONS = '''
import json, sys
from src.sessions.manager import SessionManager

# The core's construction (src/desktop/services.py), minus its optional helpers.
manager = SessionManager(max_history=50, max_age_hours=24, persist_dir=sys.argv[1])
'''


def _fail_final_flush(monkeypatch):
    """The temporary file's flush passes; the flush after the rename fails."""
    real, calls = win32.flush, []

    def flush(handle):
        calls.append(handle)
        if len(calls) == 2:
            raise OSError("flush failed")
        real(handle)

    monkeypatch.setattr(win32, "flush", flush)


def test_a_reset_after_its_commit_point_keeps_its_epoch_and_pending_fence(paths, monkeypatch):
    from src.sessions.manager import SessionManager, _PublishedButUnsyncedError

    folder = paths.data_dir / "sessions"
    manager = SessionManager(max_history=50, max_age_hours=24, persist_dir=str(folder))
    manager.reset("before")
    _fail_final_flush(monkeypatch)
    with pytest.raises(_PublishedButUnsyncedError):
        manager.reset("after")
    monkeypatch.undo()
    # Committed and visible, never acknowledged as durable: the epoch stays, fenced.
    assert "after" in manager._reset_epochs and "after" in manager._pending_reset_epochs
    assert "after" in json.loads((folder / "reset_epochs.json").read_text())
    restarted = child('''
        print(json.dumps(sorted(manager._reset_epochs)))
    ''', folder, prelude=SESSIONS)
    assert restarted == ["after", "before"]


def test_a_reset_failing_before_its_commit_point_keeps_the_old_epochs(paths, monkeypatch):
    from src.sessions.manager import SessionManager, _PublishedButUnsyncedError

    folder = paths.data_dir / "sessions"
    manager = SessionManager(max_history=50, max_age_hours=24, persist_dir=str(folder))
    manager.reset("before")

    def refused(handle, data):
        raise OSError("write failed")

    monkeypatch.setattr(win32, "write_all", refused)
    with pytest.raises(OSError) as raised:
        manager.reset("lost")
    monkeypatch.undo()
    assert not isinstance(raised.value, _PublishedButUnsyncedError)
    assert "lost" not in manager._reset_epochs and "lost" in manager._pending_reset_epochs
    assert sorted(json.loads((folder / "reset_epochs.json").read_text())) == ["before"]
    with held(folder) as chain:
        assert [name for name in os.listdir(chain.path) if name.endswith(".tmp")] == []


# --- identity and cleanup ----------------------------------------------------------------------


AUTHORITY = '''
import json, sys
from pathlib import Path
from src.desktop.authority import OwnerAuthority
from src.desktop.platform.windows import windows_profile_paths
from src.desktop.platform.windows_files import user_sid

paths = windows_profile_paths("test", environ={"LOCALAPPDATA": sys.argv[1]})
'''


def test_identity_published_but_unproven_refuses_authentication_until_a_restart(
        tmp_path, paths, monkeypatch):
    from src.desktop.authority import OwnerAuthority

    _fail_final_flush(monkeypatch)
    authority = OwnerAuthority(paths)
    monkeypatch.undo()
    assert authority.durability_degraded
    with pytest.raises(PermissionError, match="durability unproven"):
        authority.authenticate_local(peer_uid=windows_files.user_sid())
    record = json.loads(paths.identity_file.read_text())
    assert record["owner_sid"] == windows_files.user_sid()
    restarted = child('''
        authority = OwnerAuthority(paths)
        context = authority.authenticate_local(peer_uid=user_sid())
        print(json.dumps({"degraded": authority.durability_degraded,
                          "installation": authority.installation_id}))
        authority.release_runtime()
    ''', tmp_path, prelude=AUTHORITY)
    assert restarted == {"degraded": False, "installation": record["installation_id"]}


def test_identity_failing_before_its_commit_point_leaves_no_record(paths, monkeypatch):
    from src.desktop.authority import OwnerAuthority

    def refused(handle, data):
        raise OSError("write failed")

    monkeypatch.setattr(win32, "write_all", refused)
    with pytest.raises(OSError):
        OwnerAuthority(paths)
    monkeypatch.undo()
    assert not paths.identity_file.exists()


def test_cleanup_evidence_published_but_unproven_is_an_error_and_stays(paths, monkeypatch):
    from src.desktop.resource_cleanup import ResourceCleanupError, ResourceCleanupJournal

    path = paths.data_dir / "resource-cleanup.json"
    journal = ResourceCleanupJournal(path)
    _fail_final_flush(monkeypatch)
    with pytest.raises(ResourceCleanupError, match="durability is unverified"):
        journal.finish({"engine": {"state": "released"}})
    monkeypatch.undo()
    assert json.loads(path.read_text())["state"] == "complete"

    def refused(handle, data):
        raise OSError("write failed")

    monkeypatch.setattr(win32, "write_all", refused)
    with pytest.raises(OSError):
        ResourceCleanupJournal(path)  # before its commit point: the evidence is unchanged
    monkeypatch.undo()
    assert json.loads(path.read_text())["state"] == "complete"


# --- interrupted history and the journal ------------------------------------------------------


@pytest.fixture
def graph(paths):
    from src.desktop.authority import OwnerAuthority
    from src.desktop.commands import JournalStore
    from src.desktop.conversations import ConversationStore
    from src.desktop.events import EventJournal
    from src.desktop.schedules import ScheduleService
    from src.scheduler.scheduler import Scheduler

    authority = OwnerAuthority(paths)
    owner = authority.authenticate_local(peer_uid=authority.owner_uid)
    store = JournalStore(paths.data_dir / "journal.sqlite3", "test")
    conversations = ConversationStore(store, EventJournal(store))
    cid = conversations.create()["conversation"]["id"]
    scheduler = Scheduler(str(paths.data_dir / "schedules.json"), desktop_recovery=True)
    service = ScheduleService(scheduler, authority=authority, conversations=conversations)
    yield scheduler, service, owner, cid
    store.close()
    authority.release_runtime()


class _FlushFails:
    """``os`` for the Windows variants, whose flush (their barrier) fails."""

    def __getattr__(self, name):
        return getattr(os, name)

    @staticmethod
    def fsync(fd):
        raise OSError("flush failed")


async def test_interrupted_history_failure_keeps_the_scheduler_outbox(graph, monkeypatch):
    import src.desktop.platform.windows_engine as engine
    from src.desktop.schedules import ScheduleService
    from src.scheduler.scheduler import Scheduler

    scheduler, service, owner, cid = graph
    item = await service.invoke("schedules.save", {
        "description": "Example", "action": "reminder", "channel_id": cid,
        "cron": "* * * * *"}, owner=owner)
    await scheduler._mark_run_started(item)
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    with monkeypatch.context() as patch:
        patch.setattr(engine, "os", _FlushFails())
        await ScheduleService(restarted, authority=service.authority,
                              conversations=service.conversations).recover()
    again = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    outbox = again.list_all()[0]["_interrupted_run_history"]
    assert outbox[0]["run_binding"] == item["run_binding"]  # kept for the next publication
    await ScheduleService(again, authority=service.authority,
                          conversations=service.conversations).recover()
    assert "_interrupted_run_history" not in again.list_all()[0]
    assert len(await again.history.query(item["id"])) == 1


def test_journal_initialization_barrier_failure_is_a_storage_error(paths, monkeypatch):
    import src.desktop.platform.windows_desktop as desktop
    from src.desktop.commands import JournalStorageError, JournalStore

    database = paths.data_dir / "transport.sqlite3"

    def refused(*args, **kwargs):
        raise OSError("flush failed")

    monkeypatch.setattr(desktop, "flush_object", refused)
    with pytest.raises(JournalStorageError):
        JournalStore(database, "test", identity="install:owner")
    monkeypatch.undo()
    store = JournalStore(database, "test", identity="install:owner")
    store.close()


# --- before the commit point: the consumer keeps its prior state -------------------------------


async def test_interrupted_history_refused_before_its_append_keeps_history_and_outbox(graph, sddl):
    from src.desktop.schedules import ScheduleService
    from src.scheduler.scheduler import Scheduler

    scheduler, service, owner, cid = graph
    item = await service.invoke("schedules.save", {
        "description": "Example", "action": "reminder", "channel_id": cid,
        "cron": "* * * * *"}, owner=owner)
    await scheduler._mark_run_started(item)
    history = scheduler.history.path
    if not history.exists():
        history.write_text("", newline="")
    before = history.read_bytes()
    sddl(history, "D:P(A;;FA;;;WD)", directory=False)  # refused before any byte is written
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    await ScheduleService(restarted, authority=service.authority,
                          conversations=service.conversations).recover()
    assert history.read_bytes() == before
    again = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    assert again.list_all()[0]["_interrupted_run_history"][0]["run_binding"] == item["run_binding"]
    sddl(history, f"D:P(A;;FA;;;{windows_files.user_sid()})", directory=False)
    await ScheduleService(again, authority=service.authority,
                          conversations=service.conversations).recover()
    assert "_interrupted_run_history" not in again.list_all()[0]
    assert len(await again.history.query(item["id"])) == 1


def test_cleanup_finish_failing_before_its_commit_point_keeps_the_running_record(
        paths, monkeypatch):
    from src.desktop.resource_cleanup import ResourceCleanupError, ResourceCleanupJournal

    path = paths.data_dir / "resource-cleanup.json"
    journal = ResourceCleanupJournal(path)
    prior = path.read_bytes()

    def refused(handle, data):
        raise OSError("write failed")

    monkeypatch.setattr(win32, "write_all", refused)
    with pytest.raises(OSError) as raised:
        journal.finish({"engine": {"state": "released"}})
    monkeypatch.undo()
    assert not isinstance(raised.value, ResourceCleanupError)  # the caller sees the failure itself
    assert path.read_bytes() == prior and json.loads(prior)["state"] == "running"
    with held(path.parent) as chain:
        assert [name for name in os.listdir(chain.path) if name.endswith(".tmp")] == []


def test_journal_initialization_failing_before_its_commit_point_keeps_the_database(
        paths, monkeypatch):
    import hashlib

    import src.desktop.schema as schema
    from src.desktop.commands import JournalStorageError, JournalStore

    database = paths.data_dir / "journal" / "transport.sqlite3"
    JournalStore(database, "test", identity="install:owner").close()
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    def refused(*args, **kwargs):
        raise RuntimeError("schema check failed")

    monkeypatch.setattr(schema, "validate_domains", refused)
    with pytest.raises(JournalStorageError):
        JournalStore(database, "test", identity="install:owner")
    monkeypatch.undo()
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    moved = database.parent.with_name("moved")
    os.rename(database.parent, moved)  # nothing is left open or held
    os.rename(moved, database.parent)
    JournalStore(database, "test", identity="install:owner").close()
