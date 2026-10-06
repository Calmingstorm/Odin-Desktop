"""Actual retained quota observer composition and runtime retirement boundaries."""
from types import SimpleNamespace

import pytest

from src.llm.codex_quota_check import CodexQuotaCheckService
from tests.desktop_adapters.step8_runtime_guard import temporary_guard_graph


@pytest.fixture(autouse=True)
def _no_external_quota_requests(monkeypatch):
    import aiohttp

    def refuse(*args, **kwargs):
        raise AssertionError("quota composition tests cannot use real network sessions")

    monkeypatch.setattr(aiohttp, "ClientSession", refuse)


def test_quota_owner_constructor_is_lazy_and_exactly_one_per_runtime(tmp_path, monkeypatch):
    constructions = []
    checks = []
    constructor = CodexQuotaCheckService.__init__

    def observe(self, *args, **kwargs):
        constructions.append(self)
        constructor(self, *args, **kwargs)

    async def check(self):
        checks.append(self)

    monkeypatch.setattr(CodexQuotaCheckService, "__init__", observe)
    monkeypatch.setattr(CodexQuotaCheckService, "check_once", check)
    with temporary_guard_graph(tmp_path, False) as (core, runner):
        manager = core.management
        service = manager.codex_quota_check
        assert constructions == [service]
        assert type(service) is CodexQuotaCheckService
        assert service._task is not None
        assert service._session is None
        runner.run(manager.start_background())
        runner.run(manager.start_background())
        assert checks == [service]
        assert not service._task.done()
        task = service._task
    assert task.done()
    assert service._closed
    assert service._task is None


def test_quota_lookup_tracks_current_generation_and_disabled_live_config(tmp_path):
    with temporary_guard_graph(tmp_path, False) as (core, _):
        manager = core.management
        check = manager.codex_quota_check
        assert check.get_pool() is None
        old_pool = object()
        replacement_pool = object()
        manager.providers.codex_client = SimpleNamespace(auth=old_pool)
        assert check.get_pool() is None
        manager.settings.config.openai_codex.enabled = True
        assert check.get_pool() is old_pool
        manager.providers.codex_client = SimpleNamespace(auth=replacement_pool)
        assert check.get_pool() is replacement_pool
        manager.settings.config.openai_codex.enabled = False
        assert check.get_pool() is None
        manager.providers.codex_client = None
        manager.settings.config.openai_codex.enabled = True
        assert check.get_pool() is None


def test_quota_observer_closes_before_serving_provider_generation(tmp_path, monkeypatch):
    order = []
    with temporary_guard_graph(tmp_path, False) as (core, runner):
        manager = core.management
        quota_close = manager.codex_quota_check.close
        provider_close = manager.providers.close

        async def close_quota():
            order.append("quota")
            await quota_close()

        async def close_providers():
            order.append("providers")
            await provider_close()

        monkeypatch.setattr(manager.codex_quota_check, "close", close_quota)
        monkeypatch.setattr(manager.providers, "close", close_providers)
        runner.run(core.close())
        assert order == ["quota", "providers"]
        assert manager.codex_quota_check._closed
