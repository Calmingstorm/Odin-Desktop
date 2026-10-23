"""The defensive branches Odin 4.22.0 (PR #729) and its Desktop carry added, each exercised.

None of these is reached by a passing ordinary run: a write that fails again, a fault in one
schedule or dispatch, a redirect without a target, a file that cannot be read back, a mode
that cannot be restored, an archive without a timestamped name, a caller outside an event
loop. Each must behave as its comment says, without failing the operation around it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.discord.channel_state import ChannelStateRegistry
from src.llm import codex_auth as ca
from src.scheduler import scheduler as scheduler_module
from src.scheduler.scheduler import ScheduleConnectionUnavailableError, Scheduler
from src.tools import apply_patch as ap
from src.tools.skill_manager import SkillManager
from tests.test_apply_patch import _patch
from tests.test_desktop_codex_unsaved_rotation import credential, make, unsaved  # noqa: F401
from tests.test_session_search import _manager
from tests.test_skill_manager_coverage import _skill_code


def test_a_request_set_outside_an_event_loop_records_no_owner_task():
    registry = ChannelStateRegistry()
    registry._active_request_tasks["chan"] = object()  # a stale owner from before
    registry.set_active_request("chan", "req")
    assert registry.active_requests["chan"] == "req"
    assert "chan" not in registry._active_request_tasks


@pytest.mark.asyncio
async def test_a_file_retry_that_fails_again_keeps_serving_the_rotation(
        tmp_path, monkeypatch, caplog):
    auth = ca.CodexAuth(str(tmp_path / "auth.json"))
    pending = {"access_token": "rotated", "refresh_token": "rotated-r", "expires_at": 9999999999}
    auth._credentials = auth._unpersisted = pending

    def disk_full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ca, "_atomic_write_secure", disk_full)
    with caplog.at_level(logging.WARNING):
        assert await auth.get_access_token() == "rotated"
    assert auth._unpersisted is pending and "still unsaved" in caplog.text


@pytest.mark.asyncio
async def test_a_retry_queued_behind_another_finds_the_rotation_saved(make):  # noqa: F811
    service, secrets, oauth, _ = make([credential("a", expires_at=0)])
    auth = service.pool._loaded_auths[0]
    await unsaved(auth, secrets)
    secrets.fail = False
    secrets.entered.clear()
    secrets.gate = threading.Event()
    first = asyncio.create_task(auth.get_access_token())
    assert await asyncio.to_thread(secrets.entered.wait, 5)  # the first save is mid-write
    second = asyncio.create_task(auth.get_access_token())
    await asyncio.sleep(0.05)  # the second waits for the refresh lock, rotation unsaved
    assert not second.done() and auth._unpersisted is not None
    secrets.gate.set()
    assert await asyncio.gather(first, second) == ["rotated-access-1"] * 2
    assert secrets.writes == 1 and oauth.consumed == ["secret-refresh-a"]


@pytest.mark.asyncio
async def test_an_unexpected_dispatch_fault_is_logged_and_a_cancelled_one_is_not(caplog):
    async def fault():
        raise RuntimeError("a scheduler bug")

    failed = asyncio.create_task(fault(), name="schedule-broken")
    cancelled = asyncio.create_task(asyncio.Event().wait(), name="schedule-cancelled")
    cancelled.cancel()
    await asyncio.gather(failed, cancelled, return_exceptions=True)
    with caplog.at_level(logging.ERROR):
        scheduler_module._log_dispatch_failure(failed)
        scheduler_module._log_dispatch_failure(cancelled)
    assert "schedule-broken failed unexpectedly" in caplog.text
    assert "schedule-cancelled" not in caplog.text


@pytest.mark.asyncio
async def test_a_redirect_without_a_location_is_left_to_the_client():
    params = SimpleNamespace(response=SimpleNamespace(headers={}), url="http://192.168.1.2/hook")
    assert await scheduler_module._guard_webhook_redirect(None, None, params) is None


@pytest.mark.asyncio
async def test_a_dispatch_whose_connection_went_away_ends_quietly(tmp_path, monkeypatch):
    scheduler = Scheduler(str(tmp_path / "schedules.json"))
    snapshot = scheduler._connection_availability()
    monkeypatch.setattr(scheduler, "_execute_and_record", AsyncMock(
        side_effect=ScheduleConnectionUnavailableError(snapshot)))
    assert await scheduler._run_fired({"id": "s1"}, "reservation", None) is None


@pytest.mark.asyncio
async def test_one_schedules_fault_never_stops_the_others(tmp_path, monkeypatch, caplog):
    scheduler = Scheduler(str(tmp_path / "schedules.json"))
    broken = await scheduler.add("Broken", "reminder", "chan", cron="* * * * *", message="x")
    healthy = await scheduler.add("Healthy", "reminder", "chan", cron="* * * * *", message="y")
    for item in scheduler._schedules:
        item["next_run"] = "2020-01-01T00:00:00"
    usable = scheduler._is_usable_cron

    def faulty(cron, *, _calls=[0]):
        _calls[0] += 1
        if _calls[0] == 1:
            raise RuntimeError("an unexpected fault in one schedule")
        return usable(cron)

    monkeypatch.setattr(scheduler, "_is_usable_cron", faulty)
    ran = []

    async def callback(schedule):
        ran.append(schedule["id"])

    scheduler._callback = callback
    with caplog.at_level(logging.ERROR):
        await scheduler._tick(wait=False)  # one pass, as the loop runs it
        await asyncio.gather(*list(scheduler._dispatches))
    assert f"Scheduler tick skipped schedule {broken['id']}" in caplog.text
    assert ran == [healthy["id"]]


def test_archives_without_a_timestamped_name_sort_by_mtime_then_last(tmp_path):
    manager = _manager(tmp_path)
    archive = tmp_path / "archive"
    archive.mkdir()
    now = time.time()
    for name, text, moment in (("older.json", "deploy notes OLDER", now - 7200),
                               ("newer.json", "deploy notes NEWER", now - 60)):
        path = archive / name
        path.write_text(json.dumps({
            "channel_id": "chan", "summary": "", "created_at": moment - 10,
            "last_active": moment,
            "messages": [{"role": "user", "content": text, "timestamp": moment}]}))
        os.utime(path, (moment, moment))
    (archive / "gone.json").symlink_to(archive / "missing-target.json")  # stat fails
    results = manager._search_archives("deploy notes", 5)
    assert [result["content"] for result in results] == [
        "deploy notes NEWER", "deploy notes OLDER"]


def test_a_mode_restore_that_fails_after_commit_keeps_the_patch(tmp_path, monkeypatch):
    target = tmp_path / "config.txt"
    target.write_text("old\n")
    target.chmod(0o644)
    alias = tmp_path / "alias.txt"
    os.link(target, alias)
    original_inode = alias.stat().st_ino
    real_fchmod = os.fchmod

    def refuse_restore(fd, mode):
        if mode & 0o077 and os.fstat(fd).st_ino == original_inode:
            raise OSError(1, "Operation not permitted")
        return real_fchmod(fd, mode)

    monkeypatch.setattr(ap.os, "fchmod", refuse_restore)
    ap.apply_plan(str(tmp_path), ap.parse_patch(_patch(
        "*** Update File: config.txt\n@@\n-old\n+new")))
    assert target.read_text() == "new\n" and alias.read_text() == "old\n"
    assert not list(tmp_path.glob(".odin-patch-*"))


def _failed_skill(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "custom.py").write_text("def (:::")  # a module that fails to load
    manager = SkillManager(str(skills), tool_executor=SimpleNamespace())
    assert not manager.has_skill("custom")
    return manager, skills / "custom.py"


def test_a_failed_skill_that_cannot_be_read_back_is_left_alone(tmp_path, monkeypatch):
    manager, path = _failed_skill(tmp_path)
    read_bytes = type(path).read_bytes

    def unreadable(self):
        if self == path:
            raise OSError(13, "Permission denied")
        return read_bytes(self)

    monkeypatch.setattr(type(path), "read_bytes", unreadable)
    result = manager.create_skill("custom", _skill_code("custom"))
    assert result.startswith("Failed to read the existing skill file:")
    assert path.read_text() == "def (:::" and not manager.has_skill("custom")


def test_a_rejected_candidate_whose_restore_fails_says_so(tmp_path, monkeypatch):
    manager, path = _failed_skill(tmp_path)
    write_bytes = type(path).write_bytes

    def unwritable(self, data):
        if self == path:
            raise OSError(28, "No space left on device")
        return write_bytes(self, data)

    monkeypatch.setattr(type(path), "write_bytes", unwritable)
    result = manager.create_skill("custom", "def (still broken")
    assert "The previous custom.py could not be restored" in result
    assert not manager.has_skill("custom")



def test_a_rejected_candidate_over_a_file_never_loaded_restores_it_without_an_error(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    manager = SkillManager(str(skills), tool_executor=SimpleNamespace())
    path = skills / "late.py"
    path.write_text("# written after the skills were loaded\n")  # on disk, never loaded
    assert "late.py" not in manager.definition_errors
    result = manager.create_skill("late", "def (:::")
    assert result.endswith("The previous late.py was kept unchanged.")
    assert path.read_text() == "# written after the skills were loaded\n"
    assert "late.py" not in manager.definition_errors
