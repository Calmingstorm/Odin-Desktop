"""Skills lifecycle uses real managers; all pip/process/keyring I/O is stubbed."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.desktop.authority import OwnerAuthority
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.secrets import ProfileSecretStore
from src.desktop.skills import SkillsService
from src.permissions.manager import PermissionManager
from src.tools.skill_manager import SkillManager, _install_packages


def code(name="demo", *, schema=None, dependencies=None, config=None, body="return 'ok'"):
    definition = {"name": name, "description": "A harmless skill",
                  "input_schema": schema or {"type": "object", "properties": {}}}
    if dependencies is not None:
        definition["dependencies"] = dependencies
    if config is not None:
        definition["config_schema"] = config
    return f"SKILL_DEFINITION = {definition!r}\nasync def execute(inp, context):\n    {body}\n"


class Keyring:
    def __init__(self):
        self.values = {}
        self.fail = False

    def get_password(self, namespace, name):
        if self.fail:
            raise RuntimeError("keyring unavailable")
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        if self.fail:
            raise RuntimeError("keyring unavailable")
        self.values[namespace, name] = value

    def delete_password(self, namespace, name):
        self.values.pop((namespace, name), None)


@pytest.fixture
def graph(tmp_path, monkeypatch):
    # No test can reach real pip, even if a regression tries installing a dep.
    monkeypatch.setattr("src.tools.skill_manager.subprocess.run", MagicMock(
        return_value=SimpleNamespace(returncode=1, stdout="", stderr="")))
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    permissions = PermissionManager(authority)
    backend = Keyring()
    settings = SimpleNamespace(paths=paths, secrets=ProfileSecretStore(paths, backend=backend),
                               config=SimpleNamespace(tools=SimpleNamespace(
                                   tool_timeouts={"demo": 7}, skill_allowed_urls=["https://example.com/"])))
    executor = SimpleNamespace(
        config=settings.config.tools,
        _permission_manager=permissions,
        check_permission=lambda _name, ident: None if permissions.is_owner(ident)
        else "Permission denied",
    )
    invalidate = MagicMock()
    service = SkillsService(settings, executor=executor, permissions=permissions,
                            owner_id=authority.owner_id, invalidate=invalidate)
    yield SimpleNamespace(service=service, authority=authority, backend=backend,
                          executor=executor, settings=settings, invalidate=invalidate)
    if service.skill_manager:
        service.skill_manager.close()
    authority.release_runtime()


def owner(graph):
    return PermissionManager.set_request_owner(
        graph.authority.authenticate_local(peer_uid=graph.authority.owner_uid))


async def test_start_close_and_owner_lifecycle(graph):
    service = graph.service
    assert service.get_tool_definitions() == []
    await service.start()
    await service.start()
    assert service.skill_manager._allowed_urls == ("https://example.com",)
    assert service.skill_manager._tool_timeouts == {"demo": 7}
    assert await service.handle("skills.list", {}) == []
    token = owner(graph)
    try:
        result = await service.handle("skills.save", {"name": "demo", "code": code()})
        assert "created" in result["result"]
        assert [row["name"] for row in service.get_tool_definitions()] == ["demo"]
        await service.handle("skills.set_enabled", {"name": "demo", "enabled": False})
        assert service.get_tool_definitions() == []
        assert "disabled" in await service.skill_manager.execute(
            "demo", {}, requester_id=graph.authority.owner_id)
        await service.handle("skills.save", {"name": "demo", "code": code(body="return 'changed'")})
        await service.reload()
        assert (await service.handle("skills.get", {"name": "demo"}))["status"] == "disabled"
        await service.handle("skills.set_enabled", {"name": "demo", "enabled": True})
        assert len(service.get_tool_definitions()) == 1
        await service.handle("skills.delete", {"name": "demo"})
        assert service.get_tool_definitions() == []
    finally:
        PermissionManager.reset_request_owner(token)
    assert graph.invalidate.call_count >= 7
    await service.close()
    assert service.get_tool_definitions() == []


async def test_skill_text_config_and_id_cannot_create_authority(graph):
    await graph.service.start()
    with pytest.raises(MethodError, match="authenticated owner"):
        await graph.service.handle("skills.save", {
            "name": "demo", "code": code(), "owner_id": graph.authority.owner_id,
            "authenticated": True, "config": {"owner_id": graph.authority.owner_id},
        })
    assert graph.service.get_tool_definitions() == []


async def test_bad_schema_edit_rollback_and_qualification(graph):
    await graph.service.start()
    token = owner(graph)
    try:
        await graph.service.handle("skills.save", {"name": "demo", "code": code()})
        original = graph.service.skill_manager._skills["demo"]
        malformed = code(schema={"type": "object", "properties": {"x": {"type": "invalid"}}})
        report = await graph.service.handle("skills.validate", {"code": malformed})
        assert report["valid"] is False
        with pytest.raises(MethodError):
            await graph.service.handle("skills.save", {"name": "demo", "code": malformed})
        assert graph.service.skill_manager._skills["demo"] is original
        definitions = graph.service.get_tool_definitions()
        definitions[0]["input_schema"]["type"] = "array"
        assert graph.service.get_tool_definitions()[0]["input_schema"]["type"] == "object"
    finally:
        PermissionManager.reset_request_owner(token)


async def test_config_keyring_failure_no_plaintext_fallback(graph):
    await graph.service.start()
    token = owner(graph)
    config_schema = {"type": "object", "properties": {"password": {"type": "string"}}}
    try:
        await graph.service.handle("skills.save", {
            "name": "demo", "code": code(config=config_schema)})
        response = await graph.service.handle("skills.config.set", {
            "name": "demo", "config": {"password": "test-only-placeholder"}})
        assert response["config"]["password"].startswith("[redacted")
        config = graph.service.skill_manager.get_skill_config("demo")
        assert config["password"] == "test-only-placeholder"
        marker = graph.service.skill_manager.skills_dir / "config" / "demo.json"
        assert json.loads(marker.read_text()) == {
            "storage": "profile-keyring"}
        graph.backend.fail = True
        with pytest.raises(MethodError, match="skill operation failed"):
            await graph.service.handle("skills.config.set", {"name": "demo", "config": {}})
        graph.backend.fail = False
        config = graph.service.skill_manager.get_skill_config("demo")
        assert config["password"] == "test-only-placeholder"
        await graph.service.handle("skills.delete", {"name": "demo"})
        assert graph.backend.values == {}
    finally:
        PermissionManager.reset_request_owner(token)


async def test_test_delivery_seam_does_not_run_skill(graph):
    assert "skills.test" not in graph.service.METHODS
    await graph.service.start()
    token = owner(graph)
    try:
        await graph.service.handle("skills.save", {"name": "demo", "code": code()})
        with pytest.raises(MethodError) as refusal:
            await graph.service.handle("skills.test", {"name": "demo"})
        assert refusal.value.code == "capability_unavailable"
        assert graph.service.skill_manager._skills["demo"].total_executions == 0
    finally:
        PermissionManager.reset_request_owner(token)


async def test_direct_dispatch_schema_and_current_permission(graph):
    await graph.service.start()
    token = owner(graph)
    try:
        schema = {"type": "object", "properties": {"label": {"type": "string"}},
                  "required": ["label"]}
        await graph.service.handle("skills.save", {"name": "demo", "code": code(schema=schema)})
        manager = graph.service.skill_manager
        assert "schema validation failed" in await manager.execute(
            "demo", {}, requester_id=graph.authority.owner_id)
        assert await manager.execute(
            "demo", {"label": "ordinary"}, requester_id=graph.authority.owner_id) == "ok"
    finally:
        PermissionManager.reset_request_owner(token)
    assert "Permission denied" in await manager.execute(
        "demo", {"label": "ordinary"}, requester_id=graph.authority.owner_id)


def test_pip_retained_arguments_success_failure_timeout(monkeypatch):
    run = MagicMock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("src.tools.skill_manager.subprocess.run", run)
    assert _install_packages(["example-package>=1"]) == (True, "")
    args, kwargs = run.call_args
    assert args[0] == [sys.executable, "-m", "pip", "install", "--quiet",
                       "--disable-pip-version-check", "example-package>=1"]
    assert kwargs["timeout"] == 120
    run.return_value = SimpleNamespace(returncode=1, stdout="opaque index detail", stderr="")
    assert _install_packages(["example-package"])[1] == "pip installation failed"
    run.side_effect = subprocess.TimeoutExpired("pip", 120)
    assert "timed out" in _install_packages(["example-package"])[1]
    run.reset_mock()
    assert not _install_packages(["example package"])[0]
    run.assert_not_called()


async def test_dependency_install_and_failure_before_import(graph, monkeypatch):
    monkeypatch.setattr("src.tools.skill_manager._is_package_installed", lambda _spec: False)
    run = MagicMock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("src.tools.skill_manager.subprocess.run", run)
    await graph.service.start()
    token = owner(graph)
    try:
        await graph.service.handle("skills.save", {
            "name": "demo", "code": code(dependencies=["example-package>=1"])})
        assert run.call_count == 1
        assert graph.service.get_tool_definitions()[0]["name"] == "demo"
        run.return_value.returncode = 1
        with pytest.raises(MethodError):
            await graph.service.handle("skills.save", {
                "name": "absent", "code": code("absent", dependencies=["example-package"])})
        assert not graph.service.skill_manager.has_skill("absent")
    finally:
        PermissionManager.reset_request_owner(token)


def test_profiles_do_not_share_module_slots(tmp_path):
    executor = SimpleNamespace(check_permission=lambda *_: None)
    first = SkillManager(str(tmp_path / "first"), executor)
    second = SkillManager(str(tmp_path / "second"), executor)
    first.create_skill("demo", code())
    second.create_skill("demo", code(body="return 'other'"))
    first_slot = first._skills["demo"].module_name
    second_slot = second._skills["demo"].module_name
    assert first_slot != second_slot
    first.close()
    assert second_slot in sys.modules
    second.close()


async def test_cancelled_dependency_work_settles_before_unlock(graph, monkeypatch):
    import threading

    await graph.service.start()
    entered, finish = threading.Event(), threading.Event()
    real_create = graph.service.skill_manager.create_skill

    def slow_create(*args):
        entered.set()
        assert finish.wait(3)
        return real_create(*args)

    monkeypatch.setattr(graph.service.skill_manager, "create_skill", slow_create)
    token = owner(graph)
    try:
        task = asyncio.create_task(graph.service.handle(
            "skills.save", {"name": "demo", "code": code()}))
        await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert graph.service._lock.locked()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert graph.service.skill_manager.has_skill("demo")
        assert not graph.service._lock.locked()
    finally:
        finish.set()
        PermissionManager.reset_request_owner(token)


async def test_failed_startup_module_listing_delete_and_reload(graph):
    directory = graph.settings.paths.data_dir / "skills"
    directory.mkdir()
    (directory / "bad.py").write_text(code("bad", schema={
        "type": "object", "properties": {}, "required": ["undefined"]}))
    (directory / "wrong.py").write_text(code("foreign"))
    await graph.service.start()
    assert graph.service.get_tool_definitions() == []
    listing = await graph.service.handle("skills.list", {})
    assert {row["name"] for row in listing} == {"bad", "wrong"}
    token = owner(graph)
    try:
        await graph.service.handle("skills.delete", {"name": "bad"})
        await graph.service.reload()
        assert [row["name"] for row in await graph.service.handle("skills.list", {})] == ["wrong"]
    finally:
        PermissionManager.reset_request_owner(token)


async def test_disabled_write_failure_cannot_change_publication(graph, monkeypatch):
    await graph.service.start()
    token = owner(graph)
    try:
        await graph.service.handle("skills.save", {"name": "demo", "code": code()})
        monkeypatch.setattr(graph.service.skill_manager, "_save_disabled_set",
                            MagicMock(side_effect=OSError("temporary storage failure")))
        with pytest.raises(MethodError):
            await graph.service.handle("skills.set_enabled", {"name": "demo", "enabled": False})
        assert graph.service.get_tool_definitions()[0]["name"] == "demo"
        assert graph.service.skill_manager._disabled == set()
    finally:
        PermissionManager.reset_request_owner(token)


async def test_unconfigured_skill_needs_no_keyring_and_effective_reload(graph):
    await graph.service.start()
    graph.backend.fail = True
    token = owner(graph)
    try:
        await graph.service.handle("skills.save", {"name": "demo", "code": code()})
        assert await graph.service.skill_manager.execute(
            "demo", {}, requester_id=graph.authority.owner_id) == "ok"
        # Desired saved restart-only settings are not yet the effective owner.
        graph.settings.config = SimpleNamespace(tools=SimpleNamespace(
            tool_timeouts={"demo": 20}, skill_allowed_urls=[]))
        await graph.service.reload()
        assert graph.service.skill_manager._tool_timeouts == {"demo": 7}
        assert graph.service.skill_manager._allowed_urls == ("https://example.com",)
        graph.service.update_runtime_config(SimpleNamespace(
            tool_timeouts={"demo": 12}, skill_allowed_urls=["https://example.org/"]))
        assert graph.service.skill_manager._tool_timeouts == {"demo": 12}
        assert graph.service.skill_manager._allowed_urls == ("https://example.org",)
    finally:
        PermissionManager.reset_request_owner(token)


async def test_cancelled_startup_remains_owned_unpublished_and_closable(graph, monkeypatch):
    import threading

    entered, finish = threading.Event(), threading.Event()
    real_manager = SkillManager

    def construct(*args, **kwargs):
        entered.set()
        assert finish.wait(3)
        manager = real_manager(*args, **kwargs)
        manager.create_skill("demo", code())
        return manager

    monkeypatch.setattr("src.desktop.skills.SkillManager", construct)
    task = asyncio.create_task(graph.service.start())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert graph.service._lock.locked()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert graph.service.get_tool_definitions() == []
        slot = graph.service.skill_manager._skills["demo"].module_name
        assert slot in sys.modules
        await graph.service.close()
        assert slot not in sys.modules
    finally:
        finish.set()


async def test_builtin_name_reserved_and_catalog_hook(graph):
    callback = MagicMock()
    graph.service.set_on_catalog_changed(callback)
    await graph.service.start()
    token = owner(graph)
    try:
        with pytest.raises(MethodError):
            await graph.service.handle("skills.save", {
                "name": "read_file", "code": code("read_file")})
        assert graph.service.get_tool_definitions() == []
        assert graph.service.list_skills() == []
        assert callback.call_count == 2
    finally:
        PermissionManager.reset_request_owner(token)


async def test_dynamic_dependency_contract_must_qualify(graph, monkeypatch):
    await graph.service.start()
    monkeypatch.setattr("src.tools.skill_manager._is_package_installed", lambda _spec: False)
    token = owner(graph)
    try:
        dynamic = code() + "SKILL_DEFINITION['dependencies'] = ['example-package']\n"
        with pytest.raises(MethodError):
            await graph.service.handle("skills.save", {"name": "demo", "code": dynamic})
        assert graph.service.get_tool_definitions() == []
    finally:
        PermissionManager.reset_request_owner(token)
