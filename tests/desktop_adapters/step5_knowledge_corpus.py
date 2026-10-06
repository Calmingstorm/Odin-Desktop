"""Whole immutable knowledge suites with exact reversible setup projections."""
# Exact reversible frozen source hunks are intentionally unsplit.
# ruff: noqa: E501
from __future__ import annotations

import ast
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, frozen_source, register_module

CORPUS_SELECTIONS = {
    "test_knowledge_dedup": None,
    "test_knowledge_versions": None,
    "test_learning_disabled_crud": None,
    "test_web_api_knowledge_mem": None,
}
CORPUS_EXCLUSIONS = {}
SUITES = {
    "test_knowledge_dedup": "f77544f1c865bf02a3ec432b5d7707081e7bfcab37aba8e9c7a41df97a204af8",
    "test_knowledge_versions": "cfe23cff2e90e9f1a8e2e589fe7ceb5eb1c79e7b91b7af83a01b28d05dbdc147",
    "test_learning_disabled_crud": "d69a0a0e9ce26a14e502ad98087647ac194611ba4bb450c7c70636f5ebb2cd87",
    "test_web_api_knowledge_mem": "a84b2df4f781a34395ffda41d2ac7ecc0f0b35082a0266ae781fbc99ade750dc",
}


def setup_hunks(name, source):
    rules = []
    if name in {"test_knowledge_dedup", "test_knowledge_versions"}:
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_make_app")
        rules.append((ast.get_source_segment(source, node),
                      "def _make_app(bot):\n    from tests.desktop_adapters.step5_knowledge_services import knowledge_app\n    return knowledge_app(bot)"))
    if name == "test_web_api_knowledge_mem":
        rules.append(("from src.web.api.knowledge_mem import (",
                      "from tests.desktop_adapters.step5_knowledge_services import ("))
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_app")
        rules.append((ast.get_source_segment(source, node),
                      "def _app(*registrars, bot):\n    from tests.desktop_adapters.step5_knowledge_services import app\n    return app(*registrars, bot=bot)"))
        rules.append(('patch("src.web.api.knowledge_mem._safe_int_param", side_effect=ValueError)',
                      'patch("src.desktop.knowledge._safe_int_param", side_effect=ValueError)'))
        rules.append(("routes = web.RouteTableDef()\n        register_knowledge(routes, kbot)",
                      "from tests.desktop_adapters.step5_knowledge_services import search_fixture\n        routes = search_fixture(kbot)"))
        rules.append(('(docs / "one.md").write_text("imported document body one")',
                      '(docs / "one.md").write_text("imported document body one")\n        from tests.desktop_adapters.step5_knowledge_services import import_fixture\n        _app = lambda *registrars, bot: import_fixture(bot, tmp_path)'))
        node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == "_with_identity")
        rules.append((ast.get_source_segment(source, node),
                      "def _with_identity(self, bot, identity):\n        from tests.desktop_adapters.step5_knowledge_services import scoped_memory_fixture\n        return scoped_memory_fixture(bot, identity)"))
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_memory_bot")
        rules.append((ast.get_source_segment(source, node),
                      "def _memory_bot(initial=None):\n    from tests.desktop_adapters.step5_knowledge_services import retained_memory_bot\n    return retained_memory_bot(initial)"))
    if name == "test_learning_disabled_crud":
        rules.append(("from src.web.api.knowledge_mem import register_learned_context",
                      "from tests.desktop_adapters.step5_knowledge_services import register_learned_context"))
        rules.append(("routes = web.RouteTableDef()\n    register_learned_context(routes, SimpleNamespace(reflector=reflector))\n    app = web.Application()\n    app.add_routes(routes)",
                      "routes = []\n    register_learned_context(routes, SimpleNamespace(reflector=reflector))\n    app = routes"))
    rules.append(("from aiohttp.test_utils import TestClient, TestServer",
                  "from tests.desktop_adapters.step5_knowledge_services import TestClient, TestServer"))
    return rules


def transformed_source(name):
    original = frozen_source(f"tests/{name}.py").decode()
    if hashlib.sha256(original.encode()).hexdigest() != SUITES[name]:
        raise ValueError("inherited source hash changed")
    source = original
    rules = setup_hunks(name, original)
    for before, after in rules:
        if source.count(before) != 1:
            raise ValueError("setup hunk must match exactly once")
        source = source.replace(before, after, 1)
    reversed_source = source
    for before, after in reversed(rules):
        if reversed_source.count(after) != 1:
            raise ValueError("reverse setup hunk must match exactly once")
        reversed_source = reversed_source.replace(after, before, 1)
    if reversed_source != original or corpus(ast.parse(source)) != corpus(ast.parse(original)):
        raise ValueError("frozen assertions/decorators/signatures changed")
    return source


def evidence():
    result = []
    for name in CORPUS_SELECTIONS:
        source = frozen_source(f"tests/{name}.py").decode()
        result.append({"path": f"tests/{name}.py", "inherited_sha256": hashlib.sha256(source.encode()).hexdigest(),
                       "setup_hunks": [{"before_source": before, "after_source": after,
                                         "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                                         "after_sha256": hashlib.sha256(after.encode()).hexdigest()}
                                        for before, after in setup_hunks(name, source)]})
    return result


def export_suite(namespace, name):
    module = ModuleType("desktop_step5_knowledge_" + name)
    module.__file__ = f"tests/{name}.py"
    exec(compile(transformed_source(name), module.__file__, "exec"), module.__dict__)
    for key, value in vars(module).items():
        if hasattr(value, "_fixture_function_marker") or hasattr(value, "_pytestfixturefunction"):
            if key in namespace:
                # Equal names belong to only the web-API suite in this corpus.
                raise ValueError("fixture collision")
            namespace[key] = value
    register_module(namespace, module, prefix=name, full_class_name=True)


def load(namespace):
    for name in CORPUS_SELECTIONS:
        export_suite(namespace, name)
