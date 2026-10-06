"""Whole frozen Records suites, with old HTTP setup translated to named reads.

No assertions, parameters, signatures or decorators are rewritten. The stream
policy suites additionally exercise a sealed, test-only pinned policy engine;
that compatibility engine is not desktop admission or a renderer transport.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

from aiohttp import web

from scripts.maintenance.fixture_corpus import corpus, frozen_source, nodes
from src.desktop.management import MethodError
from src.desktop.records import RecordsService

SUITES = {
    "test_action_diffs": "6f4bf035e5d971fd5d8bca66aa47317b937e067d291d74436c818ac6e62a8596",
    "test_campaign_audit_observability": (
        "77dc718bbf05897961c4fa61ab129eb4d5f4081823571d507444072b3324387a"
    ),
    "test_audit_tail_v412": "563ea02abbd219b6a61d46ca7dbeddfee5e762e169ddabe3a3fe30d6c0603af7",
    "test_log_search": "8df01eb2ba4d492eb9d99c8f21a5e8de78014fb4ab29ce064d93cc01e239d84d",
    "test_web_campaign_streams": "3e997d843f5d6e171c476526cc2b1a16de3236292a565b2d8a734f90c402697c",
    "test_campaign_websocket_coverage": (
        "faaf9e25f7f58664271b5f59f392db799c8698694b7a2160511772127f6f1119"
    ),
}
CORPUS_SELECTIONS = {
    "test_action_diffs": None, "test_campaign_audit_observability": None,
    "test_audit_tail_v412": None, "test_log_search": None,
    "test_web_campaign_streams": None, "test_campaign_websocket_coverage": None,
}
CORPUS_EXCLUSIONS = {}
CASE_MAP = {}
SETUP_HUNKS = {}


def _service(bot):
    return RecordsService(SimpleNamespace(data_dir=Path(bot.audit.path).parent), audit=bot.audit)


def create_api_routes(bot):
    """Only the old route fixture boundary changes; the real service decides."""
    service = _service(bot)
    routes = web.RouteTableDef()
    for path, method in (
        ("/api/audit/diffs", "audit.diffs"), ("/api/logs/search", "logs.search"),
        ("/api/logs/stats", "logs.stats"), ("/api/observability/failures", "audit.failures"),
    ):
        async def read(request, _method=method):
            try:
                return web.json_response(await service.handle(_method, dict(request.query)))
            except MethodError as exc:
                return web.json_response({"error": str(exc)}, status=400)
        routes.get(path)(read)
    return routes


def setup_api(app, bot):
    app.router.add_routes(create_api_routes(bot))


def register_aggregates(routes, bot):
    for route in create_api_routes(bot):
        routes.route(route.method, route.path)(route.handler)


class SetupOnly(ast.NodeTransformer):
    def __init__(self):
        self.hunks = []

    def visit_Assert(self, node):
        return node

    def visit_ImportFrom(self, node):
        original = copy.deepcopy(node)
        if node.module in {"src.web.api", "src.web.api.observability"}:
            node.module = __name__
        elif node.module == "src.web":
            node.module = "tests.desktop_adapters.step5_records_legacy"
        elif node.module == "src.config.schema" and any(
            item.name in {"ApiTokenIdentity", "WebConfig"} for item in node.names
        ):
            node.module = "tests.desktop_adapters.step5_records_legacy"
        elif node.module == "tests.test_web_campaign_authorization":
            node.module = "tests.desktop_adapters.step5_records_legacy"
        if ast.dump(original) != ast.dump(node):
            self.hunks.append({"line": node.lineno, "before": ast.dump(original),
                               "after": ast.dump(node), "after_source": ast.unparse(node)})
        return node

    def visit_Constant(self, node):
        if isinstance(node.value, str) and node.value.startswith("src.web.websocket."):
            replacement = ast.Constant(node.value.replace(
                "src.web.websocket.", "tests.desktop_adapters.step5_records_legacy.websocket."))
            self.hunks.append({"line": node.lineno, "before": ast.dump(node),
                               "after": ast.dump(replacement),
                               "after_source": ast.unparse(replacement)})
            return ast.copy_location(replacement, node)
        return node


def transformed_tree(suite):
    source = frozen_source(f"tests/{suite}.py")
    assert hashlib.sha256(source).hexdigest() == SUITES[suite]
    original = ast.parse(source)
    transformer = SetupOnly()
    tree = ast.fix_missing_locations(transformer.visit(copy.deepcopy(original)))
    for hunk in transformer.hunks:
        matches = [(symbol, node) for symbol, node in nodes(original)
                   if getattr(node, "lineno", None) == hunk["line"]
                   and ast.dump(node) == hunk["before"]]
        assert len(matches) == 1
        hunk["symbol"] = matches[0][0]
        statement = isinstance(matches[0][1], ast.ImportFrom)
        hunk["operation"] = (
            "records_named_fixture_import" if statement else "records_fixture_patch_target"
        )
        hunk["kind"] = "statement" if statement else "expression"
        hunk["before_sha256"] = hashlib.sha256(hunk["before"].encode()).hexdigest()
        representation = json.dumps([hunk["after"]]) if statement else hunk["after"]
        hunk["after_sha256"] = hashlib.sha256(representation.encode()).hexdigest()
    # Reconstruct independently from exact whole-node matches. Broad setup
    # transformations can never silently change any additional source node.
    expected = copy.deepcopy(original)
    for hunk in transformer.hunks:
        matches = [node for symbol, node in nodes(expected)
                   if symbol == hunk["symbol"] and getattr(node, "lineno", None) == hunk["line"]
                   and ast.dump(node) == hunk["before"]]
        assert len(matches) == 1
        replacement = ast.parse(hunk["after_source"]).body[0]
        if isinstance(matches[0], ast.Constant):
            replacement = replacement.value
            matches[0].value = replacement.value
        else:
            matches[0].module = replacement.module
        assert ast.dump(matches[0]) == hunk["after"]
    assert ast.dump(expected) == ast.dump(tree)
    assert corpus(original) == corpus(tree)
    return tree, transformer.hunks


def export_suite(namespace, suite):
    tree, hunks = transformed_tree(suite)
    SETUP_HUNKS[suite] = hunks
    module = ModuleType(f"desktop_step5_records_{suite}")
    module.__file__ = str(Path(__file__).parents[1] / f"{suite}.py")
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    register_module(namespace, suite, module)


def register_module(namespace, suite, module):
    for name, value in vars(module).items():
        if name.startswith("test_"):
            exported = f"test_step5_records_{suite[5:]}__{name[5:]}"
            value.__module__ = namespace["__name__"]
            namespace[exported] = value
            CASE_MAP[f"tests/{suite}.py::{name}"] = exported
        elif name.startswith("Test") and isinstance(value, type):
            exported = f"TestStep5Records_{suite[5:]}_{name[4:]}"
            value.__module__ = namespace["__name__"]
            namespace[exported] = value
            for method in vars(value):
                if method.startswith("test_"):
                    CASE_MAP[f"tests/{suite}.py::{name}::{method}"] = f"{exported}::{method}"
        elif getattr(value, "_pytestfixturefunction", None) is not None or getattr(
            value, "_fixture_function_marker", None
        ) is not None:
            value.__module__ = namespace["__name__"]
            namespace[name] = value


def load(namespace):
    for suite in SUITES:
        export_suite(namespace, suite)


SOURCE_HASHES = {
    f"tests/{suite}.py": hashlib.sha256(frozen_source(f"tests/{suite}.py")).hexdigest()
    for suite in SUITES
}
