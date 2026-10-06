"""Desktop host service exercises Odin's real candidate/registry lifecycle."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.config.persistence import DELETE_CONFIG_PATH
from src.config.schema import Config
from src.desktop.hosts import HostsService
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.provisioning import fresh_config
from src.tools.hosts.control import fingerprint_public_key


class Settings:
    """In-memory atomic adapter; real SettingsService gets integration coverage."""
    def __init__(self, paths):
        self.paths = paths
        self.config = fresh_config(paths)
        self.revision = "r0"
        self.fail = False
        self.calls = []

    def save_changes(self, changes, *, method, expected_revision):
        assert expected_revision == self.revision
        if self.fail:
            raise MethodError("internal_error", "fixture save failed")
        data = self.config.model_dump()
        for path, value in changes:
            node = data
            for key in path[:-1]:
                node = node.setdefault(key, {})
            if value is DELETE_CONFIG_PATH:
                node.pop(path[-1], None)
            else:
                node[path[-1]] = value
        self.config = Config.model_validate(data)
        self.calls.append((changes, method))
        self.revision = f"r{len(self.calls)}"
        return {"revision": self.revision, "fields": []}


@pytest.fixture
def service(tmp_path):
    paths = ProfilePaths.from_xdg(environ={
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }, home=tmp_path)
    return HostsService(Settings(paths))


async def prepare_test(service, alias="lab", **extra):
    prepared = await service.handle("hosts.prepare", {"alias": alias, "address": "127.0.0.1",
                                   "confirm_local": True, **extra})
    tested = await service.handle("hosts.test", {"token": prepared["candidate_token"]})
    assert tested["tested"] is True
    return prepared["candidate_token"]


@pytest.mark.asyncio
async def test_local_enrollment_requires_only_odin_confirmation(service):
    with pytest.raises(MethodError, match="confirm_local"):
        await service.handle("hosts.prepare", {"alias": "lab", "address": "localhost"})
    prepared = await service.handle("hosts.prepare", {"alias": "lab", "address": "::1",
                                    "confirm_local": True, "trust_mode": "ca"})
    assert prepared["trust_mode"] == "legacy" and prepared["fingerprints"] == []
    assert "lab" not in service.registry.active_aliases()
    with pytest.raises(MethodError, match="connection test"):
        await service.handle("hosts.commit", {"token": prepared["candidate_token"]})
    # Harmless actual local test command from Odin's enrollment implementation.
    result = await service.handle("hosts.test", {"token": prepared["candidate_token"]})
    assert result["last_test"]["ok"]
    result = await service.handle("hosts.commit", {"token": prepared["candidate_token"]})
    assert result["saved"] and result["trust_state"] == "local"
    assert result["host"]["host_id"] == prepared["host_id"]
    rows = await service.handle("hosts.list", {})
    assert rows["default_host"] == "localhost" and len(rows["hosts"]) == 2


@pytest.mark.asyncio
async def test_list_keeps_configured_inactive_default_without_mutation(service):
    await service.handle("hosts.set_enabled", {"alias": "localhost", "enabled": False})
    revision = service.settings.revision
    snapshot = service.registry.snapshot()
    rows = await service.handle("hosts.list", {})
    assert rows["default_host"] == ""
    assert rows["configured_default_host"] == "localhost"
    assert service.settings.config.tools.default_host == "localhost"
    assert service.settings.revision == revision
    assert service.registry.snapshot() is snapshot


@pytest.mark.asyncio
async def test_generation_drain_revoke_and_references(service):
    token = await prepare_test(service)
    await service.handle("hosts.commit", {"token": token})
    lease = service.registry.acquire("lab")
    generation = service.registry.generation
    result = await service.handle("hosts.set_enabled", {"alias": "lab", "enabled": False})
    assert result["saved"] and not result["targetable"] and result["draining"]
    assert service.registry.generation == generation + 1
    assert not lease.revoked and service.registry.acquire("lab") is None
    process_registry = SimpleNamespace(
        force_revoke_host=AsyncMock(side_effect=RuntimeError("fixture"))
    )
    service.executor = SimpleNamespace(_process_registry=process_registry)
    revoked = await service.handle("hosts.force_revoke", {"alias": "lab"})
    assert lease.revoked and revoked["leases_interrupted"] == 1
    assert revoked["processes"]["unknown"] == 1
    lease.release()
    await service.handle("hosts.settings", {"default_host": "lab"})
    refs = await service.handle("hosts.references", {"alias": "lab"})
    assert refs["references"] == [{"kind": "default_host", "location": "tools.default_host"}]
    with pytest.raises(MethodError, match="blocked"):
        await service.handle("hosts.delete", {"alias": "lab"})
    await service.handle("hosts.settings", {"default_host": ""})
    removed = await service.handle("hosts.delete", {"alias": "lab"})
    assert removed["saved"] and removed["trust_state"] == "removed"


@pytest.mark.asyncio
async def test_failed_save_and_stale_candidate_leave_registry_unchanged(service):
    token = await prepare_test(service)
    old = service.registry.snapshot()
    service.settings.fail = True
    with pytest.raises(MethodError, match="fixture save failed"):
        await service.handle("hosts.commit", {"token": token})
    assert service.registry.snapshot() is old
    assert service.enrollments.get(token).tested
    service.settings.fail = False
    await service.handle("hosts.commit", {"token": token})
    token = await prepare_test(service)
    await service.handle("hosts.set_enabled", {"alias": "lab", "enabled": False})
    with pytest.raises(MethodError, match="changed after"):
        await service.handle("hosts.commit", {"token": token})
    assert not service.registry.get("lab").enabled


@pytest.mark.asyncio
async def test_tofu_preview_exact_confirmation_and_pinned_mismatch(service, monkeypatch):
    import base64
    key = "ssh-ed25519 " + base64.b64encode(b"fixture-host-key-material").decode()
    monkeypatch.setattr(service.enrollments, "scan", AsyncMock(return_value=(key,)))
    monkeypatch.setattr(
        "src.tools.hosts.control._run_argv",
        AsyncMock(return_value=(0, b"odin-host-test linux\n")),
    )
    body = {"alias": "remote", "address": "host.example.invalid",
            "ssh_user": "deploy", "trust_mode": "tofu"}
    with pytest.raises(MethodError, match="TOFU is disabled"):
        await service.handle("hosts.prepare", body)
    await service.handle("hosts.settings", {"allow_host_tofu": True})
    preview = await service.handle("hosts.prepare", body)
    await service.handle("hosts.test", {"token": preview["candidate_token"]})
    with pytest.raises(MethodError, match="second confirmation"):
        await service.handle("hosts.commit", {"token": preview["candidate_token"]})
    with pytest.raises(MethodError, match="exact candidate"):
        await service.handle("hosts.prepare", {**body, "confirm_tofu": True,
                                            "candidate_fingerprints": ["SHA256:wrong"]})
    confirmed = await service.handle("hosts.prepare", {**body, "confirm_tofu": True,
                                        "candidate_fingerprints": preview["fingerprints"]})
    await service.handle("hosts.test", {"token": confirmed["candidate_token"]})
    result = await service.handle("hosts.commit", {"token": confirmed["candidate_token"]})
    assert result["targetable"] and result["host"]["trust_mode"] == "tofu"
    with pytest.raises(MethodError, match="does not match"):
        await service.handle("hosts.prepare", {**body, "trust_mode": "pinned",
                                "expected_fingerprints": ["SHA256:" + "A" * 43]})
    assert preview["fingerprints"] == [fingerprint_public_key(key)]


@pytest.mark.asyncio
async def test_public_key_shapes_and_validation(service, monkeypatch):
    monkeypatch.setattr("src.desktop.hosts.public_key_info", AsyncMock(return_value={
        "public_key": "fixture public key", "fingerprint": "SHA256:fixture",
        "authorized_keys_command": "fixture", "permissions": "fixture",
    }))
    result = await service.handle("hosts.public_key", {})
    assert not result["restart_pending"]
    service.settings.config.tools.ssh_key_path = "desired-only"
    assert (await service.handle("hosts.public_key", {}))["restart_pending"]
    for params in ({}, {"default_host": "absent"}, {"allow_host_tofu": "yes"}, {"allow": True}):
        with pytest.raises(MethodError):
            await service.handle("hosts.settings", params)
    with pytest.raises(MethodError, match="boolean"):
        await service.handle("hosts.set_enabled", {"alias": "localhost", "enabled": "false"})
    with pytest.raises(MethodError, match="not found"):
        await service.handle("hosts.references", {"alias": "absent"})


@pytest.mark.asyncio
async def test_executor_registry_and_schedule_reference_composition(service):
    executor = SimpleNamespace(host_registry=service.registry, _background_tasks={})
    scheduler = SimpleNamespace(list_all=lambda: [{"tool_input": {"host": "localhost"}}])
    composed = HostsService(service.settings, executor=executor, scheduler=scheduler)
    assert composed.registry is executor.host_registry
    refs = await composed.handle("hosts.references", {"alias": "localhost"})
    assert {r["kind"] for r in refs["references"]} == {"default_host", "task_reference"}


@pytest.mark.asyncio
async def test_real_settings_service_persists_host_activation(service):
    from src.config.schema import load_config
    from src.desktop.provisioning import ensure_profile
    from src.desktop.secrets import ProfileSecretStore
    from src.desktop.settings import SettingsService

    config = ensure_profile(service.settings.paths)
    backend = SimpleNamespace(get_password=lambda *_: None)
    settings = SettingsService(
        service.settings.paths, ProfileSecretStore(service.settings.paths, backend=backend),
        config=config,
    )
    service = HostsService(settings)
    token = await prepare_test(service)
    result = await service.handle("hosts.commit", {"token": token})
    assert result["saved"] and result["targetable"]
    saved = load_config(settings.paths.config_file)
    assert saved.tools.hosts["lab"].host_id == result["host"]["host_id"]
    await service.handle("hosts.settings", {"default_host": "lab"})
    assert service.registry.default_host == "lab"
    assert load_config(settings.paths.config_file).tools.default_host == "lab"
    field = settings.get_fields(["tools.default_host"])[0]
    assert field["effective"] == "lab" and field["apply_state"] == "applied"


@pytest.mark.asyncio
async def test_cancellation_before_publication_leaves_candidate_intact(service):
    import asyncio

    token = await prepare_test(service)
    async with service._lock:
        task = asyncio.create_task(service.handle("hosts.commit", {"token": token}))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert service.registry.get("lab") is None
    assert service.enrollments.get(token).tested
    assert service.settings.calls == []
