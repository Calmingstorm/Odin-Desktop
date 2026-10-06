"""OpenRouter named methods using real profile settings and provider owners."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import yaml

from src.audit.logger import AuditLogger
from src.config.schema import Config
from src.desktop.codex_accounts import CodexAccountsService
from src.desktop.management import MethodError
from src.desktop.model_settings import ModelSettingsService
from src.desktop.openrouter_admin import METHODS, READ_METHODS, OpenRouterAdminService
from src.desktop.paths import ProfilePaths
from src.desktop.providers import ProviderOwner
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from src.llm.context_budget import compatible_agent_unavailable_reason
from src.llm.openai_compatible import OpenAICompatibleClient
from src.usage.rollup import UsageRollup
from src.web.api import llm_admin
from src.web.api.llm_admin import _openrouter_endpoint_rows as retained_endpoint_rows
from tests.test_desktop_settings import MemoryKeyring

ROWS = [{"tag": "route", "provider_name": "Route", "context_length": 100_000,
         "max_completion_tokens": 20_000, "supports_tools": True,
         "supports_reasoning": True, "quantization": "unknown"}]
MODEL = {"id": "vendor/model", "variant": "standard", "supports_tools": True,
         "supports_reasoning": True, "supported_efforts": [], "agent_eligible": True,
         "context_length": 100_000, "max_completion_tokens": 20_000}


@pytest.fixture
def service(tmp_path, monkeypatch):
    paths = ProfilePaths.from_xdg("fixture", home=tmp_path, environ={})
    paths.create_private()
    paths.config_file.write_text("{}\n", encoding="utf-8")
    backend = MemoryKeyring()
    settings = SettingsService(paths, ProfileSecretStore(paths, backend=backend), config=Config())
    cfg = settings.config.openai_compatible
    cfg.enabled = True
    cfg.preset = "openrouter"
    cfg.base_url = "https://openrouter.ai/api/v1"
    cfg.model = "vendor/model"
    cfg.api_key = "fixture-key"
    settings.secrets.set("openai_compatible.api_key", "fixture-key")
    provider = ProviderOwner(settings, CodexAccountsService(settings))
    provider.compatible_client = OpenAICompatibleClient(
        "fixture-key", model=cfg.model, base_url=cfg.base_url,
        openrouter_routing=cfg.openrouter,
    )
    monkeypatch.setattr(llm_admin, "_openrouter_models", AsyncMock(
        return_value=([MODEL], False, None)))
    monkeypatch.setattr(llm_admin, "_openrouter_endpoint_rows", AsyncMock(return_value=ROWS))
    return OpenRouterAdminService(settings, provider=provider)


@pytest.mark.asyncio
async def test_read_methods_and_catalogue_profile_precedence(service):
    assert METHODS == service.METHODS
    assert READ_METHODS == {
        "openrouter.catalogue", "openrouter.endpoints", "providers.compat.diagnostic",
        "models.status", "models.provider.get",
    }
    from src.config.schema import OpenAICompatibleModelProfile
    cfg = service.settings.config.openai_compatible
    cfg.model_profiles[cfg.model] = OpenAICompatibleModelProfile(
        total_window_tokens=90_000, max_output_tokens=10_000)
    cfg.openrouter.catalogue_profiles[cfg.model] = OpenAICompatibleModelProfile(
        total_window_tokens=100_000, max_output_tokens=20_000)
    before = service.settings.paths.config_file.read_bytes()
    result = await service.handle("openrouter.catalogue", {})
    assert result["models"][0]["profile_source"] == "operator"
    assert result["models"][0]["profile_conflict"] is True
    expected = compatible_agent_unavailable_reason(cfg.model, cfg) is None
    assert result["models"][0]["agent_eligible"] is expected
    assert result["models"][0]["endpoints"] == ROWS
    assert len(result["quick_add"]) <= 8
    assert service.settings.paths.config_file.read_bytes() == before


@pytest.mark.asyncio
async def test_select_pin_unpin_persists_and_adopts_actual_runtime(service):
    revision = service.settings.revision
    result = await service.handle("openrouter.select", {
        "model": "vendor/model", "provider_tag": "route", "expected_revision": revision,
    })
    assert result["provider_tag"] == "route"
    assert result["profile"]["total_window_tokens"] == 100_000
    cfg = service.settings.config.openai_compatible
    assert cfg.openrouter.model_pins == {"vendor/model": "route"}
    assert service.provider.compatible_client.openrouter_routing is cfg.openrouter
    saved = yaml.safe_load(service.settings.paths.config_file.read_text())
    assert saved["openai_compatible"]["openrouter"]["model_pins"] == {"vendor/model": "route"}
    assert "fixture-key" not in service.settings.paths.config_file.read_text()
    with pytest.raises(MethodError) as error:
        await service.handle("openrouter.select", {
            "model": "vendor/model", "expected_revision": revision,
        })
    assert error.value.code == "stale_binding"
    await service.handle("openrouter.select", {"model": "vendor/model"})
    assert service.settings.config.openai_compatible.openrouter.model_pins == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("change,code", [("endpoint", "stale_binding"), ("policy", "bad_request")])
async def test_rechecks_current_owner_after_remote_await(service, monkeypatch, change, code):
    before = service.settings.paths.config_file.read_bytes()
    async def models(cfg):
        if change == "endpoint":
            service.settings.config.openai_compatible.base_url = "https://example.com/v1"
        else:
            service.settings.config.openai_compatible.openrouter.only = ["different"]
        return [MODEL], False, None
    monkeypatch.setattr(llm_admin, "_openrouter_models", models)
    with pytest.raises(MethodError) as error:
        await service.handle("openrouter.select", {"model": "vendor/model"})
    assert error.value.code == code
    assert service.settings.paths.config_file.read_bytes() == before


@pytest.mark.asyncio
async def test_disk_failure_does_not_adopt_or_disclose(service, monkeypatch):
    previous = service.provider.compatible_client.openrouter_routing
    def fail(*args, **kwargs):
        raise RuntimeError("fixture-key disk details")
    monkeypatch.setattr("src.desktop.settings._patch_config_paths", fail)
    with pytest.raises(MethodError) as error:
        await service.handle("openrouter.select", {"model": "vendor/model"})
    assert error.value.code == "internal_error"
    assert error.value.message == "OpenRouter model policy not saved"
    assert service.provider.compatible_client.openrouter_routing is previous


@pytest.mark.asyncio
async def test_keyring_failure_does_not_fall_back(service):
    service.settings.secrets._backend.locked = True
    service.settings.config.openai_compatible.api_key = "unsafe-fallback"
    with pytest.raises(MethodError) as error:
        await service.handle("openrouter.endpoints", {"model": "vendor/model"})
    assert error.value.code == "unavailable"
    assert "unsafe-fallback" not in error.value.message


@pytest.mark.asyncio
async def test_preview_preserves_pin_policy_and_diagnostic_scrubs(service, monkeypatch):
    service.settings.config.openai_compatible.openrouter.model_pins = {"vendor/model": "missing"}
    service.settings.config.openai_compatible.openrouter.allow_fallbacks = False
    detail = await service.handle("openrouter.endpoints", {"model": "vendor/model"})
    assert detail["effective_profile"] is None
    monkeypatch.setattr(service.provider.compatible_client, "health_check", AsyncMock(
        return_value={"healthy": False, "error": "offline fixture-key", "token": "private"}))
    result = await service.handle("providers.compat.diagnostic", {})
    assert result["health"]["healthy"] is False
    assert result["health"]["error"] == "offline [REDACTED]"
    assert result["health"]["token"] == "[REDACTED]"
    service.provider.compatible_client = None
    with pytest.raises(MethodError) as error:
        await service.handle("providers.compat.diagnostic", {})
    assert error.value.code == "unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [
    "vendor/model:free", "vendor/model:batch", "invalid", "vendor/model?secret",
])
async def test_invalid_or_ineligible_models_do_not_write(service, model):
    before = service.settings.paths.config_file.read_bytes()
    with pytest.raises(MethodError) as error:
        await service.handle("openrouter.select", {"model": model})
    assert error.value.code == "bad_request"
    assert service.settings.paths.config_file.read_bytes() == before


@pytest.mark.asyncio
async def test_tools_inventory_affordances_real_settings(service):
    result = await ModelSettingsService(service.settings).handle("tools.list", {})
    command = next(item for item in result["tools"] if item["name"] == "run_command")
    assert command["cost"] == "medium" and command["risk"] == "high"
    assert command["state"] == "unavailable"


@pytest.mark.asyncio
async def test_catalogue_and_endpoint_copies_scrub_keyring_and_known_tokens(service, monkeypatch):
    rows = [{**ROWS[0], "provider_name": "Route fixture-key", "api_key": "hidden"}]
    monkeypatch.setattr(llm_admin, "_openrouter_endpoint_rows", AsyncMock(return_value=rows))
    service.settings.config.openai_compatible.openrouter.order = ["fixture-key"]
    detail = await service.handle("openrouter.endpoints", {"model": "vendor/model"})
    assert detail["endpoints"][0]["provider_name"] == "Route [REDACTED]"
    assert detail["endpoints"][0]["api_key"] == "[REDACTED]"
    catalogue = await service.handle("openrouter.catalogue", {})
    assert catalogue["routing"]["order"] == ["[REDACTED]"]
    assert "fixture-key" not in str(catalogue)
    # Original config/runtime rows are unmodified. D19 applies to model input,
    # not credential-bearing diagnostic copies shown to the settings renderer.
    assert service.settings.config.openai_compatible.openrouter.order == ["fixture-key"]
    assert rows[0]["provider_name"] == "Route fixture-key"


@pytest.mark.asyncio
async def test_retained_auth_scoped_cache_hashes_credentials(service, monkeypatch):
    saved = dict(llm_admin._openrouter_cache)
    try:
        llm_admin._openrouter_cache.update(models=None, fetched_at=0, error=None, details={})
        fetch = AsyncMock(return_value={"data": {"endpoints": [
            {"tag": "route", "provider_name": "Route"},
        ]}})
        monkeypatch.setattr("src.llm.openrouter.fetch_json", fetch)
        await retained_endpoint_rows("vendor/model", api_key="fixture-key-a")
        await retained_endpoint_rows("vendor/model", api_key="fixture-key-a")
        await retained_endpoint_rows("vendor/model", api_key="fixture-key-b")
        assert fetch.await_count == 2
        assert len(llm_admin._openrouter_cache["details"]) == 2
        assert "fixture-key" not in str(list(llm_admin._openrouter_cache["details"]))
    finally:
        llm_admin._openrouter_cache.clear()
        llm_admin._openrouter_cache.update(saved)


@pytest.mark.asyncio
async def test_measured_cache_real_usage_read_and_scrubbing(service, monkeypatch):
    root = service.settings.paths.data_dir
    usage = UsageRollup(str(root / "usage"), trajectory_directory=str(root / "trajectories"),
                        agent_trajectory_directory=str(root / "agents"),
                        audit=AuditLogger(str(root / "audit.jsonl")))
    service.usage = lambda: usage
    measured = (await usage.summary("30d")).get("upstream_cache", [])
    assert (await service.handle("openrouter.catalogue", {}))["measured_cache"] == measured
    # Inject only the telemetry read boundary, keeping its real owner reference.
    monkeypatch.setattr(usage, "summary", AsyncMock(return_value={"upstream_cache": [
        {"provider": "fixture-key", "cached_tokens": 4, "authorization": "Bearer other"}
    ]}))
    result = await service.handle("openrouter.catalogue", {})
    assert result["measured_cache"] == [{"provider": "[REDACTED]", "cached_tokens": 4,
                                           "authorization": "[REDACTED]"}]
    usage.summary.assert_awaited_once_with("30d")


@pytest.mark.asyncio
async def test_status_and_provider_get_use_serving_and_profile_owners(service):
    configured = service.settings.config.llm_provider.active_provider
    result = await service.handle("models.provider.get", {})
    assert result["configured_provider"] == configured
    # The compat graph exists but the configured main model is still codex;
    # configuring a transport does not claim to have switched the main model.
    assert result["serving_provider"] is None
    status = await service.handle("models.status", {})
    assert status["main_model"] == service.settings.config.llm_provider.model
    assert status["openai_compatible"]["configured"] is True
    assert status["openai_compatible"]["openrouter_recognized"] is True
    assert status["openai_compatible"]["has_api_key"] is True
    assert "fixture-key" not in str(status)
    with pytest.raises(MethodError) as error:
        await service.handle("models.provider.set", {"provider": "invalid"})
    assert error.value.code == "bad_request"
