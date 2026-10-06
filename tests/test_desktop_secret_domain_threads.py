"""Actual domain keyring boundaries reject event-loop execution, no real vault."""
import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from src.config.schema import Config, OutboundWebhookTarget
from src.desktop.codex_accounts import CodexAccountsService
from src.desktop.integrations import IntegrationsService
from src.desktop.management import MethodError
from src.desktop.model_settings import ModelSettingsService
from src.desktop.providers import ProviderOwner


class WorkerSecrets:
    def __init__(self, **values):
        self.values = values
        self.calls = []
        self.loop_thread = threading.get_ident()

    def check(self, operation, name):
        assert threading.get_ident() != self.loop_thread
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        assert threading.current_thread().daemon
        self.calls.append((operation, name))

    def get(self, name):
        self.check("get", name)
        return self.values.get(name)

    def set(self, name, value):
        self.check("set", name)
        self.values[name] = value
        return True

    def clear(self, name):
        self.check("clear", name)
        self.values.pop(name, None)
        return True


def credential(**changes):
    return {"access_token": "fixture-access", "refresh_token": "fixture-refresh",
            "expires_at": 9999999999, "account_id": "fixture-account", **changes}


@pytest.mark.asyncio
async def test_codex_live_list_mutation_reload_and_lazy_restore_offloop():
    secrets = WorkerSecrets(codex_accounts=json.dumps([credential()]))
    service = CodexAccountsService(SimpleNamespace(secrets=secrets))
    assert (await service.handle("codex.accounts.list", {}))["account_count"] == 1
    pool = service.pool
    auth = pool.current
    await service.handle("codex.accounts.label", {"index": 0, "label": "primary"})
    await pool.reload_async()
    assert pool.current is auth
    await auth.invalidate_current()
    assert await pool.acquire() == ("fixture-access", "fixture-account", 0)
    await service.handle("codex.accounts.remove", {"index": 0})
    assert (await service.handle("codex.accounts.list", {}))["configured"] is False
    assert any(operation == "set" for operation, _ in secrets.calls)
    await service.close()


@pytest.mark.asyncio
async def test_codex_explicit_unlock_refresh_is_lazy_and_generation_fenced():
    secrets = WorkerSecrets(codex_accounts=json.dumps([credential()]))
    service = CodexAccountsService(SimpleNamespace(secrets=secrets))
    assert await service.refresh_pool_if_initialized() is None
    assert secrets.calls == []
    pool = await service.get_pool()
    auth = pool.current
    lock = auth._refresh_lock
    assert await service.refresh_pool_if_initialized() == 1
    assert pool.current is auth and pool.current._refresh_lock is lock
    secrets.values["codex_accounts"] = json.dumps([credential(access_token="changed-access")])
    assert await service.refresh_pool_if_initialized() == 1
    assert pool.current is not auth
    assert await pool.get_access_token() == "changed-access"
    await service.close()


@pytest.mark.asyncio
async def test_codex_retained_http_refresh_durable_save_offloop(monkeypatch):
    secrets = WorkerSecrets(codex_accounts=json.dumps([credential(expires_at=0)]))
    service = CodexAccountsService(SimpleNamespace(secrets=secrets))
    pool = await service.get_pool()

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def read(self):
            return json.dumps({"access_token": "rotated-access", "refresh_token": "rotated-refresh",
                               "expires_in": 3600}).encode()

    class Session(Response):
        def __init__(self, **kwargs):
            pass

        def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("src.llm.codex_auth.aiohttp.ClientSession", Session)
    assert await pool.get_access_token() == "rotated-access"
    saved = json.loads(secrets.values["codex_accounts"])[0]
    assert saved["refresh_token"] == "rotated-refresh"
    assert pool.current.expected["access_token"] == "rotated-access"
    await service.close()


@pytest.mark.asyncio
async def test_codex_cancelled_write_settles_before_pool_gate_released():
    entered, release = threading.Event(), threading.Event()

    class BlockingSecrets(WorkerSecrets):
        def set(self, name, value):
            entered.set()
            assert release.wait(5)
            return super().set(name, value)

    secrets = BlockingSecrets(codex_accounts=json.dumps([credential()]))
    service = CodexAccountsService(SimpleNamespace(secrets=secrets))
    await service.get_pool()
    mutation = asyncio.create_task(service.handle("codex.accounts.label", {
        "index": 0, "label": "settled",
    }))
    try:
        for _ in range(500):
            if entered.is_set():
                break
            await asyncio.sleep(.001)
        assert entered.is_set()
        mutation.cancel()
        await asyncio.sleep(.02)
        assert not mutation.done()
        assert service.pool._pool_lock.locked()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await mutation
    assert service.pool.current.expected["label"] == "settled"
    await service.close()


@pytest.mark.asyncio
async def test_provider_async_preparation_reads_secrets_offloop():
    config = Config()
    config.openai_codex.enabled = True
    config.openai_codex.auxiliary.enabled = False
    config.ollama.enabled = True
    config.openai_compatible.enabled = True
    secrets = WorkerSecrets(codex_accounts=json.dumps([credential()]))
    secrets.values["openai_compatible.api_key"] = "fixture-key"
    settings = SimpleNamespace(config=config, secrets=secrets)
    accounts = CodexAccountsService(settings)
    owner = ProviderOwner(settings, accounts)
    changes = [(("openai_codex", "enabled"), True), (("ollama", "enabled"), True),
               (("openai_compatible", "enabled"), True)]
    change = await owner.prepare_settings_async(config, changes)
    assert change.clients["codex"].auth is accounts.pool
    assert len(secrets.calls) == 3
    await change.rollback()
    change = await owner.prepare_reload_async(config, changes)
    await change.rollback()
    await owner.close()
    await accounts.close()


@pytest.mark.asyncio
async def test_integrations_restore_and_transaction_offloop():
    secrets = WorkerSecrets()
    config = Config()
    settings = SimpleNamespace(config=config, secrets=secrets, revision=0)

    def save_changes(changes, **kwargs):
        assert threading.get_ident() != secrets.loop_thread
        settings.config.outbound_webhooks.targets = [
            OutboundWebhookTarget(**row) for row in changes[0][1]
        ]
        settings.revision += 1

    settings.save_changes = save_changes
    service = IntegrationsService(settings)
    target = await service.handle("webhooks.outbound.save", {
        "url": "https://example.invalid/hook", "secret": "fixture-signing",
    })
    restored = IntegrationsService(settings)
    listed = await restored.handle("webhooks.outbound.list", {})
    assert listed["webhooks"][0]["has_secret"]
    await service.handle("webhooks.outbound.delete", {"id": target["id"]})
    assert secrets.values == {}


@pytest.mark.asyncio
async def test_integrations_failed_persistence_restores_vault_offloop():
    secrets = WorkerSecrets()
    config = Config()

    def fail(*args, **kwargs):
        assert threading.get_ident() != secrets.loop_thread
        raise RuntimeError("fixture persistence failure")

    settings = SimpleNamespace(config=config, secrets=secrets, revision=0, save_changes=fail)
    service = IntegrationsService(settings)
    with pytest.raises(MethodError):
        await service.handle("webhooks.outbound.save", {
            "url": "https://example.invalid/hook", "secret": "fixture-signing",
        })
    assert secrets.values == {}
    assert service.dispatcher.get_status()["webhook_count"] == 0
    assert secrets.calls[-1][0] == "clear"


@pytest.mark.asyncio
async def test_integrations_cancelled_write_settles_adoption_before_gate_release():
    entered, release = threading.Event(), threading.Event()

    class BlockingSecrets(WorkerSecrets):
        def set(self, name, value):
            entered.set()
            assert release.wait(5)
            return super().set(name, value)

    secrets = BlockingSecrets()
    config = Config()
    settings = SimpleNamespace(config=config, secrets=secrets, revision=0)

    def save_changes(changes, **kwargs):
        settings.config.outbound_webhooks.targets = [
            OutboundWebhookTarget(**row) for row in changes[0][1]
        ]
        settings.revision += 1

    settings.save_changes = save_changes
    service = IntegrationsService(settings)
    mutation = asyncio.create_task(service.handle("webhooks.outbound.save", {
        "url": "https://example.invalid/hook", "secret": "fixture-signing",
    }))
    try:
        for _ in range(500):
            if entered.is_set():
                break
            await asyncio.sleep(.001)
        assert entered.is_set()
        mutation.cancel()
        await asyncio.sleep(.02)
        assert not mutation.done()
        assert service._lock.locked()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await mutation
    assert service.dispatcher.get_status()["webhook_count"] == 1
    assert len(settings.config.outbound_webhooks.targets) == 1


@pytest.mark.asyncio
async def test_model_discovery_vault_read_offloop(monkeypatch):
    secrets = WorkerSecrets()
    settings = SimpleNamespace(config=Config(), secrets=secrets)
    service = ModelSettingsService(settings)

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def json(self):
            return {"data": [{"id": "fixture-model"}]}

    class Session(Response):
        def __init__(self, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("src.desktop.model_settings.aiohttp.ClientSession", Session)
    result = await service.handle("models.discover", {"provider": "compat"})
    assert result["models"] == ["fixture-model"]
    assert secrets.calls == [("get", "openai_compatible.api_key")]
