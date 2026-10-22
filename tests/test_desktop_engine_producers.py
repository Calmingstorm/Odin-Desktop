"""Odin 4.22.0's independent producers in Desktop's shutdown barriers.

Scheduled runs now go in their own tasks (#708) and housekeeping also runs on a timer
(#715). Shutdown stops and settles both before requests, providers and stores are torn
down, and producer quiescence is claimed only from the tasks themselves, never from a field
a stop routine cleared.
"""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.desktop.services import EngineServices
from src.discord.housekeeping import Housekeeping
from tests.test_desktop_background_core import cleanup, session
from tests.test_desktop_core_lifecycle import request
from tests.test_desktop_request_core import Provider


def engine_with(**changes):
    """A harmless owner graph (as test_desktop_engine_services.cleanup_engine)."""
    deps = SimpleNamespace(
        channel_state=SimpleNamespace(shutdown_steering=AsyncMock()),
        loop_manager=SimpleNamespace(shutdown=AsyncMock(), _loops={}),
        scheduler=SimpleNamespace(stop=AsyncMock(), _task=None, _dispatches=set()),
        runtime_context=SimpleNamespace(),
        agent_manager=SimpleNamespace(_agents={}, cleanup=AsyncMock()),
        tool_executor=SimpleNamespace(_process_registry=None),
        native_tools=SimpleNamespace(owners={}),
        browser_manager=None, llm_gateway=SimpleNamespace(close=AsyncMock()),
        sessions=SimpleNamespace(save=Mock()), turn_store=SimpleNamespace(close=Mock()),
    )
    for name, value in changes.items():
        setattr(deps, name, value)
    return EngineServices(deps, None)


def housekeeping(**state):
    channel_state = SimpleNamespace(last_cleanup=time.time(), cleanup_interval=300.0,
                                    cleanup=Mock(), **state)
    return Housekeeping(get_config=lambda: SimpleNamespace(), sessions=SimpleNamespace(ids=list),
                        channel_state=channel_state,
                        prompt_builder=SimpleNamespace(prune_expired_memory=Mock()),
                        agent_manager=None, channel_logger=None, fts_index=None)


async def settle(predicate, seconds=5.0):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_the_timer_runs_the_throttled_pass_while_idle_once_and_never_after_stop():
    keeper = housekeeping()
    passes = []
    keeper.cleanup_stale = lambda: passes.append(time.time())
    keeper.start(tick_seconds=0.01)
    timer = keeper._timer
    keeper.start(tick_seconds=0.01)
    assert keeper._timer is timer  # never a second timer
    await asyncio.sleep(0.1)
    assert passes == []  # the throttle still decides; the timer only checks it
    keeper._channel_state.last_cleanup = 0
    await settle(lambda: len(passes) == 1)
    await asyncio.sleep(0.1)
    assert len(passes) == 1  # one pass per cleanup interval, however often it ticks
    await keeper.stop()
    assert timer.done() and keeper._timer is None
    keeper._channel_state.last_cleanup = 0
    await asyncio.sleep(0.1)
    assert len(passes) == 1
    await keeper.stop()  # idempotent


@pytest.mark.asyncio
async def test_close_stops_the_timer_and_claims_quiescence_from_its_task():
    keeper = housekeeping()
    keeper.start(tick_seconds=0.01)
    timer = keeper._timer
    engine = engine_with(housekeeping=keeper)
    await engine.close()
    assert timer.done() and engine.producers_quiesced
    engine.deps.turn_store.close.assert_called_once()


@pytest.mark.asyncio
async def test_a_producer_left_running_is_never_reported_settled():
    class ClearsItsField:
        """A stop that forgets its task: the field is None, the task still runs."""

        def __init__(self):
            self._timer = asyncio.create_task(asyncio.Event().wait())

        async def stop(self):
            self._timer = None

    keeper = ClearsItsField()
    timer = keeper._timer
    running = asyncio.create_task(asyncio.Event().wait())
    for changes in ({"housekeeping": keeper},
                    {"scheduler": SimpleNamespace(stop=AsyncMock(), _task=None,
                                                  _dispatches={running})}):
        engine = engine_with(**changes)
        with pytest.raises(RuntimeError, match="producers"):
            await engine.close()
        assert not engine.producers_quiesced
        engine.deps.turn_store.close.assert_not_called()
        engine.deps.llm_gateway.close.assert_not_called()
    timer.cancel()
    running.cancel()
    await asyncio.gather(timer, running, return_exceptions=True)


@pytest.mark.asyncio
async def test_core_shutdown_settles_a_running_scheduled_run_and_the_timer_first(tmp_path):
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, Provider())
    closing = None
    try:
        deps = core.engine.deps
        timer = deps.housekeeping._timer
        assert timer is not None and not timer.done()  # started with the core
        entered, release = asyncio.Event(), asyncio.Event()

        async def finishes_its_step(_schedule):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()  # a step that must finish before it ends
                raise

        deps.scheduler._callback = finishes_its_step
        saved = await request(reader, writer, "schedules.save", {
            "description": "Held check", "action": "check", "channel_id": cid,
            "run_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
            "tool_name": "run_command", "tool_input": {"command": "example"}})
        assert saved["ok"], saved
        async with asyncio.timeout(5):
            await entered.wait()  # the scheduler's own loop started it
        order = []
        close_requests = core.requests.close

        async def recorded_close():
            order.append(("requests", timer.done(), entered.is_set() and release.is_set()))
            return await close_requests()

        core.requests.close = recorded_close
        writer.close()
        await writer.wait_closed()
        closing = asyncio.create_task(core.close())
        await asyncio.sleep(0.2)
        # The run is still finishing its step: nothing beneath it was torn down.
        assert not closing.done() and order == []
        assert deps.turn_store.available
        release.set()
        async with asyncio.timeout(10):
            await closing
        assert order == [("requests", True, True)]
        assert not deps.scheduler._dispatches and timer.done()
        assert deps.housekeeping._timer is None and core.engine.producers_quiesced
    finally:
        release_fds = (rfd, wfd)
        if closing is None:
            await cleanup(core, writer, *release_fds)
        else:
            import os

            for fd in release_fds:
                os.close(fd)
