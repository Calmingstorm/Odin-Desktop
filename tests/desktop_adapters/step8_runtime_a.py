"""Whole frozen step-5 suites, with exact reversible setup-only projections."""
from __future__ import annotations

import ast
import contextvars
import hashlib
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, frozen_source, register_module
from src.desktop.state import StateService
from src.tools.builtin_policy import BuiltinToolPolicy
from src.tools.executor import ToolExecutor

ROOT = Path(__file__).resolve().parents[2]
CORPUS_SELECTIONS = {
    "test_cancelled_persistence_settles": None,
    "test_tool_failure_visibility": None,
}
CORPUS_EXCLUSIONS = {}
SUITES = {
    "test_cancelled_persistence_settles":
        "f14794cf64778fc5c19f6396394085e58214e4e0b531ac45b2f93af427bdc435",
    "test_tool_failure_visibility":
        "55298c5b3bf7cc3e6e2dbdb00426e20461ec7aa791df65f72de45dc3fd4b4e43",
}
fixture_state = contextvars.ContextVar("step8_runtime_a_owner", default=None)


def fixture_owner_id():
    state = fixture_state.get()
    if state is None:
        raise RuntimeError("authenticated temporary owner fixture required")
    return state.authority.owner_id


def fixture_executor(*, memory_path=None):
    state = fixture_state.get()
    if state is None:
        raise RuntimeError("authenticated temporary owner fixture required")
    executor = ToolExecutor(
        profile_paths=state.paths,
        permission_manager=state.manager,
        memory_path=memory_path or str(state.paths.data_dir / "memory.json"),
    )
    readiness = {"run_command_multi": True}
    executor.set_builtin_policy(BuiltinToolPolicy(
        lambda: SimpleNamespace(tools=executor.config), lambda: readiness,
    ))
    executor.set_user_context(state.authority.owner_id)
    state.executors.append(executor)
    return executor


def fixture_bot():
    return SimpleNamespace(tool_executor=fixture_executor())


def state_put_handler(executor):
    """Only project a settled, genuine memory.set success into old HTTP syntax.

    No route emulation, catch/reclassification, cancellation interception or
    alternative persistence exists here. Errors propagate from StateService.
    """
    state = fixture_state.get()
    if state is None:
        raise RuntimeError("authenticated temporary owner fixture required")
    service = StateService(state.paths, state.authority.owner_id, memory=executor)

    async def put(request):
        body = await request.json()
        scope, key = request.match_info["scope"], request.match_info["key"]
        result = await service.handle("memory.set", {
            "scope": scope, "key": key, "value": body["value"],
        })
        if result != {"status": "saved", "scope": scope, "key": key}:
            raise ValueError("memory.set did not return its committed success outcome")
        return SimpleNamespace(status=200, body=result)

    return put


def digest(data):
    return hashlib.sha256(data).hexdigest()


def records():
    return json.loads((ROOT / "maintenance/step8-part2-batch-a.json").read_text())


def setup_record(name):
    matches = [row for row in records()["decisions"] if row["path"] == f"tests/{name}.py"]
    if len(matches) != 1 or matches[0]["mode"] != "frozen-adapter":
        raise ValueError("suite must have one complete frozen restoration record")
    return matches[0]


def resolved_hunks(row, original):
    rules = []
    for rule in row["setup_hunks"]:
        if "before_source" not in rule:
            tree = ast.parse(original)
            matches = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                       and n.name == rule["symbol"]]
            if len(matches) != 1:
                raise ValueError("exact source symbol must match once")
            rule = dict(rule, before_source=ast.get_source_segment(original, matches[0]))
        rules.append(rule)
    return rules


def verify_source(name, source):
    """Reverse every exact sealed hunk and require the entire inherited source."""
    row = setup_record(name)
    original = frozen_source(row["path"])
    if (hashlib.sha256(original).hexdigest() != SUITES[name]
            or hashlib.sha256(original).hexdigest() != row["inherited_sha256"]):
        raise ValueError("inherited source hash changed")
    expected = original.decode()
    rules = resolved_hunks(row, expected)
    for rule in rules:
        before, after = rule["before_source"], rule["after_source"]
        if (digest(before.encode()) != rule["before_sha256"]
                or digest(after.encode()) != rule["after_sha256"]):
            raise ValueError("setup hunk seal changed")
        if expected.count(before) != 1:
            raise ValueError("setup hunk must match exactly once")
        expected = expected.replace(before, after, 1)
    if source != expected:
        raise ValueError("undeclared source change")
    reversed_source = source
    for rule in reversed(rules):
        if reversed_source.count(rule["after_source"]) != 1:
            raise ValueError("reverse setup hunk must match exactly once")
        reversed_source = reversed_source.replace(rule["after_source"], rule["before_source"], 1)
    if reversed_source.encode() != original:
        raise ValueError("reverse setup differs from the complete frozen source")
    if corpus(ast.parse(source)) != corpus(ast.parse(original)):
        raise ValueError("inherited assertion/signature/decorator corpus changed")
    return ast.parse(source, filename=str(ROOT / row["path"]))


def transformed_source(name):
    row = setup_record(name)
    source = frozen_source(row["path"]).decode()
    for rule in resolved_hunks(row, source):
        if source.count(rule["before_source"]) != 1:
            raise ValueError("setup hunk must match exactly once")
        source = source.replace(rule["before_source"], rule["after_source"], 1)
    verify_source(name, source)
    return source


def export_suite(namespace, name):
    tree = verify_source(name, transformed_source(name))
    module = ModuleType(f"desktop_step8_runtime_a_{name}")
    module.__file__ = str(ROOT / f"tests/{name}.py")
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    # Whole suite only. Fixture names are unchanged, and no case is filtered.
    exported = []
    for key, value in vars(module).items():
        if hasattr(value, "_fixture_function_marker") or hasattr(value, "_pytestfixturefunction"):
            namespace[key] = value
        elif key.startswith("test_"):
            exported.append(key)
        elif key.startswith("Test"):
            exported.append(key)
    expected = [n.name for n in tree.body if (
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
        or isinstance(n, ast.ClassDef) and n.name.startswith("Test")
    )]
    if sorted(exported) != sorted(expected):
        raise ValueError("incomplete whole-suite export")
    register_module(namespace, module, prefix=name, full_class_name=True)


def load(namespace):
    for name in CORPUS_SELECTIONS:
        export_suite(namespace, name)
