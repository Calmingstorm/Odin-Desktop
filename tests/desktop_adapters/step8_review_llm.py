"""PR34 exact, partial frozen LLM-admin restoration over private domain owners.

This is not an HTTP server. The familiar request spelling is a fixture carrier
for named Desktop commands. Only actual MethodError verdicts become failures;
only committed SettingsService fields become a configuration response.
"""
from __future__ import annotations

import ast
import contextvars
import copy
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, nodes
from src.config.schema import Config
from tests.desktop_adapters.review_provider_llm import CommandResponse, command, provider_graph

PATH = "tests/test_web_api_llm_admin.py"
SOURCE_SHA256 = "f3fc8276fc85ab39e3234dff0f902e1d800d8f64ec6d0c58c2d5aa01d26980d1"
RECORD = Path(__file__).resolve().parents[2] / "maintenance/step8-part2-review-llm.json"
_graph = contextvars.ContextVar("pr34_llm_graph")


class ReloadEvidence:
    """Read-only evidence of real concrete client construction, not a reload mock."""

    def __init__(self):
        self.await_count = 0

    def assert_awaited(self):
        assert self.await_count > 0

    def assert_not_awaited(self):
        assert self.await_count == 0

    def assert_awaited_once(self):
        assert self.await_count == 1


class GatewayView:
    def __init__(self, graph):
        self.graph = graph
        for name in ("codex", "ollama", "openai_compatible"):
            setattr(self, f"reload_{name}_inner", ReloadEvidence())
        self.reload_auxiliary = ReloadEvidence()


class BotView:
    def __init__(self, graph):
        self.graph = graph
        self.llm_gateway = graph.evidence

    @property
    def config(self):
        return self.graph.settings.config

    @property
    def tool_catalog(self):
        return self.graph.owner.tool_catalog

    @tool_catalog.setter
    def tool_catalog(self, value):
        self.graph.owner.tool_catalog = value


def bot():
    return _graph.get().bot


def gateway(_bot):
    return _bot.llm_gateway


def app(*_registrars, bot=None):
    graph = _graph.get()
    return graph, bot or graph.bot


@contextmanager
def capture_persistence():
    """Observe the real disk writer without replacing persistence outcomes."""
    from src.desktop import settings

    original = settings._patch_config_paths
    seen = MagicMock()

    def observe(changes, **kwargs):
        seen(changes)
        return original(changes, **kwargs)

    with patch.object(settings, "_patch_config_paths", observe):
        yield seen


def _changes(prefix, payload):
    changes = []
    for key, value in payload.items():
        if key in {"retry", "connection_pool", "context_compression"} and isinstance(value, dict):
            changes.extend({"path": f"{prefix}.{key}.{leaf}", "value": item}
                           for leaf, item in value.items())
        else:
            changes.append({"path": f"{prefix}.{key}", "value": value})
    return changes


class PrivateClient:
    """Finite named-domain carrier. No listener, route registration or web handler."""

    def __init__(self, graph):
        self.graph = graph

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def put(self, path, *, json=None, data=None):
        if path == "/api/llm/main-model":
            return await command(self.graph, "models.main.set", json if data is None else data)
        method, prefix = {
            "/api/llm/codex/config": ("providers.codex.set", "openai_codex"),
            "/api/llm/ollama/config": ("providers.ollama.set", "ollama"),
            "/api/openai-compatible/config": ("providers.compat.set", "openai_compatible"),
            "/api/llm/auxiliary/config": ("providers.auxiliary.set", "openai_codex.auxiliary"),
        }[path]
        # Non-object admission is performed by the genuine private service.
        params = data if data is not None else {
            "expected_revision": self.graph.settings.revision,
            "changes": _changes(prefix, json),
        }
        response = await command(self.graph, method, params)
        if response.verdict is not None:
            return response
        fields = response.body["fields"]
        payload = {"status": "updated"}
        # These values come from the saved result, not from submitted input or
        # a second desired Config read. Secrets are intentionally not projected.
        for field in fields:
            relative = field["path"][len(prefix) + 1:]
            cursor = payload
            segments = relative.split(".")
            for part in segments[:-1]:
                cursor = cursor.setdefault(part, {})
            cursor[segments[-1]] = field["desired"]
        return CommandResponse(payload)


def server(graph):
    return graph


def source_tree():
    source = frozen_source(PATH)
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA256
    return ast.parse(source)


def _replace(tree, rule, reverse=False):
    before = rule["after_sha256"] if reverse else rule["before_sha256"]
    matches = [node for symbol, node in nodes(tree)
               if symbol == rule["symbol"]
               and getattr(node, "lineno", None) == rule["line"]
               and hashlib.sha256(dump(node).encode()).hexdigest() == before]
    assert len(matches) == 1, (rule["symbol"], rule["line"])
    target = matches[0]
    if reverse:
        originals = [node for symbol, node in nodes(source_tree())
                     if symbol == rule["symbol"]
                     and getattr(node, "lineno", None) == rule["line"]
                     and hashlib.sha256(dump(node).encode()).hexdigest() == rule["before_sha256"]]
        assert len(originals) == 1
        replacement = copy.deepcopy(originals[0])
    else:
        text = rule["after_source"]
        replacement = (ast.parse(text, mode="eval").body
                       if rule["kind"] == "expression" else ast.parse(text).body[0])
    expected_hash = rule["before_sha256"] if reverse else rule["after_sha256"]
    assert hashlib.sha256(dump(replacement).encode()).hexdigest() == expected_hash

    class Exact(ast.NodeTransformer):
        def visit(self, node):
            if node is target:
                return ast.copy_location(replacement, node)
            return super().visit(node)

    return Exact().visit(tree)


def adapted_tree():
    original = source_tree()
    tree = copy.deepcopy(original)
    rules = json.loads(RECORD.read_text())["setup_hunks"]
    for rule in rules:
        tree = _replace(tree, rule)
    assert corpus(original) == corpus(tree), "Inherited assertions/signatures/decorators changed"
    reverted = copy.deepcopy(tree)
    for rule in reversed(rules):
        reverted = _replace(reverted, rule, reverse=True)
    assert dump(reverted) == dump(original), "Setup replacements are not exactly reversible"
    return ast.fix_missing_locations(tree)


def load(namespace):
    """Export only explicit applicable test selectors; retain ALL frozen bytes."""
    record = json.loads(RECORD.read_text())
    tree = adapted_tree()
    selected = set(record["entries"][0]["partial"]["selectors"])
    module = ModuleType("desktop_pr34_llm_partial")
    module.__dict__.update(carrier=__import__(__name__, fromlist=["load"]),
                           TestClient=PrivateClient, TestServer=server,
                           register_llm_provider="models.main.set",
                           register_provider_config="providers.codex.set",
                           register_ollama_admin="ollama-admin-excluded",
                           register_kimi_admin="compat-admin-excluded")
    exec(compile(tree, PATH, "exec"), module.__dict__)
    # Frozen carrier imports are inert; replace their names only after loading.
    module.__dict__.update(TestClient=PrivateClient, TestServer=server)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not node.name.startswith("Test"):
            continue
        cls = module.__dict__[node.name]
        for member in node.body:
            if (isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and member.name.startswith("test_")):
                selector = f"{node.name}::{member.name}"
                if selector not in selected:
                    delattr(cls, member.name)
        if any(key.startswith("test_") for key in vars(cls)):
            cls.__module__ = namespace["__name__"]
            namespace[node.name] = cls
    inherited_selectors = {symbol.replace(".", "::") for symbol, node in nodes(tree)
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and node.name.startswith("test_")}
    assert selected <= inherited_selectors
    assert not any("::" not in selector for selector in selected), (
        "Top-level cases require explicit exporter support")
    # Only admitted helper fixtures are exported. No obsolete persist/global
    # route stubs are registered and no excluded case is skipped at runtime.
    # Do not re-export empty excluded classes. Inherited methods retain their
    # original module globals, while only explicitly admitted cases collect.


async def isolated_graph(tmp_path):
    """Construct real profile graph with fixture-only credentials in its keyring."""
    config = Config(openai_codex={"enabled": True})
    async with provider_graph(tmp_path, config=config) as graph:
        graph.accounts.vault.write([{
            "access_token": "fixture-not-a-real-token", "account_id": "fixture-owner",
            "refresh_token": "fixture-not-a-real-refresh", "expires_at": 4102444800,
        }])
        # Admit the real boot client before installing observation counters.
        # Agent-only assertions then prove absence of actual client churn,
        # rather than trivially checking an unconfigured runtime.
        await graph.owner.ensure_ready()
        graph.evidence = GatewayView(graph)
        graph.bot = BotView(graph)
        build = graph.owner._build

        def observed_build(provider, *args, **kwargs):
            client = build(provider, *args, **kwargs)
            if client is not None:
                name = "openai_compatible" if provider == "compat" else provider
                getattr(graph.evidence, f"reload_{name}_inner").await_count += 1
            return client

        graph.owner._build = observed_build
        token = _graph.set(graph)
        try:
            yield graph
        finally:
            _graph.reset(token)
