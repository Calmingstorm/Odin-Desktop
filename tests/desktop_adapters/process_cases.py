"""Complete frozen process corpus, with authentic temporary setup only.

No kernel containment, scan, signal, reaper or settlement method is replaced.
Only the two obsolete handler-construction fixtures change AST; all inherited
assertions, signatures, decorators and parameter expressions are identical.
"""
from __future__ import annotations

import ast
import contextvars
import copy
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module
from src.config.schema import ToolsConfig
from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths
from src.permissions.manager import PermissionManager
from src.tools.executor import ToolExecutor
from src.tools.output_authorization import host_binding
from src.tools.process_manager import ProcessRegistry as EngineRegistry
from src.tools.workspace import resolve_workspace

_fixture = contextvars.ContextVar("process_corpus_fixture", default=None)


@contextmanager
def temporary_owner(tmp_path):
    if os.geteuid() == 0:
        raise RuntimeError("use the isolated runner as odin, not root")
    paths = ProfilePaths.from_xdg(
        environ={"XDG_CONFIG_HOME": str(tmp_path / "config"),
                 "XDG_DATA_HOME": str(tmp_path / "data"),
                 "XDG_CACHE_HOME": str(tmp_path / "cache")}, home=tmp_path,
    )
    authority = OwnerAuthority(paths)
    manager = PermissionManager(authority)
    context = authority.authenticate_local(peer_uid=os.geteuid())
    owner_token = manager.set_request_owner(context)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    workspace.chmod(0o700)
    state = SimpleNamespace(paths=paths, authority=authority, manager=manager,
                            workspace=workspace, executors=[])
    fixture_token = _fixture.set(state)
    try:
        if not manager.is_owner(authority.owner_id):
            raise RuntimeError("temporary owner authentication failed")
        yield state
    finally:
        for executor in state.executors:
            executor.set_user_context(None)
        _fixture.reset(fixture_token)
        manager.reset_request_owner(owner_token)
        authority.release_runtime()


class TemporaryProcessRegistry(EngineRegistry):
    """A real registry, differing only by a revalidated temporary workspace."""
    def __init__(self, *args, **kwargs):
        state = _fixture.get()
        if state is None:
            raise RuntimeError("process corpus requires temporary_owner")
        kwargs.setdefault("workspace", lambda: str(resolve_workspace(
            str(state.workspace), protected_roots=[state.paths.config_dir,
            state.paths.data_dir, state.paths.cache_dir, Path(__file__).resolve().parents[2]],
            create_if_missing=False,
        )))
        super().__init__(*args, **kwargs)


def desktop_process_handler(registry):
    """Use actual HandlerDeps and host resolution, never a permit-all fake."""
    state = _fixture.get()
    if state is None:
        raise RuntimeError("process corpus requires temporary_owner")
    executor = ToolExecutor(
        config=ToolsConfig(local_working_dir=str(state.workspace),
                           hosts={"localhost": {"address": "127.0.0.1", "ssh_user": "odin"}},
                           ssh_pool={"enabled": False}),
        profile_paths=state.paths, permission_manager=state.manager,
        memory_path=str(state.paths.data_dir / "memory.json"),
    )
    executor.set_user_context(state.authority.owner_id)
    executor._process_registry = registry
    state.executors.append(executor)
    target = executor.host_registry.get("localhost", targetable_only=True)
    if target is None or executor._resolve_host("localhost") is None:
        raise RuntimeError("real temporary local host is unavailable")
    for info in registry._processes.values():
        info.owner_id = state.authority.owner_id
        info.host_alias = "localhost"
        info.host_identity = target.runtime_key
        info.host_binding = host_binding(target)
    return executor.system_tools


SOURCE_PATH = "tests/test_process_manager.py"
CORPUS_SELECTIONS = {"test_process_manager": None}
CORPUS_EXCLUSIONS = {}
# Exact source digest and node digests are filled after the static frozen audit.
SOURCE_SHA256 = "4c177fe2cb8d4b4b9058f20a798309f5715e97b85c30f6881b6b0b82d1955bc6"
SETUP_HUNKS = {
    267: ("8bdc084adccec4afafe409bb46f429b5079f1e7bb26c994d87328117049b33e6",
          "h = desktop_process_handler(reg)"),
    268: ("d356a91ab4ab2537abb78d748dc4c2aab7f3bfa866777432d10d17a747a251ff", None),
    272: ("b511c5fdb80a22ddbe87ae3c752f2be5b8e09018e074223f1bed89d9ab53b472", None),
    276: ("db3331d21e689edc656dbf76aad57a30f5a50acbd8647c6323cbd62a110fc489", None),
    289: ("8bdc084adccec4afafe409bb46f429b5079f1e7bb26c994d87328117049b33e6",
          "h = desktop_process_handler(reg)"),
    290: ("d356a91ab4ab2537abb78d748dc4c2aab7f3bfa866777432d10d17a747a251ff", None),
    294: ("b511c5fdb80a22ddbe87ae3c752f2be5b8e09018e074223f1bed89d9ab53b472", None),
    298: ("db3331d21e689edc656dbf76aad57a30f5a50acbd8647c6323cbd62a110fc489", None),
}


def load(namespace):
    source = frozen_source(SOURCE_PATH)
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("process corpus baseline bytes changed")
    original = ast.parse(source)
    tree = copy.deepcopy(original)
    seen = set()

    class ExactSetup(ast.NodeTransformer):
        def visit(self, node):
            line = getattr(node, "lineno", None)
            if line not in SETUP_HUNKS:
                return super().visit(node)
            expected, replacement = SETUP_HUNKS[line]
            if hashlib.sha256(dump(node).encode()).hexdigest() != expected:
                return super().visit(node)
            if line in seen:
                raise ValueError("process setup hunk matched twice")
            seen.add(line)
            if replacement is None:
                return None
            return ast.copy_location(ast.parse(replacement).body[0], node)

    tree = ExactSetup().visit(tree)
    ast.fix_missing_locations(tree)
    if seen != set(SETUP_HUNKS) or corpus(original) != corpus(tree):
        raise ValueError("process setup/assertion/signature/parameter corpus drift")
    # Independent reverse replay restores every setup statement and requires
    # the ENTIRE resulting AST to equal the frozen original, not just corpus.
    locations = []

    def locate(node, path=()):
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for index, child in enumerate(value):
                    if isinstance(child, ast.AST):
                        child_path = (*path, field, index)
                        line = getattr(child, "lineno", None)
                        if line in SETUP_HUNKS and isinstance(child, ast.stmt):
                            expected = SETUP_HUNKS[line][0]
                            if hashlib.sha256(dump(child).encode()).hexdigest() == expected:
                                locations.append((line, child_path, child))
                        locate(child, child_path)
            elif isinstance(value, ast.AST):
                locate(value, (*path, field))

    locate(original)
    restored = copy.deepcopy(tree)
    for line, path, statement in sorted(locations):
        parent = restored
        for part in path[:-1]:
            parent = parent[part] if isinstance(part, int) else getattr(parent, part)
        index = path[-1]
        if SETUP_HUNKS[line][1] is None:
            parent.insert(index, copy.deepcopy(statement))
        else:
            parent[index] = copy.deepcopy(statement)
    if dump(restored) != dump(original):
        raise ValueError("process complete AST reverse replay failed")
    module = ModuleType("frozen_process_manager_corpus")
    module.__dict__["desktop_process_handler"] = desktop_process_handler
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    module.ProcessRegistry = TemporaryProcessRegistry
    register_module(namespace, module)
    return original, tree
