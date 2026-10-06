"""Whole frozen recovery/pool suites with setup-only profile adaptation.

Actual owner authority and BuiltinToolPolicy govern virtual handler readiness;
historical config-default declarations are inert and pools use temporary paths.
Pool child cleanup executes only under the mandatory isolated PID runner.
HTTP-shaped fixtures dispatch actual named methods without network listeners.
All assertions, case data, decorators and signatures remain source-identical.
"""

from __future__ import annotations

import ast
import contextvars
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src.config.schema import Config as ProfileConfig
from src.config.schema import SSHPoolConfig as ProfileSSHPoolConfig
from src.desktop.authority import OwnerAuthority
from src.desktop.observability import ObservabilityService
from src.desktop.paths import ProfilePaths
from src.permissions.host_access import HostAccessManager
from src.permissions.manager import PermissionManager as OwnerPermissionManager
from src.tools.builtin_policy import BuiltinToolPolicy
from src.tools.executor import ToolExecutor as EngineExecutor
from tests.desktop_adapters import step5_observability_http as http

ROOT = Path(__file__).resolve().parents[2]
_fixture = contextvars.ContextVar("desktop_observability_fixture", default=None)

FIXTURE_CAPABILITIES = frozenset({
    "test_tool", "tool_a", "tool_b", "weird_tool", "nonexistent_tool",
})


@contextmanager
def owner_fixture(tmp_path):
    """Authentic owner setup, independent of partial tool-corpus loaders.

    Keep this adapter's import closure entirely whole-suite: tools_cases also
    admits unrelated partial corpora, which are not this loader's authority.
    """
    if os.geteuid() == 0:
        raise RuntimeError("use isolated runner as non-root")
    paths = ProfilePaths.from_xdg(
        environ={
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
        home=tmp_path,
    )
    authority = OwnerAuthority(paths)
    manager = OwnerPermissionManager(authority)
    context = authority.authenticate_local(peer_uid=os.geteuid())
    request_binding = manager.set_request_owner(context)
    state = SimpleNamespace(paths=paths, authority=authority, manager=manager, executors=[])
    fixture_binding = _fixture.set(state)
    try:
        yield state
    finally:
        for executor in state.executors:
            executor.set_user_context(None)
        _fixture.reset(fixture_binding)
        manager.reset_request_owner(request_binding)
        authority.release_runtime()


class ToolExecutor(EngineExecutor):
    """Real executor and readiness policy over the source's virtual handlers."""
    def __init__(self, *args, **kwargs):
        state = _fixture.get()
        if state is None:
            raise RuntimeError("adapter requires owner_fixture")
        kwargs.setdefault("profile_paths", state.paths)
        kwargs.setdefault("permission_manager", state.manager)
        kwargs.setdefault("memory_path", str(state.paths.data_dir / "memory.json"))
        super().__init__(*args, **kwargs)
        self._host_access = HostAccessManager(
            state.paths.config_dir / f"test-host-preferences-{len(state.executors)}.json",
            available_hosts_provider=self.host_registry.active_aliases,
            permission_manager=state.manager,
        )
        self.readiness = dict.fromkeys((
            "apply_patch", "run_command", "validate_action", "get_tool_output",
            "read_file", "fetch_url", "email_send", "email_search", "email_read",
            "email_list_recent",
        ), True)
        self._builtin_policy = BuiltinToolPolicy(
            lambda: SimpleNamespace(tools=self.config),
            lambda: {**self.readiness, **{name: True for name in FIXTURE_CAPABILITIES}},
        )
        self.set_user_context(state.authority.owner_id)
        state.executors.append(self)

    async def execute(self, tool_name, tool_input, *, user_id=None):
        return await super().execute(
            tool_name, tool_input,
            user_id=_fixture.get().authority.owner_id if user_id is None else user_id,
        )


def fixture_permission_manager(*args, **kwargs):
    # The historical guest fixture becomes a real temporary owner manager.
    # Its explicitly supplied guest_user still lacks authenticated ownership.
    return _fixture.get().manager


PermissionManager = fixture_permission_manager


class SSHPoolConfig(ProfileSSHPoolConfig):
    # Historical default-string assertion only; actual pool fixtures all use
    # temporary socket_dir and never construct a pool from this declaration.
    socket_dir: str = "/tmp/odin_ssh_sockets"


def fixture_config(**kwargs):
    kwargs.pop("discord", None)
    return ProfileConfig(**kwargs)


Config = fixture_config


class TestClient(http.TestClient):
    @staticmethod
    def _observability(bot):
        executor = getattr(bot, "tool_executor", None)
        if executor is not None:
            executor = SimpleNamespace(ssh_pool=getattr(executor, "ssh_pool", None),
                                       recovery_stats=getattr(executor, "recovery_stats", None))
        gateway = getattr(bot, "llm_gateway", None)
        if gateway is not None:
            gateway = SimpleNamespace(codex_client=getattr(gateway, "codex_client", None),
                                      ollama_client=getattr(gateway, "ollama_client", None),
                                      compatible_client=None)
        return ObservabilityService(executor=executor, gateway=gateway)

CORPUS_SELECTIONS = {
    "test_recovery": None,
    "test_connection_pools": None,
}

SUITES = {
    "test_recovery": "ca668c6b04afc607b73312fa113a5dd5b0cb29dfa7e01ca973d20fa31285eab3",
    "test_connection_pools": "a49030a9d9eac9f6947cc0ee6eafa5d726843e9bf54c926ddd3191bf2adff369",
}

CORPUS_EXCLUSIONS = {}
BLOCKED_SUITES = {}


class SetupOnly(ast.NodeTransformer):
    """Replace only unavailable service fixtures and their retired route surface."""

    def visit_ImportFrom(self, node):
        if node.module == "src.config.schema" and any(
            alias.name in {"SSHPoolConfig", "Config"} for alias in node.names
        ):
            # Mixed imports keep the real remaining declared config models.
            names = []
            for alias in node.names:
                names.append(ast.ImportFrom(
                    module=__name__ if alias.name in {"SSHPoolConfig", "Config"}
                    else "src.config.schema", names=[alias], level=0,
                ))
            return [ast.copy_location(item, node) for item in names]
        if node.module == "src.tools.executor" and all(
            alias.name == "ToolExecutor" for alias in node.names
        ):
            node.module = __name__
        if node.module == "src.permissions.manager" and all(
            alias.name == "PermissionManager" for alias in node.names
        ):
            node.module = __name__
        if node.module == "aiohttp" and all(alias.name == "web" for alias in node.names):
            node.module = "tests.desktop_adapters.step5_observability_http"
        if node.module == "aiohttp.test_utils":
            node.module = __name__
        if node.module == "src.web.api":
            names = [alias for alias in node.names if alias.name == "create_api_routes"]
            if names:
                return ast.copy_location(ast.ImportFrom(
                    module="tests.desktop_adapters.step5_observability_neutral",
                    names=[ast.alias(name="create_api_routes", asname=None)], level=0,
                ), node)
        if node.module == "src.web.api" and any(alias.name == "setup_api" for alias in node.names):
            return ast.copy_location(ast.ImportFrom(
                module="tests.desktop_adapters.step5_observability_neutral",
                names=[ast.alias(name="setup_api", asname=None)], level=0,
            ), node)
        return node


def create_api_routes(_bot):
    """Socket-free fixture boundary forwards to the actual named recovery owner."""
    routes = http.RouteTableDef()
    http.register_recovery_stats(routes, _bot)
    http._register(routes, _bot, (
        ("GET", "/api/pools/ssh", "observability", "pools.ssh"),
        ("GET", "/api/pools/http", "observability", "pools.http"),
        ("POST", "/api/pools/ssh/close", "observability", "pools.close"),
    ))
    return routes


def setup_api(_app, _bot):
    _app.router.add_routes(create_api_routes(_bot))


TestServer = http.TestServer


def _load_suite(suite):
    if suite not in CORPUS_SELECTIONS:
        raise ValueError("suite has not been audited")
    path = f"tests/{suite}.py"
    source = frozen_source(path)
    if hashlib.sha256(
        source.encode() if isinstance(source, str) else source,
    ).hexdigest() != SUITES[suite]:
        raise AssertionError(f"frozen source digest changed: {path}")
    original = ast.parse(source, filename=path)
    adapted = SetupOnly().visit(ast.parse(source, filename=path))
    ast.fix_missing_locations(adapted)
    if corpus(original) != corpus(adapted):
        raise AssertionError(f"test corpus changed: {path}")
    if suite in BLOCKED_SUITES:
        raise RuntimeError(f"Frozen suite is blocked, not restored: {BLOCKED_SUITES[suite]}")
    module = ModuleType(f"desktop_step5_neutral_{suite}")
    module.__file__ = str(ROOT / path)
    module.create_api_routes = create_api_routes
    module.setup_api = setup_api
    exec(compile(adapted, module.__file__, "exec"), module.__dict__)
    return module


def register_module(namespace, suite):
    module = _load_suite(suite)
    for name, value in vars(module).items():
        if name.startswith("test_"):
            value.__module__ = namespace["__name__"]
            namespace[f"test_neutral_{suite[5:]}__{name[5:]}"] = value
        elif name.startswith("Test"):
            value.__module__ = namespace["__name__"]
            for member in vars(value).values():
                if callable(member) and hasattr(member, "__module__"):
                    member.__module__ = namespace["__name__"]
            namespace[f"TestNeutral_{suite[5:]}_{name[4:]}"] = value


def load(namespace):
    for suite in CORPUS_SELECTIONS:
        register_module(namespace, suite)

