"""Whole frozen turn-state suite against the retained named observer.

The old routes are replaced only at the HTTP/setup seam. Snapshot reads are
owned by ObservabilityService; the legacy auth gate used by the inherited
security tests is extracted from the pinned source archive, never replaced by
an allow-all fixture. No production listener is started.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import io
import tarfile
from types import ModuleType, SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient as TestClient
from aiohttp.test_utils import TestServer as TestServer

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source
from src.desktop.management import MethodError
from src.desktop.observability import ObservabilityService
from tests.desktop_adapters import step5_records_legacy as pinned

SOURCE_PATH = "tests/test_web_api_turn_state.py"
SOURCE_SHA256 = "23a20c4e9b712c53499bf638abe64cbb654e681a1ff675bd4de1882d6c0067e3"
EVIDENCE = {}
CASE_MAP = {}


def _archive_source(path):
    archive = (ROOT / "maintenance/odin-v4.13.0.tar.gz").read_bytes()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        matches = [m for m in tf if m.name == path]
        if len(matches) != 1 or not matches[0].isfile():
            raise AssertionError(f"expected one pinned regular file: {path}")
        return tf.extractfile(matches[0]).read()


admin_gate = pinned._load("src.web.api_common").admin_gate


WebConfig = pinned._load("src.config.schema").WebConfig
ApiTokenIdentity = pinned._load("src.config.schema").ApiTokenIdentity
HealthServer = pinned._health.HealthServer


def register_auth(routes, bot):
    return pinned._security.register_auth(routes, bot)


def register_turn_state(routes, bot):
    service = ObservabilityService(
        config=bot.config, turn_store=getattr(bot.services, "turn_store", None),
        model_breakers=getattr(bot.services, "model_breakers", None),
    )
    gate = turn_state_api.admin_gate(bot)

    async def read(request, method):
        denied = gate(request)
        if denied:
            return denied
        params = dict(request.query)
        try:
            body = await service.handle(method, params)
        except MethodError as exc:
            status = 503 if exc.code == "unavailable" else 400
            return web.json_response({"error": exc.message}, status=status)
        status = 503 if body.get("availability") == "unavailable" else 200
        return web.json_response(body, status=status)

    async def turns(request):
        return await read(request, "turn_state.snapshot")
    async def capacity(request):
        return await read(request, "capacity.snapshot")
    routes.get("/api/turn-state/turns")(turns)
    routes.get("/api/turn-state/capacity-breakers")(capacity)


def _adapted_tree():
    source = frozen_source(SOURCE_PATH)
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise AssertionError("pinned frozen test bytes changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    adapted = copy.deepcopy(original)
    changes = []
    replacements = {
        "aiohttp.test_utils": __name__,
        "src.config.schema": __name__,
        "src.health.server": __name__,
        "src.web.api": __name__,
        "src.web.api.security": __name__,
        "src.web.api.turn_state": __name__,
    }
    class Imports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            target = replacements.get(node.module)
            if target:
                allowed = {
                    "aiohttp.test_utils": {"TestClient", "TestServer"},
                    "src.config.schema": {"ApiTokenIdentity", "WebConfig"},
                    "src.health.server": {"HealthServer"},
                    "src.web.api": {"turn_state"},
                    "src.web.api.security": {"register_auth"},
                    "src.web.api.turn_state": {"register_turn_state"},
                }[node.module]
                if any(alias.name not in allowed for alias in node.names):
                    raise AssertionError(f"unexpected frozen import {node.module}")
                changes.append((node.lineno, node.module, [a.name for a in node.names]))
                if node.module == "src.web.api":
                    # The monkeypatch assertion still targets the route fixture's
                    # gate namespace, as it did in the original module.
                    return ast.copy_location(ast.ImportFrom(
                        module=__name__, names=[ast.alias(name="turn_state_api")], level=0), node)
                return ast.copy_location(ast.ImportFrom(module=target, names=node.names,
                                                        level=0), node)
            return node
    adapted = Imports().visit(adapted)
    ast.fix_missing_locations(adapted)
    if corpus(original) != corpus(adapted):
        raise AssertionError("assertions, decorators, parameters, or cases changed")
    EVIDENCE[SOURCE_PATH] = {
        "source_sha256": SOURCE_SHA256,
        "corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "exact_corpus": corpus(original), "whole_suite": True, "setup_edits": changes,
        "admin_gate_source": hashlib.sha256(_archive_source("src/web/api_common.py")).hexdigest(),
        "auth_harness": "sealed tests.desktop_adapters.step5_records_legacy pinned source loader",
    }
    return adapted


turn_state_api = SimpleNamespace(admin_gate=admin_gate)


def register_module(namespace):
    tree = _adapted_tree()
    module = ModuleType("desktop_step5_test_web_api_turn_state")
    module.__file__ = str(ROOT / SOURCE_PATH)
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    for node in tree.body:
        name = getattr(node, "name", "")
        if name.startswith("test_"):
            exported = f"test_step5_turn_state_{name[5:]}"
            namespace[exported] = getattr(module, name)
            CASE_MAP[f"{SOURCE_PATH}::{name}"] = exported
        elif name.startswith("Test"):
            exported = f"TestStep5TurnState_{name[4:]}"
            namespace[exported] = getattr(module, name)
            for child in node.body:
                if getattr(child, "name", "").startswith("test_"):
                    CASE_MAP[f"{SOURCE_PATH}::{name}::{child.name}"] = (
                        f"{exported}::{child.name}")


def load(namespace):
    register_module(namespace)
