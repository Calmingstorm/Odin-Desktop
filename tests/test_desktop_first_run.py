"""Core readiness and retry with disposable credentials and owners."""
import json
from types import SimpleNamespace

import pytest
import yaml

from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.provisioning import fresh_config_document
from src.desktop.runtime import RuntimeService
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from src.health.subsystem_guard import SubsystemGuard


class MemoryKeyring:
    def __init__(self):
        self.values, self.failure = {}, None

    def get_password(self, namespace, name):
        if self.failure:
            raise RuntimeError(self.failure)
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        if self.failure:
            raise RuntimeError(self.failure + value)
        self.values[namespace, name] = value

    def delete_password(self, namespace, name):
        if self.failure:
            raise RuntimeError(self.failure)
        self.values.pop((namespace, name), None)


def make_runtime(tmp_path, *, updates=None):
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    paths.create_private()
    document = fresh_config_document(paths)
    SettingsService._merge(document, updates or {})
    paths.config_file.write_text(yaml.safe_dump(document))
    settings = SettingsService(paths, ProfileSecretStore(paths, backend=MemoryKeyring()))
    core = SimpleNamespace(phase="ready", paths=paths, capabilities=(), limits={},
                           authority=SimpleNamespace(runtime_id="test-core"))
    return RuntimeService(core, settings)


def state(runtime):
    return runtime.status()["first_run"]


@pytest.mark.asyncio
async def test_async_readiness_preserves_original_unknown_cleanup_projection(tmp_path):
    from src.desktop.resource_cleanup import ResourceCleanupError, ResourceCleanupJournal

    runtime = make_runtime(tmp_path)
    receipt = tmp_path / "resource-cleanup.json"
    journal = ResourceCleanupJournal(receipt)
    with pytest.raises(ResourceCleanupError):
        journal.finish({"computer": {
            "state": "unknown", "unresolved_sessions": ["original-owner"],
        }})
    runtime.core.resource_cleanup = ResourceCleanupJournal(receipt)
    original = runtime.core.resource_cleanup.public()
    saved = receipt.read_bytes()
    for _ in range(2):
        status = await runtime.status_async()
        assert status["first_run"]["state"] == "fresh"
        assert status["resource_cleanup"] == original
        assert status["resource_cleanup"]["reconciliation_required"] is True
        assert status["resource_cleanup"]["effects_undone"] is False
        assert status["resource_cleanup"]["replay"] is False
    assert receipt.read_bytes() == saved


def authorize(runtime):
    runtime.settings.secrets.set("codex_accounts", json.dumps({"access_token": "test-private"}))


def adopt(runtime, provider="codex", model=None):
    guard = SubsystemGuard()
    guard.register("llm_" + provider)
    guard.record_success("llm_" + provider)
    model = model or runtime.config.llm_provider.model
    if provider != "codex":
        model = model.split(":", 1)[1]
    client = SimpleNamespace(breaker=SimpleNamespace(state="closed"))
    identity = SimpleNamespace(provider=provider, model=model, client=client, reasoning_effort=None)
    runtime.llm_gateway = SimpleNamespace(
        capture_serving_identity=lambda: identity, subsystem_guard=guard,
        codex_client=client if provider == "codex" else None,
        ollama_client=client if provider == "ollama" else None,
        compatible_client=client if provider == "compat" else None,
    )
    return identity, guard


def test_fresh_second_launch_setup_later_is_durable_projection(tmp_path):
    runtime = make_runtime(tmp_path)
    original = runtime.settings.paths.config_file.read_bytes()
    assert state(runtime) == {"state": "fresh", "reason": "provider_not_configured",
                              "keyring_unavailable": False}
    runtime.settings.schema()
    second = SettingsService(runtime.settings.paths, runtime.settings.secrets)
    assert state(RuntimeService(runtime.core, second)) == state(runtime)
    assert runtime.settings.paths.config_file.read_bytes() == original


@pytest.mark.parametrize("updates", [
    {"openai_codex": {"enabled": False}},
    {"openai_codex": {"request_timeout_seconds": 120}},
    {"llm_provider": {"model": "compat:test-model"}, "openai_compatible": {"enabled": True}},
])
def test_incomplete_survives_relaunch(tmp_path, updates):
    runtime = make_runtime(tmp_path, updates=updates)
    assert state(runtime)["state"] == "incomplete"
    second = SettingsService(runtime.settings.paths, runtime.settings.secrets)
    assert state(RuntimeService(runtime.core, second))["state"] == "incomplete"


def test_saved_identity_and_guard_readiness(tmp_path):
    runtime = make_runtime(tmp_path)
    authorize(runtime)
    assert state(runtime)["reason"] == "provider_runtime_unavailable"
    identity, guard = adopt(runtime, model="other-model")
    assert state(runtime)["reason"] == "provider_identity_not_adopted"
    identity.model = runtime.config.llm_provider.model
    assert state(runtime)["state"] == "effective-ready"
    guard.mark_degraded("llm_codex", "fixture failure")
    assert state(runtime)["reason"] == "provider_health_degraded"
    guard.mark_unavailable("llm_codex", "fixture failure")
    assert state(runtime)["state"] == "degraded"
    guard.mark_available("llm_codex")
    identity.client.breaker.state = "open"
    assert state(runtime)["state"] == "degraded"
    identity.client.breaker.state = "closed"
    assert state(runtime)["state"] == "effective-ready"
    identity.client._generation_retired = True
    assert state(runtime)["state"] == "degraded"
    identity.client._generation_retired = False
    runtime.llm_gateway.subsystem_guard = None
    assert state(runtime)["reason"] == "provider_effective"
    runtime.llm_gateway.subsystem_guard = SubsystemGuard()
    assert state(runtime)["reason"] == "provider_effective"
    runtime.llm_gateway.subsystem_guard.register("llm_codex")
    assert state(runtime)["reason"] == "provider_effective"


@pytest.mark.asyncio
async def test_commit_default_without_credentials_stays_fresh(tmp_path):
    runtime = make_runtime(tmp_path)
    settings = runtime.settings
    settings.owners["providers.codex.set"] = lambda *args: True
    await settings.handle("providers.codex.set", {
        "expected_revision": settings.revision,
        "changes": [{"path": "openai_codex.enabled", "value": True}],
    })
    assert (await runtime.status_async())["first_run"]["state"] == "fresh"
    second = SettingsService(settings.paths, settings.secrets)
    second_status = await RuntimeService(runtime.core, second).status_async()
    assert second_status["first_run"]["state"] == "fresh"


@pytest.mark.parametrize("provider,credential", [
    ("ollama", None), ("compat", "openai_compatible.api_key"),
])
def test_all_providers_and_unsaved_selection(tmp_path, provider, credential):
    section = "ollama" if provider == "ollama" else "openai_compatible"
    runtime = make_runtime(tmp_path, updates={
        "llm_provider": {"model": provider + ":test-model"}, section: {"enabled": True},
    })
    if credential:
        assert state(runtime)["state"] == "incomplete"
        runtime.settings.secrets.set(credential, "test-private")
    assert state(runtime)["state"] == "saved"
    adopt(runtime, provider)
    assert state(runtime)["state"] == "effective-ready"
    runtime.config.llm_provider.model = provider + ":unsaved-model"
    adopt(runtime, provider)
    assert state(runtime)["state"] == "saved"


@pytest.mark.parametrize("failure", ["locked-test-private", "missing-test-private"])
def test_retry_preserves_runtime_application_evidence(tmp_path, failure):
    runtime = make_runtime(tmp_path)
    settings, backend = runtime.settings, runtime.settings.secrets._backend
    settings.secrets.set("openai_compatible.api_key", "test-private-key")
    settings.confirm_applied([(("openai_codex", "enabled"), True)])
    boot, applied = settings._boot.copy(), settings._applied.copy()
    backend.failure = failure
    assert settings.schema()["status"]["keyring_error"]
    assert state(runtime) == {"state": "degraded", "reason": "keyring_unavailable",
                              "keyring_unavailable": True}
    backend.failure = None
    recovered = settings.schema()
    assert recovered["status"]["keyring_error"] is None
    assert settings.config.openai_compatible.api_key == "test-private-key"
    assert settings._boot == boot and settings._applied == applied
    field = next(f for f in recovered["fields"] if f["path"] == "openai_codex.enabled")
    assert field["apply_state"] == "applied" and field["effective"] is True
    assert "test-private" not in json.dumps(recovered)
    assert "test-private" not in settings.paths.config_file.read_text()
    assert not list(settings.paths.secrets_dir.iterdir())


@pytest.mark.asyncio
async def test_failed_keyring_write_distinct_error_retry_no_fallback(tmp_path):
    runtime = make_runtime(tmp_path)
    settings, backend = runtime.settings, runtime.settings.secrets._backend
    settings.owners["providers.compat.set"] = lambda *args: True
    original = settings.paths.config_file.read_bytes()
    backend.failure = "locked-test-private"
    with pytest.raises(MethodError) as exc:
        await settings.handle("secrets.set", {
            "path": "openai_compatible.api_key", "value": "write-private",
        })
    assert exc.value.code == "keyring_unavailable"
    assert "private" not in str(exc.value)
    assert settings.paths.config_file.read_bytes() == original
    backend.failure = None
    assert (await settings.handle("settings.schema", {}))["status"]["keyring_error"] is None
    assert await settings.handle("secrets.set", {"path": "openai_compatible.api_key",
                                                "value": "write-private"}) == {"set": True}
    assert "write-private" not in json.dumps(settings.schema())
    assert "write-private" not in settings.paths.config_file.read_text()


def test_corrupt_credentials_safe_failure(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.settings.secrets.set("codex_accounts", "test-private-corrupt-json")
    assert state(runtime) == {"state": "degraded", "reason": "credential_state_unavailable",
                              "keyring_unavailable": False}
    assert "test-private" not in json.dumps(runtime.status())
