"""Import from Odin against the real core owners: the exact request shapes the app's importer sends.

Temporary profiles, stubbed MCP connections and in-memory credentials only.
"""

import asyncio
import json
import threading

import pytest

from src.desktop.management import MethodError
from src.permissions.manager import PermissionManager
from src.tools.skill_manager import SkillManager
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
        # A source file that never loaded is the user's too, and a refused create records nothing.
        manager = graph.service.skill_manager
        draft = manager.skills_dir / "draft.py"
        draft.write_text("work in progress")
        with pytest.raises(MethodError) as error:
            await graph.service.handle(
                "skills.save",
                {"name": "draft", "code": code(name="draft"), "create": True, "enabled": False},
            )
        assert error.value.code == "conflict"
        assert draft.read_text() == "work in progress"
        assert "draft" not in disabled_record(manager)
        # Without create, saving still writes over a source that never loaded, as before.
        await graph.service.handle("skills.save", {"name": "draft", "code": code(name="draft")})
        assert manager.is_enabled("draft")
    finally:
        PermissionManager.reset_request_owner(token)
        await graph.service.close()


def disabled_record(manager):
    """The durable disabled list a restarted manager loads."""
    path = manager.skills_dir / ".disabled.json"
    return json.loads(path.read_text()) if path.exists() else []


def pause_loading(manager, monkeypatch, name, inspect=None):
    """Hold the first load of ``name`` (after its source is written, before it is published)."""
    loading, resume = threading.Event(), threading.Event()
    real_load = manager._load_skill

    def load(path):
        if path.stem == name and not loading.is_set():
            if inspect:
                inspect()
            loading.set()
            assert resume.wait(10)
        return real_load(path)

    monkeypatch.setattr(manager, "_load_skill", load)
    return loading, resume


@pytest.mark.asyncio
async def test_skill_created_switched_off_is_never_enabled_even_mid_create(graph, monkeypatch):  # noqa: F811
    await graph.service.start()
    token = owner(graph)
    manager = graph.service.skill_manager
    seen = {}

    def inspect():
        seen["recorded"] = "quiet" in disabled_record(manager)
        seen["listed"] = [row["name"] for row in graph.service.get_tool_definitions()]

    loading, resume = pause_loading(manager, monkeypatch, "quiet", inspect)
    try:
        save = asyncio.create_task(graph.service.handle(
            "skills.save",
            {"name": "quiet", "code": code(name="quiet"), "create": True, "enabled": False},
        ))
        assert await asyncio.to_thread(loading.wait, 10)
        # Before the save is answered: recorded off durably, and offered to no one.
        assert seen == {"recorded": True, "listed": []}
        resume.set()
        await save
        assert (await graph.service.handle("skills.get", {"name": "quiet"}))["status"] == "disabled"
        assert graph.service.get_tool_definitions() == []
        assert "disabled" in await manager.execute(
            "quiet", {}, requester_id=graph.authority.owner_id)
        # A create that doesn't load leaves no disabled record behind.
        with pytest.raises(MethodError):
            await graph.service.handle(
                "skills.save",
                {"name": "broken", "code": code(name="other"), "create": True, "enabled": False},
            )
        assert "broken" not in disabled_record(manager)
        assert disabled_record(manager) == ["quiet"]
        # Deleting it clears its disabled record too.
        await graph.service.handle("skills.delete", {"name": "quiet"})
        assert disabled_record(manager) == []
    finally:
        resume.set()
        PermissionManager.reset_request_owner(token)
        await graph.service.close()


@pytest.mark.asyncio
async def test_a_disabled_record_that_cannot_be_written_creates_nothing(graph, monkeypatch, caplog):  # noqa: F811
    await graph.service.start()
    token = owner(graph)
    manager = graph.service.skill_manager
    real_save = manager._save_disabled_set

    def full_disk(disabled=None):
        raise OSError("disk full")

    try:
        monkeypatch.setattr(manager, "_save_disabled_set", full_disk)
        with pytest.raises(MethodError):
            await graph.service.handle(
                "skills.save",
                {"name": "quiet", "code": code(name="quiet"), "create": True, "enabled": False},
            )
        assert not (manager.skills_dir / "quiet.py").exists() and not manager.has_skill("quiet")
        # Recorded, then the create fails and the record can't be cleared: it stays, logged.
        saves = iter([real_save, full_disk])
        monkeypatch.setattr(
            manager, "_save_disabled_set", lambda disabled=None: next(saves)(disabled))
        with pytest.raises(MethodError):
            await graph.service.handle(
                "skills.save",
                {"name": "broken", "code": code(name="other"), "create": True, "enabled": False},
            )
        assert disabled_record(manager) == ["broken"]
        assert "Could not clear the disabled record of broken" in caplog.text
    finally:
        PermissionManager.reset_request_owner(token)
        await graph.service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("toggle", ["disable", "enable"])
async def test_disabled_import_and_native_toggle_survive_a_restart(graph, monkeypatch, toggle):  # noqa: F811
    await graph.service.start()
    token = owner(graph)
    manager = graph.service.skill_manager
    recording, resume = threading.Event(), threading.Event()
    real_save = manager._save_disabled_set

    def save(disabled=None):
        # Hold the import while it records its skill as disabled.
        if disabled is not None and "quiet" in disabled and not recording.is_set():
            recording.set()
            assert resume.wait(10)
        return real_save(disabled)

    restarted = None
    try:
        existing = {"name": "existing", "code": code(name="existing")}
        await graph.service.handle("skills.save", existing)
        if toggle == "enable":
            manager.disable_skill("existing")
        monkeypatch.setattr(manager, "_save_disabled_set", save)
        imported = asyncio.create_task(graph.service.handle(
            "skills.save",
            {"name": "quiet", "code": code(name="quiet"), "create": True, "enabled": False},
        ))
        assert await asyncio.to_thread(recording.wait, 10)
        # The native enable_skill/disable_skill tool's own manager call, made meanwhile, waits.
        native = asyncio.create_task(
            asyncio.to_thread(getattr(manager, f"{toggle}_skill"), "existing"))
        done, _ = await asyncio.wait({native}, timeout=0.5)
        assert not done
        resume.set()
        await imported
        assert "existing" in await native
        assert disabled_record(manager) == (
            ["existing", "quiet"] if toggle == "disable" else ["quiet"])
        restarted = SkillManager(str(manager.skills_dir), graph.executor)
        assert restarted.is_enabled("existing") is (toggle == "enable")
        assert restarted.has_skill("quiet") and not restarted.is_enabled("quiet")
    finally:
        resume.set()
        if restarted is not None:
            restarted.close()
        PermissionManager.reset_request_owner(token)
        await graph.service.close()


@pytest.mark.asyncio
async def test_create_only_and_native_create_never_write_over_each_other(graph, monkeypatch):  # noqa: F811
    await graph.service.start()
    token = owner(graph)
    manager = graph.service.skill_manager
    try:
        # The native create_skill tool's own call, held after writing its source.
        local = code(name="race", body="return 'local user content'")
        loading, resume = pause_loading(manager, monkeypatch, "race")
        native = asyncio.create_task(asyncio.to_thread(manager.create_skill, "race", local))
        assert await asyncio.to_thread(loading.wait, 10)
        with pytest.raises(MethodError) as error:
            await graph.service.handle(
                "skills.save",
                {"name": "race", "code": code(name="race", body="return 'new'"), "create": True},
            )
        assert error.value.code == "conflict"
        resume.set()
        assert "created" in await native
        assert (await graph.service.handle("skills.get", {"name": "race"}))["code"] == local
        # The other way round: an import in flight makes the native create report that it exists.
        imported = code(name="other", body="return 'imported'")
        loading, resume = pause_loading(manager, monkeypatch, "other")
        save = asyncio.create_task(graph.service.handle(
            "skills.save", {"name": "other", "code": imported, "create": True}))
        assert await asyncio.to_thread(loading.wait, 10)
        refused = await asyncio.to_thread(
            manager.create_skill, "other", code(name="other", body="return 'local'"))
        assert refused.startswith("Skill 'other' already exists")
        resume.set()
        await save
        assert (await graph.service.handle("skills.get", {"name": "other"}))["code"] == imported
    finally:
        resume.set()
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
