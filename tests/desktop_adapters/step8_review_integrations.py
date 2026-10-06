"""Sealed frozen review-C adapters. Only the removed request carrier changes.

All verdicts come from actual Desktop domain owners via ManagementService.invoke.
Real aiohttp delivery servers remain real; no removed Odin HTTP listener runs.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from aiohttp.test_utils import TestClient as HttpClient
from aiohttp.test_utils import TestServer as HttpServer

from scripts.maintenance.fixture_corpus import (
    corpus,
    dump,
    frozen_source,
    nodes,
    register_module,
)
from src.config.schema import Config
from src.desktop.authority import OwnerAuthority
from src.desktop.integrations import IntegrationsService
from src.desktop.management import ManagementService
from src.desktop.paths import ProfilePaths
from src.desktop.records import RecordsService
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "maintenance/step8-part2-review-integrations.json"
SUITES = {
    "test_audit_signing": "f85926250b60a19450c80f507b5899be9186ebd8e28b16ffc5a7b0003b8282bc",
    "test_web_api_integrations_validation_coverage": (
        "e8092c3f4f2f24ddb2a3ebf1b85ae60e0084e9d21e4a36429ae2434092f2eb42"
    ),
    "test_webhook_campaign": "170a4b9a1557635c774aee9e7a9baf48f1fe39e7057fbe91e07f32fa0402e7c4",
    "test_log_search": "8df01eb2ba4d492eb9d99c8f21a5e8de78014fb4ab29ce064d93cc01e239d84d",
}
CORPUS_SELECTIONS = {
    "test_audit_signing": None,
    "test_web_api_integrations_validation_coverage": None,
    "test_webhook_campaign": None,
    "test_log_search": [
        "TestSearchLogsNoFilter", "TestSearchLogsLevel", "TestSearchLogsTimeRange",
        "TestSearchLogsKeyword", "TestSearchLogsToolName", "TestSearchLogsCombined",
        "TestSearchLogsResilience", "TestLogSearchAPI", "TestSearchAfterLog",
        "TestLogSearchEdgeCases",
    ],
}
CORPUS_EXCLUSIONS = {"test_log_search": [
    "TestGetLogStats", "TestLogStatsAPI",
    "TestLogSearchEdgeCases.test_get_log_stats_counts_unique_tools",
]}


class Backend:
    """Temporary keyring backend, with the production ProfileSecretStore adapter."""
    def __init__(self):
        self.values = {}

    def get_password(self, namespace, key):
        return self.values.get((namespace, key))

    def set_password(self, namespace, key, value):
        self.values[namespace, key] = value

    def delete_password(self, namespace, key):
        self.values.pop((namespace, key), None)


class Bindings:
    """Only construction wiring for the removed HTTP setup fixture."""
    def __init__(self):
        self.service = None
        self.router = self
        self.resources = []

    def add_routes(self, routes):
        self.service = routes.service
        self.disabled = getattr(routes, "disabled", False)
        self.resources.extend(routes.resources)


def records_routes(bot):
    routes = Bindings()
    routes.service = RecordsService(None, audit=bot.audit)
    return routes


def setup_records(app, bot):
    app.add_routes(records_routes(bot))


def register_integrations(routes, bot):
    """Temporary desired settings, real owner; no mutation or outcome stubs."""
    directory = tempfile.TemporaryDirectory(prefix="review-integrations-")
    root = Path(directory.name)
    paths = ProfilePaths.from_xdg(environ={}, home=root)
    paths.create_private()
    authority = OwnerAuthority(paths)
    authority.authenticate_local(peer_uid=__import__("os").geteuid())
    __import__("uuid").UUID(authority.owner_id)
    backend = Backend()
    vault = ProfileSecretStore(paths, backend=backend)
    config = Config()
    if hasattr(bot, "config"):
        config.outbound_webhooks = bot.config.outbound_webhooks
        # Preserve the inherited active desired-file fixture, including edits
        # deliberately distinct from rejected boot state.
        from src.config.schema import active_config_path
        configured_path = active_config_path()
        if configured_path is not None:
            paths = replace(paths, config_dir=Path(configured_path).parent)
    else:
        config.outbound_webhooks.enabled = hasattr(bot, "outbound_webhook_dispatcher")
        paths.config_file.write_text("{}")
    settings = SettingsService(paths, vault, config=config)
    dispatcher = getattr(bot, "outbound_webhook_dispatcher", None)
    if dispatcher is not None and not hasattr(dispatcher, "_webhooks"):
        # Original object() merely stood for present optional wiring.
        from src.notifications.outbound_webhooks import OutboundWebhookDispatcher
        dispatcher = OutboundWebhookDispatcher()
    routes.service = IntegrationsService(settings, dispatcher=dispatcher)
    routes.disabled = dispatcher is None and not config.outbound_webhooks.enabled
    routes.resources = [directory, authority, bot, settings]


class DesktopResponse:
    """HTTP numeric assertions project the *same* real domain verdict."""
    def __init__(self, frame, method):
        self.frame = frame
        if frame["ok"]:
            self.body = frame["result"]
            if method == "audit.verify":
                assert type(self.body["valid"]) is bool
                self.status = 200 if self.body["valid"] else 409
            else:
                self.status = 200
        else:
            error = frame["error"]
            self.status = {"bad_request": 400, "not_found": 404,
                           "unavailable": 503, "internal_error": 503,
                           "capability_unavailable": 503}[error["code"]]
            self.body = {"error": error["message"]}
            if method.startswith("webhooks.") and error["code"] == "capability_unavailable":
                self.body = {"error": "outbound webhooks not available"}

    async def json(self):
        return self.body

    async def text(self):
        return json.dumps(self.body)


class DesktopServer:
    __test__ = False
    def __new__(cls, app):
        if not isinstance(app, Bindings):
            return HttpServer(app)
        return app


class DesktopClient:
    __test__ = False
    def __new__(cls, app):
        if not isinstance(app, Bindings):
            return HttpClient(app)
        return super().__new__(cls)

    def __init__(self, app):
        self.app = app
        disabled = getattr(app, "disabled", False)
        self.manager = ManagementService(None, services=[] if disabled else [app.service],
                                         identity_key=b"review-temporary-key-32-bytes....."[:32])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        if isinstance(self.app.service, IntegrationsService):
            service = self.app.service
            if service.dispatcher is not None:
                await service.dispatcher.close()
            if len(self.app.resources) == 4:
                directory, authority, bot, settings = self.app.resources
                if hasattr(bot, "config"):
                    bot.config.outbound_webhooks = settings.config.outbound_webhooks
                authority.release_runtime()
                directory.cleanup()

    async def request(self, verb, path, *, json=None):
        parsed = urlsplit(path)
        if parsed.path == "/api/audit/verify":
            method, params = "audit.verify", {}
        elif parsed.path == "/api/logs/search":
            method = "logs.search"
            params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        elif parsed.path.startswith("/api/outbound-webhooks"):
            suffix = parsed.path.removeprefix("/api/outbound-webhooks").strip("/")
            method = {"get": "webhooks.outbound.list", "post": "webhooks.outbound.save",
                      "put": "webhooks.outbound.save", "delete": "webhooks.outbound.delete"}[verb]
            params = json if json is not None else {}
            if suffix and suffix != "stats" and isinstance(params, dict):
                params = {**params, "id": suffix}
        else:
            raise ValueError("unmapped inherited request")
        return DesktopResponse(await self.manager.invoke(method, params), method)

    async def get(self, path):
        return await self.request("get", path)

    async def post(self, path, **kw):
        return await self.request("post", path, **kw)

    async def put(self, path, **kw):
        return await self.request("put", path, **kw)

    async def delete(self, path):
        return await self.request("delete", path)


DesktopWeb = SimpleNamespace(Application=Bindings, RouteTableDef=Bindings)


def adapted_tree(suite):
    record = json.loads(RECORD.read_text())
    path = "tests/" + suite + ".py"
    source = frozen_source(path)
    entry = next(row for row in record["entries"] if row["path"] == path)
    assert hashlib.sha256(source).hexdigest() == entry["inherited_sha256"] == SUITES[suite]
    original = ast.parse(source)
    tree = copy.deepcopy(original)
    rules = list(record["ledger_by_path"][path])
    rules.extend(
        (row["symbol"], row["line"], row["key"])
        for row in record["setup_hunks"] if row["path"] == path
    )
    for symbol, line, key in rules:
        before, after, text = record["sealed_imports"][key]
        kind = "Constant" if key == "sample" else "Call" if key.endswith("_call") else "ImportFrom"
        rule = dict(path=path, symbol=symbol, line=line, kind=kind,
                    before_sha256=before, after_sha256=after, replacement=text)
        matches = [node for symbol, node in nodes(tree)
                   if symbol == rule["symbol"] and getattr(node, "lineno", None) == rule["line"]
                   and type(node).__name__ == rule["kind"]
                   and hashlib.sha256(dump(node).encode()).hexdigest() == rule["before_sha256"]]
        assert len(matches) == 1, rule
        old = matches[0]
        text = rule["replacement"]
        replacement = (ast.parse(text, mode="eval").body
                       if isinstance(old, ast.expr) else ast.parse(text).body[0])
        assert hashlib.sha256(dump(replacement).encode()).hexdigest() == rule["after_sha256"]
        ast.copy_location(replacement, old)
        class Replace(ast.NodeTransformer):
            def generic_visit(self, node):
                return replacement if node is old else super().generic_visit(node)
        tree = Replace().visit(tree)
    assert corpus(original) == corpus(tree), "no assertion/signature/decorator edits admitted"
    return original, ast.fix_missing_locations(tree)


def load(namespace):
    for suite, selected in CORPUS_SELECTIONS.items():
        _, tree = adapted_tree(suite)
        if selected is not None:
            tree.body = [node for node in tree.body
                         if not isinstance(node, ast.ClassDef) or node.name in selected]
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    node.body = [method for method in node.body if not (
                        isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and f"{node.name}.{method.name}" in CORPUS_EXCLUSIONS[suite]
                    )]
        module = ModuleType("review_" + suite)
        module.Bindings = Bindings
        exec(compile(tree, "tests/" + suite + ".py", "exec"), module.__dict__)
        register_module(namespace, module, prefix=suite[5:])
        for name, value in vars(module).items():
            if (name in {"no_retry", "loopback_connections_only"}
                    or hasattr(value, "_pytestfixturefunction")):
                value.__module__ = namespace["__name__"]
                namespace[name] = value
