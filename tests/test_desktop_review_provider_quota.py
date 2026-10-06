"""Whole frozen quota suite plus independent real Desktop keyring behavior.

Only keyring/network boundaries are doubles. Explicit standalone quota-check
construction below is laboratory evidence, not a claimed production binding.
"""
import json
from types import SimpleNamespace

import aiohttp
import pytest

from src.config.schema import Config
from src.desktop.codex_accounts import CodexAccountsService, KeyringCodexAuthPool
from src.desktop.management import ManagementService
from src.desktop.paths import ProfilePaths
from src.desktop.providers import ProviderOwner
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from src.llm.account_key import opaque_account_key
from src.llm.codex_quota_check import CodexQuotaCheckService
from tests.desktop_adapters import review_provider_quota as _frozen_quota_adapter
from tests.desktop_adapters.review_provider_quota import load


class TemporaryQuotaKeyring:
    def __init__(self):
        self.values = {}
        self.writes = 0

    def get_password(self, namespace, name):
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        self.writes += 1
        self.values[namespace, name] = value

    def delete_password(self, namespace, name):
        self.values.pop((namespace, name), None)


@pytest.fixture(autouse=True)
async def _frozen_quota_resources():
    resources = []
    token = _frozen_quota_adapter._resources.set(resources)
    try:
        yield
    finally:
        for resource in reversed(resources):
            if hasattr(resource, "_review_quota_original_records"):
                observed = resource.codex_accounts.vault.read()
                assert observed == resource._review_quota_original_records
            providers = getattr(resource, "providers", None)
            if providers is not None and isinstance(providers.codex_client, SimpleNamespace):
                # The inherited wiring probe installs transport-free auth
                # carriers; they are not provider lifecycle resources.
                providers.codex_client = None
            await resource.close()
        _frozen_quota_adapter._resources.reset(token)


@pytest.fixture
def quota_graph(tmp_path, monkeypatch):
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    paths.create_private()
    paths.config_file.write_text("{}\n")
    backend = TemporaryQuotaKeyring()
    secrets = ProfileSecretStore(paths, backend=backend)
    config = Config()
    config.openai_codex.auxiliary.enabled = False
    config.openai_codex.enabled = True
    settings = SettingsService(paths, secrets, config=config)
    secrets.set("codex_accounts", json.dumps([
        {"access_token": f"test-token-{i}", "refresh_token": f"test-refresh-{i}",
         "account_id": f"test-quota-{i}", "expires_at": 4102444800}
        for i in range(2)
    ]))
    accounts = CodexAccountsService(settings)
    providers = ProviderOwner(settings, accounts)

    def blocked(*args, **kwargs):
        raise AssertionError("No real network in independent quota tests")

    monkeypatch.setattr(aiohttp, "ClientSession", blocked)
    return settings, accounts, providers, backend


class QuotaHeaderResponse:
    status = 200
    headers = {"x-codex-primary-used-percent": "25", "x-codex-primary-window-minutes": "300"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class QuotaHeaderSession:
    closed = False

    def __init__(self):
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return QuotaHeaderResponse()

    async def close(self):
        self.closed = True


async def test_quota_real_command_owner_projects_measured_headers_without_keyring_writes(
    quota_graph,
):
    _, accounts, providers, backend = quota_graph
    pool = accounts.pool
    pool.quota.record_headers(opaque_account_key("test-quota-0"), QuotaHeaderResponse.headers)
    before, writes = dict(backend.values), backend.writes
    manager = ManagementService(SimpleNamespace(), services=[accounts], identity_key=b"q" * 32)
    try:
        result = await manager.invoke("codex.accounts.list", {})
        assert result["ok"] is True
        rows = result["result"]["accounts"]
        assert rows[0]["quota"]["primary"]["used_percent"] == 25
        assert rows[0]["quota"]["primary"]["window_minutes"] == 300
        assert rows[1]["quota"] is None
        assert "test-token" not in json.dumps(result)
        assert "test-refresh" not in json.dumps(result)
        assert backend.values == before and backend.writes == writes
    finally:
        await providers.close()
        await accounts.close()


async def test_quota_standalone_checker_consumes_real_keyring_pool_without_rotation(
    quota_graph, monkeypatch,
):
    _, accounts, providers, backend = quota_graph
    pool = accounts.pool
    session = QuotaHeaderSession()
    monkeypatch.setattr(aiohttp, "ClientSession", lambda **kwargs: session)
    service = CodexQuotaCheckService(lambda: accounts.pool)
    before, writes, current = dict(backend.values), backend.writes, pool._current_index
    try:
        await service.check_once()
        assert len(session.calls) == 2
        assert [call[1]["headers"]["Authorization"] for call in session.calls] == [
            "Bearer test-token-0", "Bearer test-token-1",
        ]
        assert all(call[1]["headers"]["Accept-Encoding"] == "identity" for call in session.calls)
        snap = pool.quota.snapshot_for(opaque_account_key("test-quota-0"))
        assert snap.primary.used_percent == 25
        assert pool.quota_check_failure(0) is None
        assert pool._current_index == current
        assert backend.values == before and backend.writes == writes
        await service.check_once()
        assert len(session.calls) == 2  # Fresh snapshots are not re-requested.
    finally:
        await service.close()
        await providers.close()
        await accounts.close()


async def test_quota_standalone_generation_fence_rejects_retired_real_pool(
    quota_graph, monkeypatch,
):
    _, accounts, providers, backend = quota_graph
    old = accounts.pool
    new = KeyringCodexAuthPool(accounts.vault)
    session = QuotaHeaderSession()
    monkeypatch.setattr(aiohttp, "ClientSession", lambda **kwargs: session)
    service = CodexQuotaCheckService(lambda: accounts.pool)
    before = dict(backend.values)
    original = old.token_for

    async def rotate(index):
        token = await original(index)
        accounts._pool = new
        return token

    monkeypatch.setattr(old, "token_for", rotate)
    try:
        await service.check_once()
        assert session.calls == []
        assert old.quota.snapshot_for(opaque_account_key("test-quota-0")) is None
        await service.check_once()
        assert len(session.calls) == 2
        assert new.quota.snapshot_for(opaque_account_key("test-quota-0")) is not None
        assert old.quota.snapshot_for(opaque_account_key("test-quota-0")) is None
        assert backend.values == before
    finally:
        await service.close()
        await providers.close()
        await accounts.close()


async def test_quota_provider_reload_observes_shared_auth_pool_not_inherited_new_pool(quota_graph):
    settings, accounts, providers, backend = quota_graph
    before = dict(backend.values)
    try:
        await providers.reload_codex()
        original_client = providers.codex_client
        original_pool = original_client.auth
        settings.config.openai_codex.enabled = False
        await providers.reload_codex()
        assert providers.codex_client is None
        settings.config.openai_codex.enabled = True
        await providers.reload_codex()
        assert providers.codex_client is not original_client
        assert providers.codex_client.auth is original_pool
        assert providers.codex_client.auth is accounts.pool
        assert backend.values == before
    finally:
        await providers.close()
        await accounts.close()


_WHOLE_QUOTA_EXPORTS = load(globals())
