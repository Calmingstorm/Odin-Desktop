"""Real durable management receipts, with only temporary stores and effects."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.desktop.commands import CommandJournal, JournalStore
from src.desktop.events import EventJournal
from src.desktop.management import ManagementService, MethodError


class Domain:
    METHODS = {"example.save", "example.read"}
    READ_METHODS = {"example.read"}

    def __init__(self):
        self.calls = 0
        self.effect = None

    async def handle(self, method, params):
        if method == "example.read":
            return {"calls": self.calls}
        if params.get("reject"):
            raise MethodError("bad_request", "Invalid field: example")
        self.calls += 1
        self.effect = params.get("value")
        await asyncio.sleep(0)
        return {"saved": True}


@pytest.fixture
def graph(tmp_path):
    store = JournalStore(tmp_path / "journal.sqlite3", "test")
    domain = Domain()

    async def publish(event):
        pass

    core = SimpleNamespace(store=store, commands=CommandJournal(store),
                           events=EventJournal(store), _publish=publish)
    manager = ManagementService(core, services=[domain],
                                identity_key=b"temporary-test-key".ljust(32, b"."))
    yield manager, domain, store
    store.close()


async def test_async_effect_reconnect_replays_without_reexecution(graph):
    manager, domain, store = graph
    params = {"value": "dummy-write-only-value"}
    first = await manager.execute("save-1", "example.save", params)
    assert first == {"ok": True, "result": {"saved": True}}
    assert domain.calls == 1
    assert await manager.execute("save-1", "example.save", params) == first
    assert domain.calls == 1
    conflict = await manager.execute("save-1", "example.save", {"value": "other"})
    assert conflict["error"]["code"] == "id_conflict"
    row = store.connection.execute("SELECT binding,response FROM command_receipts").fetchone()
    assert params["value"] not in row["binding"]
    assert params["value"] not in row["response"]


async def test_reservation_survives_cancellation_and_never_replays_effect(graph):
    manager, domain, store = graph
    entered = asyncio.Event()

    async def suspended(method, params):
        domain.calls += 1
        entered.set()
        await asyncio.Event().wait()

    domain.handle = suspended
    task = asyncio.create_task(manager.execute("cancel-1", "example.save", {}))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    replay = await manager.execute("cancel-1", "example.save", {})
    assert replay["error"]["disposition"] == "outcome_unknown"
    assert domain.calls == 1
    assert store.connection.execute("SELECT state FROM command_receipts").fetchone()[0] == "pending"


async def test_refusals_are_durable_and_reads_do_not_write(graph):
    manager, domain, store = graph
    refusal = await manager.execute("reject-1", "example.save", {"reject": True})
    assert refusal["error"]["code"] == "bad_request"
    assert await manager.execute("reject-1", "example.save", {"reject": True}) == refusal
    assert domain.calls == 0
    assert (await manager.invoke("example.read", {}))["result"] == {"calls": 0}
    assert store.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0] == 1
    assert (await manager.invoke("arbitrary.call", {}))["error"]["code"] == "capability_unavailable"


async def test_raw_exceptions_never_reflect_values(graph):
    manager, domain, _ = graph

    async def failed(method, params):
        raise OSError(params["value"])

    domain.handle = failed
    response = await manager.execute("failure-1", "example.save", {"value": "dummy-private-value"})
    assert response["error"]["disposition"] == "outcome_unknown"
    assert "dummy-private-value" not in str(response)
