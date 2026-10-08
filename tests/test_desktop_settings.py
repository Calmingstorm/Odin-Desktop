"""Real settings/keyring behavior using only an isolated temporary adapter."""

import asyncio
import json

import pytest
import yaml

from src.config.apply_registry import REDACTED
from src.config.image_defaults import IMAGE_MODEL_DEFAULTS
from src.config.persistence import DELETE_CONFIG_PATH
from src.config.schema import Config
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.secrets import ProfileSecretStore, SecretStoreError
from src.desktop.settings import SettingsService


class MemoryKeyring:
    def __init__(self):
        self.values = {}
        self.locked = False

    def get_password(self, namespace, name):
        if self.locked:
            raise RuntimeError("locked temporary backend")
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        if self.locked:
            raise RuntimeError(value)
        self.values[namespace, name] = value

    def delete_password(self, namespace, name):
        if self.locked:
            raise RuntimeError("locked temporary backend")
        self.values.pop((namespace, name), None)


@pytest.fixture
def service(tmp_path):
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    paths.create_private()
    paths.config_file.write_text("# preserved\npersonality:\n  custom_name: Odin\n")
    return SettingsService(paths, ProfileSecretStore(paths, backend=MemoryKeyring()))


async def save(service, method, changes):
    return await service.handle(
        method, {"expected_revision": service.schema()["revision"], "changes": changes}
    )


async def test_existing_missing_timezone_stays_utc_for_save_reload_and_delete(service, monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    assert service.config.timezone == "UTC"
    await save(service, "settings.set", [
        {"path": "personality.custom_name", "value": "Odin revised"},
    ])
    assert service.config.timezone == "UTC"
    assert "timezone" not in yaml.safe_load(service.paths.config_file.read_text())
    await service.reload()
    assert service.config.timezone == "UTC"
    await save(service, "settings.set", [{"path": "timezone", "value": "Europe/Paris"}])
    assert service.config.timezone == "Europe/Paris"
    await save(service, "settings.set", [{"path": "timezone", "delete": True}])
    assert service.config.timezone == "UTC"
    assert "timezone" not in yaml.safe_load(service.paths.config_file.read_text())


def test_computer_schema_exposes_only_opt_in(service):
    fields = [field["path"] for field in service.schema()["fields"]
              if field["path"].startswith("computer.")]
    assert fields == ["computer.enabled"]


def test_codex_context_utilization_schema_matches_core_validator(service):
    field = next(field for field in service.schema()["fields"]
                 if field["path"] == "openai_codex.context_utilization")
    assert field["default"] == 60
    assert field["constraints"] == {"minimum": 30, "maximum": 100}
    minimum = field["constraints"]["minimum"]
    maximum = field["constraints"]["maximum"]
    for value in (minimum, 60, maximum):
        config = Config.model_validate({"openai_codex": {"context_utilization": value}})
        assert config.openai_codex.context_utilization == value
    for value in (minimum - 1, maximum + 1):
        with pytest.raises(ValueError, match="context_utilization"):
            Config.model_validate({"openai_codex": {"context_utilization": value}})


@pytest.mark.asyncio
@pytest.mark.parametrize("path,value", [("computer.display", ":32001"),
    ("computer.platform", "wayland"), ("computer.monitor_names", ["screen"]),
    ("computer", {"enabled": True})])
async def test_computer_native_config_cannot_be_saved(service, path, value):
    before = service.paths.config_file.read_bytes()
    with pytest.raises(MethodError, match="derived from the session"):
        await save(service, "settings.set", [{"path": path, "value": value}])
    assert service.paths.config_file.read_bytes() == before


def test_namespace_and_no_file_fallback(tmp_path):
    backend = MemoryKeyring()
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    store = ProfileSecretStore(paths, backend=backend)
    assert store.get("codex_accounts") is None
    assert store.set("codex_accounts", "temporary-json") is True
    assert store.get("codex_accounts") == "temporary-json"
    other = ProfileSecretStore(
        ProfilePaths.from_xdg("other", home=tmp_path, environ={}), backend=backend
    )
    assert other.get("codex_accounts") is None
    assert not paths.secrets_dir.exists()
    store.clear("codex_accounts")
    assert store.get("codex_accounts") is None
    backend.locked = True
    with pytest.raises(SecretStoreError) as error:
        store.set("codex_accounts", "private-placeholder")
    assert "private-placeholder" not in str(error.value)
    assert not paths.secrets_dir.exists()


@pytest.mark.asyncio
async def test_generic_save_preserves_source_and_restart_truth(service):
    old = service.config.browser.enabled
    result = await save(service, "settings.set", [{"path": "browser.enabled", "value": not old}])
    field = result["fields"][0]
    assert field["desired"] is not old
    assert field["effective"] is old
    assert field["pending_restart"]
    assert "# preserved" in service.paths.config_file.read_text()


@pytest.mark.asyncio
async def test_stale_and_whole_validation_are_atomic(service):
    before = service.paths.config_file.read_text()
    original = service.config.model_dump()
    with pytest.raises(MethodError) as error:
        await service.handle(
            "settings.set",
            {
                "expected_revision": "stale",
                "changes": [{"path": "personality.name", "value": "new"}],
            },
        )
    assert error.value.code == "stale_binding"
    with pytest.raises(MethodError):
        await save(
            service,
            "settings.set",
            [
                {"path": "personality.name", "value": "new"},
                {"path": "agents.max_concurrent", "value": -1},
            ],
        )
    assert service.config.model_dump() == original
    assert service.paths.config_file.read_text() == before


@pytest.mark.asyncio
async def test_owner_method_and_secret_refusals(service):
    for method, path, value, expected in [
        ("settings.set", "ollama.model", "test-model", "providers.ollama.set"),
        ("providers.codex.set", "ollama.enabled", True, "providers.ollama.set"),
        ("settings.set", "ollama.api_key", "temporary-key", "secrets.set"),
    ]:
        with pytest.raises(MethodError, match=expected):
            await save(service, method, [{"path": path, "value": value}])


@pytest.mark.asyncio
async def test_live_owner_runs_after_save_and_failure_restores(service):
    observed = []

    async def owner(candidate, previous, changes):
        observed.append(yaml.safe_load(service.paths.config_file.read_text())["ollama"]["model"])
        await asyncio.sleep(0)

    service.owners["providers.ollama.set"] = owner
    result = await save(
        service, "providers.ollama.set", [{"path": "ollama.model", "value": "test-model"}]
    )
    assert observed == ["test-model"]
    assert result["fields"][0]["effective"] == "test-model"
    before, revision = service.paths.config_file.read_text(), service.revision
    service.owners["providers.ollama.set"] = lambda *args: False
    with pytest.raises(MethodError, match="restored"):
        await save(
            service, "providers.ollama.set", [{"path": "ollama.model", "value": "failed-model"}]
        )
    assert service.paths.config_file.read_text() == before
    assert service.config.ollama.model == "test-model"
    assert service.revision == revision


@pytest.mark.asyncio
async def test_provider_without_owner_never_reports_applied(service):
    before = service.paths.config_file.read_text()
    with pytest.raises(MethodError) as error:
        await save(
            service,
            "providers.compat.set",
            [{"path": "openai_compatible.model", "value": "test-model"}],
        )
    assert error.value.code == "capability_unavailable"
    assert service.paths.config_file.read_text() == before


@pytest.mark.asyncio
async def test_keyring_set_clear_owner_and_redaction(service):
    seen = []
    service.owners["providers.compat.set"] = lambda candidate, previous, changes: seen.append(
        candidate.openai_compatible.api_key
    )
    assert await service.handle(
        "secrets.set", {"path": "openai_compatible.api_key", "value": "temporary-credential"}
    ) == {"set": True}
    assert seen == ["temporary-credential"]
    assert service.secrets.get("openai_compatible.api_key") == "temporary-credential"
    assert "temporary-credential" not in json.dumps(service.schema())
    field = next(f for f in service.schema()["fields"] if f["path"] == "openai_compatible.api_key")
    assert field["desired"] == REDACTED
    assert "temporary-credential" not in service.paths.config_file.read_text()
    assert await service.handle("secrets.clear", {"path": "openai_compatible.api_key"}) == {
        "set": False
    }
    assert service.secrets.get("openai_compatible.api_key") is None
    assert seen[-1] == ""


@pytest.mark.asyncio
async def test_secret_apply_failure_restores_keyring(service):
    service.owners["providers.compat.set"] = lambda *args: True
    await service.handle("secrets.set", {"path": "openai_compatible.api_key", "value": "before"})
    revision = service.revision
    service.owners["providers.compat.set"] = lambda *args: False
    with pytest.raises(MethodError):
        await service.handle("secrets.set", {"path": "openai_compatible.api_key", "value": "after"})
    assert service.secrets.get("openai_compatible.api_key") == "before"
    assert service.config.openai_compatible.api_key == "before"
    assert service.revision == revision


@pytest.mark.asyncio
async def test_image_pin_follow_equal_default_and_stale(service):
    initial = service.schema()
    assert initial["image_models"]["image_model"]["status"] == "follow"
    result = await service.handle(
        "models.image.intent",
        {
            "expected_revision": initial["image_models_revision"],
            "operations": {"image_model": "pin"},
        },
    )
    assert result["image_models"]["image_model"]["status"] == "pin"
    assert result["revision"] != initial["revision"]
    assert (
        yaml.safe_load(service.paths.config_file.read_text())["image"]["openai"]["image_model"]
        == IMAGE_MODEL_DEFAULTS["image_model"]
    )
    with pytest.raises(MethodError) as error:
        await service.handle(
            "models.image.intent",
            {
                "expected_revision": initial["image_models_revision"],
                "operations": {"outer_model": "pin"},
            },
        )
    assert error.value.code == "stale_binding"
    follow = await service.handle(
        "models.image.intent",
        {
            "expected_revision": result["image_models_revision"],
            "operations": {"image_model": "follow"},
        },
    )
    assert follow["image_models"]["image_model"]["status"] == "follow"


def test_sync_sections_and_delete(service):
    service.save_changes([(("tools", "default_host"), "")], method="hosts.settings")
    service.save_changes([(("personality", "custom_name"), "Other")])
    assert service.config.personality.custom_name == "Other"
    service.save_changes([(("personality", "custom_name"), DELETE_CONFIG_PATH)])
    assert service.config.personality.custom_name == Config().personality.custom_name


def test_locked_keyring_schema_and_corrupt_config(service):
    service.secrets._backend.locked = True
    schema = service.schema()
    assert schema["status"]["keyring_error"]
    assert all(f["configured"] is None for f in schema["fields"] if f["sensitivity"] != "public")
    service.paths.config_file.write_text("[malformed")
    with pytest.raises(Exception):
        SettingsService(service.paths, service.secrets)


@pytest.mark.asyncio
async def test_prepared_owner_failure_restores_exact_saved_text(service):
    events = []

    class Token:
        async def apply(self):
            events.append("apply")
            assert "new-model" in service.paths.config_file.read_text()
            raise RuntimeError("harmless qualification failure")

        async def rollback(self):
            events.append("rollback")

    class Owner:
        def prepare_settings(self, candidate, changes):
            events.append("prepare")
            assert "new-model" not in service.paths.config_file.read_text()
            return Token()

    service.owners["providers.ollama.set"] = Owner()
    before = service.paths.config_file.read_text()
    with pytest.raises(MethodError):
        await save(
            service, "providers.ollama.set", [{"path": "ollama.model", "value": "new-model"}]
        )
    assert events == ["prepare", "apply", "rollback"]
    assert service.paths.config_file.read_text() == before


@pytest.mark.asyncio
async def test_persistence_failure_does_not_apply(service, monkeypatch):
    import src.desktop.settings as module

    calls = []
    service.owners["providers.ollama.set"] = lambda *args: calls.append("apply")
    revision = service.schema()["revision"]

    def fail(*args, **kwargs):
        raise OSError("harmless write failure")

    monkeypatch.setattr(module, "_patch_config_paths", fail)
    with pytest.raises(MethodError, match="not saved"):
        await service.handle(
            "providers.ollama.set",
            {
                "expected_revision": revision,
                "changes": [{"path": "ollama.model", "value": "unsaved-model"}],
            },
        )
    assert not calls
    assert service.revision == revision


@pytest.mark.asyncio
async def test_async_owner_rejects_interleaved_sync_writer(service):
    async def owner(candidate, previous, changes):
        with pytest.raises(MethodError, match="transaction is in progress"):
            service.save_changes([(("personality", "custom_name"), "Interleaved")])
        await asyncio.sleep(0)

    service.owners["providers.ollama.set"] = owner
    await save(service, "providers.ollama.set", [{"path": "ollama.model", "value": "new-model"}])
    assert service.config.personality.custom_name != "Interleaved"


@pytest.mark.asyncio
async def test_route_specific_validation_and_restart_only_save(service):
    service.owners["providers.ollama.set"] = lambda *args: True
    for path, value in [("ollama.timeout", 3601), ("ollama.base_url", "https://8.8.8.8")]:
        with pytest.raises(MethodError):
            await save(service, "providers.ollama.set", [{"path": path, "value": value}])
    with pytest.raises(MethodError):
        await save(
            service,
            "providers.codex.set",
            [{"path": "openai_codex.request_timeout_seconds", "value": True}],
        )
    old = service.config.openai_codex.connection_pool.max_connections
    result = await save(
        service,
        "providers.codex.set",
        [
            {
                "path": "openai_codex.connection_pool.max_connections",
                "value": old + 1,
            }
        ],
    )
    assert result["fields"][0]["pending_restart"]
    assert result["fields"][0]["effective"] == old


@pytest.mark.asyncio
async def test_reload_requires_atomic_owner_and_preserves_boot(service):
    before = service.config.browser.enabled
    service.paths.config_file.write_text(f"browser:\n  enabled: {str(not before).lower()}\n")
    with pytest.raises(MethodError, match="reload owner"):
        await service.reload()
    assert service.config.browser.enabled is before
    service.owners["runtime.reload"] = lambda candidate, previous, changes: True
    result = await service.reload()
    field = next(f for f in result["fields"] if f["path"] == "browser.enabled")
    assert field["desired"] is not before
    assert field["effective"] is before
    assert field["pending_restart"]


def test_internal_webhook_plaintext_rejected(service):
    row = {"id": "temporary", "url": "https://example.invalid", "secret": "temporary-key"}
    with pytest.raises(MethodError, match="secret"):
        service.save_changes(
            [(("outbound_webhooks", "targets"), [row])], method="webhooks.outbound.save"
        )
    row.update(url="https://operator:temporary-password@example.invalid", secret="")
    with pytest.raises(MethodError, match="keyring"):
        service.save_changes(
            [(("outbound_webhooks", "targets"), [row])], method="webhooks.outbound.save"
        )


def test_explicit_profile_defaults_on_load_and_delete(service):
    assert service.config.tools.audit_log_path == str(service.paths.data_dir / "audit.jsonl")
    service.save_changes([(("tools", "audit_log_path"), "/tmp/temporary-other-audit.jsonl")])
    service.save_changes([(("tools", "audit_log_path"), DELETE_CONFIG_PATH)])
    assert service.config.tools.audit_log_path == str(service.paths.data_dir / "audit.jsonl")
    loaded = SettingsService(service.paths, service.secrets)
    assert loaded.config.tools.audit_log_path == service.config.tools.audit_log_path


@pytest.mark.asyncio
async def test_secret_extra_params_cannot_leak_into_binding(service):
    with pytest.raises(MethodError, match="accepts only"):
        await service.handle(
            "secrets.set",
            {
                "path": "ollama.api_key",
                "value": "temporary-value",
                "changes": [{"path": "temporary-value"}],
            },
        )
    assert service.secrets.get("ollama.api_key") is None


@pytest.mark.asyncio
async def test_generic_image_default_save_keeps_following(service):
    await save(
        service,
        "settings.set",
        [
            {
                "path": "image.openai.image_model",
                "value": IMAGE_MODEL_DEFAULTS["image_model"],
            }
        ],
    )
    assert service.schema()["image_models"]["image_model"]["status"] == "follow"
    await save(
        service, "settings.set", [{"path": "image.openai.image_model", "value": "custom-image"}]
    )
    assert service.schema()["image_models"]["image_model"]["status"] == "pin"


@pytest.mark.asyncio
async def test_owner_cancellation_rolls_back_saved_values(service):
    async def owner(*args):
        raise asyncio.CancelledError

    service.owners["providers.ollama.set"] = owner
    before = service.paths.config_file.read_text()
    with pytest.raises(asyncio.CancelledError):
        await save(
            service, "providers.ollama.set", [{"path": "ollama.model", "value": "cancelled-model"}]
        )
    assert service.paths.config_file.read_text() == before
    assert not service._transaction_active
