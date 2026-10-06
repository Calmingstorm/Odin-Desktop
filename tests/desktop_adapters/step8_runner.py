"""Complete pinned runner suites with exact temporary-owner setup substitutions.

No authority, governance, signal, scan, retention or settlement implementation is
replaced. The remote fixture runs the real supervisor through local transport.
"""
# ruff: noqa: E501
from __future__ import annotations

import ast
import copy
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module
from src.config.schema import ToolHost, ToolsConfig
from src.tools.builtin_policy import BuiltinToolPolicy
from src.tools.executor import ToolExecutor
from tests.desktop_adapters.process_cases import _fixture

CORPUS_SELECTIONS = {"test_command_shell_framing": None, "test_process_zero_offset": None}
CORPUS_EXCLUSIONS = {}
SUITES = {
    "test_command_shell_framing": "cb5bd6655d51b4ed8994ea0df7f750a5295722e7234071e8935dcc4a4929324e",
    "test_process_zero_offset": "b7db1aadbd1ad1fa965f13609906808ca282089f7b3acf87f6dfcc67dcd8b052",
}
HELPER_SHA256 = "1fa6fdfcfb7281790748fe5b6ace0cedae94f7c5e36eb9da97ba95413b37f880"
HOST = "shell-test-local"
USER = None  # Bound to the authentic fixture owner before inherited execution.

# (line, column, whole node SHA256, exact replacement source, expression?)
SETUP_HUNKS = {
    "test_command_shell_framing": [
        (17, 0, "957f66910e030b6f51ed5a3e51d097e296451fb5defb3a22a96751036c9a4e82",
         "from tests.desktop_adapters.step8_runner import HOST, USER", False),
        (18, 0, "5b6286a612a1b1cb27b595c8c58854dc9d4d677966f984a1a41aa61ed92247a9",
         "from tests.desktop_adapters.step8_runner import shell_runtime as _runtime", False),
    ],
    "test_process_zero_offset": [
        (10, 0, "6ec9c85f60c45f1329f5f8f3a7f420ae5e9660bc5128c8871dcd5091b1f1f736",
         "from tests.desktop_adapters.step8_runner import delivered, job, preview", False),
    ],
    "test_process_tail_correctness": [
        (17, 0, "8dce3e2a05cc244e733c19f4bc147ac405041272953870af6f871eadf49345ce",
         "from tests.desktop_adapters.step8_runner import process_executor as executor", False),
        (29, 34, "b2de7a0b892c7480fc8487adc4adac61e17adca8ef942042af20476268fc4836", "owner_id()", True),
        (36, 53, "b2de7a0b892c7480fc8487adc4adac61e17adca8ef942042af20476268fc4836", "owner_id()", True),
        (51, 23, "b2de7a0b892c7480fc8487adc4adac61e17adca8ef942042af20476268fc4836", "owner_id()", True),
        (68, 15, "b2de7a0b892c7480fc8487adc4adac61e17adca8ef942042af20476268fc4836", "owner_id()", True),
        (106, 38, "b2de7a0b892c7480fc8487adc4adac61e17adca8ef942042af20476268fc4836", "owner_id()", True),
        (109, 23, "b2de7a0b892c7480fc8487adc4adac61e17adca8ef942042af20476268fc4836", "owner_id()", True),
    ],
}


def owner_id():
    state = _fixture.get()
    if state is None:
        raise RuntimeError("runner corpus requires authentic temporary_owner")
    return state.authority.owner_id


def _executor(tmp_path, alias):
    state = _fixture.get()
    if state is None or not state.manager.is_owner(state.authority.owner_id):
        raise RuntimeError("runner owner authentication is absent")
    config = ToolsConfig(
        hosts={alias: ToolHost(address="127.0.0.1", ssh_user="odin")},
        default_host=alias, local_working_dir=str(state.workspace),
        audit_log_path=str(state.paths.data_dir / "audit.jsonl"),
        ssh_pool={"enabled": False}, recovery={"enabled": False},
        branch_freshness={"enabled": False},
    )
    executor = ToolExecutor(config, profile_paths=state.paths,
                            permission_manager=state.manager,
                            memory_path=str(state.paths.data_dir / "memory.json"))
    executor.set_user_context(state.authority.owner_id)
    # Readiness is limited to the actual retained handlers this corpus invokes,
    # using the same callable-owner test as Desktop service composition.
    executor.set_builtin_policy(BuiltinToolPolicy(
        lambda: SimpleNamespace(tools=executor.config),
        lambda: {name: callable(executor._resolve_handler(name)) for name in (
            "run_command", "run_script", "run_command_multi", "read_file",
            "apply_patch", "manage_process", "get_tool_output")},
    ))
    state.executors.append(executor)
    return executor


def process_executor(tmp_path):
    return _executor(tmp_path, "testhost")


@asynccontextmanager
async def _runtime(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    executor = _executor(tmp_path, HOST)
    try:
        yield SimpleNamespace(executor=executor, config=executor.config)
    finally:
        registry = getattr(executor, "_process_registry", None)
        if registry is not None:
            await registry.shutdown()
        if executor.host_registry.has_active_leases(HOST):
            raise RuntimeError("temporary shell host lease did not settle")


# The retained runtime calls the original fixture's __wrapped__ async generator.
async def _shell_runtime_generator(tmp_path, monkeypatch):
    async with _runtime(tmp_path, monkeypatch) as runtime:
        yield runtime


shell_runtime = SimpleNamespace(__wrapped__=_shell_runtime_generator)


def _paths(node, path=()):
    yield path, node
    for field, value in ast.iter_fields(node):
        if isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, ast.AST):
                    yield from _paths(child, (*path, field, index))
        elif isinstance(value, ast.AST):
            yield from _paths(value, (*path, field))


def _put(tree, path, value):
    target = tree
    for part in path[:-1]:
        target = target[part] if isinstance(part, int) else getattr(target, part)
    if isinstance(path[-1], int):
        target[path[-1]] = value
    else:
        setattr(target, path[-1], value)


def adapt(path, source, expected_hash, *, hunks=None):
    if hashlib.sha256(source).hexdigest() != expected_hash:
        raise ValueError("runner frozen bytes changed")
    original = ast.parse(source, filename=path)
    tree = copy.deepcopy(original)
    replacements = []
    rules = SETUP_HUNKS[Path(path).stem] if hunks is None else hunks
    if len({(rule[0], rule[1], rule[2]) for rule in rules}) != len(rules):
        raise ValueError("runner duplicate setup hunk")
    admitted = SETUP_HUNKS[Path(path).stem]
    if rules != admitted:
        raise ValueError("runner setup hunks differ from exact admitted allowlist")
    for line, column, digest, replacement, expression in rules:
        matches = [(p, n) for p, n in _paths(original)
                   if getattr(n, "lineno", None) == line
                   and getattr(n, "col_offset", None) == column
                   and hashlib.sha256(dump(n).encode()).hexdigest() == digest]
        if len(matches) != 1:
            raise ValueError("runner setup hunk must match exactly once")
        location, node = matches[0]
        replacement_node = (ast.parse(replacement, mode="eval").body if expression
                            else ast.parse(replacement).body[0])
        _put(tree, location, ast.copy_location(replacement_node, node))
        replacements.append((location, node))
    ast.fix_missing_locations(tree)
    if corpus(original) != corpus(tree):
        raise ValueError("runner assertion/signature/decorator/parameter corpus drift")
    restored = copy.deepcopy(tree)
    for location, node in replacements:
        _put(restored, location, copy.deepcopy(node))
    if dump(restored) != dump(original):
        raise ValueError("runner complete AST reverse replay failed")
    return original, tree


def _module(path, expected_hash):
    original, tree = adapt(path, frozen_source(path), expected_hash)
    module = ModuleType("step8_runner_frozen_" + Path(path).stem)
    module.__file__ = str(Path(__file__).resolve().parents[2] / path)
    module.__dict__["owner_id"] = owner_id
    exec(compile(tree, path, "exec"), module.__dict__)
    return module, original, tree


_helper = None


def _helper_module():
    global _helper
    if _helper is None:
        _helper, _, _ = _module("tests/test_process_tail_correctness.py", HELPER_SHA256)
    return _helper


@asynccontextmanager
async def job(*args, **kwargs):
    async with _helper_module().job(*args, **kwargs) as result:
        yield result


async def delivered(*args, **kwargs):
    return await _helper_module().delivered(*args, **kwargs)


def preview(*args, **kwargs):
    return _helper_module().preview(*args, **kwargs)


MODULES = []


def load(namespace):
    for stem, expected_hash in SUITES.items():
        module, _, _ = _module(f"tests/{stem}.py", expected_hash)
        MODULES.append(module)
        if stem == "test_command_shell_framing":
            # Export the inherited fixture intact for pytest discovery.
            module.runtime.__module__ = namespace["__name__"]
            namespace["runtime"] = module.runtime
        if stem == "test_process_zero_offset":
            module.no_background.__module__ = namespace["__name__"]
            namespace["no_background"] = module.no_background
        register_module(namespace, module, prefix="step8_runner_" + stem.removeprefix("test_"))


def bind_owner():
    for module in MODULES:
        if "USER" in module.__dict__:
            module.USER = owner_id()
