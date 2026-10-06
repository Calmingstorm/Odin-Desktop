"""Merged provider policies, settled credentials and core readiness, no live I/O."""

import asyncio
import os
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from src.config.schema import Config
from src.desktop.codex_accounts import CodexAccountsService
from src.desktop.core import CoreService, profile_config
from src.desktop.ipc import IpcServer
from src.desktop.providers import ProviderOwner
from src.llm import CodexChatClient
from src.llm.codex_quota_check import CodexQuotaCheckService
from tests.test_desktop_core_lifecycle import connect, profile
from tests.test_desktop_secret_domain_threads import WorkerSecrets, credential


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("round-3 regression tests cannot open network sessions")

    monkeypatch.setattr(aiohttp, "ClientSession", refuse)


@pytest.mark.parametrize(
    "prepare", ["prepare_settings", "prepare_settings_async", "prepare_reload",
                "prepare_reload_async"],
)
@pytest.mark.parametrize(
    "path,value",
    [("openai_codex.agent_model", "gpt-5.6-luna"),
     ("openai_codex.agent_reasoning_effort", "low"),
     ("openai_codex.connection_pool.max_connections", 12),
     ("openai_codex.connection_pool", {"max_connections": 12}),
     ("openai_codex.context_compression.keep_recent_iterations", 4)],
)
async def test_policy_preparation_retains_every_adopted_identity(monkeypatch, prepare, path, value):
    config = Config()
    settings = SimpleNamespace(config=config, secrets=WorkerSecrets())
    accounts = CodexAccountsService(settings)
    owner = ProviderOwner(settings, accounts)
    main, ollama, compat, auxiliary = object(), object(), object(), object()
    owner.codex_client, owner.ollama_client = main, ollama
    owner.compatible_client, owner.auxiliary_llm_client = compat, auxiliary
    owner.tool_catalog = SimpleNamespace(invalidate=Mock())
    candidate = config.model_copy(deep=True)
    candidate.openai_codex.agent_reasoning_effort = "low"

    def forbidden(*args, **kwargs):
        raise AssertionError("policy preparation must not traverse or rebuild providers")

    monkeypatch.setattr(owner, "_prepare_graph", forbidden)
    monkeypatch.setattr(owner, "_prepare_graph_async", forbidden)
    try:
        change = getattr(owner, prepare)(candidate, [(path, value)])
        if prepare.endswith("_async"):
            change = await change
        assert change.created == change.probes == []
        assert owner._generation == 0
        await change.apply()
        assert owner._generation == 1
        assert owner.codex is main and owner.ollama is ollama and owner.compat is compat
        assert owner.auxiliary is auxiliary
        assert owner.capture_serving_identity().client is main
        assert owner._effective_config is not candidate
        assert owner._effective_config.openai_codex.agent_reasoning_effort == "low"
        assert settings.secrets.calls == [] and accounts._pool is None
        owner.tool_catalog.invalidate.assert_called_once()
    finally:
        owner.codex_client = owner.ollama_client = owner.compatible_client = None
        owner.auxiliary_llm_client = None
        await owner.close()
        await accounts.close()


@pytest.mark.parametrize(
    "entry", ["settings", "reload", "ready", "codex", "ollama", "compat",
              "auxiliary", "switch"],
)
async def test_async_graph_entrypoints_prepare_main_and_aux_codex_offloop(monkeypatch, entry):
    import json

    config = Config()
    config.openai_codex.enabled = True
    config.openai_codex.auxiliary.enabled = True
    config.openai_codex.auxiliary.model = "gpt-6-luna"
    config.ollama.enabled = True
    config.openai_compatible.enabled = True
    secrets = WorkerSecrets(codex_accounts=json.dumps([credential()]))
    secrets.values["openai_compatible.api_key"] = "fixture-key"
    settings = SimpleNamespace(config=config, secrets=secrets, _async_lock=asyncio.Lock())
    accounts = CodexAccountsService(settings)
    owner = ProviderOwner(settings, accounts)
    pool = await accounts.get_pool()
    owner.codex_client = CodexChatClient(auth=pool, model=config.openai_codex.model)
    owner._probe_aux = AsyncMock(return_value=None)
    owner._probe_openai_compatible = AsyncMock(return_value=None)
    configured = pool.is_configured
    worker_checks, builds = [], []
    build = owner._build

    def checked():
        secrets.check("configured", "codex_accounts")
        worker_checks.append(threading.get_ident())
        return configured()

    def loop_build(provider, *args, **kwargs):
        assert threading.get_ident() == secrets.loop_thread
        assert asyncio.get_running_loop() is not None
        builds.append((provider, kwargs.get("auxiliary", False)))
        return build(provider, *args, **kwargs)

    monkeypatch.setattr(pool, "is_configured", checked)
    monkeypatch.setattr(owner, "_build", loop_build)
    change = None
    try:
        if entry in {"settings", "reload"}:
            prepare = getattr(owner, f"prepare_{entry}_async")
            change = await prepare(config, [("openai_codex.enabled", True)])
            await change.apply()
        elif entry == "ready":
            await owner.ensure_ready()
        elif entry == "switch":
            writes = []

            def persist():
                secrets.check("persist", "settings")
                writes.append(True)

            result = await owner.switch_provider("codex", persist=persist)
            assert "error" not in result
            assert writes == [True]
        else:
            method = "reload_openai_compatible" if entry == "compat" else f"reload_{entry}"
            await getattr(owner, method)()
        assert len(worker_checks) == 1
        assert ("codex", True) in builds
        assert owner.auxiliary.aux_client.auth is pool
        assert owner.auxiliary.primary_client is owner.main
        assert owner.auxiliary.aux_client is not owner.main
        if entry in {"settings", "reload", "codex", "switch"}:
            assert ("codex", False) in builds
            assert owner.codex.auth is pool
    finally:
        if change is not None:
            await change.rollback()
        await owner.close()
        await accounts.close()


async def test_cancelled_provider_credential_worker_settles_before_graph_build():
    entered, release = threading.Event(), threading.Event()

    class BlockingSecrets(WorkerSecrets):
        def get(self, name):
            entered.set()
            assert release.wait(5)
            return super().get(name)

    config = Config()
    config.openai_codex.enabled = False
    config.openai_codex.auxiliary.enabled = False
    config.ollama.enabled = True
    secrets = BlockingSecrets()
    settings = SimpleNamespace(config=config, secrets=secrets)
    accounts = CodexAccountsService(settings)
    owner = ProviderOwner(settings, accounts)
    owner._build = Mock(side_effect=AssertionError("cancelled preparation must not build"))
    task = asyncio.create_task(owner.prepare_settings_async(config, [("ollama.enabled", True)]))
    try:
        for _ in range(500):
            if entered.is_set():
                break
            await asyncio.sleep(.001)
        assert entered.is_set()
        task.cancel()
        await asyncio.sleep(.02)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert secrets.calls == [("get", "ollama.api_key")]
    owner._build.assert_not_called()
    assert owner._generation == 0
    await owner.close()
    await accounts.close()


async def test_core_initial_event_precedes_single_listener_and_quota_start(tmp_path, monkeypatch):
    class TemporaryKeyring:
        def get_password(self, namespace, name):
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()
            return None

    def config(paths):
        result = profile_config(paths)
        result.openai_codex.enabled = False
        return result

    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file, config_provider=config,
                       secret_backend=TemporaryKeyring())
    order = []
    server_start, quota_start = IpcServer.start, CodexQuotaCheckService.start

    async def admit(server):
        assert core.phase == "ready"
        assert int(core.events.high) > 0
        assert core._published_seq == int(core.events.high)
        assert core.management.codex_quota_check._task is None
        order.append("listener")
        await server_start(server)

    async def observe(service):
        assert order == ["listener"]
        order.append("quota")
        await quota_start(service)

    monkeypatch.setattr(IpcServer, "start", admit)
    monkeypatch.setattr(CodexQuotaCheckService, "start", observe)
    monkeypatch.setattr(CodexQuotaCheckService, "check_once", AsyncMock())
    writer = None
    try:
        await core.start(read_fd)
        assert order == ["listener", "quota"]
        quota = core.management.codex_quota_check
        assert quota._task is not None and not quota._task.done()
        _, writer, welcome = await connect(socket_path)
        assert welcome["event_high"] == str(core.events.high)
        assert core.settings is core.management.settings
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
    assert quota._closed and quota._task is None
