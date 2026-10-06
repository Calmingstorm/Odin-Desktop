"""Socket-free HTTP-shaped fixtures for the complete frozen observability corpus.

Only imports and the obsolete dummy Discord Config keyword are adapted. Every
route invokes a real desktop service. The settings persistence hook preserves
the legacy async persistence spy while the real profile settings owner validates,
writes a disposable profile and publishes the candidate. No production HTTP
registrars, algorithms, listening sockets or live paths are used.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import json as json_module
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qsl, urlsplit

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src.config import persistence
from src.config.schema import Config as DesktopConfig
from src.desktop import model_settings
from src.desktop import settings as settings_module
from src.desktop.management import MethodError
from src.desktop.model_settings import ModelSettingsService
from src.desktop.observability import ObservabilityService
from src.desktop.paths import ProfilePaths
from src.desktop.records import RecordsService
from src.desktop.settings import SettingsService
from src.tools.registry import get_documentation_tool_definitions

SUITES = {
    "test_web_api_observability": (
        "1765d74d7ec40651c9cf21c24033b2192e99db3517b2d603a09105c6fc916c4f"
    ),
    "test_campaign_prefix_measurement": (
        "7358e6be380f5210a689c000dfbce7cb344f87bf58743c09b728b2bb05e5fa5f"
    ),
}
CORPUS_SELECTIONS = {
    "test_web_api_observability": None,
    "test_campaign_prefix_measurement": None,
}
CORPUS_EXCLUSIONS = {}
CASE_MAP = {}
EVIDENCE = {}
SETUP_HUNKS = {}


def fixture_config(**kwargs):
    obsolete = kwargs.pop("discord", None)
    if obsolete is not None and (not isinstance(obsolete, dict)
                                 or set(obsolete) != {"token"}
                                 or not isinstance(obsolete["token"], str)):
        raise AssertionError("Unaudited Discord fixture")
    return DesktopConfig(**kwargs)


Config = fixture_config
get_tool_definitions = get_documentation_tool_definitions


class RouteTableDef(list):
    """Fixture route table carries named methods, never executable HTTP handlers."""


class _Router:
    def __init__(self):
        self.routes = []

    def add_routes(self, routes):
        self.routes.extend(routes)


class Application:
    def __init__(self):
        self.router = _Router()


web = SimpleNamespace(RouteTableDef=RouteTableDef, Application=Application)


def _register(routes, bot, mappings):
    routes.extend((verb, path, owner, method, bot) for verb, path, owner, method in mappings)


def register_tools_meta(routes, bot):
    _register(routes, bot, (
        ("GET", "/api/tools", "models", "tools.list"),
        ("GET", "/api/tools/builtins", "models", "tools.list"),
        ("POST", "/api/tools/builtins/{name}/enabled", "models", "tools.set_enabled"),
        ("GET", "/api/tools/timeouts", "models", "tools.timeouts.get"),
        ("PUT", "/api/tools/timeouts", "models", "tools.timeouts.set"),
        ("GET", "/api/tools/stats", "observability", "observability.tools"),
    ))


def register_bulkheads(routes, bot):
    _register(routes, bot, (
        ("GET", "/api/tools/bulkheads", "observability", "observability.bulkheads"),
    ))


def register_aggregates(routes, bot):
    _register(routes, bot, (
        ("GET", "/api/observability/context", "observability", "observability.context"),
        ("GET", "/api/observability/failures", "records", "audit.failures"),
        ("GET", "/api/usage/totals", "observability", "observability.usage_totals"),
    ))


def register_audit_log(routes, bot):
    _register(routes, bot, (
        ("GET", "/api/audit", "records", "audit.query"),
        ("GET", "/api/audit/diffs", "records", "audit.diffs"),
        ("GET", "/api/audit/verify", "records", "audit.verify"),
    ))


def register_log_search(routes, bot):
    _register(routes, bot, (
        ("GET", "/api/logs/search", "records", "logs.search"),
        ("GET", "/api/logs/stats", "records", "logs.stats"),
    ))


def register_risk_classification(routes, bot):
    _register(routes, bot, (
        ("GET", "/api/risk/stats", "observability", "observability.risk"),
        ("GET", "/api/risk/recent", "observability", "observability.risk_recent"),
        ("GET", "/api/governor/stats", "observability", "observability.governor"),
        ("GET", "/api/audit/risk", "observability", "observability.audit_risk"),
    ))


def register_recovery_stats(routes, bot):
    _register(routes, bot, (
        ("GET", "/api/recovery/stats", "observability", "recovery.stats"),
        ("GET", "/api/recovery/recent", "observability", "recovery.recent"),
    ))


def register_branch_freshness(routes, bot):
    _register(routes, bot, (
        ("GET", "/api/freshness/stats", "observability", "observability.freshness"),
        ("GET", "/api/freshness/recent", "observability", "observability.freshness_recent"),
    ))


def register_validation_stats(routes, bot):
    _register(routes, bot, (
        ("GET", "/api/validation/stats", "observability", "observability.validation"),
    ))


def register_affordances(routes, bot):
    _register(routes, bot, (
        ("GET", "/api/affordances", "observability", "observability.affordances"),
    ))


def register_compression_stats(routes, bot):
    _register(routes, bot, (
        ("GET", "/api/compression/stats", "observability", "observability.compression"),
    ))


def register_usage_cost(routes, bot):
    _register(routes, bot, (("GET", "/api/usage", "observability", "observability.usage"),))


def register_degradation(routes, bot):
    _register(routes, bot, (
        ("GET", "/api/subsystems/status", "observability", "observability.subsystems"),
    ))


class Response:
    def __init__(self, result, status=200):
        self.status = status
        # A real JSON boundary, including null/booleans and serialization failure.
        self._text = json_module.dumps(result, allow_nan=False)

    async def json(self):
        return json_module.loads(self._text)


class TestServer:
    __test__ = False

    def __init__(self, app):
        self.app = app


class TestClient:
    __test__ = False

    def __init__(self, server):
        self.app = server.app
        self.owners = {}
        self.calls = []

    async def __aenter__(self):
        self._temp = TemporaryDirectory(prefix="desktop-observability-http-")
        self.paths = ProfilePaths.from_xdg("fixture", home=Path(self._temp.name), environ={})
        self.paths.create_private()
        self.paths.config_file.write_text("{}\n", encoding="utf-8")
        return self

    async def __aexit__(self, *args):
        self._temp.cleanup()

    def _models(self, bot):
        key = id(bot)
        if key not in self.owners:
            settings = SettingsService(
                self.paths, SimpleNamespace(get=lambda _: None), config=bot.config,
            )
            executor = getattr(bot, "tool_executor", None)
            if executor is not None and isinstance(getattr(executor, "config", None), Mock):
                executor.config = bot.config.tools.model_copy(deep=True)
            # This is backend availability evidence supplied by the frozen fake,
            # not a reimplementation of inventory or enablement policy.
            hidden = bot.tool_catalog.backend_hidden_names()
            if not isinstance(hidden, (set, frozenset)):
                hidden = set()
            if executor is not None:
                executor._builtin_policy = SimpleNamespace(
                    is_available=lambda name: name not in hidden,
                )
            service = ModelSettingsService(settings, executor=executor, provider=bot)
            self.owners[key] = service
        return self.owners[key]

    async def _model_call(self, bot, method, params):
        service = self._models(bot)
        cancelled = False
        original_patch = settings_module._patch_config_paths

        def write(changes, *, path):
            nonlocal cancelled
            # AsyncMock's await arguments remain exactly those of the inherited
            # fixture. Only the persistence primitive is injected, never save,
            # validation, rollback, config publication or timeout reconciliation.
            hook = persistence.persist_config_paths_locked
            if not isinstance(hook, Mock):
                raise AssertionError("Frozen write fixture must inject its persistence hook")
            with ThreadPoolExecutor(max_workers=1) as pool:
                error, cancelled = pool.submit(lambda: asyncio.run(hook(changes))).result()
            if error is not None:
                raise error
            return original_patch(changes, path=path)

        with (
            patch.object(settings_module, "_patch_config_paths", write),
            patch.object(
                model_settings, "get_documentation_tool_definitions",
                lambda *_: get_tool_definitions(),
            ),
            patch.object(model_settings, "computer_definitions", lambda: []),
        ):
            try:
                result = await service.handle(method, params)
            finally:
                bot.config = service.settings.config
        return result, cancelled

    @staticmethod
    def _observability(bot):
        # Do not pass MagicMock as the lazy composition root: it manufactures
        # nonexistent owners. Only the actual supplied services node is exposed.
        services = getattr(bot, "services", None)
        graph = (
            SimpleNamespace(services=services) if isinstance(services, SimpleNamespace) else None
        )
        executor = getattr(bot, "tool_executor", None)
        if isinstance(executor, Mock):
            # MagicMock creates arbitrary children on getattr. Expose only the
            # six frozen configured counters, so missing composition owners
            # remain missing when the real service walks its graph.
            executor = SimpleNamespace(**{
                name: getattr(executor, name) for name in (
                    "risk_stats", "recovery_stats", "freshness_stats",
                    "command_governor", "validation_stats", "bulkheads",
                )
            })
        return ObservabilityService(
            executor=executor, audit=getattr(bot, "audit", None),
            compression_stats=getattr(bot, "compression_stats", None),
            config=getattr(bot, "config", None), usage_rollup=getattr(bot, "usage_rollup", None),
            subsystem_guard=getattr(bot, "subsystem_guard", None), graph=graph,
        )

    async def request(self, verb, url, *, json=None, data=None):
        parsed = urlsplit(url)
        params = dict(parse_qsl(parsed.query))
        for route_verb, path, owner, method, bot in self.app.router.routes:
            if route_verb != verb:
                continue
            name = None
            if "{name}" in path:
                prefix, suffix = path.split("{name}")
                if not parsed.path.startswith(prefix) or not parsed.path.endswith(suffix):
                    continue
                name = parsed.path[len(prefix):-len(suffix)]
                if not name or "/" in name:
                    continue
            elif parsed.path != path:
                continue
            if verb != "GET":
                if data is not None:
                    try:
                        params = json_module.loads(data)
                    except (ValueError, TypeError):
                        return Response({"error": "invalid JSON"}, 400)
                else:
                    params = json
                if not isinstance(params, dict):
                    return Response({"error": "expected JSON object"}, 400)
                params = dict(params)
                if name is not None:
                    params["name"] = name
            self.calls.append((owner, method, params))
            try:
                cancelled = False
                if owner == "models":
                    result, cancelled = await self._model_call(bot, method, params)
                    if parsed.path == "/api/tools":
                        result = result["tools"]
                elif owner == "records":
                    result = await RecordsService(self.paths, audit=bot.audit).handle(
                        method, params,
                    )
                else:
                    result = await self._observability(bot).handle(method, params)
                status = (
                    499 if cancelled
                    else 409 if method == "audit.verify" and result.get("valid") is False
                    else 200
                )
                return Response(result, status)
            except MethodError as exc:
                status = {
                    "bad_request": 400, "not_found": 404, "internal_error": 500,
                    "internal": 500, "unavailable": 503, "capability_unavailable": 503,
                }.get(exc.code, 500)
                result = {"error": exc.message}
                if exc.message == "usage history not enabled":
                    result = {"available": False, "reason": exc.message}
                return Response(result, status)
        return Response({"error": "not found"}, 404)

    async def get(self, url, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return await self.request("POST", url, **kwargs)

    async def put(self, url, **kwargs):
        return await self.request("PUT", url, **kwargs)


# The frozen ``from src.web.api import observability as obs`` remains a module
# shaped fixture boundary, not a production alias or sys.modules replacement.
# The module identity also preserves the original monkeypatch target exactly.
observability = sys.modules[__name__]


class SetupOnly(ast.NodeTransformer):
    def __init__(self):
        self.hunks = []

    def visit_Assert(self, node):
        return node

    def visit_ImportFrom(self, node):
        before = copy.deepcopy(node)
        if node.module in {"aiohttp", "aiohttp.test_utils", "src.config.schema",
                           "src.web.api", "src.web.api.observability"}:
            node.module = __name__
        if ast.dump(before) != ast.dump(node):
            self.hunks.append({"line": node.lineno, "before": ast.dump(before),
                               "after": ast.dump(node), "after_source": ast.unparse(node)})
        return node


def transformed_tree(stem):
    path = f"tests/{stem}.py"
    source = frozen_source(path)
    assert hashlib.sha256(source).hexdigest() == SUITES[stem]
    original = ast.parse(source, filename=path)
    transformer = SetupOnly()
    adapted = ast.fix_missing_locations(transformer.visit(copy.deepcopy(original)))
    assert corpus(original) == corpus(adapted)
    SETUP_HUNKS[stem] = transformer.hunks
    EVIDENCE[path] = {
        "source_sha256": hashlib.sha256(source).hexdigest(), "whole_suite": True,
        "full_corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "full_assert_parameter_ast_preserved_before_projection": True,
        "sealed_fixture_edits": transformer.hunks,
    }
    return adapted


def register_module(namespace, stem, tree, module):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            exported = f"TestStep5HTTP_{stem}_{node.name[4:]}"
            namespace[exported] = vars(module)[node.name]
            for child in node.body:
                if getattr(child, "name", "").startswith("test_"):
                    CASE_MAP[f"tests/{stem}.py::{node.name}::{child.name}"] = (
                        f"{exported}::{child.name}"
                    )
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ):
            exported = f"test_step5_http_{stem}_{node.name[5:]}"
            namespace[exported] = vars(module)[node.name]
            CASE_MAP[f"tests/{stem}.py::{node.name}"] = exported


def load(namespace):
    for stem in CORPUS_SELECTIONS:
        tree = transformed_tree(stem)
        module = ModuleType(f"desktop_step5_http_{stem}")
        module.__file__ = str(Path(__file__).parents[1] / f"{stem}.py")
        exec(compile(tree, module.__file__, "exec"), module.__dict__)
        register_module(namespace, stem, tree, module)
