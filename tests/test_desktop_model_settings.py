"""Route-parity tests using isolated configuration, temporary credentials and HTTP."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp import web

from src.config.schema import Config, ToolsConfig
from src.desktop.management import MethodError
from src.desktop.model_settings import METHODS, READ_METHODS, ModelSettingsService
from src.llm import system_prompt
from src.tools.builtin_policy import BuiltinToolPolicy


class Settings:
    """Persistence seam; real Config validators, no profile or keyring access."""

    def __init__(self):
        self.config = Config()
        self.revision = "r0"
        self.secrets = SimpleNamespace(get=lambda path: "fixture-credential")
        self.writes = []
        self.fail = False

    def save_changes(self, changes, *, method="settings.set", expected_revision=None):
        if expected_revision is not None and expected_revision != self.revision:
            raise MethodError("stale_binding", "stale revision")
        if self.fail:
            raise MethodError("storage_unavailable", "fixture storage failure")
        values = self.config.model_dump()
        for path, value in changes:
            target = values
            for segment in path[:-1]:
                target = target[segment]
            target[path[-1]] = value
        self.config = Config.model_validate(values)
        self.writes.append((method, changes))
        self.revision = f"r{len(self.writes)}"
        return {"revision": self.revision, "fields": []}


class Cache:
    def __init__(self):
        self.invalidations = 0
        self.rebuilds = 0

    def invalidate(self):
        self.invalidations += 1

    def rebuild_default(self):
        self.rebuilds += 1


@pytest.fixture
def service():
    saved_presets = dict(system_prompt._USER_PRESETS)
    settings = Settings()
    provider = SimpleNamespace(tool_catalog=Cache(), prompt_builder=Cache())
    instance = ModelSettingsService(settings, provider=provider)
    yield instance
    system_prompt.register_user_presets(saved_presets)


@pytest.mark.asyncio
async def test_exact_methods_and_unavailable_owner(service):
    assert METHODS == service.METHODS
    assert READ_METHODS == {"models.agents.get", "models.discover", "personality.get",
                            "tools.list", "tools.timeouts.get"}
    with pytest.raises(MethodError) as error:
        await service.handle("models.main.set", {"model": "gpt-6.1-sol"})
    assert error.value.code == "unavailable"
    assert service.settings.writes == []
    with pytest.raises(MethodError) as error:
        await service.handle("not_a_method", {})
    assert error.value.code == "unknown_method"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [None, "", "inherit", "auto", "compat:", "ollama:"])
async def test_main_requires_concrete_model_and_schema(service, model):
    with pytest.raises(MethodError):
        await service.handle("models.main.set", {"model": model})
    assert not service.settings.writes


@pytest.mark.asyncio
async def test_main_delegates_provider_and_persistence_atomically(service):
    calls = []

    async def switch(provider, persist, *, model_ref):
        calls.append((provider, model_ref))
        persist()
        return {"status": "switched", "effective_model": "endpoint-model"}

    service.provider.switch_provider = switch
    answer = await service.handle("models.main.set", {"model": "ollama:sample:latest"})
    assert answer == {"status": "switched", "effective_model": "endpoint-model",
                      "main_model": "ollama:sample:latest", "configured_provider": "ollama"}
    assert calls == [("ollama", "ollama:sample:latest")]
    assert service.settings.config.llm_provider.model == "ollama:sample:latest"
    method, changes = service.settings.writes[0]
    assert method == "models.main.set"
    assert changes == [(('llm_provider', 'model'), 'ollama:sample:latest'),
                       (('llm_provider', 'active_provider'), 'ollama')]


@pytest.mark.asyncio
async def test_main_provider_failure_is_not_persisted_or_leaked(service):
    async def switch(provider, persist, *, model_ref):
        return {"error": "fixture-credential endpoint rejected"}

    service.provider.switch_provider = switch
    with pytest.raises(MethodError) as error:
        await service.handle("models.main.set", {"model": "gpt-6.1-sol"})
    assert error.value.code == "bad_request"
    assert "fixture-credential" not in str(error.value)
    assert service.settings.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("code,disposition", [
    ("stale_binding", "stale_binding"), ("storage_unavailable", "rejected"),
])
async def test_main_preserves_persist_method_error_after_owner_cleanup(service, code, disposition):
    failure = MethodError(code, "fixture failure", disposition=disposition)
    cleaned_up = False
    adopted = []

    def fail(*args, **kwargs):
        raise failure

    async def switch(provider, persist, *, model_ref):
        nonlocal cleaned_up
        try:
            persist()
        except MethodError:
            cleaned_up = True
            return {"error": "persist failed"}
        pytest.fail("Persistence failure must abort adoption")

    service.settings.save_changes = fail
    service.settings.confirm_applied = lambda changes: adopted.append(changes)
    service.provider.switch_provider = switch
    with pytest.raises(MethodError) as error:
        await service.handle("models.main.set", {"model": "ollama:fixture"})
    assert error.value is failure
    assert error.value.disposition == disposition
    assert cleaned_up and not adopted
    assert service.settings.writes == []
    assert not service._persisted


@pytest.mark.asyncio
async def test_main_stale_revision_preserved_by_real_owner_without_adoption(tmp_path, monkeypatch):
    import aiohttp
    from src.desktop.codex_accounts import CodexAccountsService
    from src.desktop.paths import ProfilePaths
    from src.desktop.providers import ProviderOwner
    from src.desktop.settings import SettingsService
    from src.llm import OllamaClient

    def forbidden_network(*args, **kwargs):
        pytest.fail("Model adoption regression must not open a network session")

    monkeypatch.setattr(aiohttp, "ClientSession", forbidden_network)
    paths = ProfilePaths.from_xdg("fixture", home=tmp_path, environ={})
    paths.create_private()
    paths.config_file.write_text("{}\n", encoding="utf-8")
    config = Config()
    config.ollama.enabled = True
    config.openai_codex.enabled = False
    config.openai_codex.auxiliary.enabled = False
    settings = SettingsService(paths, SimpleNamespace(get=lambda path: None), config=config)
    owner = ProviderOwner(settings, CodexAccountsService(settings))
    service = ModelSettingsService(settings, provider=owner)
    closed = []
    original_close = OllamaClient.close

    async def close(client):
        closed.append(client)
        await original_close(client)

    monkeypatch.setattr(OllamaClient, "close", close)
    try:
        stale_revision = settings.revision
        await service.handle("models.main.set", {
            "model": "ollama:adopted", "expected_revision": stale_revision,
        })
        before_config = settings.config.model_dump()
        before_bytes = paths.config_file.read_bytes()
        before_revision = settings.revision
        before_identity = owner.capture_serving_identity()
        before_client = owner.ollama
        before_generation = owner._generation
        before_closed = len(closed)
        with pytest.raises(MethodError) as error:
            await service.handle("models.main.set", {
                "model": "ollama:rejected", "expected_revision": stale_revision,
            })
        assert error.value.code == "stale_binding"
        assert error.value.disposition == "stale_binding"
        assert not service._persisted
        assert settings.config.model_dump() == before_config
        assert settings.revision == before_revision
        assert paths.config_file.read_bytes() == before_bytes
        assert owner.capture_serving_identity() == before_identity
        assert owner.ollama is before_client
        assert owner._generation == before_generation
        assert not getattr(before_client, "_generation_retired", False)
        assert len(closed) == before_closed + 1
        assert closed[-1] is not before_client
        assert closed[-1].model == "rejected"
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_agents_exact_route_fields_normalization_and_catalog(service):
    answer = await service.handle("models.agents.set", {
        "model": " auto ", "auto_model_allowlist": ["gpt-6-luna", "gpt-6-luna"],
        "model_selection_hints": {"gpt-6-luna": "lightweight tasks"},
        "iteration_timeout_seconds": 1,
    })
    assert answer["status"] == "updated"
    assert answer["model"] == "auto"
    assert answer["auto_model_allowlist"] == ["gpt-6-luna"]
    assert answer["model_selection_hints"] == {"gpt-6-luna": "lightweight tasks"}
    assert answer["iteration_timeout_seconds"] != 1
    assert await service.handle("models.agents.get", {}) == {k: v for k, v in answer.items()
                                                             if k != "status"}
    assert service.provider.tool_catalog.invalidations == 1


@pytest.mark.asyncio
async def test_agents_invalid_atomic_and_persist_failure(service):
    before = service.settings.config.model_dump()
    with pytest.raises(MethodError):
        await service.handle("models.agents.set", {"model": "gpt-6-luna", "thinking_mode": "bogus"})
    assert service.settings.config.model_dump() == before
    service.settings.fail = True
    with pytest.raises(MethodError):
        await service.handle("models.agents.set", {"model": "gpt-6-luna"})
    assert service.provider.tool_catalog.invalidations == 0
    assert service.settings.config.model_dump() == before


@pytest.mark.asyncio
async def test_personality_preset_lifecycle_and_route_shapes(service):
    assert await service.handle("personality.presets.save", {
        "name": "  Quiet Reader ", "display_name": "Reader", "voice": "quiet",
    }) == {"status": "saved", "name": "quiet_reader"}
    result = await service.handle("personality.get", {})
    assert result["presets"]["quiet_reader"] == {"name": "Reader", "identity": "", "voice": "quiet"}
    assert result["user_presets"] == ["quiet_reader"]
    assert "odin" in result["builtin_presets"]
    assert "quiet_reader" not in result["builtin_presets"]
    assert service.provider.prompt_builder.rebuilds == 0
    assert await service.handle("personality.set", {"preset": "quiet_reader"}) == {
        "status": "updated", "preset": "quiet_reader"}
    assert service.provider.prompt_builder.rebuilds == 1
    assert await service.handle("personality.presets.delete", {"name": "quiet_reader"}) == {
        "status": "deleted", "name": "quiet_reader"}
    assert service.settings.config.personality.preset == "odin"
    assert "quiet_reader" not in system_prompt._USER_PRESETS
    assert service.provider.prompt_builder.rebuilds == 2
    assert all(method == "settings.set" for method, changes in service.settings.writes)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,params", [
    ("personality.presets.save", {"name": "odin", "voice": "quiet"}),
    ("personality.presets.save", {"name": "punctuation?", "voice": "quiet"}),
    ("personality.presets.save", {"name": "blank"}),
    ("personality.presets.delete", {"name": "odin"}),
    ("personality.presets.delete", {"name": "absent"}),
])
async def test_personality_refuses_invalid_presets(service, method, params):
    with pytest.raises(MethodError):
        await service.handle(method, params)
    assert not service.settings.writes


@pytest.mark.asyncio
async def test_personality_failed_storage_does_not_publish(service):
    presets = dict(system_prompt._USER_PRESETS)
    service.settings.fail = True
    with pytest.raises(MethodError):
        await service.handle("personality.presets.save", {"name": "unsaved", "voice": "test"})
    assert system_prompt._USER_PRESETS == presets
    assert service.provider.prompt_builder.rebuilds == 0


@pytest.mark.asyncio
async def test_personality_custom_omitted_fields_reset_and_presets_are_copies(service):
    await service.handle("personality.set", {
        "preset": "custom", "custom_name": "Reader",
        "custom_identity": "test", "custom_voice": "quiet",
    })
    await service.handle("personality.set", {"preset": "odin"})
    result = await service.handle("personality.get", {})
    assert result["custom_name"] == result["custom_identity"] == result["custom_voice"] == ""
    result["presets"]["odin"]["voice"] = "changed response"
    fresh = await service.handle("personality.get", {})
    assert fresh["presets"]["odin"]["voice"] != "changed response"


@pytest.mark.asyncio
async def test_inventory_documentation_not_fake_readiness(service):
    result = await service.handle("tools.list", {})
    assert result["global_enabled"] is True
    assert result["disabled_count"] == 0
    rows = {t["name"]: t for t in result["tools"]}
    assert rows["run_command"]["input_schema"]["properties"]["command"]
    assert rows["computer_session"]["state"] == "unavailable"
    assert all(t["state"] == "unavailable" for t in result["tools"])
    policy = BuiltinToolPolicy(lambda: service.settings.config, lambda: {"run_command": True})
    service.executor = SimpleNamespace(_builtin_policy=policy)
    rows = {t["name"]: t for t in (await service.handle("tools.list", {}))["tools"]}
    assert rows["run_command"]["state"] == "available"
    assert rows["run_script"]["state"] == "unavailable"


@pytest.mark.asyncio
async def test_tool_toggle_preserves_unknowns_and_idempotence(service):
    service.settings.config.tools.disabled_tools = ["future_tool"]
    result = await service.handle("tools.set_enabled", {"name": "run_command", "enabled": False})
    assert result["disabled_count"] == 2
    assert service.settings.config.tools.disabled_tools == ["future_tool", "run_command"]
    assert next(t for t in result["tools"] if t["name"] == "run_command")["state"] == "disabled"
    await service.handle("tools.set_enabled", {"name": "run_command", "enabled": False})
    assert len(service.settings.writes) == 1
    await service.handle("tools.set_enabled", {"name": "run_command", "enabled": True})
    assert service.settings.config.tools.disabled_tools == ["future_tool"]
    assert service.provider.tool_catalog.invalidations == 2
    service.settings.config.tools.enabled = False
    rows = (await service.handle("tools.list", {}))["tools"]
    assert all(t["state"] == "global_disabled" for t in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [
    {"name": "unknown", "enabled": True}, {"name": "run_command", "enabled": 1},
    {"name": "run_command", "enabled": True, "other": True},
])
async def test_invalid_tool_switch_has_no_effect(service, params):
    with pytest.raises(MethodError):
        await service.handle("tools.set_enabled", params)
    assert not service.settings.writes


@pytest.mark.asyncio
async def test_timeout_shapes_partial_writes_and_stale_executor_reconciliation(service):
    executor_config = ToolsConfig()
    service.executor = SimpleNamespace(config=executor_config)
    params = {"default_timeout": 401, "overrides": {"run_command": 600}}
    assert await service.handle("tools.timeouts.set", params) == {
        "default_timeout": 401, "overrides": {"run_command": 600}}
    assert executor_config.command_timeout_seconds == 401
    assert executor_config.tool_timeouts == {"run_command": 600}
    executor_config.command_timeout_seconds = 20
    executor_config.tool_timeouts = {}
    await service.handle("tools.timeouts.set", params)
    assert len(service.settings.writes) == 1
    assert executor_config.command_timeout_seconds == 401
    assert executor_config.tool_timeouts == {"run_command": 600}
    result = await service.handle("tools.timeouts.set", {"overrides": {}})
    assert result == {"default_timeout": 401, "overrides": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [
    {"default_timeout": True}, {"default_timeout": 0}, {"default_timeout": "20"},
    {"overrides": []}, {"overrides": {"run_command": True}},
    {"overrides": {"run_command": 0}}, {"overrides": {"": 20}},
])
async def test_timeout_positive_strict_integer_rules(service, params):
    with pytest.raises(MethodError):
        await service.handle("tools.timeouts.set", params)
    assert not service.settings.writes


@pytest.mark.asyncio
async def test_timeout_storage_failure_preserves_executor(service):
    service.executor = SimpleNamespace(config=ToolsConfig())
    before = service.executor.config.model_dump()
    service.settings.fail = True
    with pytest.raises(MethodError):
        await service.handle("tools.timeouts.set", {"default_timeout": 601})
    assert service.executor.config.model_dump() == before


@pytest.mark.asyncio
async def test_revision_fence(service):
    with pytest.raises(MethodError) as error:
        await service.handle("models.agents.set", {"model": "auto", "expected_revision": "stale"})
    assert error.value.code == "stale_binding"
    assert not service.settings.writes


@pytest.mark.asyncio
async def test_discover_actual_endpoint_without_enabled_provider(service):
    seen = []

    async def models(request):
        seen.append((request.path, request.headers.get("Authorization")))
        return web.json_response({"data": [{"id": "local-model"}, {"id": 2}, {}]})

    async def tags(request):
        seen.append((request.path, request.headers.get("Authorization")))
        return web.json_response({"models": [{"name": "local:latest", "size": 123}]})

    app = web.Application()
    app.router.add_get("/v1/models", models)
    app.router.add_get("/api/tags", tags)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        service.settings.config.openai_compatible.enabled = False
        service.settings.config.ollama.enabled = False
        service.settings.config.openai_compatible.base_url = f"http://127.0.0.1:{port}/v1/"
        service.settings.config.ollama.base_url = f"http://127.0.0.1:{port}"
        result = await service.handle("models.discover", {"provider": "compat"})
        assert result == {
            "models": ["local-model"],
            "active_model": service.settings.config.openai_compatible.model,
        }
        assert await service.handle("models.discover", {"provider": "ollama"}) == {
            "models": [{"name": "local:latest", "size": 123}]}
        assert seen == [("/v1/models", "Bearer fixture-credential"), ("/api/tags", None)]
        assert not service.settings.writes
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [
    {"provider": "codex"}, {"provider": "compat", "base_url": "file:///fixture"},
    {"provider": "ollama", "base_url": "http://169.254.169.254"},
    {"provider": "ollama", "base_url": "http://8.8.8.8"},
])
async def test_discovery_retains_endpoint_validation(service, params):
    with pytest.raises(MethodError):
        await service.handle("models.discover", params)


@pytest.mark.asyncio
async def test_real_settings_persistence_personality_agents_and_inventory(tmp_path):
    from src.desktop.paths import ProfilePaths
    from src.desktop.settings import SettingsService

    paths = ProfilePaths.from_xdg("fixture", home=tmp_path, environ={})
    paths.create_private()
    paths.config_file.write_text("{}\n", encoding="utf-8")
    vault = SimpleNamespace(get=lambda path: None)
    settings = SettingsService(paths, vault, config=Config())
    service = ModelSettingsService(settings)
    saved_presets = dict(system_prompt._USER_PRESETS)
    try:
        revision = settings.revision
        await service.handle("models.agents.set", {
            "model": "auto", "auto_model_allowlist": ["gpt-6-luna"],
            "expected_revision": revision,
        })
        assert settings.revision != revision
        await service.handle("personality.presets.save", {"name": "fixture", "voice": "quiet"})
        await service.handle("personality.set", {"preset": "fixture"})
        await service.handle("tools.set_enabled", {"name": "run_command", "enabled": False})
        loaded = SettingsService(paths, vault)
        assert loaded.config.agents.model == "auto"
        assert loaded.config.personality.preset == "fixture"
        assert loaded.config.personality.user_presets["fixture"].voice == "quiet"
        assert loaded.config.tools.disabled_tools == ["run_command"]
    finally:
        system_prompt.register_user_presets(saved_presets)


@pytest.mark.asyncio
async def test_real_settings_timeouts_and_main_model(tmp_path):
    from src.desktop.paths import ProfilePaths
    from src.desktop.settings import SettingsService

    paths = ProfilePaths.from_xdg("fixture", home=tmp_path, environ={})
    paths.create_private()
    paths.config_file.write_text("{}\n", encoding="utf-8")
    vault = SimpleNamespace(get=lambda path: None)
    settings = SettingsService(paths, vault, config=Config())

    async def switch(provider, persist, *, model_ref):
        persist()
        return {"status": "switched"}

    service = ModelSettingsService(settings, provider=SimpleNamespace(switch_provider=switch))
    await service.handle("tools.timeouts.set", {
        "default_timeout": 451, "overrides": {"run_command": 651},
    })
    await service.handle("models.main.set", {"model": "ollama:fixture"})
    loaded = SettingsService(paths, vault)
    assert loaded.config.tools.command_timeout_seconds == 451
    assert loaded.config.tools.tool_timeouts == {"run_command": 651}
    assert loaded.config.llm_provider.model == "ollama:fixture"
    assert loaded.config.llm_provider.active_provider == "ollama"


@pytest.mark.asyncio
async def test_failed_post_persistence_cache_is_unknown_not_rejected(service):
    def fail_invalidation():
        raise ValueError("fixture cache adoption failed")

    service.provider.tool_catalog.invalidate = fail_invalidation
    with pytest.raises(MethodError) as error:
        await service.handle("models.agents.set", {"model": "auto"})
    assert error.value.code == "internal"
    assert error.value.disposition == "outcome_unknown"
    assert service.settings.config.agents.model == "auto"


@pytest.mark.asyncio
async def test_confirm_applied_only_after_actual_owner_success(service):
    adopted = []
    service.settings.confirm_applied = lambda changes: adopted.append(changes)
    await service.handle("models.agents.set", {"model": "auto"})
    assert adopted == [[(("agents", "model"), "auto")]]
    adopted.clear()
    service.executor = SimpleNamespace(config=ToolsConfig())
    await service.handle("tools.timeouts.set", {"default_timeout": 403})
    assert adopted == [[(("tools", "command_timeout_seconds"), 403)]]
    adopted.clear()
    service.provider = None
    await service.handle("personality.set", {"preset": "odin"})
    assert adopted == []


@pytest.mark.asyncio
async def test_discovery_vault_failure_never_calls_endpoint(service, monkeypatch):
    def locked(path):
        raise MethodError("capability_unavailable", "Temporary vault is locked")

    def unexpected_session(*args, **kwargs):
        pytest.fail("vault failure must not fall back to unauthenticated endpoint")

    service.settings.secrets.get = locked
    monkeypatch.setattr("src.desktop.model_settings.aiohttp.ClientSession", unexpected_session)
    with pytest.raises(MethodError) as error:
        await service.handle("models.discover", {"provider": "compat"})
    assert error.value.code == "capability_unavailable"


@pytest.mark.asyncio
async def test_discovery_http_failure_body_and_credentials_are_not_reflected(service):
    async def denied(request):
        return web.Response(status=401, text="fixture-credential denied body")

    app = web.Application()
    app.router.add_get("/models", denied)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        with pytest.raises(MethodError) as error:
            await service.handle("models.discover", {
                "provider": "compat", "base_url": f"http://127.0.0.1:{port}",
            })
        assert str(error.value) == "Invalid API key"
        assert service.settings.writes == []
    finally:
        await runner.cleanup()
