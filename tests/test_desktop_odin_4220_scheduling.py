"""Odin 4.22.0 (PR #729) in Desktop: Odin's new and rewritten scheduler cases.

Desktop keeps tests/test_scheduler.py, tests/test_campaign_coverage_core_scheduler.py and
tests/test_campaign_scheduler_admission.py byte for byte as Odin v4.13.0 wrote them. Odin
4.22.0's cases for the scheduling lanes (#708) and the webhook destination policy (#724)
run here verbatim, with those files' own helpers and fixtures. Two rewritten frozen cases
(the bounded webhook response, the queued obsolete schedule) are deselected by the reviewed
direct-shared-engine exclusion; their 4.22.0 versions are the ones here. These schedulers
run without Desktop's missed-run recovery, as Odin's; tests/test_desktop_schedule_lanes.py
covers the lanes with it.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.scheduler import scheduler as module
from src.scheduler.scheduler import Scheduler
from tests.test_campaign_coverage_core_scheduler import Response, Session  # noqa: F401
from tests.test_scheduler import _SCHEDULE_STEPS, _make_scheduler  # noqa: F401


class TestInterruptedOneTimeRuns:
    async def test_reminders_and_webhooks_start_on_time_beside_running_work(
        self, tmp_path, monkeypatch
    ):
        """#708: a long check or workflow no longer holds the schedules due with
        or after it. Lanes by kind: a reminder or a webhook starts on time."""
        s = _make_scheduler(tmp_path)
        started = {}
        release = asyncio.Event()

        async def callback(schedule):
            started[schedule["description"]] = asyncio.get_running_loop().time()
            if schedule["description"] == "slow work":
                await release.wait()

        async def webhook(_config):
            started["ping"] = asyncio.get_running_loop().time()
            await release.wait()

        monkeypatch.setattr(s, "_execute_webhook", webhook)
        soon = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        await s.add("slow work", "workflow", "chan1", run_at=soon, steps=_SCHEDULE_STEPS)
        await s.add("ping", "webhook", "chan1", run_at=soon,
                    webhook_config={"url": "http://192.168.1.13/hook"})
        await s.add("reminder", "reminder", "chan1", run_at=soon, message="y")
        s.start(callback)
        try:
            for _ in range(200):
                if len(started) == 3:
                    break
                await asyncio.sleep(0.01)
            assert set(started) == {"slow work", "ping", "reminder"}  # work still running
            await s.add("later", "reminder", "chan1",
                        run_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
                        message="z")
            for _ in range(300):
                if "later" in started:
                    break
                await asyncio.sleep(0.01)
            assert "later" in started  # due meanwhile: also on time
        finally:
            release.set()
            await s.stop()

    async def test_due_work_waits_unreserved_and_runs_earliest_first(self, tmp_path, caplog):
        """Checks, workflows and digests still run one at a time, as before: a
        second one is not started beside the first (whose spawned agents a
        concurrent run could have refused). It is not reserved meanwhile, the
        loop does not poll for it, and the earliest due starts next."""
        caplog.set_level("INFO", logger="odin.scheduler")
        s = _make_scheduler(tmp_path)
        release = asyncio.Event()
        order = []

        async def callback(schedule):
            order.append(schedule["description"])
            if schedule["description"] == "first":
                await release.wait()

        s._callback = callback
        now = datetime.now(UTC)
        await s.add("first", "workflow", "chan1",
                    run_at=(now - timedelta(minutes=3)).isoformat(), steps=_SCHEDULE_STEPS)
        await s.add("due last", "workflow", "chan1",
                    run_at=(now - timedelta(minutes=1)).isoformat(), steps=_SCHEDULE_STEPS)
        await s.add("due second", "check", "chan1",
                    run_at=(now - timedelta(minutes=2)).isoformat(),
                    tool_name="run_command", tool_input={"host": "synthetic", "command": "x"})
        publishes = []
        publish = s._publish

        async def counting(candidate):
            publishes.append(len(candidate))
            return await publish(candidate)

        s._publish = counting
        await s._tick(wait=False)
        for _ in range(100):
            if order:
                break
            await asyncio.sleep(0.01)
        assert order == ["first"]
        settled = len(publishes)
        for _ in range(3):
            await s._tick(wait=False)
        assert len(publishes) == settled  # the waiting work is not reserved
        assert s._compute_tick_delay() == 60.0  # nor polled: the run's end wakes the loop
        waiting = [r for r in s.list_all() if r["description"] != "first"]
        assert all(record.get("last_run") is None for record in waiting)
        assert caplog.text.count("it starts when the running work schedule ends") == 2
        release.set()
        await asyncio.gather(*list(s._dispatches))
        await s._tick()
        assert order == ["first", "due second", "due last"]
        assert s.list_all() == []

    async def test_a_waiting_tick_fires_each_due_schedule_once(self, tmp_path):
        s = _make_scheduler(tmp_path)
        calls = []

        async def failing(schedule):
            calls.append(schedule["description"])
            raise RuntimeError("synthetic failure")

        s._callback = failing
        past = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
        await s.add("a", "workflow", "chan1", run_at=past, steps=_SCHEDULE_STEPS,
                    max_retries=2, retry_backoff_seconds=1)
        await s.add("b", "workflow", "chan1", run_at=past, steps=_SCHEDULE_STEPS)
        # Its retry is due at once; one tick still fires each schedule once.
        s._compute_retry_at = lambda _schedule: past
        await s._tick()
        assert sorted(calls) == ["a", "b"]

    async def test_a_running_one_time_schedule_is_not_reserved_again(self, tmp_path):
        """PR #729 review R3: ticks kept running beside it, and its due next_run
        was reserved, refused by the overlap guard and rolled back on every
        one-second tick: two schedule-file rewrites per second."""
        s = _make_scheduler(tmp_path)
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def callback(schedule):
            calls.append(schedule["id"])
            entered.set()
            await release.wait()

        s._callback = callback
        past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        await s.add("once", "reminder", "chan1", run_at=past, message="x")
        publishes = []
        publish = s._publish

        async def counting(candidate):
            publishes.append(len(candidate))
            return await publish(candidate)

        s._publish = counting
        await s._tick(wait=False)
        await asyncio.wait_for(entered.wait(), timeout=2)
        settled = len(publishes)
        for _ in range(3):
            await s._tick(wait=False)
        assert len(publishes) == settled  # nothing reserved or rolled back
        assert s._compute_tick_delay() == 60.0  # ticks are not pinned to one second
        release.set()
        await asyncio.gather(*list(s._dispatches))
        assert calls == [calls[0]] and s.list_all() == []

    async def test_a_recurring_slot_due_during_its_own_run_runs_when_it_ends(self, tmp_path):
        """While ticks waited for every run, a slot that came due during a long
        run fired as soon as it ended. Running beside the loop must keep that,
        and must not reserve and roll back the slot on every tick meanwhile."""
        s = _make_scheduler(tmp_path)
        entered = asyncio.Event()
        release = asyncio.Event()
        runs = []

        async def callback(schedule):
            runs.append(schedule["id"])
            entered.set()
            if len(runs) == 1:
                await release.wait()

        s._callback = callback
        await s.add("every five minutes", "reminder", "chan1", cron="*/5 * * * *")
        overdue = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        async with s._lock:
            s._schedules[0]["next_run"] = overdue
        await s._tick(wait=False)
        await asyncio.wait_for(entered.wait(), timeout=2)
        async with s._lock:  # the next slot comes due while the first run is going
            s._schedules[0]["next_run"] = overdue
        publishes = []
        publish = s._publish

        async def counting(candidate):
            publishes.append(len(candidate))
            return await publish(candidate)

        s._publish = counting
        for _ in range(3):
            await s._tick(wait=False)
        assert publishes == [] and len(runs) == 1
        assert s._compute_tick_delay() == 60.0
        release.set()
        await asyncio.gather(*list(s._dispatches))
        await s._tick()  # the run's end wakes the loop: the missed slot runs now
        assert len(runs) == 2
        nxt = datetime.fromisoformat(s.list_all()[0]["next_run"])
        assert nxt.astimezone(UTC) > datetime.now(UTC)

    async def test_a_dispatch_cancelled_before_it_starts_releases_its_reservation(
        self, tmp_path
    ):
        s = _make_scheduler(tmp_path)
        s._callback = AsyncMock()
        past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        await s.add("once", "reminder", "chan1", run_at=past, message="x")
        await s._tick(wait=False)
        assert s._gate_reservations  # reserved, its dispatch not started yet
        dispatches = list(s._dispatches)
        for task in dispatches:
            task.cancel()
        await asyncio.gather(*dispatches, return_exceptions=True)
        s._callback.assert_not_awaited()
        assert s._gate_reservations == {}


@pytest.mark.parametrize("body,wire_key", [(None, None), ({"fixture": 1}, "json"),
                                         ([1, 2], "json"), (123, "data")])
async def test_webhook_serialization_bounded_response_and_session_cleanup(
    tmp_path, monkeypatch, body, wire_key
):
    response = Response(202, "x" * 5000)
    session = Session(response)
    monkeypatch.setattr(module, "_webhook_session", lambda: session)
    scheduler = module.Scheduler(str(tmp_path / "schedules.json"))
    cfg = module.Scheduler._normalize_webhook_config({
        "url": "https://fixture.invalid/hook", "method": "put", "body": body,
        "headers": {"X-Fixture": "yes"}, "timeout": 7, "expected_status_codes": [202],
    })
    result = await scheduler._execute_webhook(cfg)
    assert result == {"status_code": 202, "body": "x" * 4096, "headers": response.headers}
    method, url, kwargs = session.requests[0]
    assert (method, url) == ("PUT", "https://fixture.invalid/hook")
    assert kwargs["timeout"].total == 7
    assert kwargs["headers"] == {"X-Fixture": "yes"}
    if wire_key:
        assert kwargs[wire_key] == (str(body) if wire_key == "data" else body)
    else:
        assert "json" not in kwargs and "data" not in kwargs
    assert response.entered and response.exited
    await scheduler.stop()
    assert session.closed


async def test_webhook_unexpected_status_releases_response_and_reuses_session(
    tmp_path, monkeypatch
):
    response = Response(503, "fixture unavailable")
    session = Session(response)
    scheduler = module.Scheduler(str(tmp_path / "schedules.json"))
    scheduler._http_session = session

    def no_new_session():
        raise AssertionError("existing HTTP session should be reused")

    monkeypatch.setattr(module, "_webhook_session", no_new_session)
    with pytest.raises(RuntimeError, match="status 503, expected one of \\[200\\]"):
        await scheduler._execute_webhook({
            "url": "https://fixture.invalid", "expected_status_codes": [200],
        })
    assert response.exited
    assert not session.closed
    await scheduler.stop()


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/computeMetadata/v1/",
])
def test_creating_a_metadata_webhook_schedule_is_refused(url):
    with pytest.raises(ValueError, match="metadata"):
        module.Scheduler._validate_webhook_config({"url": url})


def test_private_and_homelab_destinations_stay_allowed():
    for url in ("http://192.168.1.13:8080/hook", "http://localhost:3000/x",
                "https://10.0.0.5/notify"):
        module.Scheduler._validate_webhook_config({"url": url})


async def test_an_existing_metadata_schedule_never_sends(tmp_path, monkeypatch):
    # A schedule saved before the check existed is refused at run time.
    session = Session(Response(200, "never"))
    monkeypatch.setattr(module, "_webhook_session", lambda: session)
    scheduler = module.Scheduler(str(tmp_path / "schedules.json"))
    with pytest.raises(ValueError, match="metadata"):
        await scheduler._execute_webhook({"url": "http://169.254.169.254/latest/"})
    assert session.requests == []
    await scheduler.stop()


async def test_a_redirect_to_metadata_is_refused_and_released():
    class _Redirect:
        headers = {"Location": "http://169.254.169.254/latest/meta-data/"}
        closed = False

        def close(self):
            self.closed = True

    response = _Redirect()
    params = type("P", (), {"url": "https://hooks.example/start", "response": response})()
    with pytest.raises(ValueError, match="metadata"):
        await module._guard_webhook_redirect(None, None, params)
    assert response.closed
    response.headers = {"Location": "/next"}  # same-site relative hop: allowed
    response.closed = False
    await module._guard_webhook_redirect(None, None, params)
    assert not response.closed


async def test_webhook_session_resolves_through_the_metadata_guard():
    from src.notifications.outbound_webhooks import _WebhookResolver

    session = module._webhook_session()
    try:
        assert isinstance(session.connector._resolver, _WebhookResolver)
        assert any(module._guard_webhook_redirect in t.on_request_redirect
                   for t in session.trace_configs)
    finally:
        await session.close()


@pytest.mark.parametrize("route", ["tick", "one_time", "trigger"])
@pytest.mark.parametrize("change", ["delete", "pause", "payload"])
async def test_queued_obsolete_schedule_never_starts(tmp_path, route, change):
    scheduler = Scheduler(str(tmp_path / "schedules.json"))
    if route == "trigger":
        timing = {"trigger": {"source": "github"}}
    elif route == "one_time":
        timing = {"run_at": "2999-01-01T00:00:00Z"}
    else:
        timing = {"cron": "0 * * * *"}
    first = await scheduler.add("first", "reminder", "1", **timing)
    second = await scheduler.add("second", "reminder", "1", message="old", **timing)
    if route != "trigger":
        for schedule in scheduler._schedules:
            schedule["next_run"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    entered, release = asyncio.Event(), asyncio.Event()
    calls, messages = [], []

    async def callback(schedule):
        calls.append(schedule["id"])
        messages.append(schedule.get("message"))
        if schedule["id"] == first["id"]:
            entered.set()
            await release.wait()

    scheduler._callback = callback
    dispatch = scheduler.fire_triggers("github", {}) if route == "trigger" else scheduler._tick()
    pending = asyncio.create_task(dispatch)
    await asyncio.wait_for(entered.wait(), 2)
    try:
        if change == "delete":
            await scheduler.delete(second["id"])
        elif change == "pause":
            await scheduler.update(second["id"], paused=True)
        else:
            await scheduler.update(second["id"], message="new")
    finally:
        release.set()
    await pending
    if change == "payload" and route != "trigger":
        # A tick reserves a schedule only when its lane can start it (#708):
        # the second waited unreserved, so the change came first and it runs
        # once, as changed, never with the obsolete payload.
        assert calls == [first["id"], second["id"]] and messages[-1] == "new"
        assert len(await scheduler.history.query()) == 2
    else:
        assert calls == [first["id"]]
        assert len(await scheduler.history.query()) == 1
    assert "old" not in messages
    assert scheduler._gate_reservations == {}
    assert scheduler._in_flight == set()
