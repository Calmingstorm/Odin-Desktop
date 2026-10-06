"""Asynchronous control envelope admission never holds SQLite across effects."""
import asyncio

import pytest

from src.desktop.commands import CommandJournal, JournalStore


@pytest.mark.asyncio
async def test_async_envelope_pending_duplicate_cannot_repeat_control(tmp_path):
    store = JournalStore(tmp_path / "control.sqlite3", "profile")
    commands = CommandJournal(store)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def handler():
        assert store._depth == 0
        calls.append("control")
        entered.set()
        await release.wait()
        return {"ok": True, "result": {"disposition": "requested"}}

    try:
        task = asyncio.create_task(commands.execute_async(
            "control-id", "control.stop", {}, handler))
        await entered.wait()
        duplicate = await commands.execute_async("control-id", "control.stop", {}, handler)
        assert duplicate["error"]["disposition"] == "outcome_unknown"
        conflict = await commands.execute_async("control-id", "control.steer", {}, handler)
        assert conflict["error"]["code"] == "id_conflict"
        release.set()
        original = await task
        assert await commands.execute_async("control-id", "control.stop", {}, handler) == original
        assert calls == ["control"]
    finally:
        release.set()
        store.close()


@pytest.mark.asyncio
async def test_cancelled_control_envelope_stays_unknown_after_restart(tmp_path):
    path = tmp_path / "control.sqlite3"
    store = JournalStore(path, "profile")
    entered = asyncio.Event()

    async def handler():
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(CommandJournal(store).execute_async(
        "cancelled-id", "control.resume", {}, handler))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    store.close()
    reopened = JournalStore(path, "profile")
    calls = []

    async def never():
        calls.append("unexpected replay")
        return {"ok": True, "result": {}}

    try:
        replay = await CommandJournal(reopened).execute_async(
            "cancelled-id", "control.resume", {}, never)
        assert replay["error"]["disposition"] == "outcome_unknown"
        assert calls == []
    finally:
        reopened.close()
