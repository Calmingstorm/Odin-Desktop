"""Test-only HTTP spelling bridge calling real named Desktop services."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.audit.logger import AuditLogger
from src.desktop.codex_accounts import CodexAccountsService
from src.desktop.management import MethodError
from src.desktop.model_settings import ModelSettingsService
from src.desktop.openrouter_admin import OpenRouterAdminService
from src.desktop.paths import ProfilePaths
from src.desktop.providers import ProviderOwner
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from src.llm import CodexChatClient, OllamaClient, OpenAICompatibleClient
from src.usage.rollup import UsageRollup

ROOT = ContextVar("step5_llm_fixture_root")


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, namespace, name):
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        self.values[namespace, name] = value

    def delete_password(self, namespace, name):
        self.values.pop((namespace, name), None)


async def persist_config_paths_locked(changes):
    """Frozen fault injection probe, never the actual profile writer."""
    return None, False


class ConfigSectionRef:
    """Live section pointer across Desktop's validated Config publications.

    Upstream setup retained mutable section identity. Every explicit read/write
    here addresses real settings; no runtime behavior or attributes are invented.
    """
    def __init__(self, settings, name):
        object.__setattr__(self, "settings", settings)
        object.__setattr__(self, "name", name)

    def __getattr__(self, name):
        return getattr(getattr(self.settings.config, self.name), name)

    def __setattr__(self, name, value):
        setattr(getattr(self.settings.config, self.name), name, value)


class Fixture:
    def __init__(self, root):
        self.paths = ProfilePaths.from_xdg(home=root, environ={})
        self.paths.create_private()
        self.paths.config_file.write_text("{}\n")
        self.settings = SettingsService(self.paths, ProfileSecretStore(
            self.paths, backend=MemoryKeyring()))
        self.codex = CodexAccountsService(self.settings)
        self.llm_gateway = ProviderOwner(self.settings, self.codex)
        self.audit = AuditLogger(str(self.paths.data_dir / "audit.jsonl"))
        self.usage_rollup = UsageRollup(str(self.paths.data_dir / "usage"),
            trajectory_directory=str(self.paths.data_dir / "trajectories"),
            agent_trajectory_directory=str(self.paths.data_dir / "trajectories" / "agents"),
            audit=self.audit)
        self.openrouter = OpenRouterAdminService(
            self.settings, provider=self.llm_gateway, usage=self.usage_rollup)
        self.models = ModelSettingsService(self.settings, provider=self.llm_gateway)
        real_save = self.settings.save_changes

        def save(changes, **kwargs):
            # All frozen persist seams are no-await coroutines. Drain once,
            # before the real synchronous atomic profile publication.
            probe = persist_config_paths_locked(changes)
            try:
                probe.send(None)
            except StopIteration as settled:
                failure, cancelled = settled.value
            else:
                probe.close()
                raise AssertionError("fixture persistence probe unexpectedly yielded")
            if cancelled:
                raise asyncio.CancelledError
            if failure is not None:
                raise MethodError("internal_error", "Injected temporary persistence failure")
            return real_save(changes, **kwargs)

        self.settings.save_changes = save

    @property
    def config(self):
        return self.settings.config

    def section(self, name):
        return ConfigSectionRef(self.settings, name)

    def client(self, kind):
        if kind == "codex":
            return CodexChatClient(auth=self.codex.pool, model=self.config.openai_codex.model)
        if kind == "ollama":
            return OllamaClient(
                base_url=self.config.ollama.base_url, model=self.config.ollama.model)
        return OpenAICompatibleClient("fixture-key", model=self.config.openai_compatible.model,
                                      base_url=self.config.openai_compatible.base_url)


def register_openai_compatible_admin(*args):
    """Inert route-selection marker, not a production HTTP handler."""


def register_llm_provider(*args):
    """Inert route-selection marker."""


def _provider_client(models=None, healthy=True):
    client = OpenAICompatibleClient("fixture-key", model="m1", base_url="http://localhost:11434")
    client.health_check = AsyncMock(return_value={"healthy": healthy, "models": models or []})
    client.pool_stats = lambda: {"active": 1}
    return client


def _make_bot(tmp_path=None):
    return Fixture(tmp_path or ROOT.get())


def _app(*registrars, bot=None):
    bot = bot or _make_bot()
    app = web.Application()

    async def dispatch(request):
        path = request.path
        params = await request.json() if request.can_read_body else {}
        status = 200
        service = bot.openrouter
        if path == "/api/affordances":
            method, service = "tools.list", bot.models
        elif path == "/api/openrouter/catalogue":
            method = "openrouter.catalogue"
        elif path.startswith("/api/openrouter/models/"):
            model, _, operation = path.removeprefix("/api/openrouter/models/").rpartition("/")
            method = {"endpoints": "openrouter.endpoints", "select": "openrouter.select"}[operation]
            params = {**params, "model": model}
        elif path == "/api/openai-compatible/diagnostic":
            method = "providers.compat.diagnostic"
        elif path in ("/api/llm/status", "/api/llm/data"):
            method = "models.status"
        elif path == "/api/llm/active" and request.method == "GET":
            method = "models.provider.get"
        elif path in ("/api/llm/active", "/api/llm/switch"):
            method = "models.provider.set"
        elif path == "/api/llm/main-model":
            method, service = "models.main.set", bot.models
        else:
            raise AssertionError(f"Unmapped frozen route: {request.method} {path}")
        try:
            body = await service.handle(method, params)
        except MethodError as exc:
            status = {"bad_request": 400, "not_found": 404, "stale_binding": 409,
                      "unavailable": 503, "internal_error": 500}.get(exc.code, 500)
            body = {"error": str(exc)}
        else:
            if method == "tools.list":
                body = {"affordances": {row["name"]: {"cost": row["cost"], "risk": row["risk"]}
                                        for row in body["tools"]}}
            elif method == "providers.compat.diagnostic" and not body["health"].get("healthy"):
                status = 502
        return web.json_response(body, status=status)

    app.router.add_route("*", "/{path:.*}", dispatch)
    return app, bot


async def _client(bot):
    app, _ = _app(bot=bot)
    return TestClient(TestServer(app))
