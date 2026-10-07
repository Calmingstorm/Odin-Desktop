"""The native loss fixture follows the real management/foreground ownership seam."""
from types import SimpleNamespace

import pytest

from src.computer.models import RequestContext
from src.desktop.computer_binding import ComputerBindingService, bind_foreground
from src.desktop.core import CoreService
from src.desktop.resource_cleanup import (
    ResourceCleanupError,
    ResourceCleanupJournal,
    close_execution_owners,
)
from tests.desktop_fixtures.native_reconciliation_entry import bind_dormant_native_owner
from tests.test_desktop_core_lifecycle import profile
from tests.test_desktop_request_core import Provider, service


@pytest.mark.asyncio
@pytest.mark.parametrize("quarantined", [False, True])
async def test_dormant_fixture_survives_actual_foreground_startup(tmp_path, quarantined):
    paths, socket, token = profile(tmp_path)
    core = service(paths, socket, token, Provider())
    # Use the real binding method without starting unrelated engine producers.
    settings = SimpleNamespace(config=core.config_provider(paths))
    computer = ComputerBindingService(core, settings)
    management = SimpleNamespace(settings=settings, computer=computer)
    integration = bind_dormant_native_owner(management, tmp_path)
    store = integration.controller.store
    grant = None
    try:
        if quarantined:
            grant = store.create_session(RequestContext(
                "owner", "channel", "turn", "localhost", surface="desktop"),
                environment="existing_session")
            store.set_state(grant.session_id, "quarantined", revoke=True)
        await computer.start()
        owners = {"computer": integration}
        catalog = SimpleNamespace(invalidate=lambda: None)
        core.management = management
        core.requests = SimpleNamespace()
        core.engine = SimpleNamespace(deps=SimpleNamespace(
            native_owners=owners, tool_catalog=catalog))
        CoreService._bind_foreground_computer(core)
        foreground = owners["computer"]
        assert foreground is core.requests.computer_foreground
        assert foreground is bind_foreground(computer, core.requests)
        assert foreground.controller is integration.controller
        assert foreground.controller.store is store
        assert foreground.controller._live == {}
        resources = await close_execution_owners(computer=foreground, registry=None)
        journal = ResourceCleanupJournal(tmp_path / "cleanup.json")
        if quarantined:
            assert resources["computer"]["state"] == "unknown"
            assert resources["computer"]["unresolved_sessions"] == [grant.session_id]
            assert store.get_session(grant.session_id).state == "quarantined"
            assert store.cleanup(grant.session_id) is None
            with pytest.raises(ResourceCleanupError):
                journal.finish(resources)
            assert journal.public()["reconciliation_required"] is True
            assert ResourceCleanupJournal(journal.path).public()["reconciliation_required"] is True
        else:
            assert resources["computer"]["state"] == "released"
            journal.finish(resources)
            assert journal.public()["reconciliation_required"] is False
    finally:
        store.close()
