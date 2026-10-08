"""Real retained transports, throwaway profile/keyring and fake network only."""

import asyncio
import json

import aiohttp
import pytest
import yaml

from src.config.schema import Config
from src.desktop.codex_accounts import CodexAccountsService
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.providers import ProviderOwner
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from src.llm import CodexChatClient, OllamaClient, OpenAICompatibleClient
from src.llm.errors import LLMClientRetiredError


class TemporaryKeyring:
    def __init__(self):
        self.values = {}
        self.locked = False
        self.reads = 0

    def get_password(self, namespace, name):
        self.reads += 1
        if self.locked:
            raise RuntimeError("temporary keyring locked")
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        if self.locked:
            raise RuntimeError("temporary keyring locked")
        self.values[namespace, name] = value

    def delete_password(self, namespace, name):
        self.values.pop((namespace, name), None)


@pytest.fixture
def graph(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    paths.create_private()
    paths.config_file.write_text("{}\n")
    keyring = TemporaryKeyring()
    secrets = ProfileSecretStore(paths, backend=keyring)
    config = Config()
    config.openai_codex.auxiliary.enabled = False
    settings = SettingsService(paths, secrets, config=config)
    accounts = CodexAccountsService(settings)
    owner = ProviderOwner(settings, accounts)
    settings.owners.update(dict.fromkeys(owner.METHODS, owner))
    return settings, accounts, owner, keyring


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Provider tests must not open a network session")

    monkeypatch.setattr(aiohttp, "ClientSession", blocked)


async def save(settings, method, *changes):
    return await settings.handle(
        method,
        {
            "expected_revision": settings.revision,
            "changes": [{"path": p, "value": v} for p, v in changes],
        },
    )


def credentials(settings):
    settings.secrets.set(
        "codex_accounts",
        json.dumps(
            [
                {
                    "access_token": "isolated-placeholder",
                    "account_id": "temporary-account",
                    "refresh_token": "isolated-refresh-placeholder",
                    "expires_at": 4102444800,
                }
            ]
        ),
    )


@pytest.fixture
def fake_network(monkeypatch):
    calls = []

    async def healthy(self):
        calls.append(("catalogue", self))
        return {"healthy": True}

    async def chat(self, messages, system, **kwargs):
        calls.append(("chat", self, kwargs))
        self._last_stream_usage_received = True
        return "accepted"

    monkeypatch.setattr(OpenAICompatibleClient, "health_check", healthy)
    monkeypatch.setattr(OpenAICompatibleClient, "chat", chat)
    monkeypatch.setattr(CodexChatClient, "chat", chat)
    monkeypatch.setattr(OllamaClient, "chat", chat)
    return calls


def test_construction_never_unlocks_or_connects(graph, monkeypatch):
    settings, accounts, owner, keyring = graph
    assert keyring.reads == 0
    assert accounts._pool is None
    assert owner.main is owner.codex is owner.compat is owner.ollama is None
    assert owner.capture_serving_identity().client is None
    assert not list(settings.paths.secrets_dir.iterdir())


@pytest.mark.asyncio
async def test_ollama_settings_adopts_actual_retained_client(graph):
    settings, _, owner, _ = graph
    await save(
        settings,
        "providers.ollama.set",
        ("ollama.enabled", True),
        ("ollama.num_ctx", 65536),
        ("ollama.timeout", 44),
    )
    assert isinstance(owner.ollama, OllamaClient)
    assert owner.ollama.num_ctx == 65536
    assert owner.ollama.timeout == 44
    assert owner.ollama._session is None
    assert owner.main is None  # configured backend is not an implicit switch
    await owner.close()


@pytest.mark.asyncio
async def test_codex_reuses_keyring_pool_and_real_client(graph):
    settings, accounts, owner, _ = graph
    credentials(settings)
    await save(
        settings,
        "providers.codex.set",
        ("openai_codex.enabled", True),
        ("openai_codex.request_timeout_seconds", 240),
        ("openai_codex.connection_pool.max_connections", 6),
    )
    assert isinstance(owner.codex, CodexChatClient)
    assert owner.codex.auth is accounts.pool
    assert owner.main is owner.codex
    assert owner.codex.request_timeout == 240
    assert owner.codex.pool_max_connections == 6
    assert owner.codex._session is None
    await owner.close()


@pytest.mark.asyncio
async def test_locked_keyring_has_no_fallback(graph):
    settings, accounts, owner, keyring = graph
    keyring.locked = True
    with pytest.raises(MethodError) as error:
        await save(settings, "providers.codex.set", ("openai_codex.enabled", True))
    assert error.value.code == "unavailable"
    assert owner.codex is None
    assert accounts._pool is None
    assert settings.paths.config_file.read_text() == "{}\n"
    assert not list(settings.paths.secrets_dir.iterdir())


@pytest.mark.asyncio
async def test_unconfigured_switch_does_not_persist_or_publish(graph):
    _, _, owner, _ = graph
    writes = []
    result = await owner.switch_provider("codex", persist=lambda: writes.append(True))
    assert "error" in result
    assert writes == []
    assert owner.main is None
    await owner.close()


@pytest.mark.asyncio
async def test_main_switch_preserves_revision_until_real_persist(graph):
    settings, _, owner, _ = graph
    await save(settings, "providers.ollama.set", ("ollama.enabled", True))
    revision = settings.revision
    before = owner.capture_serving_identity()

    def persist():
        assert settings.revision == revision
        assert owner.capture_serving_identity() == before
        settings.save_changes(
            [
                (("llm_provider", "model"), "ollama:temporary-model"),
                (("llm_provider", "active_provider"), "ollama"),
            ],
            method="models.main.set",
            expected_revision=revision,
        )

    result = await owner.switch_provider(
        "ollama", persist=persist, model_ref="ollama:temporary-model"
    )
    assert result == {"provider": "ollama", "model": "temporary-model"}
    assert owner.main is owner.ollama
    assert owner.main.model == "temporary-model"
    assert settings.config.llm_provider.model == "ollama:temporary-model"
    await owner.close()


@pytest.mark.asyncio
async def test_main_pair_uses_real_owner_and_one_persistence_revision(graph):
    from src.desktop.model_settings import ModelSettingsService

    settings, _, owner, _ = graph
    credentials(settings)
    await save(settings, "providers.codex.set", ("openai_codex.enabled", True))
    old = owner.capture_serving_identity()
    revision = settings.revision
    service = ModelSettingsService(settings, provider=owner)
    answer = await service.handle("models.main.set", {
        "model": "codex:gpt-6.1-sol", "reasoning_effort": "high", "expected_revision": revision,
    })
    assert answer["main_model"] == "codex:gpt-6.1-sol"
    assert settings.revision != revision
    assert settings.config.openai_codex.reasoning_effort == "high"
    assert owner._effective_config.openai_codex.reasoning_effort == "high"
    assert owner.capture_serving_identity() != old
    stored = yaml.safe_load(settings.paths.config_file.read_text())
    assert stored["llm_provider"]["model"] == "codex:gpt-6.1-sol"
    assert stored["openai_codex"]["reasoning_effort"] == "high"
    await owner.close()


@pytest.mark.asyncio
async def test_main_pair_stale_revision_keeps_real_owner_and_effort(graph):
    from src.desktop.model_settings import ModelSettingsService

    settings, _, owner, _ = graph
    credentials(settings)
    await save(settings, "providers.codex.set", ("openai_codex.enabled", True))
    before = owner.capture_serving_identity()
    effort = settings.config.openai_codex.reasoning_effort
    contents = settings.paths.config_file.read_text()
    with pytest.raises(MethodError) as error:
        await ModelSettingsService(settings, provider=owner).handle("models.main.set", {
            "model": "codex:gpt-6.1-sol", "reasoning_effort": "high", "expected_revision": "stale",
        })
    assert error.value.code == "stale_binding"
    assert owner.capture_serving_identity() == before
    assert settings.config.openai_codex.reasoning_effort == effort
    assert owner._effective_config.openai_codex.reasoning_effort == effort
    assert settings.paths.config_file.read_text() == contents
    await owner.close()


@pytest.mark.asyncio
async def test_persist_failure_restores_exact_live_identity(graph):
    settings, _, owner, _ = graph
    await save(settings, "providers.ollama.set", ("ollama.enabled", True))
    old = owner.ollama
    before = owner.capture_serving_identity()

    def failed():
        raise OSError("isolated failure")

    assert "error" in await owner.switch_provider("ollama", persist=failed)
    assert owner.ollama is old
    assert owner.capture_serving_identity() == before
    assert not getattr(old, "_generation_retired", False)
    await owner.close()


@pytest.mark.asyncio
async def test_compatible_qualifies_retained_client_before_publication(graph, fake_network):
    settings, _, owner, _ = graph
    await settings.handle(
        "secrets.set", {"path": "openai_compatible.api_key", "value": "temporary-key"}
    )
    await save(
        settings,
        "providers.compat.set",
        ("openai_compatible.enabled", True),
        ("openai_compatible.base_url", "https://temporary.invalid/v1"),
    )
    assert isinstance(owner.compat, OpenAICompatibleClient)
    assert owner.compat.api_key == "temporary-key"
    assert owner.compat.base_url == "https://temporary.invalid/v1"
    assert [row[0] for row in fake_network] == ["catalogue", "chat"]
    assert all(row[1] is owner.compat for row in fake_network)
    await owner.close()


@pytest.mark.asyncio
async def test_compatible_probe_failure_rolls_back_disk_and_closes_candidate(
    graph, fake_network, monkeypatch
):
    settings, _, owner, _ = graph
    await settings.handle(
        "secrets.set", {"path": "openai_compatible.api_key", "value": "temporary-key"}
    )
    before = settings.paths.config_file.read_text()
    closed = []

    async def unhealthy(self):
        return {"healthy": False, "error": "isolated refusal"}

    async def close(self):
        closed.append(self)

    monkeypatch.setattr(OpenAICompatibleClient, "health_check", unhealthy)
    monkeypatch.setattr(OpenAICompatibleClient, "close", close)
    with pytest.raises(MethodError):
        await save(settings, "providers.compat.set", ("openai_compatible.enabled", True))
    assert owner.compat is None
    assert settings.config.openai_compatible.enabled is False
    assert settings.paths.config_file.read_text() == before
    assert len(closed) == 1 and isinstance(closed[0], OpenAICompatibleClient)


@pytest.mark.asyncio
async def test_secret_rotation_applies_new_key_not_previous(graph, fake_network):
    settings, _, owner, _ = graph
    await settings.handle(
        "secrets.set", {"path": "openai_compatible.api_key", "value": "previous-temporary"}
    )
    await save(settings, "providers.compat.set", ("openai_compatible.enabled", True))
    old = owner.compat
    await settings.handle(
        "secrets.set", {"path": "openai_compatible.api_key", "value": "next-temporary"}
    )
    assert owner.compat is not old
    assert owner.compat.api_key == "next-temporary"
    assert settings.secrets.get("openai_compatible.api_key") == "next-temporary"
    assert getattr(old, "_generation_retired")
    await owner.close()


@pytest.mark.asyncio
async def test_retired_client_waits_for_real_generation_lease(graph, monkeypatch):
    settings, _, owner, _ = graph
    await save(settings, "providers.ollama.set", ("ollama.enabled", True))
    old = owner.ollama
    closed = asyncio.Event()

    async def close(self):
        if self is old:
            closed.set()

    monkeypatch.setattr(OllamaClient, "close", close)
    async with old.generation_lease():
        await save(settings, "providers.ollama.set", ("ollama.timeout", 55))
        await asyncio.sleep(0)
        assert owner.ollama is not old
        assert old._generation_retired
        assert not closed.is_set()
    await asyncio.wait_for(closed.wait(), 1)
    with pytest.raises(LLMClientRetiredError):
        async with old.generation_lease():
            pass
    await owner.close()


@pytest.mark.asyncio
async def test_auxiliary_real_wrapper_shared_auth_and_fallback(graph, fake_network):
    settings, accounts, owner, _ = graph
    credentials(settings)
    await save(settings, "providers.codex.set", ("openai_codex.enabled", True))
    await save(
        settings,
        "providers.auxiliary.set",
        ("openai_codex.auxiliary.enabled", True),
        ("openai_codex.auxiliary.model", "gpt-6-luna"),
    )
    assert owner.auxiliary.aux_client.auth is accounts.pool
    assert owner.auxiliary.primary_client is owner.main
    assert owner.auxiliary.aux_client is not owner.main
    assert owner.auxiliary.aux_client.reasoning_effort is None
    assert await owner.auxiliary.chat([], "", task="compaction") == "accepted"
    assert fake_network[-1][1] is owner.auxiliary.aux_client
    old = owner.auxiliary
    await save(settings, "providers.auxiliary.set", ("openai_codex.auxiliary.enabled", False))
    assert owner.auxiliary is None
    assert old is not owner.auxiliary
    await owner.close()


@pytest.mark.asyncio
async def test_stale_prepared_graph_cannot_replace_new_generation(graph):
    settings, _, owner, _ = graph
    config = settings.config.model_copy(deep=True)
    config.ollama.enabled = True
    stale = owner.prepare_settings(config, [(("ollama", "enabled"), True)])
    await save(settings, "providers.ollama.set", ("ollama.enabled", True), ("ollama.timeout", 66))
    current = owner.ollama
    with pytest.raises(MethodError):
        await stale.apply()
    assert owner.ollama is current
    assert owner.ollama.timeout == 66
    await owner.close()


@pytest.mark.asyncio
async def test_closed_owner_refuses_new_admission(graph):
    _, _, owner, _ = graph
    await owner.close()
    with pytest.raises(MethodError):
        await owner.ensure_ready()


@pytest.mark.asyncio
async def test_default_auxiliary_intent_does_not_block_configuring_inactive_backend(graph):
    settings, _, owner, _ = graph
    settings.config.openai_codex.auxiliary.enabled = True
    await save(settings, "providers.ollama.set", ("ollama.enabled", True))
    assert isinstance(owner.ollama, OllamaClient)
    assert owner.auxiliary is None
    await owner.close()


@pytest.mark.asyncio
async def test_secret_clear_retires_compatible_not_restores_deleted_key(graph, fake_network):
    settings, _, owner, _ = graph
    await settings.handle(
        "secrets.set", {"path": "openai_compatible.api_key", "value": "temporary-key"}
    )
    await save(settings, "providers.compat.set", ("openai_compatible.enabled", True))
    old = owner.compat
    await settings.handle("secrets.clear", {"path": "openai_compatible.api_key"})
    assert owner.compat is None
    assert settings.secrets.get("openai_compatible.api_key") is None
    assert old._generation_retired
    await owner.close()


@pytest.mark.asyncio
async def test_explicit_codex_reload_cannot_use_credentials_path(graph):
    settings, accounts, owner, _ = graph
    credentials(settings)
    settings.config.openai_codex.enabled = True
    settings.config.openai_codex.credentials_path = "/invalid-unused-profile-credential-path"
    assert (await owner.reload_codex())["configured"]
    assert owner.codex.auth is accounts.pool
    assert owner.codex._session is None
    await owner.close()


@pytest.mark.asyncio
async def test_direct_policy_reads_follow_settings_without_changing_effective_identity(graph):
    settings, _, owner, _ = graph
    settings.config.agents.max_iterations = 17
    assert owner.get_config().agents.max_iterations == 17
    assert owner.capture_serving_identity().client is None
    await owner.close()


@pytest.mark.asyncio
async def test_cancellation_during_persist_settles_then_publishes(graph):
    import threading

    settings, _, owner, _ = graph
    await save(settings, "providers.ollama.set", ("ollama.enabled", True))
    started, release = threading.Event(), threading.Event()

    def persist():
        started.set()
        assert release.wait(2)
        settings.save_changes(
            [
                (("llm_provider", "model"), "ollama:cancel-model"),
                (("llm_provider", "active_provider"), "ollama"),
            ],
            method="models.main.set",
        )

    task = asyncio.create_task(
        owner.switch_provider("ollama", persist=persist, model_ref="ollama:cancel-model")
    )
    for _ in range(100):
        if started.is_set():
            break
        await asyncio.sleep(0.005)
    assert started.is_set()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert settings.config.llm_provider.model == "ollama:cancel-model"
    assert owner.main is owner.ollama
    assert owner.capture_serving_identity().model == "cancel-model"
    await owner.close()


@pytest.mark.asyncio
async def test_settings_apply_and_switch_use_same_transaction_order(graph):
    settings, _, owner, _ = graph
    await save(settings, "providers.ollama.set", ("ollama.enabled", True))
    applying = asyncio.create_task(save(settings, "providers.ollama.set", ("ollama.timeout", 77)))
    switching = asyncio.create_task(owner.switch_provider("ollama"))
    results = await asyncio.wait_for(asyncio.gather(applying, switching), 2)
    assert results[1]["provider"] == "ollama"
    assert owner.ollama.timeout == 77
    await owner.close()


@pytest.mark.asyncio
async def test_reload_prepare_main_and_backends_publish_single_generation(graph, fake_network):
    settings, _, owner, _ = graph
    before = owner.capture_serving_identity()
    candidate = settings.config.model_copy(deep=True)
    candidate.ollama.enabled = True
    candidate.llm_provider.model = "ollama:reload-model"
    candidate.llm_provider.active_provider = "ollama"
    token = owner.prepare_reload(
        candidate,
        [(("ollama", "enabled"), True), (("llm_provider", "model"), "ollama:reload-model")],
    )
    assert owner.capture_serving_identity() == before
    async with owner.provider_lock:
        await token.qualify()
        assert owner.main is None
        token.publish()
    assert owner.main is owner.ollama
    assert owner.capture_serving_identity().model == "reload-model"
    await owner.close()


@pytest.mark.asyncio
async def test_reload_prepare_failure_preserves_all_old_clients(graph, fake_network, monkeypatch):
    settings, _, owner, _ = graph
    await save(settings, "providers.ollama.set", ("ollama.enabled", True))
    original = owner.ollama
    candidate = settings.config.model_copy(deep=True)
    candidate.ollama.timeout = 77
    candidate.openai_compatible.enabled = True
    candidate.openai_compatible.api_key = "reload-temporary-key"
    token = owner.prepare_reload(
        candidate,
        [
            (("ollama", "timeout"), 77),
            (("openai_compatible", "enabled"), True),
            (("openai_compatible", "api_key"), "reload-temporary-key"),
        ],
    )

    async def refuse(self):
        return {"healthy": False}

    monkeypatch.setattr(OpenAICompatibleClient, "health_check", refuse)
    with pytest.raises(MethodError):
        await token.qualify()
    await token.rollback()
    assert owner.ollama is original
    assert owner.compat is None
    assert not getattr(original, "_generation_retired", False)
    await owner.close()


@pytest.mark.asyncio
async def test_removing_last_account_reload_retires_codex_generation(graph):
    settings, accounts, owner, _ = graph
    credentials(settings)
    settings.config.openai_codex.enabled = True
    await owner.reload_codex()
    old = owner.codex
    settings.secrets.set("codex_accounts", "[]")
    accounts.pool.reload()
    assert not accounts.pool.is_configured()
    result = await owner.reload_codex()
    assert result["configured"] is False
    assert owner.codex is owner.main is None
    assert old._generation_retired
    await owner.close()
