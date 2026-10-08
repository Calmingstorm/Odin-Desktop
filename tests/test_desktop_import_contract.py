"""Import from Odin against the real core owners: the exact request shapes the app's importer sends.

Temporary profiles, stubbed MCP connections and in-memory credentials only.
"""

import pytest

from src.desktop.management import MethodError
from src.permissions.manager import PermissionManager
from tests.test_desktop_mcp import harness  # noqa: F401 - pytest fixture
from tests.test_desktop_model_settings import service  # noqa: F401 - pytest fixture
from tests.test_desktop_skills import code, graph, owner  # noqa: F401 - pytest fixture
from tests.test_desktop_state import state  # noqa: F401 - pytest fixture


@pytest.mark.asyncio
async def test_mcp_save_accepts_the_import_shape_switched_off_and_refuses_a_stale_revision(harness):  # noqa: F811
    svc, *_ = harness
    await svc.handle(
        "mcp.save",
        {
            "name": "Imported",
            "transport": "stdio",
            "enabled": False,
            "tool_allowlist": [],
            "expected_revision": svc.settings.revision,
            "timeout_seconds": 120,
            "command": "stub-program",
            "args": ["-x"],
        },
    )
    server = svc.settings.config.mcp.servers["Imported"]
    assert server.enabled is False and server.command == "stub-program" and server.args == ["-x"]
    with pytest.raises(MethodError) as error:
        await svc.handle(
            "mcp.save",
            {
                "name": "Second",
                "transport": "stdio",
                "enabled": False,
                "tool_allowlist": [],
                "expected_revision": "stale-revision",
                "command": "stub-program",
                "args": [],
            },
        )
    assert error.value.code == "stale_binding"
    assert "Second" not in svc.settings.config.mcp.servers


@pytest.mark.asyncio
async def test_skill_create_never_replaces_an_existing_skill(graph):  # noqa: F811
    await graph.service.start()
    token = owner(graph)
    try:
        local = code(body="return 'local user content'")
        await graph.service.handle("skills.save", {"name": "demo", "code": local})
        with pytest.raises(MethodError) as error:
            await graph.service.handle(
                "skills.save",
                {
                    "name": "demo",
                    "code": code(body="return 'imported content'"),
                    "create": True,
                },
            )
        assert error.value.code == "conflict"
        assert (await graph.service.handle("skills.get", {"name": "demo"}))["code"] == local
        fresh = code(name="fresh")
        await graph.service.handle("skills.save", {"name": "fresh", "code": fresh, "create": True})
        await graph.service.handle("skills.set_enabled", {"name": "fresh", "enabled": False})
        assert (await graph.service.handle("skills.get", {"name": "fresh"}))["status"] == "disabled"
    finally:
        PermissionManager.reset_request_owner(token)
        await graph.service.close()


@pytest.mark.asyncio
async def test_preset_create_never_replaces_a_saved_preset(service):  # noqa: F811
    await service.handle(
        "personality.presets.save", {"name": "mine", "identity": "local", "voice": "calm"}
    )
    with pytest.raises(MethodError) as error:
        await service.handle(
            "personality.presets.save",
            {
                "name": "mine",
                "display_name": "Imported",
                "identity": "incoming",
                "voice": "loud",
                "create": True,
            },
        )
    assert error.value.code == "conflict"
    assert service.settings.config.personality.user_presets["mine"].identity == "local"
    result = await service.handle(
        "personality.presets.save",
        {
            "name": "other",
            "identity": "incoming",
            "voice": "loud",
            "create": True,
        },
    )
    assert result == {"status": "saved", "name": "other"}


@pytest.mark.asyncio
async def test_memory_if_absent_keeps_an_existing_entry(state):  # noqa: F811
    svc, _ = state
    await svc.handle("memory.set", {"scope": "global", "key": "k", "value": "local"})
    assert await svc.handle(
        "memory.set", {"scope": "global", "key": "k", "value": "incoming", "if_absent": True}
    ) == {"status": "exists", "scope": "global", "key": "k"}
    assert (await svc.handle("memory.get", {"scope": "global", "key": "k"}))["value"] == "local"
    assert await svc.handle(
        "memory.set", {"scope": "global", "key": "n", "value": "new", "if_absent": True}
    ) == {"status": "saved", "scope": "global", "key": "n"}
    # Without the flag the existing contract is unchanged: a set replaces.
    await svc.handle("memory.set", {"scope": "global", "key": "k", "value": "replaced"})
    assert (await svc.handle("memory.get", {"scope": "global", "key": "k"}))["value"] == "replaced"
