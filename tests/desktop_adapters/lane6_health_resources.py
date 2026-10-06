"""Whole frozen resource, context-window and ranked-search corpora.

The context-window observer is an LLM evidence store, not a desktop window
observer. Its pure engine tests need no native display and use no desktop API.
Real engine owners retained by desktop.services execute all restored cases.
Missing named management surfaces are explicit case-level deferrals, never
fake HTTP responders. Frozen assertions, parameters and decorators stay exact.
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
from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths
from src.permissions.manager import PermissionManager
from src.tools.executor import ToolExecutor

ROOT = Path(__file__).resolve().parents[2]
CORPUS_SELECTIONS = {
    "test_resource_usage": None,
    "test_window_observer": None,
    "test_search_output_capture": None,
}
SUITES = {
    "test_resource_usage": "a7b39991f16e208dd51635caceb1aee25f4099ec9bddbcadd80101aed871dcb1",
    "test_window_observer": "8df113168f7d220d99c68b71fe1571391e4102b7ced1095fa3501825a8943896",
    "test_search_output_capture": (
        "e9f008c122c7ac646b62635662eeb717f6df7804b2aef19c051c961e88f55468"
    ),
}
CORPUS_EXCLUSIONS = {}
_owner = contextvars.ContextVar("lane6_health_resources_owner", default=None)

RESOURCE_MANAGEMENT_BLOCKER = (
    "Desktop ObservabilityService has no named resource-usage method exposing "
    "session and trajectory counters. The collector survives, but management "
    "payload parity needs that concrete feature; no fabricated HTTP adapter."
)
WINDOW_MANAGEMENT_BLOCKER = (
    "Desktop ModelSettingsService/ObservabilityService have no context-windows "
    "management read/clear method exposing persisted clamps, account provenance, "
    "calibration, and saved-versus-boot-frozen runtime ceilings. The LLM observer "
    "and computation owners survive; this is not native display qualification."
)


@contextmanager
def owner_fixture(tmp_path):
    """Actual temporary profile authority; never a live profile or fake tier."""
    if os.geteuid() == 0:
        raise RuntimeError("Use the non-root PID-isolated repository runner")
    paths = ProfilePaths.from_xdg(environ={
        "XDG_CONFIG_HOME": str(tmp_path / "owner-config"),
        "XDG_DATA_HOME": str(tmp_path / "owner-data"),
        "XDG_CACHE_HOME": str(tmp_path / "owner-cache"),
    }, home=tmp_path)
    authority = OwnerAuthority(paths)
    manager = PermissionManager(authority)
    context = authority.authenticate_local(peer_uid=os.geteuid())
    request_binding = manager.set_request_owner(context)
    state = SimpleNamespace(paths=paths, authority=authority, manager=manager,
                            context=context, executor=None)
    binding = _owner.set(state)
    try:
        yield state
    finally:
        if state.executor is not None:
            state.executor.set_user_context(None)
        _owner.reset(binding)
        manager.reset_request_owner(request_binding)
        authority.release_runtime()


async def _execute_tool_captured(tool_name, tool_input, executor, skill_manager,
                                 knowledge_store, embedder, requester,
                                 *args, **kwargs):
    """Use the surviving captured-output owner with the real owner scope gate.

    Only the historical MagicMock executor setup is replaced. Search records,
    ranking, snapshots and formatting are handled by production code unchanged.
    """
    from src.discord.background_task import _execute_tool_captured as captured

    state = _owner.get()
    if state is None:
        raise RuntimeError("Captured output requires an authenticated owner fixture")
    if state.executor is None:
        state.executor = ToolExecutor(profile_paths=state.paths,
                                      permission_manager=state.manager,
                                      memory_path=str(state.paths.data_dir / "memory.json"))
        state.executor.set_user_context(state.authority.owner_id)
    kwargs["requester_id"] = state.authority.owner_id
    return await captured(tool_name, tool_input, state.executor, skill_manager,
                          knowledge_store, embedder, requester, *args, **kwargs)


class SetupOnly(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        if node.module == "src.discord.background_task" and all(
            name.name == "_execute_tool_captured" for name in node.names
        ):
            node.module = __name__
        return node


def disposition(suite, symbol):
    if suite == "test_resource_usage" and symbol.startswith("TestResourceUsageAPI."):
        return "deferred", RESOURCE_MANAGEMENT_BLOCKER
    if suite == "test_window_observer" and symbol.startswith("TestContextWindowsApi."):
        return "deferred", WINDOW_MANAGEMENT_BLOCKER
    return "restored", (
        "Actual copied engine owner; temporary authenticated profile; no listener or native display"
    )


def _load_suite(suite):
    if suite not in CORPUS_SELECTIONS:
        raise ValueError("Unaudited frozen suite")
    path = f"tests/{suite}.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES[suite]:
        raise AssertionError(f"Frozen source digest changed: {path}")
    original = ast.parse(source, filename=path)
    adapted = SetupOnly().visit(ast.parse(source, filename=path))
    ast.fix_missing_locations(adapted)
    if corpus(original) != corpus(adapted):
        raise AssertionError(f"Assertion/signature/decorator/parameter corpus changed: {path}")
    module = ModuleType(f"lane6_health_resources_{suite}")
    module.__file__ = str(ROOT / path)
    exec(compile(adapted, module.__file__, "exec"), module.__dict__)
    return module


def register_module(namespace, suite):
    module = _load_suite(suite)
    for name, value in vars(module).items():
        if name.startswith("test_"):
            if disposition(suite, name)[0] != "restored":
                continue
            value.__module__ = namespace["__name__"]
            namespace[f"test_resources_{suite[5:]}__{name[5:]}"] = value
        elif name.startswith("Test"):
            cases = [member_name for member_name in vars(value)
                     if member_name.startswith("test_")]
            restored = [member_name for member_name in cases
                        if disposition(suite, f"{name}.{member_name}")[0] == "restored"]
            if not restored:
                continue
            for member_name in cases:
                if member_name not in restored:
                    delattr(value, member_name)
            value.__module__ = namespace["__name__"]
            for member_name, member in vars(value).items():
                if callable(member) and hasattr(member, "__module__"):
                    member.__module__ = namespace["__name__"]
            namespace[f"TestResources_{suite[5:]}_{name[4:]}"] = value


def load(namespace):
    for suite in CORPUS_SELECTIONS:
        register_module(namespace, suite)
