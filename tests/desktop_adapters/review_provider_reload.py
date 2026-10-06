"""Whole inherited rollback suite with real Desktop durable phase projections."""

import ast
import copy
import hashlib
from types import ModuleType, SimpleNamespace

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, nodes, register_module
from src.config.schema import Config
from tests.desktop_adapters.review_provider_llm import provider_graph, save

PATH = "tests/test_campaign_provider_reload_coverage.py"
SHA256 = "e710eaf69e4d04367498a18432f0238460bdce0b0412adfa74ecb59bdab78f39"
SOURCE_PATH = PATH
SOURCE_SHA256 = SHA256
SUITES = {
    "test_campaign_provider_reload_coverage":
        "e710eaf69e4d04367498a18432f0238460bdce0b0412adfa74ecb59bdab78f39",
}
CORPUS_SELECTIONS = {"test_campaign_provider_reload_coverage": None}
CORPUS_EXCLUSIONS = {}
MODULE = "tests.desktop_adapters.review_provider_reload"
HUNKS = (
    (
        "<module>",
        4,
        "from aiohttp.test_utils import TestClient, TestServer",
        f"from {MODULE} import TestClient, TestServer",
    ),
    (
        "<module>",
        6,
        "from src.web.api.llm_admin import register_provider_config",
        f"from {MODULE} import register_provider_config",
    ),
    (
        "<module>",
        7,
        "from tests.test_web_api_llm_admin import _app, _gw",
        f"from {MODULE} import _app, _gw",
    ),
    (
        "test_enabled_compatible_reload_reason_rolls_back_configuration",
        17,
        'monkeypatch.setattr("src.web.api.llm_admin.persist_config_paths_locked", persist)',
        f'monkeypatch.setattr("{MODULE}.persist_config_paths_locked", persist)',
    ),
    (
        "test_enabled_compatible_reload_reason_rolls_back_configuration",
        18,
        'gateway.reload_openai_compatible_inner = AsyncMock(return_value={'
        '"configured": True, "reason": "candidate qualification failed"})',
        'gateway._probe_openai_compatible = '
        'AsyncMock(return_value="candidate qualification failed")',
    ),
)
GRAPH = None
persist_config_paths_locked = None


def hunk_records():
    return [
        {
            "path": PATH,
            "symbol": owner,
            "line": line,
            "before_source": before,
            "after_source": after,
            "kind": "statement",
            "reversible": True,
            "before_sha256": hashlib.sha256(dump(ast.parse(before).body[0]).encode()).hexdigest(),
            "after_sha256": hashlib.sha256(dump(ast.parse(after).body[0]).encode()).hexdigest(),
        }
        for owner, line, before, after in HUNKS
    ]


def source_tree():
    source = frozen_source(PATH)
    assert hashlib.sha256(source).hexdigest() == SHA256
    return ast.parse(source, filename=PATH)


def replace(tree, owner, line, before, after):
    matches = [
        node
        for symbol, node in nodes(tree)
        if symbol == owner
        and getattr(node, "lineno", None) == line
        and dump(node) == dump(ast.parse(before).body[0])
    ]
    assert len(matches) == 1, (owner, line)
    target, replacement = matches[0], ast.parse(after).body[0]

    class Exact(ast.NodeTransformer):
        def visit(self, node):
            if node is target:
                return ast.copy_location(copy.deepcopy(replacement), node)
            return super().visit(node)

    return Exact().visit(tree)


def adapted_tree():
    original = source_tree()
    tree = copy.deepcopy(original)
    for rule in HUNKS:
        tree = replace(tree, *rule)
    assert corpus(tree) == corpus(original)
    reverse = copy.deepcopy(tree)
    for owner, line, before, after in reversed(HUNKS):
        reverse = replace(reverse, owner, line, after, before)
    assert dump(reverse) == dump(original)
    return ast.fix_missing_locations(tree)


@pytest.fixture(autouse=True)
async def desktop_provider_graph(tmp_path, monkeypatch):
    global GRAPH
    import aiohttp

    import src.desktop.settings as domain

    def no_network(*args, **kwargs):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(aiohttp, "ClientSession", no_network)
    config = Config(openai_compatible={"enabled": True, "api_key": "temporary-placeholder"})
    async with provider_graph(tmp_path, config=config) as graph:
        GRAPH = graph
        graph.events = []
        graph.owner.compatible_client = graph.owner._build("compat", graph.settings.config)
        real_patch, real_restore = domain._patch_config_paths, graph.settings._restore

        def patch(changes, **kwargs):
            result = real_patch(changes, **kwargs)
            graph.events.append(list(changes))
            return result

        def restore(snapshot):
            result = real_restore(snapshot)
            graph.events.append(
                [
                    (path, graph.settings.config.openai_compatible.model)
                    for path, _ in graph.events[0]
                ]
            )
            return result

        monkeypatch.setattr(domain, "_patch_config_paths", patch)
        monkeypatch.setattr(graph.settings, "_restore", restore)
        monkeypatch.setattr(
            __import__(MODULE, fromlist=["persist_config_paths_locked"]),
            "persist_config_paths_locked",
            None,
        )
        try:
            yield graph
        finally:
            GRAPH = None


def register_provider_config(*args):
    raise AssertionError("legacy route registration forbidden")


def _app(*registrars):
    assert GRAPH is not None and registrars == (register_provider_config,)
    return GRAPH, SimpleNamespace(config=GRAPH.settings.config, llm_gateway=GRAPH.owner)


def _gw(bot):
    assert bot.llm_gateway is GRAPH.owner
    return bot.llm_gateway


class TestServer:
    __test__ = False

    def __init__(self, graph):
        self.graph = graph


class TestClient:
    __test__ = False

    def __init__(self, server):
        self.graph = server.graph

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def put(self, path, *, json):
        assert path == "/api/openai-compatible/config"
        result = await save(
            self.graph,
            "providers.compat.set",
            *((f"openai_compatible.{name}", value) for name, value in json.items()),
        )
        if persist_config_paths_locked is not None:
            for event in self.graph.events:
                await persist_config_paths_locked(event)
        return result


def load(namespace):
    module = ModuleType("desktop_review_provider_reload_frozen")
    exec(compile(adapted_tree(), PATH, "exec"), module.__dict__)
    register_module(namespace, module)
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        if getattr(value, "__module__", None) == module.__name__:
            value.__module__ = namespace["__name__"]
        namespace[name] = value
    namespace["desktop_provider_graph"] = desktop_provider_graph
