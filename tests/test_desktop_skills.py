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
from src.permissions.host_access import HostAccessManager
from src.permissions.manager import PermissionManager
from src.tools.executor import ToolExecutor
from src.tools.output_authorization import (
    request_host_authorizer,
    request_scope_authorizer,
    request_tool_scope,
)
from src.tools.output_delivery import delivery_scope
from src.tools.result_capture import capture_active
from src.tools.skill_manager import (
    MAX_SKILL_OUTPUT_CHARS,
    SkillManager,
    _install_packages,
    resolve_dependencies,
)


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
    monkeypatch.setattr(sys, "path", [*sys.path])  # a profile's package folder joins it
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


async def test_test_runs_real_skill_with_empty_input_and_owner_scope(graph):
    assert "skills.test" in graph.service.METHODS
    assert "skills.test" not in graph.service.READ_METHODS
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.config = graph.settings.config.tools
    executor._permission_manager = graph.service.permissions
    live_hosts = ["isolated-fixture"]
    executor._host_access = HostAccessManager(
        path=graph.settings.paths.config_dir / "host-preferences.json",
        available_hosts_provider=lambda: live_hosts,
        permission_manager=graph.service.permissions,
    )
    graph.service.executor = executor
    await graph.service.start()
    token = owner(graph)
    allowed = {"demo"}
    live_tools = {"demo"}

    def resolver():
        return live_tools

    def host_resolver():
        return ["isolated-fixture"]

    tool_token = request_tool_scope.set(allowed)
    resolver_token = request_scope_authorizer.set(resolver)
    host_token = request_host_authorizer.set(host_resolver)
    delivery_token = delivery_scope.set(("prior-owner", "prior-channel"))
    try:
        body = (
            "import json\n"
            "    from src.tools.output_authorization import request_host_authorizer\n"
            "    from src.tools.output_delivery import delivery_scope\n"
            "    from src.tools.result_capture import capture_active\n"
            "    nested = await context.execute_tool('read_file', {'host': 'isolated-fixture', "
            "'path': '/harmless-fixture'})\n"
            "    return json.dumps({'input': inp, 'owner': context._requester_id, "
            "'hosts': context.get_hosts(), 'host_scope': request_host_authorizer.get()(), "
            "'delivery': delivery_scope.get(), 'capture': capture_active(), 'nested': nested})"
        )
        await graph.service.handle("skills.save", {"name": "demo", "code": code(body=body)})
        tested = await graph.service.handle("skills.test", {
            "name": "demo", "input": {"ignored": True}, "requester_id": "foreign",
            "owner_id": "foreign", "allowed_tools": ["read_file"], "allowed_hosts": ["foreign"],
        })
        assert tested["is_error"] is False
        assert json.loads(tested["result"]) == {
            "input": {}, "owner": graph.authority.owner_id,
            "hosts": ["isolated-fixture"], "host_scope": ["isolated-fixture"],
            "delivery": [graph.authority.owner_id, ""], "capture": True,
            "nested": "Permission denied: tool scope revoked or unavailable.",
        }
        assert delivery_scope.get() == ("prior-owner", "prior-channel")
        assert not capture_active()
        assert request_tool_scope.get() is allowed
        assert request_scope_authorizer.get() is resolver
        assert request_host_authorizer.get() is host_resolver
        live_hosts.clear()
        assert json.loads((await graph.service.handle("skills.test", {"name": "demo"}))[
            "result"])["hosts"] == []
        live_tools.clear()
        assert allowed == {"demo"}
        denied = await graph.service.handle("skills.test", {"name": "demo"})
        assert denied == {
            "result": "Permission denied: selected skill scope revoked or unavailable.",
            "is_error": False,  # Retained Odin's exact prefix rule.
        }
        assert graph.service.skill_manager._skills["demo"].total_executions == 2
    finally:
        delivery_scope.reset(delivery_token)
        request_host_authorizer.reset(host_token)
        request_scope_authorizer.reset(resolver_token)
        request_tool_scope.reset(tool_token)
        PermissionManager.reset_request_owner(token)


async def test_test_requires_real_owner_and_preserves_disabled_unknown_semantics(graph):
    await graph.service.start()
    token = owner(graph)
    try:
        await graph.service.handle("skills.save", {"name": "demo", "code": code()})
        assert await graph.service.handle("skills.test", {"name": "demo"}) == {
            "result": "ok", "is_error": False}
        await graph.service.handle("skills.set_enabled", {"name": "demo", "enabled": False})
        disabled = await graph.service.handle("skills.test", {"name": "demo"})
        assert disabled == {
            "result": "Skill 'demo' is disabled. Use enable_skill to re-activate it.",
            "is_error": True,
        }
        assert graph.service.skill_manager._skills["demo"].total_executions == 1
        with pytest.raises(MethodError) as unknown:
            await graph.service.handle("skills.test", {"name": "missing"})
        assert unknown.value.code == "not_found"
    finally:
        PermissionManager.reset_request_owner(token)
    with pytest.raises(MethodError) as denied:
        await graph.service.handle("skills.test", {
            "name": "demo", "owner_id": graph.authority.owner_id, "authenticated": True,
        })
    assert denied.value.code == "permission_denied"
    assert graph.service.skill_manager._skills["demo"].total_executions == 1


@pytest.mark.parametrize("body,is_error", [
    ("return 'harmless api_key=test-only-placeholder'", False),
    ("raise RuntimeError('api_key=test-only-placeholder')", True),
    ("from src.tools.output_delivery import DeliveredOutput\n"
     "    return DeliveredOutput('api_key=test-only-placeholder')", False),
    ("return 'Skill error: api_key=test-only-placeholder'", True),
    ("return \"Skill 'demo' reports a failure\"", True),
    ("return 'x' * 100000 + ' api_key=test-only-placeholder'", False),
])
async def test_test_scrubs_and_bounds_real_skill_output(graph, body, is_error):
    await graph.service.start()
    token = owner(graph)
    try:
        await graph.service.handle("skills.save", {"name": "demo", "code": code(body=body)})
        result = await graph.service.handle("skills.test", {"name": "demo"})
        assert result["is_error"] is is_error
        assert "test-only-placeholder" not in result["result"]
        assert "Traceback" not in result["result"]
        assert len(result["result"]) <= MAX_SKILL_OUTPUT_CHARS
        if "100000" in body:
            assert result["result"].endswith(f"[truncated at {MAX_SKILL_OUTPUT_CHARS} chars]")
        elif "api_key" in body:
            assert "[REDACTED]" in result["result"]
    finally:
        PermissionManager.reset_request_owner(token)


async def test_test_sanitizes_manager_exception_and_restores_scope(graph, monkeypatch):
    await graph.service.start()
    token = owner(graph)
    delivery_token = delivery_scope.set(("prior-owner", "prior-channel"))
    try:
        await graph.service.handle("skills.save", {"name": "demo", "code": code()})

        def failure(_name):
            raise RuntimeError("api_key=test-only-placeholder " + "x" * 100000)

        monkeypatch.setattr(graph.service.skill_manager, "get_skill_config", failure)
        result = await graph.service.handle("skills.test", {"name": "demo"})
        assert result["is_error"] is True
        assert result["result"].startswith("[REDACTED]")
        assert "test-only-placeholder" not in result["result"]
        assert "Traceback" not in result["result"]
        assert len(result["result"]) == MAX_SKILL_OUTPUT_CHARS
        assert delivery_scope.get() == ("prior-owner", "prior-channel")
        assert not capture_active()
        assert graph.service.skill_manager._skills["demo"].total_executions == 0
    finally:
        delivery_scope.reset(delivery_token)
        PermissionManager.reset_request_owner(token)


async def test_test_cancellation_is_not_converted_to_error_result(graph):
    await graph.service.start()
    token = owner(graph)
    delivery_token = delivery_scope.set(("prior-owner", "prior-channel"))
    try:
        await graph.service.handle("skills.save", {"name": "demo", "code": code(
            body="import asyncio\n    raise asyncio.CancelledError()")})
        with pytest.raises(asyncio.CancelledError):
            await graph.service.handle("skills.test", {"name": "demo"})
        assert delivery_scope.get() == ("prior-owner", "prior-channel")
        assert not capture_active()
        assert graph.service.skill_manager._skills["demo"].total_executions == 1
        # No wedged service lock after cancellation; no execution retry.
        assert len(await graph.service.handle("skills.list", {})) == 1
    finally:
        delivery_scope.reset(delivery_token)
        PermissionManager.reset_request_owner(token)


async def test_direct_dispatch_leaves_input_handling_to_skill_and_checks_permission(graph):
    await graph.service.start()
    token = owner(graph)
    try:
        schema = {"type": "object", "properties": {"label": {"type": "string"}},
                  "required": ["label"]}
        await graph.service.handle("skills.save", {"name": "demo", "code": code(schema=schema)})
        manager = graph.service.skill_manager
        assert await manager.execute(
            "demo", {}, requester_id=graph.authority.owner_id) == "ok"
        assert await manager.execute(
            "demo", {"label": "ordinary"}, requester_id=graph.authority.owner_id) == "ok"
    finally:
        PermissionManager.reset_request_owner(token)
    assert "Permission denied" in await manager.execute(
        "demo", {"label": "ordinary"}, requester_id=graph.authority.owner_id)


@pytest.mark.parametrize("value", ["", 0, None])
async def test_blank_optional_input_reaches_skill_unchanged(graph, value):
    await graph.service.start()
    token = owner(graph)
    try:
        schema = {"type": "object", "properties": {
            "optional": {"type": "integer", "minimum": 1}}}
        await graph.service.handle("skills.save", {"name": "demo", "code": code(
            schema=schema, body="return repr(inp)")})
        supplied = {"optional": value}
        manager = graph.service.skill_manager
        assert await manager.execute(
            "demo", supplied, requester_id=graph.authority.owner_id) == repr(supplied)
        assert manager._skills["demo"].total_executions == 1
    finally:
        PermissionManager.reset_request_owner(token)


def test_pip_retained_arguments_success_failure_timeout(monkeypatch):
    run = MagicMock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("src.tools.skill_manager.subprocess.run", run)
    assert _install_packages(["example-package>=1"]) == (True, "")
    args, kwargs = run.call_args
    assert args[0] == [sys.executable, "-m", "pip", "install", "--quiet",
                       "--disable-pip-version-check", "example-package>=1"]
    assert kwargs["timeout"] == 120
    run.return_value = SimpleNamespace(returncode=1, stdout="opaque index detail", stderr="")
    assert _install_packages(["example-package"])[1] == "opaque index detail"
    run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")
    assert _install_packages(["example-package"])[1] == "pip installation failed"
    run.side_effect = subprocess.TimeoutExpired("pip", 120)
    assert "timed out" in _install_packages(["example-package"])[1]
    run.reset_mock()
    assert not _install_packages(["example package"])[0]
    run.assert_not_called()


def test_pip_installs_into_the_profiles_package_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "path", [*sys.path])
    run = MagicMock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("src.tools.skill_manager.subprocess.run", run)
    target = tmp_path / "skill-packages"
    assert _install_packages(["example-package>=1"], target=target) == (True, "")
    assert run.call_args[0][0] == [sys.executable, "-m", "pip", "install", "--quiet",
                                   "--disable-pip-version-check", "--target", str(target),
                                   "--upgrade", "example-package>=1"]
    assert target.stat().st_mode & 0o777 == 0o700
    assert sys.path[-1] == str(target)  # after the runtime's own packages


def demo_wheel(folder) -> None:
    """A one-module wheel, installed from this folder without an index."""
    import base64
    import hashlib
    import zipfile

    dist = "odin_demo_pkg-1.0.dist-info"
    files = {"odin_demo_pkg/__init__.py": "VALUE = 42\n",
             f"{dist}/METADATA": "Metadata-Version: 2.1\nName: odin-demo-pkg\nVersion: 1.0\n",
             f"{dist}/WHEEL": ("Wheel-Version: 1.0\nGenerator: odin-test\n"
                               "Root-Is-Purelib: true\nTag: py3-none-any\n")}

    def digest(text: str) -> str:
        raw = hashlib.sha256(text.encode()).digest()
        return "sha256=" + base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    record = "".join(f"{path},{digest(text)},{len(text.encode())}\n"
                     for path, text in files.items())
    with zipfile.ZipFile(folder / "odin_demo_pkg-1.0-py3-none-any.whl", "w") as wheel:
        for path, text in files.items():
            wheel.writestr(path, text)
        wheel.writestr(f"{dist}/RECORD", record + f"{dist}/RECORD,,\n")


def test_a_dependency_installs_into_the_profile_and_imports(tmp_path, monkeypatch):
    pytest.importorskip("pip")  # the packaged runtime gets pip with phase 4
    monkeypatch.setattr(sys, "path", [*sys.path])
    (tmp_path / "wheels").mkdir()
    demo_wheel(tmp_path / "wheels")
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(tmp_path / "wheels"))
    target = tmp_path / "skill-packages"
    already, added, diagnostics = resolve_dependencies(["odin-demo-pkg==1.0"], target)
    assert (already, added) == ([], ["odin-demo-pkg==1.0"]), diagnostics
    try:
        import odin_demo_pkg

        assert odin_demo_pkg.VALUE == 42 and odin_demo_pkg.__file__.startswith(str(target))
        assert resolve_dependencies(["odin-demo-pkg==1.0"], target)[:2] == (
            ["odin-demo-pkg==1.0"], [])
    finally:
        sys.modules.pop("odin_demo_pkg", None)


async def test_skills_install_into_the_profiles_package_folder(graph, monkeypatch):
    targets = []
    monkeypatch.setattr("src.tools.skill_manager._is_package_installed", lambda _spec: False)
    monkeypatch.setattr("src.tools.skill_manager._install_packages",
                        lambda specs, target=None: (targets.append(target) or True, ""))
    await graph.service.start()
    token = owner(graph)
    try:
        await graph.service.handle("skills.save", {
            "name": "demo", "code": code(dependencies=["example-package>=1"])})
    finally:
        PermissionManager.reset_request_owner(token)
    assert targets == [graph.settings.paths.data_dir / "skill-packages"]


async def test_dependency_install_failure_is_diagnostic_if_imports_work(graph, monkeypatch):
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
        run.return_value.stderr = "ERROR: No matching distribution found for example-package"
        await graph.service.handle("skills.save", {
            "name": "absent", "code": code("absent", dependencies=["example-package"])})
        skill = graph.service.skill_manager._skills["absent"]
        assert any("No matching distribution found" in d.message for d in skill.diagnostics)
        with pytest.raises(MethodError):
            await graph.service.handle("skills.save", {
                "name": "broken", "code": code("broken") +
                "raise ImportError('disposable import failure')\n"})
        assert not graph.service.skill_manager.has_skill("broken")
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
    assert [row["name"] for row in graph.service.get_tool_definitions()] == ["foreign"]
    assert graph.service.skill_manager._skills["foreign"].file_path.name == "wrong.py"
    module_name = graph.service.skill_manager._skills["foreign"].module_name
    assert module_name in sys.modules
    assert "wrong.py" not in graph.service.skill_manager.definition_errors
    listing = await graph.service.handle("skills.list", {})
    assert {row["name"] for row in listing} == {"bad", "foreign"}
    token = owner(graph)
    try:
        await graph.service.handle("skills.delete", {"name": "bad"})
        await graph.service.reload()
        assert [row["name"] for row in await graph.service.handle("skills.list", {})] == ["foreign"]
        await graph.service.handle("skills.delete", {"name": "foreign"})
        assert not (directory / "wrong.py").exists()
        assert module_name not in sys.modules
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


async def test_dynamic_dependency_failure_does_not_block_publication(graph, monkeypatch):
    await graph.service.start()
    monkeypatch.setattr("src.tools.skill_manager._is_package_installed", lambda _spec: False)
    token = owner(graph)
    try:
        dynamic = code() + "SKILL_DEFINITION['dependencies'] = ['example-package']\n"
        await graph.service.handle("skills.save", {"name": "demo", "code": dynamic})
        assert [row["name"] for row in graph.service.get_tool_definitions()] == ["demo"]
        diagnostics = graph.service.skill_manager._skills["demo"].diagnostics
        assert any(d.level == "error" for d in diagnostics)
    finally:
        PermissionManager.reset_request_owner(token)


@pytest.mark.parametrize("dynamic", [False, True])
@pytest.mark.parametrize("dependencies, diagnostic", [
    (["example package"], "Refused unsafe dependency"),
    (["example-package @ https://example.com/package.whl"], "Refused unsafe dependency"),
    (["example-package"] * 11, "Too many dependencies"),
    ("example-package", "dependencies must be a list of strings"),
    ([None], "dependencies must be a list of strings"),
])
async def test_dependency_metadata_diagnostic_only_at_load(
        graph, monkeypatch, dynamic, dependencies, diagnostic):
    run = MagicMock(side_effect=AssertionError("unsafe specs must never reach pip"))
    monkeypatch.setattr("src.tools.skill_manager.subprocess.run", run)
    source = code(dependencies=dependencies)
    if dynamic:
        source = code() + f"SKILL_DEFINITION['dependencies'] = {dependencies!r}\n"
    source = "import json\n" + source
    directory = graph.settings.paths.data_dir / "skills"
    directory.mkdir()
    (directory / "demo.py").write_text(source)
    await graph.service.start()
    manager = graph.service.skill_manager
    assert [row["name"] for row in manager.get_tool_definitions()] == ["demo"]
    assert any(diagnostic in d.message for d in manager._skills["demo"].diagnostics)
    assert manager.validate_skill_code(source)["valid"] is True
    assert manager.definition_errors == {}
    run.assert_not_called()


@pytest.mark.parametrize("specs", [
    ["example package"], ["example-package @ https://example.com/package.whl"],
    ["example-package"] * 11,
])
def test_install_dependency_refusal_remains_before_pip(monkeypatch, specs):
    run = MagicMock(side_effect=AssertionError("unsafe specs must never reach pip"))
    monkeypatch.setattr("src.tools.skill_manager.subprocess.run", run)
    assert _install_packages(specs)[0] is False
    installed, new, diagnostics = resolve_dependencies(specs)
    assert installed == new == []
    assert any(d.level == "error" for d in diagnostics)
    run.assert_not_called()


def test_pip_failure_returns_both_streams_scrubbed_in_dependency_diagnostics(monkeypatch):
    # Synthetic credentials only. Exercise copied assignments/JSON/token rules
    # and authenticated HTTP index userinfo while preserving pip's explanation.
    token = "ghp_" + "x" * 36
    stdout = 'Looking in indexes: https://test-user:fake-pass@example.com/simple\npassword=fake-pass'
    stderr = (f'ERROR: No matching distribution found for example-package\n{token}\n'
              '{"api_key":"fake-key"}')
    run = MagicMock(return_value=SimpleNamespace(returncode=1, stdout=stdout, stderr=stderr))
    monkeypatch.setattr("src.tools.skill_manager.subprocess.run", run)
    monkeypatch.setattr("src.tools.skill_manager._is_package_installed", lambda _spec: False)
    _, _, diagnostics = resolve_dependencies(["example-package"])
    output = diagnostics[0].message
    assert "Looking in indexes" in output
    assert "No matching distribution found for example-package" in output
    assert "example.com/simple" in output
    assert "[REDACTED]" in output
    for secret in ("test-user", "fake-pass", "fake-key", token):
        assert secret not in output


def test_pip_echoed_environment_tokens_and_url_userinfo_scrubbed(monkeypatch):
    monkeypatch.setenv("PIP_AUTH_TOKEN", "synthetic-short")
    monkeypatch.setenv("PACKAGE_PASSWORD", "synthetic-pass")
    stdout = ("ERROR: proxy authentication failed: synthetic-short synthetic-pass\n"
              "https://fake-user:p@ss@example.com/simple\n"
              "https://fake-user:p%40ss@example.com/simple")
    run = MagicMock(return_value=SimpleNamespace(returncode=1, stdout=stdout, stderr=""))
    monkeypatch.setattr("src.tools.skill_manager.subprocess.run", run)
    success, output = _install_packages(["example-package"])
    assert not success
    assert "proxy authentication failed" in output
    assert output.count("example.com/simple") == 2
    for secret in ("synthetic-short", "synthetic-pass", "fake-user", "p@ss", "p%40ss"):
        assert secret not in output


def test_pip_cannot_start_exception_does_not_reflect_secrets(monkeypatch):
    run = MagicMock(side_effect=OSError("password=synthetic-pass"))
    monkeypatch.setattr("src.tools.skill_manager.subprocess.run", run)
    assert _install_packages(["example-package"]) == (
        False, "pip installation could not start")


def test_pip_timeout_partial_streams_are_useful_and_scrubbed(monkeypatch):
    run = MagicMock(side_effect=subprocess.TimeoutExpired(
        "pip", 120, output=b"Retrying index: password=fake-pass",
        stderr=b"ERROR: index unreachable"))
    monkeypatch.setattr("src.tools.skill_manager.subprocess.run", run)
    success, output = _install_packages(["example-package"])
    assert not success
    assert "timed out after 120s" in output
    assert "Retrying index" in output and "index unreachable" in output
    assert "fake-pass" not in output
