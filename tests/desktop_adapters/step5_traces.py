"""Whole frozen trajectory/Codex suites against named Desktop methods.

Only transport imports/constructors are adapted. The Codex regression corpus
keeps its synthetic canonical/shadow files to qualify the retained file owner;
production Desktop persistence remains exclusively keyring-backed. No sockets.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from aiohttp import web

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source
from src.desktop.codex_accounts import CodexAccountsService, _Login
from src.desktop.management import MethodError
from src.desktop.trajectories import TrajectoriesService
from src.llm import codex_auth as ca
from src.trajectories.saver import TrajectoryTurn as EngineTrajectoryTurn

EVIDENCE = {}
CASE_MAP = {}
CORPUS_SELECTIONS = {
    "test_trajectories": None,
    "test_webui_selected_trace_filters": None,
    "test_codex_account_mutation_regressions": None,
}
CORPUS_EXCLUSIONS = {}
SUITES = {
    "test_trajectories": "24d4529b88240c5a4e875545bbe16fc9413cbc5131791e9b2d919bdf3a3b1d08",
    "test_webui_selected_trace_filters":
        "1debb7f9aa4dd9e610f149b4611fc7e36c67c1a885b49b0151d26016b486babc",
    "test_codex_account_mutation_regressions":
        "3675f61a8df4d3f7824a0911f47a960302449d78a71a16801fb5a41198384132",
}

# Historical transport defaults are inert serialization fixture inputs. The
# retained implementation and production Desktop defaults are not changed.
DEFAULT_TRAJECTORY_DIR = "./data/trajectories"


class TrajectoryTurn(EngineTrajectoryTurn):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("source", "discord")
        super().__init__(*args, **kwargs)


def _response(data, status=200):
    return web.json_response(data, status=status)


async def _invoke(service, method, params):
    try:
        return _response(await service.handle(method, params))
    except MethodError as exc:
        status = {"bad_request": 400, "not_found": 404,
                  "capability_unavailable": 503}.get(exc.code, 500)
        return _response({"error": exc.message}, status)


def register_trajectories(routes, bot):
    service = TrajectoriesService(saver=getattr(bot, "trajectory_saver", None))

    @routes.get("/api/trajectories")
    async def files(request):
        return await _invoke(service, "trajectories.list", {})

    @routes.get("/api/trajectories/{filename}")
    async def read(request):
        return await _invoke(service, "trajectories.read", {
            **request.query, "filename": request.match_info["filename"],
        })

    @routes.get("/api/trajectories/search/query")
    async def search(request):
        return await _invoke(service, "trajectories.search", dict(request.query))

    @routes.get("/api/trajectories/message/{message_id}")
    async def message(request):
        return await _invoke(service, "trajectories.message", dict(request.match_info))


def setup_api(app, bot):
    routes = web.RouteTableDef()
    register_trajectories(routes, bot)
    app.add_routes(routes)


class _FileFixtureVault:
    """Exact inherited filesystem regression fixture, NEVER production."""

    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        return json.loads(self.path.read_text())

    def write(self, raw):
        ca._atomic_write_secure(self.path, json.dumps(raw))


def register_codex_oauth(routes, bot):
    service = CodexAccountsService(None, vault=_FileFixtureVault(
        bot.config.openai_codex.credentials_path))
    service._pool = bot.llm_gateway.codex_client.auth
    # The inherited file-owner fixture lacks the keyring row metadata handle.
    # Supply that setup seam without changing the owner, locks or credentials.
    for auth in service.pool._accounts:
        auth.expected = dict(auth._load())
    service.providers = bot.llm_gateway

    @routes.get("/api/codex/status")
    async def status(request):
        return await _invoke(service, "codex.accounts.list", {})

    @routes.post("/api/codex/account/{index}/refresh")
    async def refresh(request):
        return await _invoke(service, "codex.accounts.refresh", dict(request.match_info))

    @routes.put("/api/codex/account/{index}/label")
    async def label(request):
        return await _invoke(service, "codex.accounts.label", {
            **await request.json(), "index": int(request.match_info["index"]),
        })

    @routes.delete("/api/codex/account/{index}")
    async def remove(request):
        return await _invoke(service, "codex.accounts.remove", {
            "index": int(request.match_info["index"]),
        })

    @routes.post("/api/codex/device-poll")
    async def poll(request):
        params = await request.json()
        # Adapt only the inherited blocking device transport seam. The real
        # named method still owns merging, durable settlement and publication.
        creds = await ca.CodexAuth.poll_device_auth(
            params["device_auth_id"], params["user_code"], params.get("interval", 5))
        auth_id = params["device_auth_id"]
        service._logins[auth_id] = _Login(
            params["user_code"], 5, time.monotonic() + 900, 0, credentials=creds)
        return await _invoke(service, "codex.login.poll", params)


class TestServer:
    __test__ = False

    def __init__(self, app):
        self.app = app


class _Reply:
    def __init__(self, response):
        self.status = response.status
        self._body = response.body

    async def json(self):
        return json.loads(self._body)


class TestClient:
    """Route-shaped fixture calls, not an HTTP server or renderer API."""
    __test__ = False

    def __init__(self, server):
        self.app = server.app

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def _call(self, method, url, *, params=None, json=None):
        parts = urlsplit(url)
        query = {key: values[-1] for key, values in parse_qs(parts.query).items()}
        query.update(params or {})
        for route in self.app.router.routes():
            if route.method != method:
                continue
            match = route.resource.get_info()
            template = match.get("formatter", match.get("path", ""))
            actual = parts.path.split("/")
            pattern = template.split("/")
            if len(actual) != len(pattern):
                continue
            info = {}
            for expected, value in zip(pattern, actual):
                if expected.startswith("{") and expected.endswith("}"):
                    info[expected[1:-1]] = value
                elif expected != value:
                    break
            else:
                async def body():
                    return json
                return _Reply(await route.handler(SimpleNamespace(
                    query=query, match_info=info, json=body)))
        return _Reply(_response({"error": "fixture route not found"}, 404))

    async def get(self, url, **kwargs):
        return await self._call("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return await self._call("POST", url, **kwargs)

    async def put(self, url, **kwargs):
        return await self._call("PUT", url, **kwargs)

    async def delete(self, url, **kwargs):
        return await self._call("DELETE", url, **kwargs)


def adapted_tree(stem):
    path = f"tests/{stem}.py"
    source = frozen_source(path)
    assert hashlib.sha256(source).hexdigest() == SUITES[stem]
    original = ast.parse(source, filename=path)
    adapted = copy.deepcopy(original)
    changes = []
    # Exactly these obsolete transport imports, at module scope or in helpers.
    class Imports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module == "src.trajectories.saver":
                adapted_names = [alias for alias in node.names
                                 if alias.name in {"DEFAULT_TRAJECTORY_DIR", "TrajectoryTurn"}]
                if adapted_names:
                    changes.append({"line": node.lineno,
                                    "operation": "historical_transport_fixture_defaults"})
                    other_names = [alias for alias in node.names if alias not in adapted_names]
                    fixture_import = ast.copy_location(ast.ImportFrom(
                        module="tests.desktop_adapters.step5_traces",
                        names=adapted_names, level=0), node)
                    if not other_names:
                        return fixture_import
                    return [ast.copy_location(ast.ImportFrom(
                        module="src.trajectories.saver", names=other_names, level=0), node),
                        fixture_import]
            if node.module in {"aiohttp.test_utils", "src.web.api",
                               "src.web.api.sessions_chat", "src.web.api.codex_admin"}:
                allowed = {"TestClient", "TestServer", "setup_api",
                           "register_trajectories", "register_codex_oauth"}
                if not all(alias.name in allowed for alias in node.names):
                    raise ValueError("unexpected transport import")
                changes.append({"line": node.lineno, "from": node.module})
                node.module = "tests.desktop_adapters.step5_traces"
            return node
    adapted = Imports().visit(adapted)
    assert corpus(original) == corpus(adapted)
    EVIDENCE[path] = {
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "full_corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "full_assert_parameter_ast_preserved_before_projection": True,
        "whole_suite": True, "sealed_fixture_edits": changes,
    }
    return adapted


def export_suite(namespace, stem):
    tree = adapted_tree(stem)
    module = ModuleType(f"desktop_step5_{stem}")
    module.__file__ = str(ROOT / f"tests/{stem}.py")
    exec(compile(ast.fix_missing_locations(tree), module.__file__, "exec"), module.__dict__)
    register_module(namespace, stem, tree, module)


def register_module(namespace, stem, tree, module):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            exported = f"TestStep5_{stem}_{node.name[4:]}"
            namespace[exported] = vars(module)[node.name]
            for child in node.body:
                if getattr(child, "name", "").startswith("test_"):
                    CASE_MAP[f"tests/{stem}.py::{node.name}::{child.name}"] = (
                        f"{exported}::{child.name}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                exported = f"test_step5_{stem}_{node.name[5:]}"
                namespace[exported] = vars(module)[node.name]
                CASE_MAP[f"tests/{stem}.py::{node.name}"] = exported


def load(namespace):
    for stem in CORPUS_SELECTIONS:
        export_suite(namespace, stem)
