"""Odin 4.22.0's scheduling lanes (#708) with Desktop's missed-run recovery (D12).

A slot that waits for its lane (another schedule's run) or for its own scheduled run is not
downtime: it runs when it can, as in Odin. A slot overdue at startup, or one that came due
while its lane was free and nothing ticked (the app asleep), still waits for an explicit run.
A controlled clock stands in for minutes of waiting.
"""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.events import EventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.schedules import ScheduleService
from src.scheduler.scheduler import Scheduler

START = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)


class Clock(datetime):
    """``datetime`` whose ``now`` is the test's instant (scheduler and preview share it)."""

    instant = START

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz is not None else cls.instant.replace(tzinfo=None)


@pytest.fixture
def graph(tmp_path, monkeypatch):
    import src.desktop.schedules as preview_module
    import src.scheduler.scheduler as scheduler_module

    Clock.instant = START
    monkeypatch.setattr(preview_module, "datetime", Clock)
    monkeypatch.setattr(scheduler_module, "datetime", Clock)
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


class Runs:
    """The schedules' callback: records each run; a gated one runs until released."""

    def __init__(self):
        self.started = []
        self.gates = {}

    def hold(self, sid):
        self.gates[sid] = asyncio.Event()

    async def __call__(self, schedule):
        self.started.append(schedule["id"])
        gate = self.gates.get(schedule["id"])
        if gate is not None:
            await gate.wait()


async def add(graph, description, *, action="check", cron="0 * * * *"):
    _, service, owner, cid = graph
    extra = ({"tool_name": "run_command", "tool_input": {"command": "example"}}
             if action == "check" else {"message": "Example"})
    return await service.invoke("schedules.save", {
        "description": description, "action": action, "channel_id": cid, "cron": cron,
        **extra}, owner=owner)


async def due_at(scheduler, sid, when):
    async with scheduler._lock:
        values = scheduler.list_all()
        for value in values:
            if value["id"] == sid:
                value["next_run"] = when.isoformat()
        await scheduler._publish(values)


def record(scheduler, sid):
    return next(value for value in scheduler.list_all() if value["id"] == sid)


async def settle(predicate):
    # A run starts after the scheduler's off-loop persistence: wait in real time.
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the expected run never started")


async def drain(scheduler):
    while scheduler._dispatches:
        await asyncio.gather(*list(scheduler._dispatches), return_exceptions=True)
        await asyncio.sleep(0)


async def tick_at(scheduler, when):
    Clock.instant = when
    await scheduler._tick(wait=False)


def not_missed(value):
    return "recovery_required" not in value and "missed_run" not in value


@pytest.mark.asyncio
async def test_a_slot_held_by_its_busy_lane_runs_once_the_lane_frees(graph):
    scheduler = graph[0]
    long, waiting = await add(graph, "Long check"), await add(graph, "Waiting check")
    reminder = await add(graph, "Reminder", action="reminder")
    await due_at(scheduler, long["id"], START)
    await due_at(scheduler, waiting["id"], START + timedelta(seconds=30))
    await due_at(scheduler, reminder["id"], START + timedelta(seconds=40))
    runs = Runs()
    runs.hold(long["id"])
    scheduler._callback = runs
    await tick_at(scheduler, START)
    await settle(lambda: runs.started == [long["id"]])
    await tick_at(scheduler, START + timedelta(seconds=30))  # due; its lane is busy
    await tick_at(scheduler, START + timedelta(seconds=40))  # another lane runs on time
    await settle(lambda: runs.started == [long["id"], reminder["id"]])
    await tick_at(scheduler, START + timedelta(minutes=5))  # held well past the 60 s grace
    assert runs.started == [long["id"], reminder["id"]]
    assert not_missed(record(scheduler, waiting["id"]))
    runs.gates[long["id"]].set()
    await drain(scheduler)
    await tick_at(scheduler, START + timedelta(minutes=5, seconds=1))
    await settle(lambda: runs.started[-1] == waiting["id"])
    await drain(scheduler)
    assert runs.started == [long["id"], reminder["id"], waiting["id"]]
    assert not_missed(record(scheduler, waiting["id"]))
    assert record(scheduler, waiting["id"])["next_run"] == (START + timedelta(hours=1)).isoformat()


@pytest.mark.asyncio
async def test_a_slot_due_during_its_own_long_run_follows_it(graph):
    scheduler = graph[0]
    item = await add(graph, "Minutely check", cron="* * * * *")
    await due_at(scheduler, item["id"], START)
    runs = Runs()
    runs.hold(item["id"])
    scheduler._callback = runs
    await tick_at(scheduler, START)  # runs; its next slot is 12:01
    await settle(lambda: runs.started == [item["id"]])
    await tick_at(scheduler, START + timedelta(minutes=5))  # still running, 4 minutes past it
    assert runs.started == [item["id"]] and not_missed(record(scheduler, item["id"]))
    runs.gates.pop(item["id"]).set()
    await drain(scheduler)
    await tick_at(scheduler, START + timedelta(minutes=5, seconds=1))
    await settle(lambda: len(runs.started) == 2)
    await drain(scheduler)
    assert not_missed(record(scheduler, item["id"]))
    assert record(scheduler, item["id"])["next_run"] == (START + timedelta(minutes=6)).isoformat()


@pytest.mark.asyncio
async def test_a_slot_overdue_at_startup_still_waits_for_an_explicit_run(graph):
    scheduler, service, owner, _ = graph
    item = await add(graph, "Check")
    await due_at(scheduler, item["id"], START - timedelta(hours=2))
    restarted = Scheduler(str(scheduler.data_path), desktop_recovery=True)
    restarted._callback = Runs()
    await tick_at(restarted, START)
    await drain(restarted)
    assert restarted._callback.started == []
    assert record(restarted, item["id"])["recovery_required"]


@pytest.mark.asyncio
async def test_a_slot_due_while_its_lane_was_free_counts_from_its_due_time(graph):
    """An earlier run of the lane ended before this slot came due: the slot was not held,
    so a late first look (the app asleep, nothing ticking) is missed time, as before."""
    scheduler = graph[0]
    first, later = await add(graph, "First check"), await add(graph, "Later check")
    await due_at(scheduler, first["id"], START)
    await due_at(scheduler, later["id"], START + timedelta(minutes=10))
    runs = Runs()
    scheduler._callback = runs
    await tick_at(scheduler, START)
    await drain(scheduler)
    assert runs.started == [first["id"]]
    await tick_at(scheduler, START + timedelta(minutes=30))
    await drain(scheduler)
    assert runs.started == [first["id"]]
    assert record(scheduler, later["id"])["recovery_required"]


@pytest.mark.asyncio
async def test_a_runs_end_is_recorded_before_its_task_is_done(graph):
    """A tick can run after a dispatch's task is done but before its done callbacks: the
    lane already reads free there, so the lane's end time must already be recorded."""
    from src.scheduler.scheduler import _lane

    scheduler = graph[0]
    item = await add(graph, "Quick check")
    await due_at(scheduler, item["id"], START)
    scheduler._callback = Runs()
    await tick_at(scheduler, START)
    task = next(iter(scheduler._dispatches))
    lane = _lane(record(scheduler, item["id"]))
    while not task.done():
        await asyncio.sleep(0)
    # Resumed ahead of the task's done callbacks (the ready queue is FIFO).
    assert lane not in scheduler._busy_lanes()
    assert scheduler._lane_freed_at.get(lane) == START
    assert scheduler._run_ended_at.get(item["id"]) == START


@pytest.mark.asyncio
async def test_a_tick_queued_on_the_completions_publication_keeps_the_held_slot(
        graph, monkeypatch):
    """Odin's review R2: the run's completion publishes under the scheduler lock; a tick
    queued on that lock runs once it is released, possibly before the finished task's
    done callbacks. It must still see the lane's end and keep the held slot."""
    scheduler = graph[0]
    long, waiting = await add(graph, "Long check"), await add(graph, "Waiting check")
    await due_at(scheduler, long["id"], START)
    await due_at(scheduler, waiting["id"], START + timedelta(seconds=30))
    runs = Runs()
    runs.hold(long["id"])
    scheduler._callback = runs
    await tick_at(scheduler, START)
    await settle(lambda: runs.started == [long["id"]])
    await tick_at(scheduler, START + timedelta(seconds=30))  # held behind the long run
    Clock.instant = START + timedelta(minutes=5)
    publish, gate, publishing = scheduler._publish, asyncio.Event(), asyncio.Event()

    async def held_publication(values):
        publishing.set()
        await gate.wait()
        return await publish(values)

    monkeypatch.setattr(scheduler, "_publish", held_publication)
    runs.gates[long["id"]].set()
    async with asyncio.timeout(5):
        await publishing.wait()  # the completion's publication, inside the lock
    monkeypatch.setattr(scheduler, "_publish", publish)
    queued = asyncio.create_task(scheduler._tick(wait=False))
    await asyncio.sleep(0.05)
    assert not queued.done()  # it waits for the lock the completion holds
    gate.set()
    async with asyncio.timeout(5):
        await queued
    await drain(scheduler)
    if runs.started[-1] != waiting["id"]:
        await tick_at(scheduler, START + timedelta(minutes=5, seconds=1))
        await settle(lambda: runs.started[-1] == waiting["id"])
        await drain(scheduler)
    assert runs.started == [long["id"], waiting["id"]]
    assert not_missed(record(scheduler, waiting["id"]))
