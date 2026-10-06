"""Explicit partial inherited image cases, not whole-suite restoration."""

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, nodes, register_module
from src.desktop.management import MethodError
from tests.desktop_adapters import review_provider_image as frozen
from tests.desktop_adapters.review_provider_llm import CommandResponse

SELECTION = frozenset(
    {
        "test_metadata_uses_presence_not_default_equality",
        "test_follow_both_atomic_preserves_other_text_and_runtime",
        "test_generic_roundtrip_preserves_follow_and_pin",
        "test_bad_operation_rejected",
        "test_equal_value_pin_invalidates_stale_follow_revision",
    }
)
MODULE = "tests.desktop_adapters.review_provider_image_inherited"


def config_fixture(**kwargs):
    from src.config.schema import Config as ActualConfig

    discord = kwargs.pop("discord", None)
    assert discord is None or (
        isinstance(discord, dict)
        and set(discord) == {"token"}
        and isinstance(discord["token"], str)
    )
    return ActualConfig(**kwargs)


Config = config_fixture


class Graph:
    def __init__(self, settings):
        self.settings = settings

    @property
    def config(self):
        return self.settings.config


def make_graph(tmp_path):
    settings = frozen.temporary_settings(tmp_path)
    settings.paths.config_file.write_text(
        "discord:\n  token: fake\n# keep this\nimage:\n  openai:\n    outer_model: custom-outer\n"
    )
    return Graph(settings)


class TestServer:
    __test__ = False

    def __init__(self, graph):
        self.graph = graph


class BaseTestClient:
    __test__ = False

    def __init__(self, server):
        self.graph = server.graph

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def project(self, result):
        payload = dict(result)
        if "image_models" in payload:
            payload["image_model_defaults"] = payload.pop("image_models")
        if "image_models_revision" in payload:
            payload["image_model_revision"] = payload.pop("image_models_revision")
        return CommandResponse(payload)

    async def get(self, path):
        assert path == "/api/config/meta"
        return self.project(await self.graph.settings.handle("settings.schema", {}))

    async def post(self, path, **kwargs):
        assert path == "/api/config/image-models"
        try:
            return self.project(
                await self.graph.settings.handle("models.image.intent", kwargs.get("json"))
            )
        except MethodError as error:
            return CommandResponse(error=error)

    async def put(self, path, *, json):
        assert path == "/api/config"
        try:
            return self.project(
                await self.graph.settings.handle(
                    "settings.set",
                    {
                        "expected_revision": self.graph.settings.revision,
                        "changes": [{"path": name, "value": value} for name, value in json.items()],
                    },
                )
            )
        except MethodError as error:
            return CommandResponse(error=error)


TestClient = BaseTestClient


def hunk_pairs():
    pairs = []
    for symbol, node in nodes(frozen.source_tree()):
        replacement = None
        if isinstance(node, ast.ImportFrom) and node.module == "aiohttp.test_utils":
            replacement = copy.deepcopy(node)
            replacement.module = MODULE
        elif isinstance(node, ast.FunctionDef) and node.name == "state":
            replacement = ast.parse("""def state(tmp_path):
    graph = make_graph(tmp_path)
    yield graph, graph, graph.settings.paths.config_file
""").body[0]
            replacement.decorator_list = copy.deepcopy(node.decorator_list)
        elif isinstance(node, ast.ImportFrom) and node.module == "src.config.schema":
            replacement = ast.parse(f"from {MODULE} import Config").body[0]
        if replacement is not None:
            pairs.append((symbol, node.lineno, node, replacement))
    return pairs


def hunk_records():
    return [
        {
            "path": frozen.PATH,
            "symbol": symbol,
            "line": line,
            "before_source": ast.unparse(before),
            "after_source": ast.unparse(after),
            "before_sha256": hashlib.sha256(dump(before).encode()).hexdigest(),
            "after_sha256": hashlib.sha256(dump(after).encode()).hexdigest(),
            "reversible": True,
            "kind": "expression" if isinstance(before, ast.Call) else "statement",
        }
        for symbol, line, before, after in hunk_pairs()
    ]


def adapted_tree():
    original = frozen.source_tree()
    tree = copy.deepcopy(original)
    for symbol, line, before, after in hunk_pairs():
        matches = [
            n
            for s, n in nodes(tree)
            if s == symbol and getattr(n, "lineno", None) == line and dump(n) == dump(before)
        ]
        assert len(matches) == 1, (symbol, line)
        target = matches[0]

        class Replace(ast.NodeTransformer):
            def visit(self, node):
                if node is target:
                    return ast.copy_location(copy.deepcopy(after), node)
                return super().visit(node)

        tree = Replace().visit(tree)
    assert corpus(tree) == corpus(original)
    return ast.fix_missing_locations(tree)


def load_partial(namespace):
    tree = adapted_tree()
    tree.body = [
        n
        for n in tree.body
        if not (
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("test_")
            and n.name not in SELECTION
        )
    ]
    module = ModuleType("desktop_review_provider_image_partial")
    module.make_graph = make_graph
    exec(compile(tree, frozen.PATH, "exec"), module.__dict__)
    register_module(namespace, module)
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        if getattr(value, "__module__", None) == module.__name__:
            value.__module__ = namespace["__name__"]
        namespace[name] = value
