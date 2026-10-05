"""Step 6A lifecycle and domains through actual authenticated local transport."""
from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest

from src.desktop.core import CoreService
from src.desktop.management import ManagementService, MethodError
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_management_core import TemporaryKeyring


@pytest.fixture
async def connected(tmp_path, monkeypatch):
    import aiohttp

    def refused(*args, **kwargs):
        pytest.fail("Step 6A core tests require stubbed network backends")

    monkeypatch.setattr(aiohttp, "ClientSession", refused)
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    service = CoreService(paths, socket_path, token_file, secret_backend=TemporaryKeyring())
    writer = None
    try:
        await service.start(read_fd)
        reader, writer, welcome = await connect(socket_path)
        yield service, reader, writer, welcome
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await service.close()
        os.close(read_fd)
        os.close(write_fd)


async def test_service_readiness_and_absent_delivery_are_honest(connected):
    service, reader, writer, welcome = connected
    capabilities = set(welcome["capabilities"])
    assert {"skills.save", "mcp.save", "computer.status", "computer.activation.set"} <= capabilities
    assert not {"skills.test", "submission.send", "computer_act", "schedules.list"} & capabilities
    assert (await request(reader, writer, "skills.list"))["result"] == []
    mcp = await request(reader, writer, "mcp.status")
    assert mcp["ok"] and mcp["result"]["server_count"] == 0
    computer = await request(reader, writer, "computer.status")
    assert computer["ok"] and computer["result"]["session"] is None
    assert not computer["result"]["readiness"]["input_supported"]
    health = (await request(reader, writer, "health.get"))["result"]
    assert health["workspace"]["local_only"] is True
    assert health["browser"]["state"] == "disabled"
    assert not health["computer"]["native_qualified"]
    assert service.management.executor._browser_manager is None


async def test_skill_save_publication_receipt_reload_and_revocation(connected):
    service, reader, writer, _ = connected
    code = (
        'SKILL_DEFINITION = {"name": "sample", "description": "fixture", '
        '"input_schema": {"type": "object", "properties": {}}}\n'
        'async def execute(inp, context):\n    return "fixture"\n'
    )
    command_id = str(uuid.uuid4())
    saved = await request(reader, writer, "skills.save",
                          {"name": "sample", "code": code}, command_id)
    assert saved["ok"], saved
    manager = service.management
    assert "sample" in {tool["name"] for tool in manager.tool_catalog.merged_definitions()}
    assert await request(reader, writer, "skills.save", {
        "name": "sample", "code": code}, command_id) == saved
    assert (await request(reader, writer, "runtime.reload", {"scope": "skills"}))["ok"]
    assert (await request(reader, writer, "skills.set_enabled", {
        "name": "sample", "enabled": False}))["ok"]
    assert "sample" not in {tool["name"] for tool in manager.tool_catalog.merged_definitions()}
    assert (await request(reader, writer, "skills.test", {"name": "sample"}))["error"][
        "code"] == "capability_unavailable"


async def test_computer_activation_transaction_is_not_native_qualification(connected):
    service, reader, writer, _ = connected
    schema = (await request(reader, writer, "settings.schema"))["result"]
    changed = await request(reader, writer, "computer.activation.set", {
        "expected_revision": schema["revision"],
        "changes": [{"path": "computer.enabled", "value": True}],
    })
    assert changed["ok"], changed
    assert service.management.computer.controller.enabled
    assert not service.management.computer.published_available
    assert "computer_act" not in {
        tool["name"] for tool in service.management.tool_catalog.merged_definitions()}


async def test_parent_loss_cancels_service_qualification_before_publication(tmp_path, monkeypatch):
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    entered, cleaned = asyncio.Event(), asyncio.Event()

    async def suspended():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def close():
        pass

    manager = SimpleNamespace(start=suspended, close=close, methods={})
    monkeypatch.setattr(ManagementService, "compose", lambda *args, **kwargs: manager)
    core = CoreService(paths, socket_path, token_file)
    startup = asyncio.create_task(core.start(read_fd))
    try:
        await entered.wait()
        os.close(write_fd)
        write_fd = None
        with pytest.raises(RuntimeError, match="supervisor"):
            await asyncio.wait_for(startup, 2)
        assert cleaned.is_set() and core.server is None
        assert not socket_path.exists()
    finally:
        await core.close()
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


async def test_failed_close_does_not_strand_other_transport_owners():
    calls = []

    class Owner:
        METHODS = READ_METHODS = set()

        def __init__(self, name, fail=False):
            self.name, self.fail = name, fail

        async def close(self):
            calls.append(self.name)
            if self.fail:
                raise RuntimeError("fixture cleanup failed")

    manager = ManagementService(SimpleNamespace(), services=[Owner("first"), Owner("second", True)],
                                identity_key=b"fixture".ljust(32, b"."))
    manager.providers = Owner("providers")
    with pytest.raises(MethodError) as exc:
        await manager.close()
    assert exc.value.disposition == "outcome_unknown"
    assert calls == ["second", "first", "providers"]
