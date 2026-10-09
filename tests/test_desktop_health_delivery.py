"""D17 delivery health observes the real durable request graph through IPC."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from src.desktop.core import CoreService
from src.health.checker import check_delivery
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_delivery import build
from tests.test_desktop_management_core import TemporaryKeyring
from tests.test_desktop_request_core import Provider, configured, service, settled


def delivery_component(report):
    component = next(item for item in report["components"] if item["name"] == "delivery")
    assert report["unavailable_count"] == sum(
        item["status"] == "unavailable" for item in report["components"])
    return component


def assert_ready(report):
    assert delivery_component(report) == {
        "name": "delivery", "healthy": True, "status": "ok", "detail": "Delivery ready",
    }
    assert report["unavailable_count"] == sum(
        item["status"] == "unavailable" for item in report["components"]
        if item["name"] != "delivery")


@pytest.fixture
async def composed(tmp_path, monkeypatch):
    import aiohttp

    def refuse_network(*args, **kwargs):
        pytest.fail("Delivery health proofs must not open network clients")

    monkeypatch.setattr(aiohttp, "ClientSession", refuse_network)
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider()
    core = service(paths, socket_path, token_file, provider)
    core._secret_backend = TemporaryKeyring()
    assert configured(paths).openai_compatible.enabled
    before = check_delivery(core).to_dict()
    assert before == {
        "name": "delivery", "healthy": False, "status": "down",
        "detail": "Delivery not ready", "metadata": {"reason": "delivery_not_composed"},
    }
    # Enabled provider configuration by itself did not make delivery ready.
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        yield core, provider, reader, writer
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


async def test_health_delivery_ready_after_startup_and_real_guarded_turn(composed):
    core, provider, reader, writer = composed
    assert core.requests.delivery is core.delivery is core.engine.deps.delivery
    assert core.engine.requests is core.requests
    assert core.delivery.sink is None  # Direct journal IPC needs no external sink.
    startup = await request(reader, writer, "health.get")
    assert startup["ok"], startup
    assert_ready(startup["result"])

    created = await request(reader, writer, "conversations.create")
    cid = created["result"]["conversation"]["id"]
    accepted = await request(reader, writer, "submission.send", {
        "client_submission_id": "health-delivery-proof", "conversation_id": cid,
        "text": "Harmless delivery health proof",
    })
    assert accepted["ok"], accepted
    await settled(core)
    snapshot = await request(reader, writer, "conversation.snapshot", {"conversation_id": cid})
    replies = [item for item in snapshot["result"]["messages"]["items"]
               if item["role"] == "assistant"]
    assert [item["text"] for item in replies] == ["Guarded answer 1."]
    assert provider.calls == 1
    assert core.store.connection.execute(
        "SELECT COUNT(*) FROM desktop_delivery_outbox WHERE request_id=?",
        (accepted["result"]["request_id"],)).fetchone()[0] > 0
    after = await request(reader, writer, "health.get")
    assert after["ok"], after
    assert_ready(after["result"])



async def test_health_reads_the_composed_engine_parts_not_odin_bot_names(composed):
    """Sessions, knowledge, scheduler, loops and agents are composed; none is "not initialised"."""
    core, _provider, reader, writer = composed
    health = await request(reader, writer, "health.get")
    assert health["ok"], health
    components = {item["name"]: item for item in health["result"]["components"]}
    for name in ("sessions", "knowledge", "scheduler", "loops", "agents"):
        assert components[name]["status"] == "ok", components[name]
        assert "not initialised" not in components[name]["detail"]
    deps = core.engine.deps
    assert components["scheduler"]["metadata"]["count"] == len(deps.scheduler.list_all())
    assert components["agents"]["metadata"]["total"] == len(deps.agent_manager._agents)


async def test_core_registers_each_scheduled_run_with_work_webhooks_included(composed):
    """The scheduler's run observer is the core's own, so a webhook run, which never reaches the
    callback admission, still names its binding in Work as it starts."""
    core, _provider, _reader, _writer = composed
    scheduler = core.engine.deps.scheduler
    assert scheduler.run_observer == core._observe_schedule_run
    cid = core.conversations.create()["conversation"]["id"]
    owner = core.authority.authenticate_local(peer_uid=core.authority.owner_uid)
    token = core.permissions.set_request_owner(owner)
    try:
        added = await scheduler.add("inert webhook", "webhook", cid, cron="0 0 * * *",
                                    requester_id=core.authority.owner_id,
                                    webhook_config={"url": "https://example.invalid/x"})
        current = next(s for s in scheduler._schedules if s["id"] == added["id"])
        current["run_binding"] = {"run_id": "r-start", "generation": current["_generation"]}
        scheduler._observe_run_start(dict(current))
        listed = core.work.list({"kind": "schedule"})["items"]
        [item] = [i for i in listed if i["manager_id"] == added["id"]]
        assert item["detail"]["run_binding"]["run_id"] == "r-start"
        foreign = {**current, "requester_id": "someone-else"}
        core._observe_schedule_run(foreign)  # another requester's definition is not Work's
    finally:
        core.permissions.reset_request_owner(token)

async def _until(condition):
    for _ in range(500):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("the condition never held")


@contextmanager
def _as_owner(core):
    """The owner context a chat turn's tools run in, which saving a schedule requires."""
    owner = core.authority.authenticate_local(peer_uid=core.authority.owner_uid)
    token = core.permissions.set_request_owner(owner)
    try:
        yield
    finally:
        core.permissions.reset_request_owner(token)


def _schedule_states(core, after, schedule_id):
    return [event["payload"]["state"] for event in core.events.between(after)
            if event["type"] == "work.updated" and event["payload"]["manager_id"] == schedule_id]


async def test_core_work_follows_schedules_saved_outside_schedule_calls(composed):
    """Odin's schedule tools save and delete through the scheduler alone, never a
    schedules.* call. The scheduler's change notice brings Work up to date before any run."""
    core, _provider, _reader, _writer = composed
    scheduler = core.engine.deps.scheduler
    cid = core.conversations.create()["conversation"]["id"]
    high = core.events.high
    with _as_owner(core):
        added = await scheduler.add("inert reminder", "reminder", cid, cron="17 3 * * *",
                                    message="inert", requester_id=core.authority.owner_id)
        await _until(lambda: _schedule_states(core, high, added["id"]) == ["scheduled"])
        await scheduler.delete(added["id"])
        await _until(lambda: _schedule_states(core, high, added["id"]) == [
            "scheduled", "cancelled"])


async def test_core_work_catch_up_failure_is_logged_and_the_next_change_retries(
        composed, monkeypatch):
    core, _provider, _reader, _writer = composed
    scheduler = core.engine.deps.scheduler
    cid = core.conversations.create()["conversation"]["id"]
    failures, real = [RuntimeError("inert storage failure")], core.work.sync_schedules

    def flaky():
        if failures:
            raise failures.pop()
        real()

    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("odin.desktop.core")
    logger.addHandler(handler)
    monkeypatch.setattr(core.work, "sync_schedules", flaky)
    try:
        high = core.events.high
        with _as_owner(core):
            added = await scheduler.add("inert reminder", "reminder", cid, cron="17 3 * * *",
                                        message="inert", requester_id=core.authority.owner_id)
        await _until(lambda: records)
        assert records[0].getMessage() == "Work could not follow a schedule change"
        assert _schedule_states(core, high, added["id"]) == []
        # The retry follows a change made outside any turn's owner context: the catch-up
        # runs with the core's own sealed authority, as the scheduler task does.
        await scheduler.update(added["id"], description="inert reminder, renamed")
        await _until(lambda: _schedule_states(core, high, added["id"]) == ["scheduled"])
    finally:
        logger.removeHandler(handler)


async def test_core_queues_one_catch_up_for_notices_that_arrive_before_it_runs(
        composed, monkeypatch):
    core, _provider, _reader, _writer = composed
    scheduler = core.engine.deps.scheduler
    passes = []
    monkeypatch.setattr(core.work, "sync_schedules", lambda: passes.append(1))

    def notify():
        for subscriber in tuple(scheduler._change_subscribers):
            subscriber()

    for _ in range(3):
        notify()  # a burst: three publications before the loop runs anything
    await _until(lambda: passes)
    for _ in range(20):
        await asyncio.sleep(0)
    assert len(passes) == 1
    notify()  # a change after the pass started queues the next one
    await _until(lambda: len(passes) == 2)


async def test_core_stops_following_the_scheduler_when_it_closes(composed, monkeypatch):
    core, _provider, _reader, _writer = composed
    scheduler = core.engine.deps.scheduler
    await core.close()

    def closed():
        raise AssertionError("a closed core's Work follows nothing")

    monkeypatch.setattr(core.work, "sync_schedules", closed)
    core._sync_schedule_work()  # a notice queued before close finds the core closed
    assert not scheduler._change_subscribers  # webhooks and Work both unsubscribed


async def test_core_imports_definitions_saved_before_it_started(tmp_path, monkeypatch):
    """A schedule an older version saved from chat never reached Work. The next core start
    imports it, without waiting for the scheduler's next change."""
    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **k: pytest.fail("no network"))
    paths, socket_path, token_file = profile(tmp_path)

    async def run(check):
        core = service(paths, socket_path, token_file, Provider())
        core._secret_backend = TemporaryKeyring()
        read_fd, write_fd = os.pipe()
        try:
            await core.start(read_fd)
            return await check(core)
        finally:
            await core.close()
            os.close(read_fd)
            os.close(write_fd)

    async def older_version(core):
        core._schedule_subscription()  # as 1.0.3: nothing tells Work of a tool's save
        cid = core.conversations.create()["conversation"]["id"]
        with _as_owner(core):
            added = await core.engine.deps.scheduler.add(
                "inert reminder", "reminder", cid, cron="17 3 * * *", message="inert",
                requester_id=core.authority.owner_id)
            await asyncio.sleep(0)
            assert core.work.list({"kind": "schedule"})["items"] == []
        return added["id"]

    async def listed(core):
        with _as_owner(core):
            return [(item["manager_id"], item["state"])
                    for item in core.work.list({"kind": "schedule"})["items"]]

    schedule_id = await run(older_version)
    assert await run(listed) == [(schedule_id, "scheduled")]


@pytest.mark.parametrize("owner,attribute,replacement,reason", [
    ("core", "delivery", None, "delivery_not_composed"),
    ("delivery", "store", None, "delivery_store_unbound"),
    ("delivery", "events", None, "delivery_store_unbound"),
    ("requests", "delivery", None, "delivery_request_unbound"),
    ("engine", "requests", None, "delivery_engine_unbound"),
    ("deps", "delivery", None, "delivery_engine_unbound"),
    ("engine", "_close_attempted", True, "delivery_engine_closed"),
])
async def test_health_delivery_rechecks_missing_and_mismatched_binding(
    composed, owner, attribute, replacement, reason,
):
    core, _, reader, writer = composed
    target = {"core": core, "delivery": core.delivery, "requests": core.requests,
              "engine": core.engine, "deps": core.engine.deps}[owner]
    original = getattr(target, attribute)
    try:
        setattr(target, attribute, replacement)
        report = (await request(reader, writer, "health.get"))["result"]
        assert delivery_component(report) == {
            "name": "delivery", "healthy": False, "status": "down",
            "detail": "Delivery not ready", "metadata": {"reason": reason},
        }
    finally:
        setattr(target, attribute, original)
    assert_ready((await request(reader, writer, "health.get"))["result"])


async def test_health_delivery_not_ready_after_requests_close(composed):
    core, _, reader, writer = composed
    await core.requests.close()
    report = (await request(reader, writer, "health.get"))["result"]
    assert delivery_component(report) == {
        "name": "delivery", "healthy": False, "status": "down",
        "detail": "Delivery not ready", "metadata": {"reason": "delivery_requests_closed"},
    }


async def test_quiescing_admission_does_not_close_durable_delivery(composed):
    core, _, reader, writer = composed
    shutdown = await request(reader, writer, "runtime.shutdown", {"reason": "app_exit"})
    assert shutdown["ok"], shutdown
    assert not core.lifetime.admitting
    assert not core._closed and not core.requests._closed
    # Quiescence refuses new execution but must finish delivery for existing
    # requests. This diagnostic is delivery readiness, not admission authority.
    assert_ready((await request(reader, writer, "health.get"))["result"])


def test_health_delivery_not_ready_after_store_close(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    core = CoreService(paths, socket_path, token_file)
    store, events, _, _, _, delivery = build(tmp_path / "delivery.db")
    # A real durable journal with diagnostic-only request/engine bindings. No
    # background consumer can touch persistence after this test closes it.
    core.store, core.events, core.delivery = store, events, delivery
    core.requests = SimpleNamespace(delivery=delivery, store=store, _closed=False)
    core.engine = SimpleNamespace(requests=core.requests, deps=SimpleNamespace(delivery=delivery),
                                  _close_attempted=False)
    try:
        assert check_delivery(core).healthy
        store.close()
        assert check_delivery(core).to_dict() == {
            "name": "delivery", "healthy": False, "status": "down",
            "detail": "Delivery not ready", "metadata": {"reason": "delivery_store_closed"},
        }
    finally:
        store.close()


async def test_health_delivery_not_ready_after_core_close(composed):
    core, _, _, _ = composed
    # Retain the real health callback, not a cached readiness result. The IPC
    # listener correctly closes, so post-close inspection uses its read seam.
    records = core.management.methods["health.get"]
    await core.close()
    report = await records.handle("health.get", {})
    assert delivery_component(report) == {
        "name": "delivery", "healthy": False, "status": "down",
        "detail": "Delivery not ready", "metadata": {"reason": "core_closed"},
    }
