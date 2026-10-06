"""Phase 1 desktop skill and host authority contracts, hermetic only."""

from __future__ import annotations

import asyncio
import base64
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.config.schema import ToolHost
from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths
from src.permissions.host_access import HostAccessManager
from src.permissions.manager import PermissionManager
from src.tools.hosts import (
    HostEnrollmentManager,
    HostForceRevokedError,
    HostRegistry,
    HostTrustError,
)
from src.tools.hosts.control import scan_host_references
from src.tools.hosts.trust import fingerprint_public_key
from src.tools.skill_context import (
    MAX_SKILL_FILES,
    MAX_SKILL_MESSAGES,
    ResourceTracker,
    SkillContext,
)
from src.tools.skill_manager import (
    LoadedSkill,
    SkillManager,
    resolve_dependencies,
)


def _context(**kwargs):
    executor = kwargs.pop(
        "tool_executor", SimpleNamespace(execute=AsyncMock(return_value="admitted"))
    )
    return SkillContext(executor, "desktop_test", **kwargs)


async def test_host_command_requires_public_executor_admission():
    executor = SimpleNamespace(execute=AsyncMock(return_value="admitted"), _run_on_host=AsyncMock())
    context = _context(tool_executor=executor, requester_id="owner")
    assert await context.run_on_host("build", "true") == "admitted"
    executor.execute.assert_awaited_once_with(
        "run_command", {"host": "build", "command": "true"}, user_id="owner"
    )
    executor._run_on_host.assert_not_called()
    with pytest.raises(AttributeError):
        await _context(tool_executor=SimpleNamespace(_run_on_host=AsyncMock())).run_on_host(
            "build", "true"
        )


def test_host_inventory_has_no_desired_config_fallback():
    executor = SimpleNamespace(config=SimpleNamespace(hosts={"private": object()}))
    assert _context(tool_executor=executor).get_hosts() == []
    access = SimpleNamespace(get_allowed_hosts=lambda owner: ["scoped"] if owner == "owner" else [])
    executor._host_access = access
    assert _context(tool_executor=executor, requester_id="owner").get_hosts() == ["scoped"]
    assert _context(tool_executor=executor).get_hosts() == []


async def test_unwired_conversation_delivery_is_explicitly_unavailable():
    context = _context()
    with pytest.raises(RuntimeError, match="Phase 2"):
        await context.post_message("hello")
    with pytest.raises(RuntimeError, match="Phase 2"):
        await context.post_file(b"content", "notes.txt")
    assert context._tracker.messages_sent == context._tracker.files_sent == 0


async def test_conversation_callbacks_preserve_quotas():
    message, attachment = AsyncMock(), AsyncMock()
    tracker = ResourceTracker(messages_sent=MAX_SKILL_MESSAGES - 1, files_sent=MAX_SKILL_FILES - 1)
    context = _context(message_callback=message, file_callback=attachment, resource_tracker=tracker)
    await context.post_message("hello")
    await context.post_message("over quota")
    await context.post_file(b"content", "notes.txt", "caption")
    await context.post_file(b"content", "over.txt")
    message.assert_awaited_once_with("hello")
    attachment.assert_awaited_once_with(b"content", "notes.txt", "caption")
    assert tracker.messages_sent == MAX_SKILL_MESSAGES
    assert tracker.files_sent == MAX_SKILL_FILES


async def test_schedule_destination_is_not_a_free_form_scheduler_id():
    scheduler = SimpleNamespace(
        add=AsyncMock(), update=AsyncMock(), delete=AsyncMock(), list_all=lambda: ["foreign"]
    )
    context = _context(scheduler=scheduler, requester_id="owner")
    signature = inspect.signature(SkillContext.schedule_task)
    assert "conversation_id" in signature.parameters
    assert "channel_id" not in signature.parameters
    with pytest.raises(RuntimeError, match="Validated conversation"):
        await context.schedule_task(
            "task", "reminder", "foreign", requester_id="other", message="hello"
        )
    with pytest.raises(RuntimeError, match="Validated conversation"):
        await context.update_schedule("task", conversation_id="foreign")
    with pytest.raises(RuntimeError, match="Validated conversation"):
        await context.delete_schedule("task")
    assert context.list_schedules() == []
    scheduler.add.assert_not_called()
    scheduler.update.assert_not_called()
    scheduler.delete.assert_not_called()


async def test_unscoped_history_store_cannot_be_used_by_skill():
    store = SimpleNamespace(search_history=AsyncMock(return_value=[{"content": "foreign"}]))
    context = _context(session_manager=store)
    with pytest.raises(RuntimeError, match="Owner-scoped"):
        await context.search_history("query")
    store.search_history.assert_not_called()


async def test_url_grants_are_instance_scoped_and_used_for_hardened_fetch(monkeypatch):
    from src.tools import safe_fetch

    fetch = AsyncMock(
        return_value=SimpleNamespace(content_type="text/plain", body=b"ok", text=lambda: "ok")
    )
    monkeypatch.setattr(safe_fetch, "safe_fetch", fetch)
    granted = _context(allowed_urls=("http://127.0.0.1:8188/",))
    denied = _context()
    assert await granted.http_get("http://127.0.0.1:8188/status") == "ok"
    assert fetch.await_args.kwargs["allowed_urls"] == ["http://127.0.0.1:8188"]
    assert "Access denied" in await denied.http_get("http://127.0.0.1:8188/status")
    assert fetch.await_count == 1
    assert "Access denied" in await denied.http_post("http://127.0.0.1:8188/status")
    assert await granted.http_post("http://127.0.0.1:8188/status", json={"test": True}) == "ok"
    assert fetch.await_args.kwargs["allowed_urls"] == ["http://127.0.0.1:8188"]


async def test_restricted_files_and_generic_command_calls_stay_denied():
    executor = SimpleNamespace(execute=AsyncMock())
    context = _context(tool_executor=executor, requester_id="owner")
    assert "Access denied" in await context.read_file("build", "/home/owner/.ssh/id_ed25519")
    assert "Access denied" in await context.execute_tool(
        "read_file", {"host": "build", "path": "/etc/shadow"}
    )
    assert "not allowed" in await context.execute_tool(
        "run_command", {"host": "build", "command": "true"}
    )
    executor.execute.assert_not_called()


def test_missing_skill_dependencies_use_retained_installer(monkeypatch):
    monkeypatch.setattr("src.tools.skill_manager._is_package_installed", lambda _spec: False)
    calls = []

    def install(packages):
        calls.append(packages)
        return True, "fixture dependency installed"

    monkeypatch.setattr("src.tools.skill_manager._install_packages", install)
    installed, added, diagnostics = resolve_dependencies(["example-package>=1"])
    assert installed == [] and added == ["example-package>=1"]
    assert diagnostics[0].level == "warn"
    assert calls == [["example-package>=1"]]


def test_missing_dependencies_leave_import_failure_to_module(tmp_path, monkeypatch):
    manager = SkillManager(str(tmp_path), SimpleNamespace(), allowed_urls=("http://127.0.0.1:8188",))
    monkeypatch.setattr("src.tools.skill_manager._is_package_installed", lambda _spec: False)
    monkeypatch.setattr("src.tools.skill_manager._install_packages",
                        lambda packages: (False, "fixture dependency installation failed"))
    code = (
        'SKILL_DEFINITION = {"name": "missing", "description": "test", '
        '"input_schema": {"type": "object", "properties": {}}, '
        '"dependencies": ["example-package>=1"]}\n'
        'raise ImportError("disposable missing import")\n'
        'async def execute(inp, context):\n'
        '    return "ok"\n'
    )
    result = manager.create_skill("missing", code)
    assert "ImportError" in manager.definition_errors["missing.py"]
    assert "missing" not in manager._skills
    assert "failed to load" in result
    manager.close()


def test_reference_scan_uses_explicit_engine_repositories_only():
    config = SimpleNamespace(
        tools=SimpleNamespace(
            default_host="build", governor=SimpleNamespace(host_overrides={"build": {}})
        )
    )
    scheduler = SimpleNamespace(
        list_all=lambda: [{"tool_input": {"host": "build", "hosts": ["build"]}}]
    )
    tasks = {
        "active": SimpleNamespace(status="running", steps=[{"host": "build"}]),
        "settled": SimpleNamespace(status="completed", steps=[{"host": "build"}]),
    }
    refs = scan_host_references(config, "build", scheduler=scheduler, background_tasks=tasks)
    assert {ref["kind"] for ref in refs} == {"governor", "default_host", "task_reference"}
    assert any(ref["location"] == "background_tasks.active.steps.0.host" for ref in refs)
    assert not any("settled" in ref["location"] for ref in refs)


async def test_enrollment_requires_exact_trust_then_successful_test(tmp_path, monkeypatch):
    key = "ssh-ed25519 " + base64.b64encode(b"test-key").decode()
    manager = HostEnrollmentManager(HostRegistry({}, trust_dir=tmp_path))
    monkeypatch.setattr(manager, "scan", AsyncMock(return_value=(key,)))
    details = {
        "address": "example.invalid",
        "ssh_user": "deploy",
        "os": "linux",
        "trust_mode": "pinned",
    }
    with pytest.raises(HostTrustError, match="expected_fingerprints"):
        await manager.prepare("build", details, allow_tofu=False)
    candidate = await manager.prepare(
        "build",
        {**details, "expected_fingerprints": [fingerprint_public_key(key)]},
        allow_tofu=False,
    )
    with pytest.raises(HostTrustError, match="connection test"):
        manager.consume(candidate.token)
    monkeypatch.setattr(
        "src.tools.hosts.control._run_argv", AsyncMock(return_value=(0, b"odin-host-test linux\n"))
    )
    tested = await manager.test(candidate.token)
    assert tested.tested
    assert manager.consume(candidate.token) is tested
    with pytest.raises(HostTrustError, match="unknown or expired"):
        manager.consume(candidate.token)


async def test_local_enrollment_requires_consent_and_baseline_linux_check(tmp_path, monkeypatch):
    manager = HostEnrollmentManager(HostRegistry({}, trust_dir=tmp_path))
    with pytest.raises(HostTrustError, match="confirm_local"):
        await manager.prepare("local", {"address": "localhost", "os": "linux"}, allow_tofu=False)
    candidate = await manager.prepare(
        "local", {"address": "localhost", "os": "linux", "confirm_local": True}, allow_tofu=False
    )
    probe = AsyncMock(return_value=(0, b"odin-host-test linux\n"))
    monkeypatch.setattr("src.tools.hosts.control._run_argv", probe)
    assert (await manager.test(candidate.token)).tested
    probe.assert_awaited_once_with(["sh", "-c", "printf 'odin-host-test linux\\n'"], 15.0)


async def test_generation_leases_drain_and_force_revoke_keeps_uncertainty(tmp_path):
    host = ToolHost(address="localhost", os="linux")
    registry = HostRegistry({"local": host}, trust_dir=tmp_path)
    lease = registry.acquire("local")
    assert lease is not None
    old_generation = lease.target.generation
    staged = registry.stage({"local": host.model_copy(update={"enabled": False})})
    registry.publish_staged(staged)
    assert registry.acquire("local") is None
    assert lease.target.generation == old_generation
    assert registry.draining_aliases() == ("local",)
    assert registry.force_revoke("local") == 1
    with pytest.raises(HostForceRevokedError, match="outcome_unknown=true"):
        await lease.run(lambda: asyncio.sleep(0))
    lease.release()
    assert registry.draining_aliases() == ()


def test_trust_paths_require_explicit_profile_and_follow_directory_symlinks(tmp_path):
    with pytest.raises(ValueError, match="explicit profile"):
        HostRegistry({})
    with pytest.raises(ValueError, match="absolute"):
        HostRegistry({}, trust_dir="relative")
    paths = ProfilePaths.from_xdg("test", environ={}, home=tmp_path)
    registry = HostRegistry({}, profile_paths=paths)
    assert registry._trust_dir == paths.data_dir / "host_trust"
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    real.chmod(0o775)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    registry = HostRegistry({}, trust_dir=link)
    key = "ssh-ed25519 " + base64.b64encode(b"test-key").decode()
    destination = Path(registry.materialize_trust("test", "test", "pinned", (key,)))
    assert destination.parent == link
    assert destination.read_text() == f"test {key}\n"
    assert destination.stat().st_mode & 0o777 == 0o600
    assert (real / destination.name).read_text() == f"test {key}\n"
    assert real.stat().st_mode & 0o777 == 0o775


async def test_skill_host_discovery_requires_authentic_owner_and_live_inventory(tmp_path):
    authority = OwnerAuthority(ProfilePaths.from_xdg("test", environ={}, home=tmp_path))
    permission = PermissionManager(authority)
    access = HostAccessManager(
        tmp_path / "preferences.json",
        available_hosts=["build", "private"],
        permission_manager=permission,
    )
    context = _context(
        tool_executor=SimpleNamespace(_host_access=access), requester_id=authority.owner_id
    )
    assert context.get_hosts() == []
    token = permission.set_request_owner(authority.authenticate_local(peer_uid=authority.owner_uid))
    try:
        await access.set_default_host(authority.owner_id, "build")
        assert context.get_hosts() == ["build", "private"]
        access.set_available_hosts(["build"])
        assert context.get_hosts() == ["build"]
    finally:
        permission.reset_request_owner(token)
    assert context.get_hosts() == []


async def test_skill_manager_preserves_selected_scope_denial_and_uncertainty(tmp_path):
    from src.tools.execution_outcome import ToolFailure, dispatch_evidence

    executor = SimpleNamespace(check_permission=lambda _name, _owner: "Owner intake unavailable")
    manager = SkillManager(str(tmp_path), executor)
    execute = AsyncMock(return_value="must not execute")
    definition = {"name": "test", "description": "fixture",
                  "input_schema": {"type": "object", "properties": {}}}
    manager._skills["test"] = LoadedSkill("test", definition, execute, tmp_path / "test.py", "now")
    refused = await manager.execute("test", {}, requester_id="untrusted")
    assert isinstance(refused, ToolFailure)
    assert "Owner intake" in refused
    execute.assert_not_called()

    async def uncertain(_inp, context):
        dispatch_evidence.get().uncertain = True
        assert context._allowed_urls == ("http://127.0.0.1:8188",)
        return "effect may have occurred"

    manager._executor = SimpleNamespace(check_permission=lambda _name, _owner: None)
    manager._allowed_urls = ("http://127.0.0.1:8188",)
    manager._skills["test"].execute_fn = uncertain
    result = await manager.execute("test", {}, requester_id="owner")
    assert isinstance(result, ToolFailure)
    assert result.uncertain_outcome
