"""Owner barrier wiring never upgrades unknown to release or starts a new owner."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.desktop.management import ManagementService
from src.desktop.resource_cleanup import (
    ResourceCleanupError,
    ResourceCleanupJournal,
    close_execution_owners,
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


@pytest.mark.asyncio
async def test_engine_bridge_never_retries_original_unknown_owner_receipt(tmp_path):
    registry = SimpleNamespace(shutdown=AsyncMock())
    computer = SimpleNamespace(close=AsyncMock())
    retained = {"computer": {"state": "released"},
                "processes": {"state": "unknown", "error_type": "ProcessCleanupError"}}
    engine = SimpleNamespace(execution_cleanup_results=retained, cleanup_outcome={
        "state": "unknown", "failures": [
            {"stage": "execution_owners", "error_type": "ResourceCleanupError"}]})
    core = SimpleNamespace(engine=engine, computer=computer)
    management = SimpleNamespace(executor=SimpleNamespace(_process_registry=registry))
    journal = ResourceCleanupJournal(tmp_path / "receipt.json")
    for _ in range(2):
        resources = await close_existing_execution_owners(core, management)
        with pytest.raises(ResourceCleanupError):
            journal.finish(resources)
        resources["processes"]["state"] = "released"
    registry.shutdown.assert_not_called()
    computer.close.assert_not_called()
    assert retained["processes"]["state"] == "unknown"
    saved = json.loads(journal.path.read_text())
    assert saved["resources"]["processes"]["error_type"] == "ProcessCleanupError"
    assert saved["resources"]["engine"]["failures"][0]["stage"] == "execution_owners"


@pytest.mark.asyncio
async def test_engine_bridge_before_barriers_reports_unknown_not_absent():
    registry = SimpleNamespace(shutdown=AsyncMock())
    core = SimpleNamespace(engine=SimpleNamespace(execution_cleanup_results=None))
    result = await close_existing_execution_owners(
        core, SimpleNamespace(executor=SimpleNamespace(_process_registry=registry)),
    )
    assert set(result) == {"computer", "processes", "engine"}
    assert all(row["state"] == "unknown" for row in result.values())
    registry.shutdown.assert_not_called()


@pytest.mark.asyncio
async def test_core_engine_failure_flag_cannot_be_overwritten_by_clean_barriers():
    core = SimpleNamespace(_engine_cleanup_failed=True, engine=SimpleNamespace(
        execution_cleanup_results={"computer": {"state": "not_started"},
                                   "processes": {"state": "released"}},
        cleanup_outcome={"state": "released"},
    ))
    result = await close_existing_execution_owners(core, None)
    assert result["engine"]["state"] == "unknown"
    assert core.engine.cleanup_outcome["state"] == "released"


@pytest.mark.asyncio
async def test_partial_owner_barrier_results_survive_cancellation():
    import asyncio

    retained = {}
    computer = SimpleNamespace(close=AsyncMock())
    registry = SimpleNamespace(shutdown=AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await close_execution_owners(computer=computer, registry=registry, resources=retained)
    assert retained["computer"]["state"] == "released"
    assert retained["processes"] == {"state": "unknown", "error_type": "CancelledError"}
    computer.close.assert_awaited_once()
    registry.shutdown.assert_awaited_once()


def _management_owner(calls, name, *, fails=False, synchronous=False):
    def close_sync():
        calls.append(name)
        if fails:
            raise RuntimeError("private owner failure")

    async def close_async():
        close_sync()

    return SimpleNamespace(close=close_sync if synchronous else close_async,
                           METHODS=(), READ_METHODS=())


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_owner", [None, "browser", "second", "providers", "ssh"])
async def test_management_shutdown_orders_all_owners_and_journals_after_continuation(
    tmp_path, failing_owner,
):
    calls = []
    path = tmp_path / "receipt.json"
    journal = ResourceCleanupJournal(path)
    finish = journal.finish

    def finish_after_owners(resources):
        calls.append("journal")
        finish(resources)

    journal.finish = finish_after_owners
    core = SimpleNamespace(
        computer=_management_owner(calls, "computer"), resource_cleanup=journal,
    )
    first = _management_owner(calls, "first")
    second = _management_owner(calls, "second", fails=failing_owner == "second",
                               synchronous=True)
    browser = _management_owner(calls, "browser", fails=failing_owner == "browser")
    manager = ManagementService(core, services=(first, second), identity_key=b"m" * 32)
    manager.lifecycle_services = (*manager.services, browser)
    manager.providers = _management_owner(calls, "providers", fails=failing_owner == "providers")
    manager.executor = SimpleNamespace(
        _process_registry=SimpleNamespace(shutdown=AsyncMock(
            side_effect=lambda: calls.append("processes"))),
        ssh_pool=_management_owner(calls, "ssh", fails=failing_owner == "ssh",
                                   synchronous=True),
    )

    if failing_owner is None:
        await manager.close()
    else:
        with pytest.raises(ResourceCleanupError, match="unverified"):
            await manager.close()

    assert calls == ["computer", "processes", "browser", "second", "first",
                     "providers", "ssh", "journal"]
    saved = json.loads(path.read_text())
    assert saved["resources"]["computer"]["state"] == "released"
    assert saved["resources"]["processes"]["state"] == "released"
    assert saved["resources"]["services"] == {
        "state": "released" if failing_owner is None else "unknown",
    }
    assert saved["state"] == ("complete" if failing_owner is None else "unknown")
    assert "private owner failure" not in json.dumps(saved)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_journal", [False, True])
@pytest.mark.parametrize("barrier", [None, False])
async def test_management_unsettled_producers_never_close_shared_owners(
    tmp_path, monkeypatch, with_journal, barrier,
):
    calls = []
    engine = SimpleNamespace()
    if barrier is not None:
        engine.producers_quiesced = barrier
    core = SimpleNamespace(engine=engine)
    if with_journal:
        core.resource_cleanup = ResourceCleanupJournal(tmp_path / "receipt.json")
    service = _management_owner(calls, "service")
    manager = ManagementService(core, services=(service,), identity_key=b"m" * 32)
    manager.lifecycle_services = (service, _management_owner(calls, "browser"))
    manager.providers = _management_owner(calls, "providers")
    manager.executor = SimpleNamespace(ssh_pool=_management_owner(calls, "ssh"))

    async def execution_barriers(actual_core, actual_manager):
        assert actual_core is core and actual_manager is manager
        calls.append("execution_barriers")
        return {"processes": {"state": "released"}}

    monkeypatch.setattr("src.desktop.resource_cleanup.close_existing_execution_owners",
                        execution_barriers)
    with pytest.raises(ResourceCleanupError):
        await manager.close()
    assert calls == ["execution_barriers"]
    if with_journal:
        saved = json.loads(core.resource_cleanup.path.read_text())
        assert saved["state"] == "unknown"
        assert saved["resources"] == {
            "processes": {"state": "released"},
            "services": {"state": "unknown", "reason": "producers_not_quiesced"},
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown_owner", [None, "computer", "service", "providers", "ssh"])
async def test_management_no_journal_unknown_is_unverified_and_others_still_close(unknown_owner):
    calls = []
    core = SimpleNamespace(computer=_management_owner(
        calls, "computer", fails=unknown_owner == "computer"))
    manager = ManagementService(core, services=(_management_owner(
        calls, "service", fails=unknown_owner == "service"),), identity_key=b"m" * 32)
    manager.providers = _management_owner(calls, "providers", fails=unknown_owner == "providers")
    manager.executor = SimpleNamespace(ssh_pool=_management_owner(
        calls, "ssh", fails=unknown_owner == "ssh"))
    if unknown_owner is None:
        await manager.close()
    else:
        with pytest.raises(ResourceCleanupError, match="unverified"):
            await manager.close()
    assert calls == ["computer", "service", "providers", "ssh"]


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_state", ["released", "unknown"])
async def test_management_engine_owned_transports_are_not_closed_again(tmp_path, engine_state):
    calls = []
    engine = SimpleNamespace(
        producers_quiesced=True,
        execution_cleanup_results={"computer": {"state": "released"},
                                   "processes": {"state": "released"}},
        cleanup_outcome={"state": engine_state},
    )
    core = SimpleNamespace(engine=engine, computer=SimpleNamespace(close=AsyncMock()),
                           resource_cleanup=ResourceCleanupJournal(tmp_path / "receipt.json"))
    manager = ManagementService(core, services=(_management_owner(calls, "service"),),
                                identity_key=b"m" * 32)
    manager.lifecycle_services = (*manager.services, _management_owner(calls, "browser"))
    manager._engine_owned = True
    manager.providers = SimpleNamespace(close=AsyncMock())
    registry = SimpleNamespace(shutdown=AsyncMock())
    pool = SimpleNamespace(close=AsyncMock())
    manager.executor = SimpleNamespace(_process_registry=registry, ssh_pool=pool)

    if engine_state == "unknown":
        with pytest.raises(ResourceCleanupError, match="unverified"):
            await manager.close()
    else:
        await manager.close()

    assert calls == ["browser", "service"]
    core.computer.close.assert_not_called()
    registry.shutdown.assert_not_called()
    manager.providers.close.assert_not_called()
    pool.close.assert_not_called()
    saved = json.loads(core.resource_cleanup.path.read_text())
    assert saved["resources"]["services"]["state"] == "released"
    assert saved["resources"]["engine"]["state"] == engine_state


@pytest.mark.asyncio
async def test_management_start_qualifies_lifecycle_before_publishing_available_methods():
    calls = []
    service = SimpleNamespace(METHODS=("read", "effect"), READ_METHODS=("read",))
    manager = ManagementService(SimpleNamespace(), services=(service,), identity_key=b"m" * 32)

    def start_service():
        calls.append("service")
        service.management_methods = ("read",)

    async def start_browser():
        assert calls == ["service"]
        assert "effect" in manager.methods
        calls.append("browser")

    service.start = start_service
    manager.lifecycle_services = (service, SimpleNamespace(start=start_browser))
    await manager.start()
    assert calls == ["service", "browser"]
    assert manager.methods == {"read": service}
    assert manager.read_methods == {"read"}
