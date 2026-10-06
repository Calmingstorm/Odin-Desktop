"""Real scheduler, throwaway stores and stubbed external effects only."""
import asyncio
import copy
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.events import EventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.schedules import ScheduleService
from src.scheduler.scheduler import NonRetryableScheduleError, Scheduler
from src.web.api.schedules_api import schedule_methods


@pytest.fixture
def graph(tmp_path):
    paths = ProfilePaths.from_xdg("test", home=tmp_path, environ={})
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


async def add(graph, action="reminder", **kwargs):
    _, service, owner, cid = graph
    return await service.invoke("schedules.save", {"description": "Example", "action": action,
        "channel_id": cid, "cron": "* * * * *", **kwargs}, owner=owner)


async def overdue(scheduler, *, days=1):
    async with scheduler._lock:
        values = scheduler.list_all()
        values[0]["next_run"] = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        await scheduler._publish(values)


@pytest.mark.asyncio
async def test_missed_reminders_coalesce_and_bounded(graph):
    scheduler, _, _, _ = graph
    await add(graph)
    await overdue(scheduler, days=365)
    seen = []
    async def effect(schedule):
        seen.append(copy.deepcopy(schedule))
        assert scheduler.assert_run_binding(schedule) == schedule["run_binding"]
        persisted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
        assert persisted.list_all()[0]["settlement"] == "unknown"
    scheduler._callback = effect
    await scheduler._tick()
    await scheduler._tick()
    assert len(seen) == 1
    assert seen[0]["missed_run"]["missed_count"] == 128
    assert seen[0]["missed_run"]["count_truncated"] is True
    assert scheduler.list_all()[0]["settlement"] == "success"
    assert (await scheduler.history.query())[0]["run_binding"] == seen[0]["run_binding"]
    with pytest.raises(PermissionError):
        scheduler.assert_run_binding(seen[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("action,payload", [
    ("check", {"tool_name": "run_command", "tool_input": {"command": "example"}}),
    ("workflow", {"steps": [{"tool_name": "example", "tool_input": {}}]}),
    ("webhook", {"webhook_config": {"url": "https://example.com"}}),
])
async def test_missed_effects_wait_for_manual_run(graph, action, payload):
    scheduler, service, owner, _ = graph
    item = await add(graph, action, **payload)
    await overdue(scheduler)
    scheduler._callback = AsyncMock()
    scheduler._execute_webhook = AsyncMock(return_value={"status_code": 200})
    await scheduler._tick()
    scheduler._callback.assert_not_awaited()
    scheduler._execute_webhook.assert_not_awaited()
    current = scheduler.list_all()[0]
    assert current["recovery_required"]
    assert current["missed_run"]["workflow_catchup_limit"] == 0
    result = await service.invoke("schedules.run", {"id": item["id"]}, owner=owner)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_uncertain_effect_never_retries_or_replays_on_restart(graph):
    scheduler, service, owner, _ = graph
    item = await add(graph, "check", tool_name="run_command",
                     tool_input={"command": "example"}, max_retries=3)
    scheduler._callback = AsyncMock(side_effect=NonRetryableScheduleError("outcome unknown"))
    result = await service.invoke("schedules.run", {"id": item["id"]}, owner=owner)
    assert result["status"] == "failure"
    current = scheduler.list_all()[0]
    assert current["settlement"] == "unknown" and current["paused"]
    assert "retry_at" not in current
    await service.invoke("schedules.reset_failures", {"id": item["id"]}, owner=owner)
    with pytest.raises(ValueError):
        await service.invoke("schedules.run", {"id": item["id"]}, owner=owner)
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    restarted._callback = AsyncMock()
    await restarted._tick()
    restarted._callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_protocol_authority_timing_destination_and_history(graph):
    scheduler, service, owner, _ = graph
    methods = schedule_methods(service)
    assert set(methods) == service.methods
    with pytest.raises(PermissionError):
        await methods["schedules.list"]({}, owner=SimpleNamespace(owner_id=owner.owner_id))
    for value in ({"requester_id": "forged"},
                  {"run_at": "2020-01-01T00:00:00Z", "cron": None},
                  {"run_at": "2040-01-01T00:00:00", "cron": None}):
        with pytest.raises((ValueError, PermissionError)):
            await add(graph, **value)
    item = await add(graph)
    generation = item["_generation"]
    with pytest.raises(ValueError):
        await methods["schedules.save"]({"id": item["id"], "action": "workflow"}, owner=owner)
    result = await methods["schedules.save"]({"id": item["id"], "paused": True}, owner=owner)
    assert result["_generation"] == generation
    scheduler._callback = AsyncMock()
    await methods["schedules.run"]({"id": item["id"]}, owner=owner)
    history = await methods["schedules.history"]({"id": item["id"]}, owner=owner)
    assert history[0]["status"] == "success"
    scheduler._callback.assert_awaited_once()
    await methods["schedules.delete"]({"id": item["id"]}, owner=owner)
    history = await methods["schedules.history"]({"id": item["id"]}, owner=owner)
    assert history[0]["status"] == "success"
    cron = await methods["schedules.validate_cron"]({"expression": "0 9 * * *"}, owner=owner)
    assert cron["valid"] and len(cron["next_runs"]) == 5


@pytest.mark.asyncio
async def test_reserved_run_keeps_destination_during_edit(graph):
    scheduler, service, owner, cid = graph
    item = await add(graph)
    other = service.conversations.create()["conversation"]["id"]
    async def effect(schedule):
        binding = scheduler.assert_run_binding(schedule)
        await service.invoke("schedules.save", {"id": item["id"], "channel_id": other}, owner=owner)
        assert binding["conversation_id"] == cid
        assert schedule["run_binding"]["conversation_id"] == cid
    scheduler._callback = effect
    await scheduler.run_now(item["id"])
    assert scheduler.list_all()[0]["channel_id"] == other
    assert (await scheduler.history.query())[0]["run_binding"]["conversation_id"] == cid


@pytest.mark.asyncio
async def test_retained_router_no_replay_on_delivery_failure(graph):
    from src.discord.scheduled_events import ScheduledEventHandlers, ScheduledEventsDeps
    from src.tools import ToolResult
    scheduler, _, owner, cid = graph
    item = await add(
        graph, "check", tool_name="run_command", tool_input={"command": "example"},
        max_retries=2,
    )
    @asynccontextmanager
    async def admission(schedule):
        scheduler.assert_run_binding(schedule)
        yield SimpleNamespace(owner_id=owner.owner_id, conversation_id=cid)
    dispatch = AsyncMock(
        return_value=ToolResult(output="recorded", ok=True, tool_name="run_command")
    )
    publish = AsyncMock(side_effect=RuntimeError("delivery unavailable"))
    deps = ScheduledEventsDeps(get_config=lambda: None,
        tool_executor=SimpleNamespace(check_permission=lambda *args: None),
        audit=SimpleNamespace(log_event=AsyncMock()), llm_gateway=None,
        tool_loop=None, agent_task_tools=None, admit_schedule=admission,
        dispatch_tool=dispatch, publish_notice=publish)
    scheduler._callback = ScheduledEventHandlers(deps)._on_scheduled_task
    await scheduler.run_now(item["id"])
    dispatch.assert_awaited_once()
    assert scheduler.list_all()[0]["settlement"] == "unknown"
    assert "retry_at" not in scheduler.list_all()[0]


@pytest.mark.asyncio
async def test_work_control_cas(graph):
    scheduler, _, _, _ = graph
    item = await add(graph)
    binding = {"generation": item["_generation"], "revision": item["_revision"],
        "owner_id": item["requester_id"], "conversation_id": item["channel_id"]}
    await scheduler.desktop_control(item["id"], "pause", expected_binding=binding)
    with pytest.raises(ValueError):
        await scheduler.desktop_control(item["id"], "resume", expected_binding=binding)
    assert scheduler.list_all()[0]["paused"] is True


@pytest.mark.asyncio
async def test_boot_missed_due_and_cancellation_reconciliation(graph):
    scheduler, service, owner, _ = graph
    item = await add(graph, "check", tool_name="run_command", tool_input={"command": "example"})
    await overdue(scheduler)
    loaded = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    assert loaded.list_all()[0]["recovery_required"]
    assert loaded.list_all()[0]["missed_run"]["policy"] == "manual"
    async def cancelled(schedule):
        scheduler.assert_run_binding(schedule)
        raise asyncio.CancelledError
    scheduler._callback = cancelled
    with pytest.raises(asyncio.CancelledError):
        await scheduler.run_now(item["id"])
    persisted_binding = scheduler.list_all()[0]["last_run_binding"]
    assert scheduler.list_all()[0]["settlement"] == "unknown"
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    assert restarted.list_all()[0]["settlement"] == "unknown"
    assert restarted.list_all()[0]["last_run_binding"] == persisted_binding
    recovery = ScheduleService(restarted, authority=service.authority,
                               conversations=service.conversations)
    await recovery.recover()
    again = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    assert not again.list_all()[0].get("paused")
    assert again.list_all()[0]["settlement"] == "unknown"
    history = await recovery.invoke("schedules.history", {"id": item["id"]}, owner=owner)
    assert len(history) == 1 and history[0]["status"] == "unknown"
    assert history[0]["run_binding"] == persisted_binding


@pytest.mark.asyncio
@pytest.mark.parametrize("timing", ["cron", "trigger"])
@pytest.mark.parametrize("interruption", ["cancel", "boot"])
async def test_interrupted_definition_keeps_next_run_and_durable_unknown(
    graph, timing, interruption
):
    scheduler, service, owner, _ = graph
    values = {} if timing == "cron" else {
        "cron": None, "trigger": {"source": "generic", "event": "push"}
    }
    item = await add(graph, "check", tool_name="run_command",
                     tool_input={"command": "example"}, max_retries=3, **values)
    next_run = scheduler.list_all()[0].get("next_run")
    if interruption == "cancel":
        async def cancelled(schedule):
            scheduler.assert_run_binding(schedule)
            raise asyncio.CancelledError
        scheduler._callback = cancelled
        notifications = []
        unsubscribe = scheduler.subscribe_changes(lambda: notifications.append(True))
        with pytest.raises(asyncio.CancelledError):
            await scheduler.run_now(item["id"])
        unsubscribe()
        assert len(notifications) == 3  # reservation, start, unknown settlement
    else:
        # Persist exactly the pre-effect start marker a terminated process
        # leaves behind, including a retry that must never be replayed.
        async with scheduler._lock:
            items = scheduler.list_all()
            items[0]["retry_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
            await scheduler._publish(items)
        await scheduler._mark_run_started(item)
    binding = item.get("run_binding") or scheduler.list_all()[0]["last_run_binding"]
    for _ in range(2):
        restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
        recovery = ScheduleService(restarted, authority=service.authority,
                                   conversations=service.conversations)
        await recovery.recover()
        current = restarted.list_all()[0]
        assert current["settlement"] == "unknown"
        assert current["last_run_binding"] == binding
        assert not current.get("paused") and "inert_reason" not in current
        assert current.get("next_run") == next_run
        assert not {"run_started_at", "run_binding", "retry_at",
                    "_interrupted_run_history"} & current.keys()
        restarted._callback = AsyncMock()
        await restarted._tick()
        restarted._callback.assert_not_awaited()
        history = await recovery.invoke("schedules.history", {"id": item["id"]}, owner=owner)
        assert len(history) == 1 and history[0]["status"] == "unknown"
        assert history[0]["run_binding"] == binding
    if timing == "cron":
        # A controllable clock reaches the next real slot without catch-up,
        # sleeps, or changes to any product deadline.
        due = datetime.fromisoformat(next_run)
        from unittest.mock import patch
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return due.astimezone(tz) if tz else due.replace(tzinfo=None)
        with patch("src.scheduler.scheduler.datetime", Clock):
            await restarted._tick()
    else:
        await restarted.fire_triggers("generic", {"event": "push"})
    restarted._callback.assert_awaited_once()
    new_binding = restarted._callback.await_args.args[0]["run_binding"]
    assert new_binding != binding
    assert restarted.list_all()[0]["settlement"] == "success"
    history = await restarted.history.query(item["id"])
    assert [entry["status"] for entry in history] == ["success", "unknown"]
    assert history[1]["run_binding"] == binding


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["reminder", "check"])
async def test_interrupted_elapsed_cron_skips_replay_and_resumes_cadence(graph, action):
    scheduler, service, _, _ = graph
    values = {"tool_name": "run_command", "tool_input": {"command": "example"}} \
        if action == "check" else {}
    item = await add(graph, action, **values)
    await overdue(scheduler)
    await scheduler._mark_run_started(item)
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    await ScheduleService(restarted, authority=service.authority,
                          conversations=service.conversations).recover()
    current = restarted.list_all()[0]
    assert not current.get("paused")
    assert "recovery_required" not in current and "missed_run" not in current
    assert datetime.fromisoformat(current["next_run"]) > datetime.now(UTC)
    restarted._callback = AsyncMock()
    await restarted._tick()
    restarted._callback.assert_not_awaited()
    assert (await restarted.history.query(item["id"]))[0]["status"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["check", "workflow", "webhook"])
async def test_interrupted_one_time_stays_quarantined_with_odin_wording(graph, action):
    scheduler, service, owner, _ = graph
    values = {
        "check": {"tool_name": "run_command", "tool_input": {"command": "example"}},
        "workflow": {"steps": [{"tool_name": "example", "tool_input": {}}]},
        "webhook": {"webhook_config": {"url": "https://example.com"}},
    }[action]
    item = await add(graph, action, cron=None,
                     run_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(), **values)
    await scheduler._mark_run_started(item)
    started = scheduler.list_all()[0]["run_started_at"]
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    await ScheduleService(restarted, authority=service.authority,
                          conversations=service.conversations).recover()
    current = restarted.list_all()[0]
    reason = (
        f"One-time schedule started at {started!r} but its completion was never recorded "
        "(Odin stopped or could not save the result); it may have partly run, so it was not "
        "run again. Check what it did, then set a new run_at to re-arm it"
    )
    assert current["paused"] and current["inert_reason"] == reason[:300]
    assert current["settlement"] == "unknown"
    restarted._callback = AsyncMock()
    restarted._execute_webhook = AsyncMock()
    await restarted._tick()
    restarted._callback.assert_not_awaited()
    restarted._execute_webhook.assert_not_awaited()
    with pytest.raises(ValueError, match="One-time schedule started at"):
        await restarted.run_now(item["id"])
    with pytest.raises(ValueError, match="One-time schedule started at"):
        await restarted.update(item["id"], paused=False)
    assert (await restarted.history.query(item["id"]))[0]["run_binding"] == item["run_binding"]
    rearmed = await restarted.update(
        item["id"], run_at=(datetime.now(UTC) + timedelta(hours=2)).isoformat()
    )
    assert not rearmed["paused"] and "inert_reason" not in rearmed


@pytest.mark.asyncio
async def test_interrupted_history_survives_failed_store_write_without_duplicates(
    graph, monkeypatch
):
    scheduler, service, _, _ = graph
    item = await add(graph)
    await scheduler._mark_run_started(item)
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    recovery = ScheduleService(restarted, authority=service.authority,
                               conversations=service.conversations)
    with monkeypatch.context() as m:
        def failed_write(self):
            raise OSError("injected schedule store write failure")
        m.setattr(Scheduler, "_save", failed_write)
        with pytest.raises(OSError, match="injected schedule store"):
            await recovery.recover()
    assert len(await restarted.history.query(item["id"])) == 1
    again = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    await ScheduleService(again, authority=service.authority,
                          conversations=service.conversations).recover()
    assert len(await again.history.query(item["id"])) == 1
    assert not again.list_all()[0].get("paused")


@pytest.mark.asyncio
async def test_interrupted_history_outbox_retries_failed_history_storage(graph, monkeypatch):
    scheduler, service, _, _ = graph
    item = await add(graph)
    await scheduler._mark_run_started(item)
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    with monkeypatch.context() as m:
        def unavailable(pending):
            raise OSError("history unavailable")
        m.setattr(restarted.history, "_record_interrupted_sync", unavailable)
        await ScheduleService(restarted, authority=service.authority,
                              conversations=service.conversations).recover()
    assert not await restarted.history.query(item["id"])
    again = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    assert again.list_all()[0]["_interrupted_run_history"][0]["run_binding"] == item["run_binding"]
    await ScheduleService(again, authority=service.authority,
                          conversations=service.conversations).recover()
    assert "_interrupted_run_history" not in again.list_all()[0]
    assert len(await again.history.query(item["id"])) == 1


@pytest.mark.asyncio
async def test_interrupted_existing_history_read_failure_keeps_outbox(graph, monkeypatch):
    from pathlib import Path

    scheduler, service, _, _ = graph
    item = await add(graph)
    await scheduler._mark_run_started(item)
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    pending = restarted.list_all()[0]["_interrupted_run_history"][0]
    await restarted.history.record_interrupted(pending)
    original_bytes = restarted.history.path.read_bytes()
    original_open = Path.open

    class Unreadable:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def seek(self, offset):
            pass
        def __iter__(self):
            raise OSError("injected history read failure")

    def unreadable(path, *args, **kwargs):
        if path == restarted.history.path and args == ("a+",):
            return Unreadable()
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(Path, "open", unreadable)
        await ScheduleService(restarted, authority=service.authority,
                              conversations=service.conversations).recover()
    assert restarted.history.path.read_bytes() == original_bytes
    assert restarted.list_all()[0]["_interrupted_run_history"] == [pending]
    again = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    await ScheduleService(again, authority=service.authority,
                          conversations=service.conversations).recover()
    assert len(await again.history.query(item["id"])) == 1
    assert "_interrupted_run_history" not in again.list_all()[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_target", ["file", "directory"])
async def test_interrupted_fsync_failure_retries_before_outbox_retirement(
    graph, monkeypatch, failure_target
):
    import os
    import stat

    scheduler, service, _, _ = graph
    item = await add(graph)
    await scheduler._mark_run_started(item)
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    pending = restarted.list_all()[0]["_interrupted_run_history"][0]
    real_fsync = os.fsync
    real_save = Scheduler._save
    events = []
    failing = True

    def fsync(fd):
        metadata = os.fstat(fd)
        target = None
        if metadata.st_ino == restarted.history.path.stat().st_ino:
            target = "file"
            # Flush must already have exposed the complete entry.
            assert len(restarted.history.path.read_text().splitlines()) == 1
        elif stat.S_ISDIR(metadata.st_mode):
            target = "directory"
        if target:
            events.append(target)
            if failing and target == failure_target:
                raise OSError("injected history fsync failure")
        return real_fsync(fd)

    def save(writer):
        events.append("save")
        if failing:
            assert writer._schedules[0]["_interrupted_run_history"] == [pending]
        else:
            assert events == ["file", "directory", "save"]
            assert "_interrupted_run_history" not in writer._schedules[0]
        return real_save(writer)

    with monkeypatch.context() as m:
        m.setattr(os, "fsync", fsync)
        m.setattr(Scheduler, "_save", save)
        recovery = ScheduleService(restarted, authority=service.authority,
                                   conversations=service.conversations)
        await recovery.recover()
        assert restarted.list_all()[0]["_interrupted_run_history"] == [pending]
        assert events == (["file", "save"] if failure_target == "file"
                          else ["file", "directory", "save"])
        failing = False
        events.clear()
        await recovery.recover()
    assert "_interrupted_run_history" not in restarted.list_all()[0]
    assert len(await restarted.history.query(item["id"])) == 1


@pytest.mark.asyncio
async def test_consecutive_interrupted_runs_keep_scalar_and_list_outbox(graph, monkeypatch):
    scheduler, service, _, _ = graph
    item = await add(graph)
    await scheduler._mark_run_started(item)
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    first = restarted.list_all()[0]["_interrupted_run_history"][0]
    # An older durable store may still use the scalar representation.
    restarted._schedules[0]["_interrupted_run_history"] = copy.deepcopy(first)
    with monkeypatch.context() as m:
        def unavailable(self, pending):
            raise OSError("history unavailable")
        m.setattr(type(restarted.history), "_record_interrupted_sync", unavailable)
        await ScheduleService(restarted, authority=service.authority,
                              conversations=service.conversations).recover()
        for _ in range(2):
            await restarted._mark_run_started(restarted.list_all()[0])
            restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
            await ScheduleService(restarted, authority=service.authority,
                                  conversations=service.conversations).recover()
        pending = restarted.list_all()[0]["_interrupted_run_history"]
        assert len(pending) == 3 and pending[0] == first
        assert len({entry["run_binding"]["run_id"] for entry in pending}) == 3
        assert not restarted.list_all()[0].get("paused")
    again = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    again._callback = AsyncMock()
    await ScheduleService(again, authority=service.authority,
                          conversations=service.conversations).recover()
    await again._tick()
    again._callback.assert_not_awaited()
    entries = await again.history.query(item["id"])
    assert len(entries) == 3
    assert {entry["run_binding"]["run_id"] for entry in entries} == {
        entry["run_binding"]["run_id"] for entry in pending
    }
    assert "_interrupted_run_history" not in again.list_all()[0]
    assert not again.list_all()[0].get("paused")


@pytest.mark.asyncio
async def test_interrupted_dedup_uses_all_binding_and_start_evidence(graph):
    scheduler, _, _, _ = graph
    item = await add(graph)
    await scheduler._mark_run_started(item)
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    pending = restarted.list_all()[0]["_interrupted_run_history"][0]
    await restarted.history.record_interrupted(pending)
    # A match beyond the old 200-entry query window must still deduplicate.
    for _ in range(201):
        await restarted.history.record(schedule_id=item["id"], description="later",
                                       action="reminder", status="success", duration_ms=0)
    await asyncio.gather(*(restarted.history.record_interrupted(pending) for _ in range(4)))
    entries = await restarted.history.query(item["id"], status="unknown", limit=500)
    assert len(entries) == 1
    for key in ("generation", "owner_id", "conversation_id", "schedule_id"):
        other = copy.deepcopy(pending)
        other["run_binding"][key] = "different"
        await restarted.history.record_interrupted(other)
    other = copy.deepcopy(pending)
    other["error"] = "Run started at another instant; completion was never recorded"
    await restarted.history.record_interrupted(other)
    assert len(await restarted.history.query(item["id"], status="unknown", limit=500)) == 6


@pytest.mark.asyncio
async def test_webhook_timeout_does_not_retry(graph):
    scheduler, _, _, _ = graph
    item = await add(graph, "webhook", webhook_config={"url": "https://example.com"}, max_retries=3)
    scheduler._execute_webhook = AsyncMock(side_effect=TimeoutError("unknown reply"))
    await scheduler.run_now(item["id"])
    assert scheduler.list_all()[0]["settlement"] == "unknown"
    assert "retry_at" not in scheduler.list_all()[0]
    scheduler._execute_webhook.assert_awaited_once()


@pytest.mark.asyncio
async def test_paused_one_time_spent_and_rearm(graph):
    scheduler, service, owner, cid = graph
    item = await service.invoke(
        "schedules.save", {"description": "One time", "channel_id": cid,
         "run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}, owner=owner
    )
    await scheduler.update(item["id"], paused=True)
    async with scheduler._lock:
        items = scheduler.list_all()
        items[0]["run_at"] = items[0]["next_run"] = (
            datetime.now(UTC) - timedelta(hours=1)
        ).isoformat()
        await scheduler._publish(items)
    result = await service.invoke(
        "schedules.save", {"id": item["id"], "paused": False}, owner=owner
    )
    assert result["inert_reason"] and result["paused"]
    result = await service.invoke("schedules.save", {"id": item["id"],
        "run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}, owner=owner)
    assert not result["paused"] and "inert_reason" not in result
    assert result["_generation"] == item["_generation"]


@pytest.mark.asyncio
async def test_native_schedule_uses_sealed_request_service(graph):
    from src.discord.native_tools.scheduling import SchedulingTools
    scheduler, service, owner, cid = graph
    request = SimpleNamespace(owner_id=owner.owner_id, conversation_id=cid)
    def assert_request(message):
        if message is not request:
            raise PermissionError("not admitted")
    def request_provider(message=None):
        assert_request(request if message is None else message)
        return request
    service.assert_request = assert_request
    tools = SchedulingTools(scheduler=scheduler, service_provider=lambda: service,
                             request_provider=request_provider)
    with pytest.raises(PermissionError):
        await tools._handle_schedule_task(SimpleNamespace(owner_id=owner.owner_id), {})
    result = await tools._handle_schedule_task(
        request,
        {"description": "Example", "message": "Notice",
         "action": "reminder", "cron": "0 9 * * *"},
    )
    assert "Scheduled recurring" in result
    item = scheduler.list_all()[0]
    assert item["requester_id"] == owner.owner_id and item["channel_id"] == cid
    assert "Example" in tools._handle_list_schedules()
    assert "Updated" in await tools._handle_update_schedule(
        {"schedule_id": item["id"], "paused": True}
    )
    assert "Deleted" in await tools._handle_delete_schedule(
        {"schedule_id": item["id"]}
    )


@pytest.mark.asyncio
async def test_workflow_uncertain_step_never_continues_or_retries(graph):
    from src.discord.scheduled_events import ScheduledEventHandlers, ScheduledEventsDeps
    from src.tools import ToolResult
    scheduler, _, owner, cid = graph
    item = await add(graph, "workflow", steps=[
        {"tool_name": "example", "tool_input": {}},
        {"tool_name": "second", "tool_input": {}, "on_failure": "continue"}], max_retries=3)
    @asynccontextmanager
    async def admission(schedule):
        scheduler.assert_run_binding(schedule)
        yield SimpleNamespace(owner_id=owner.owner_id, conversation_id=cid)
    dispatch = AsyncMock(return_value=ToolResult(output="unknown", ok=False,
        uncertain_outcome=True, tool_name="example"))
    handler = ScheduledEventHandlers(ScheduledEventsDeps(get_config=lambda: None,
        tool_executor=SimpleNamespace(check_permission=lambda *args: None),
        audit=SimpleNamespace(log_event=AsyncMock()), llm_gateway=None, tool_loop=None,
        agent_task_tools=None, admit_schedule=admission, dispatch_tool=dispatch,
        publish_notice=AsyncMock()))
    scheduler._callback = handler._on_scheduled_task
    await scheduler.run_now(item["id"])
    dispatch.assert_awaited_once()
    assert scheduler.list_all()[0]["settlement"] == "unknown"
    assert scheduler.list_all()[0]["paused"]
    assert "retry_at" not in scheduler.list_all()[0]


@pytest.mark.asyncio
async def test_reminder_catchup_notice_and_report_hook(graph):
    from src.discord.scheduled_events import ScheduledEventHandlers, ScheduledEventsDeps
    from src.tools import ToolResult
    scheduler, service, owner, cid = graph
    item = await add(graph)
    await overdue(scheduler)
    @asynccontextmanager
    async def admission(schedule):
        scheduler.assert_run_binding(schedule)
        yield SimpleNamespace(owner_id=owner.owner_id, conversation_id=cid)
    publish = AsyncMock()
    report = AsyncMock()
    dispatch = AsyncMock(
        return_value=ToolResult(output="stored report", ok=True, tool_name="run_command")
    )
    handler = ScheduledEventHandlers(ScheduledEventsDeps(get_config=lambda: None,
        tool_executor=SimpleNamespace(check_permission=lambda *args: None),
        audit=SimpleNamespace(log_event=AsyncMock()), llm_gateway=None, tool_loop=None,
        agent_task_tools=None, admit_schedule=admission, dispatch_tool=dispatch,
        publish_notice=publish, publish_report=report))
    scheduler._callback = handler._on_scheduled_task
    await scheduler._tick()
    assert "Omitted slots:" in publish.await_args.args[1]
    await service.invoke("schedules.delete", {"id": item["id"]}, owner=owner)
    scheduler.set_known_report_formats_provider(lambda: {"paginated_embed_v1"})
    item = await add(graph, "check", tool_name="run_command", tool_input={"command": "example"},
                     report_format="paginated_embed_v1")
    await scheduler.run_now(item["id"])
    report.assert_awaited_once()
    assert report.await_args.args[1:] == ("paginated_embed_v1", "stored report", "run_command")
