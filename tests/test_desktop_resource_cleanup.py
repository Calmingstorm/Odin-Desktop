"""Owner barrier wiring never upgrades unknown to release or starts a new owner."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.desktop.resource_cleanup import (
    ResourceCleanupError,
    ResourceCleanupJournal,
    close_existing_execution_owners,
)


def test_clean_or_missing_owners_do_not_create_cleanup_authority(tmp_path):
    journal = ResourceCleanupJournal(tmp_path / "receipt.json")
    journal.finish({"computer": {"state": "not_started"}, "processes": {"state": "released"}})
    recovered = ResourceCleanupJournal(tmp_path / "receipt.json")
    assert recovered.public()["previous_unknown"] is None
    assert recovered.public()["effects_undone"] is False
    assert recovered.public()["replay"] is False


def test_interrupted_or_unknown_cleanup_survives_later_clean_exit(tmp_path):
    path = tmp_path / "receipt.json"
    ResourceCleanupJournal(path)
    recovered = ResourceCleanupJournal(path)
    assert recovered.public()["reconciliation_required"] is True
    recovered.finish({"computer": {"state": "not_started"}})
    assert ResourceCleanupJournal(path).public()["reconciliation_required"] is True


def test_unknown_cleanup_is_durable_before_error(tmp_path):
    path = tmp_path / "receipt.json"
    journal = ResourceCleanupJournal(path)
    with pytest.raises(ResourceCleanupError):
        journal.finish({"computer": {"state": "unknown", "error_type": "RuntimeError"}})
    saved = json.loads(path.read_text())
    assert saved["state"] == "unknown"
    assert saved["resources"]["computer"]["state"] == "unknown"


@pytest.mark.asyncio
async def test_existing_original_owners_closed_and_absent_not_instantiated():
    calls = []

    async def computer_close():
        calls.append("computer")

    async def registry_shutdown():
        calls.append("processes")

    computer = SimpleNamespace(close=computer_close)
    registry = SimpleNamespace(shutdown=registry_shutdown)
    management = SimpleNamespace(executor=SimpleNamespace(_process_registry=registry))
    result = await close_existing_execution_owners(SimpleNamespace(computer=computer), management)
    assert calls == ["computer", "processes"]
    assert all(record["state"] == "released" for record in result.values())
    absent = await close_existing_execution_owners(SimpleNamespace(), SimpleNamespace())
    assert absent == {"computer": {"state": "not_started"}, "processes": {"state": "not_started"}}


@pytest.mark.asyncio
async def test_native_release_failure_does_not_skip_process_barrier_or_drop_live_owner():
    computer = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("private failure")))
    registry = SimpleNamespace(shutdown=AsyncMock(return_value=1))
    core = SimpleNamespace(computer=computer)
    management = SimpleNamespace(executor=SimpleNamespace(_process_registry=registry))
    result = await close_existing_execution_owners(core, management)
    assert result["computer"] == {"state": "unknown", "error_type": "RuntimeError"}
    assert "private failure" not in json.dumps(result)
    assert result["processes"]["state"] == "released"
    registry.shutdown.assert_awaited_once()
    assert core.computer is computer


def test_durability_failure_never_reports_completed_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr("src.desktop.resource_cleanup.write_private_atomic", lambda *args: False)
    with pytest.raises(ResourceCleanupError, match="durability"):
        ResourceCleanupJournal(tmp_path / "receipt.json")


@pytest.mark.asyncio
async def test_dormant_original_native_quarantine_is_not_released_by_empty_controller(tmp_path):
    from src.computer.controller import ComputerController
    from src.computer.models import RequestContext
    from src.computer.store import ComputerStore

    store = ComputerStore(tmp_path / "computer.sqlite3", tmp_path / "evidence")
    try:
        context = RequestContext("owner", "channel", "turn", "localhost", surface="webui")
        grant = store.create_session(context, environment="existing_session")
        store.set_state(grant.session_id, "quarantined", revoke=True)
        controller = ComputerController(store, None, lambda _: True, enabled=False)
        assert controller._live == {}
        result = await close_existing_execution_owners(
            SimpleNamespace(computer=controller), SimpleNamespace(),
        )
        assert result["computer"]["state"] == "unknown"
        assert result["computer"]["unresolved_sessions"] == [grant.session_id]
        assert store.get_session(grant.session_id).state == "quarantined"
        assert store.cleanup(grant.session_id) is None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_owned_native_store_closed_cleanly_uses_readonly_durable_readback(tmp_path):
    from src.computer.store import ComputerStore

    store = ComputerStore(tmp_path / "computer.sqlite3", tmp_path / "evidence")

    async def close_owned_store():
        store.close()

    owner = SimpleNamespace(controller=SimpleNamespace(store=store), close=close_owned_store)
    result = await close_existing_execution_owners(
        SimpleNamespace(computer=owner), SimpleNamespace(),
    )
    assert result["computer"]["state"] == "released"


@pytest.mark.asyncio
async def test_owner_cancellation_propagates_and_running_marker_stays_unknown(tmp_path):
    import asyncio

    journal = ResourceCleanupJournal(tmp_path / "receipt.json")
    owner = SimpleNamespace(close=AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await close_existing_execution_owners(SimpleNamespace(computer=owner), SimpleNamespace())
    assert ResourceCleanupJournal(journal.path).public()["reconciliation_required"] is True
