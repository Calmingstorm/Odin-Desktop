"""The core starts Odin's usage backfill at boot, as OdinBot.setup_hook does."""
from __future__ import annotations

import asyncio
import json
import logging
import os

import pytest

from src.desktop.core import CoreService
from src.usage.rollup import UsageRollup
from tests.test_desktop_core_lifecycle import profile
from tests.test_desktop_management_core import TemporaryKeyring
from tests.test_usage_rollup import turn_record


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import aiohttp

    def refuse(*args, **kwargs):
        raise AssertionError("Usage backfill tests must not open network sessions")

    monkeypatch.setattr(aiohttp, "ClientSession", refuse)


async def indexed(usage, turns):
    # backfill_complete persists across restarts; wait for the indexed turns too.
    for _ in range(300):
        summary = await usage.summary("all")
        if summary["coverage"]["backfill_complete"] and summary["work"]["settled_turns"] == turns:
            return summary
        await asyncio.sleep(0.05)
    raise AssertionError(f"Usage backfill never indexed {turns} settled turn(s): {summary}")


@pytest.mark.asyncio
@pytest.mark.parametrize("historical", [False, True], ids=["empty", "historical"])
async def test_core_start_backfills_recorded_history_and_close_stops_it(tmp_path, historical):
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    try:
        if historical:
            # An established profile, then a recorded turn its usage index never saw.
            previous = CoreService(paths, socket_path, token_file,
                                   secret_backend=TemporaryKeyring())
            try:
                await previous.start(read_fd)
            finally:
                await previous.close()
            directory = paths.data_dir / "trajectories"
            directory.mkdir(exist_ok=True)
            (directory / "2026-10-06.jsonl").write_text(
                json.dumps(turn_record("existing-profile-turn")) + "\n")
        core = CoreService(paths, socket_path, token_file, secret_backend=TemporaryKeyring())
        try:
            await core.start(read_fd)
            usage = core.engine.deps.usage_rollup
            task = usage._task
            assert task is not None
            summary = await indexed(usage, int(historical))
            assert summary["available"] is True
        finally:
            await core.close()
        assert task.done() and usage._task is None
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_usage_backfill_start_failure_keeps_the_core_available(tmp_path, monkeypatch, caplog):
    async def fail(self):
        raise RuntimeError("backfill start failed")

    monkeypatch.setattr(UsageRollup, "start", fail)
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file, secret_backend=TemporaryKeyring())
    try:
        with caplog.at_level(logging.ERROR, logger="odin.desktop.core"):
            await core.start(read_fd)
        assert core.phase == "ready"
        assert socket_path.exists()
        assert "Usage backfill startup failed (non-fatal)" in caplog.text
    finally:
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
