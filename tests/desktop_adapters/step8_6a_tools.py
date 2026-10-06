"""Hash/corpus-bound inherited tool cases using private Desktop services."""
# ruff: noqa: E501
from __future__ import annotations

import ast
import contextvars
import copy
import hashlib
import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from _pytest.fixtures import FixtureFunctionDefinition

from scripts.maintenance.fixture_corpus import (
    case_mapping,
    corpus,
    dump,
    frozen_source,
    nodes,
    register_module,
)
from src.desktop.authority import OwnerAuthority
from src.desktop.mcp import MCPService
from src.desktop.paths import ProfilePaths
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService, fresh_config
from src.permissions.manager import PermissionManager
from src.tools.executor import ToolExecutor as EngineExecutor
from src.tools.mcp.manager import MCPManager as EngineMCPManager

STATE = contextvars.ContextVar("step8_6a_owner", default=None)
DISPATCH = contextvars.ContextVar("step8_6a_mcp_dispatch", default=False)
CASE_MAP = {}
TRANSFORMS = {}
MODULES = []
HOST = "shell-test-local"
USER = None
CORPUS_SELECTIONS = {
    "test_mcp_manager": None,
    "test_mcp_edges": None,
    "test_mcp_client_eras": None,
    "test_mcp_transport_http": None,
    "test_codex_replay_boundaries": None,
    "test_branch_freshness": None,
    "test_browser_wait_timeout": None,
    "test_mcp_media_checkpoint": None,
}
SUITES = {
    "test_mcp_manager": "e1bc52991260c7890115df0d4b26df7afa8a47c8160df580d5633fc682939ed3",
    "test_mcp_edges": "42dcd4392df123a0be27bc081b3a612eb4241814805e559084f4858515a69df3",
    "test_mcp_client_eras": "62c51bc82631c0554f09138ceccf7461c069e7231da58377ca55751a8cdc73a8",
    "test_mcp_transport_http": "be86586786e7cb0f22d94649bb82df033f212476831ded04b077cf2352b83301",
    "test_codex_replay_boundaries": "31ccc09d0d7d34ab0baf55cf8f16e03cadd62212e879c3da89a1d9028ebc4f1b",
    "test_branch_freshness": "42fcad58f0474c381db61d12829fa351b18df2dc7a054c25ead3017feb313871",
    "test_browser_wait_timeout": "32036111f71c333db06ecaa87227b8c44bfd9d94de236af843994ea8b6bafa99",
    "test_mcp_media_checkpoint": "b753c0ce54463d2d0eaa161974ea9ffe970066bfb4494f62ded245f699580ef6",
}
CORPUS_EXCLUSIONS = {
    "test_branch_freshness": [
        {"case": "TestFreshnessAPI.test_recent_endpoint", "reviewer": "Claude, review of step 8 part 4", "reason": "GET /api/freshness/recent is a removed Odin web UI HTTP listener route.", "source_path": "tests/test_branch_freshness.py", "source_sha256": "42fcad58f0474c381db61d12829fa351b18df2dc7a054c25ead3017feb313871"},
        {"case": "TestFreshnessAPI.test_recent_no_executor", "reviewer": "Claude, review of step 8 part 4", "reason": "503 response from GET /api/freshness/recent is a removed Odin web UI HTTP listener contract.", "source_path": "tests/test_branch_freshness.py", "source_sha256": "42fcad58f0474c381db61d12829fa351b18df2dc7a054c25ead3017feb313871"},
        {"case": "TestFreshnessAPI.test_recent_with_limit", "reviewer": "Claude, review of step 8 part 4", "reason": "GET /api/freshness/recent?limit=5 is a removed Odin web UI HTTP listener route.", "source_path": "tests/test_branch_freshness.py", "source_sha256": "42fcad58f0474c381db61d12829fa351b18df2dc7a054c25ead3017feb313871"},
        {"case": "TestFreshnessAPI.test_stats_endpoint", "reviewer": "Claude, review of step 8 part 4", "reason": "GET /api/freshness/stats is a removed Odin web UI HTTP listener route.", "source_path": "tests/test_branch_freshness.py", "source_sha256": "42fcad58f0474c381db61d12829fa351b18df2dc7a054c25ead3017feb313871"},
        {"case": "TestFreshnessAPI.test_stats_no_executor", "reviewer": "Claude, review of step 8 part 4", "reason": "503 response from GET /api/freshness/stats is a removed Odin web UI HTTP listener contract.", "source_path": "tests/test_branch_freshness.py", "source_sha256": "42fcad58f0474c381db61d12829fa351b18df2dc7a054c25ead3017feb313871"},
    ],
}


@asynccontextmanager
async def owner_fixture(tmp_path):
    if os.geteuid() == 0:
        raise RuntimeError("isolated non-root runner required")
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    authority.acquire_runtime()
    permissions = PermissionManager(authority)
    binding = permissions.set_request_owner(authority.authenticate_local(peer_uid=os.geteuid()))
    settings = SettingsService(paths, ProfileSecretStore(paths), config=fresh_config(paths))
    state = SimpleNamespace(paths=paths, authority=authority, permissions=permissions,
                            settings=settings, managers=[], engines=[], browsers=[])
    token = STATE.set(state)
    try:
        yield state
    finally:
        for manager in reversed(state.managers):
            await manager.desktop_service.close()
        for engine in reversed(state.engines):
            await engine.close()
        for browser in reversed(state.browsers):
            await browser.close()
        STATE.reset(token)
        permissions.reset_request_owner(binding)
        authority.release_runtime()


class MCPManager(EngineMCPManager):
    """Same retained engine, admitted through the genuine MCPService seam."""
    def __init__(self, *args, **kwargs):
        state = STATE.get()
        if state is None:
            raise RuntimeError("MCP setup requires canonical owner fixture")
        super().__init__(*args, **kwargs)
        self.desktop_service = MCPService(state.settings, permissions=state.permissions,
                                          manager=self)
        state.managers.append(self)

    async def execute(self, name, tool_input):
        if DISPATCH.get():
            return await super().execute(name, tool_input)
        token = DISPATCH.set(True)
        try:
            return await self.desktop_service.execute(
                name, tool_input, owner_id=STATE.get().authority.owner_id)
        finally:
            DISPATCH.reset(token)


def engine_for(executor=None):
    from src.desktop.services import build_engine_services
    state = STATE.get()
    cfg = fresh_config(state.paths)
    cfg.openai_codex.enabled = False
    cfg.ollama.enabled = False
    cfg.openai_compatible.enabled = False
    cfg.browser.enabled = False
    cfg.learning.enabled = False
    runtime = SimpleNamespace(tool_executor=executor) if executor is not None else None
    engine = build_engine_services(cfg, state.paths, state.permissions,
                                   delivery=None, runtime_context=runtime)
    state.engines.append(engine)
    return engine


def desktop_runner():
    return engine_for().runner


def desktop_media_manager(outcome):
    """Actual MCPService with protocol outcome injected at its retained backend."""
    from unittest.mock import AsyncMock

    state = STATE.get()
    manager = EngineMCPManager()
    manager.execute = AsyncMock(return_value=outcome)
    service = MCPService(state.settings, permissions=state.permissions, manager=manager)
    original = service.execute

    async def admitted(name, payload):
        return await original(name, payload, owner_id=state.authority.owner_id)

    service.execute = AsyncMock(side_effect=admitted)
    return service


class ToolExecutor(EngineExecutor):
    def __init__(self, *args, **kwargs):
        state = STATE.get()
        kwargs.setdefault("profile_paths", state.paths)
        kwargs.setdefault("permission_manager", state.permissions)
        kwargs.setdefault("memory_path", str(state.paths.data_dir / "memory.json"))
        super().__init__(*args, **kwargs)
        engine_for(self)
        self.set_user_context(state.authority.owner_id)


from src.desktop.browser_runtime import BrowserRuntime  # noqa: E402


class BrowserManager(BrowserRuntime):
    """Real profile BrowserRuntime, including qualified bundled Chromium startup."""
    def __init__(self, max_wait_timeout_seconds=60, allow_private_targets=None):
        from src.config.schema import BrowserConfig

        config = BrowserConfig(enabled=True,
                               max_wait_timeout_seconds=max(1, min(60, max_wait_timeout_seconds)),
                               allow_private_targets=allow_private_targets or [])
        super().__init__(config, STATE.get().paths,
                         bundle_root=Path("/home/odin/desktop-p41-final-stage/runtime"))
        STATE.get().browsers.append(self)

    async def _ensure_connected(self):
        if not await self.start():
            raise RuntimeError(self.status()["reason"])

    shutdown = BrowserRuntime.close


def make_bot(*, config_overrides):
    from src.config.schema import Config

    cfg = Config(**config_overrides)
    # This fixture exposes real owners, not a simulated bot/service implementation.
    return SimpleNamespace(config=cfg, browser_manager=BrowserManager(
        max_wait_timeout_seconds=cfg.browser.max_wait_timeout_seconds))


@pytest.fixture
async def runtime(tmp_path, monkeypatch):
    from src.config.schema import ToolHost, ToolsConfig
    from src.desktop.services import build_engine_services
    from src.tools.process_manager import ProcessRegistry

    state = STATE.get()
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700, exist_ok=True)
    cfg = fresh_config(state.paths)
    cfg.openai_codex.enabled = cfg.ollama.enabled = cfg.openai_compatible.enabled = False
    cfg.learning.enabled = cfg.browser.enabled = False
    cfg.tools = ToolsConfig(hosts={HOST: ToolHost(address="127.0.0.1")},
                            default_host=HOST, local_working_dir=str(workspace),
                            audit_log_path=str(state.paths.data_dir / "shell-audit.jsonl"),
                            recovery={"enabled": False}, branch_freshness={"enabled": False})
    engine = build_engine_services(cfg, state.paths, state.permissions, delivery=None)
    executor, hosts = engine.deps.tool_executor, engine.deps.host_registry
    executor.set_user_context(state.authority.owner_id)
    for module in MODULES:
        monkeypatch.setitem(module.__dict__, "USER", state.authority.owner_id)
    monkeypatch.setitem(globals(), "USER", state.authority.owner_id)
    value = SimpleNamespace(executor=executor, config=cfg.tools,
                            skills=engine.deps.skill_manager, data=state.paths.data_dir,
                            state=engine.deps.channel_state, engine=engine,
                            authority=state.authority)
    try:
        yield value
    finally:
        registry = getattr(executor, "_process_registry", None)
        if registry is not None:
            assert isinstance(registry, ProcessRegistry)
        await engine.close()
        assert not hosts.has_active_leases(HOST)


def adapted_tree(name):
    path = f"tests/{name}.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES[name]:
        raise AssertionError("inherited source hash changed")
    original = ast.parse(source, filename=path)
    adapted = copy.deepcopy(original)
    changes = []
    for symbol, node in list(nodes(adapted)):
        if (name == "test_mcp_media_checkpoint" and isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "SimpleNamespace"
                and len(node.keywords) == 1 and node.keywords[0].arg == "execute"):
            before = dump(node)
            node.func = ast.Name(id="desktop_media_manager", ctx=ast.Load())
            node.args = [ast.Name(id="outcome", ctx=ast.Load())]
            node.keywords = []
            changes.append({"symbol": symbol, "line": node.lineno,
                            "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                            "after_source": ast.unparse(node), "kind": "expression",
                            "operation": "real_mcp_service_outcome_setup"})
        if name == "test_browser_wait_timeout" and isinstance(node, ast.ImportFrom):
            if node.module == "tests.fakes" and [a.name for a in node.names] == ["make_bot"]:
                before = dump(node)
                node.module = __name__
                changes.append({"symbol": symbol, "line": node.lineno,
                                "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                                "after_source": ast.unparse(node), "kind": "statement",
                                "operation": "real_browser_runtime_setup"})
            if node.module == "src.tools.browser":
                swapped = [a for a in node.names if a.name == "BrowserManager"]
                if swapped:
                    kept = [a for a in node.names if a.name != "BrowserManager"]
                    before = dump(node)
                    replacement = [ast.ImportFrom(module=__name__, names=swapped, level=0),
                                   ast.ImportFrom(module=node.module, names=kept, level=0)]
                    changes.append({"symbol": symbol, "line": node.lineno,
                                    "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                                    "after_source": "\n".join(ast.unparse(n) for n in replacement),
                                    "kind": "statement", "operation": "real_browser_runtime_import"})

                    class ReplaceBrowser(ast.NodeTransformer):
                        def visit(self, item):
                            if item is node:
                                return [ast.copy_location(n, item) for n in replacement]
                            return super().visit(item)

                    adapted = ReplaceBrowser().visit(adapted)
        if isinstance(node, ast.ImportFrom) and node.module == "tests.test_command_shell_callers":
            before = dump(node)
            node.module = __name__
            changes.append({"symbol": symbol, "line": node.lineno,
                            "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                            "after_source": ast.unparse(node), "kind": "statement",
                            "operation": "real_desktop_runtime_import"})
        if isinstance(node, ast.ImportFrom) and node.module == "src.tools.executor":
            if all(alias.name == "ToolExecutor" for alias in node.names):
                before = dump(node)
                node.module = __name__
                changes.append({"symbol": symbol, "line": node.lineno,
                                "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                                "after_source": ast.unparse(node), "kind": "statement",
                                "operation": "exact_setup_import"})
        if name == "test_codex_replay_boundaries" and isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "__new__"
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "object"
                    and len(node.args) == 1 and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "ToolLoopRunner"):
                before = dump(node)
                node.func = ast.Name(id="desktop_runner", ctx=ast.Load())
                node.args = []
                changes.append({"symbol": symbol, "line": node.lineno,
                                "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                                "after_source": ast.unparse(node), "kind": "expression",
                                "operation": "real_desktop_runner_setup"})
        if isinstance(node, ast.ImportFrom) and node.module == "src.tools.mcp.manager":
            swapped = [a for a in node.names if a.name == "MCPManager"]
            if not swapped:
                continue
            kept = [a for a in node.names if a.name != "MCPManager"]
            replacement = [ast.ImportFrom(module=__name__, names=swapped, level=0)]
            if kept:
                replacement.append(ast.ImportFrom(module=node.module, names=kept, level=0))
            changes.append({"symbol": symbol, "line": node.lineno,
                            "before_sha256": hashlib.sha256(dump(node).encode()).hexdigest(),
                            "after_source": "\n".join(ast.unparse(n) for n in replacement),
                            "kind": "statement", "operation": "exact_setup_import"})

            class Replace(ast.NodeTransformer):
                def visit(self, item):
                    if item is node:
                        return [ast.copy_location(n, item) for n in replacement]
                    return super().visit(item)

            adapted = Replace().visit(adapted)
    assert corpus(original) == corpus(adapted)
    # Exact replacement digests use fixture_corpus' representation contract.
    for change in changes:
        if change["kind"] == "expression":
            replacement = ast.parse(change["after_source"], mode="eval").body
            representation = dump(replacement)
        else:
            import json

            replacement = ast.parse(change["after_source"]).body
            representation = json.dumps([dump(item) for item in replacement])
        change["after_sha256"] = hashlib.sha256(representation.encode()).hexdigest()
    TRANSFORMS[path] = changes
    return original, ast.fix_missing_locations(adapted)


def load(namespace):
    for name in SUITES:
        _, adapted = adapted_tree(name)
        excluded = {item["case"] for item in CORPUS_EXCLUSIONS.get(name, ())}
        for entry in case_mapping(f"tests/{name}.py", adapted, __name__, prefix=name):
            symbol = entry["baseline_selector"].split("::", 1)[1].replace("::", ".")
            if symbol not in excluded:
                CASE_MAP[entry["baseline_selector"]] = (
                    "tests/test_desktop_step8_6a_tools_corpus.py::" + entry["executable_case"])
        module = ModuleType(f"step8_6a_frozen_{name}")
        module.__file__ = str(Path(__file__).resolve().parents[1] / f"{name}.py")
        module.desktop_runner = desktop_runner
        module.desktop_media_manager = desktop_media_manager
        exec(compile(adapted, module.__file__, "exec"), module.__dict__)
        MODULES.append(module)
        for key, value in vars(module).items():
            if hasattr(value, "_pytestfixturefunction") or isinstance(value, FixtureFunctionDefinition):
                namespace[key] = value
        register_module(namespace, module, prefix=name,
                        excluded=[item['case'] for item in CORPUS_EXCLUSIONS.get(name, ())])
