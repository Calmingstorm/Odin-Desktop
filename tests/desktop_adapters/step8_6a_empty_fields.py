"""Partial empty-fields support; the inherited whole suite remains deferred.

Only fixture imports and the old fixture owner label change. Foreign identities
remain foreign. Host leases, production policy and process capture are real.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, digest, dump, frozen_source, register_module
from src.config.schema import ToolHost, ToolsConfig
from tests.desktop_adapters.owner_cases import ToolExecutor
from tests.desktop_adapters.tools_cases import owner_id

SOURCE_PATH = "tests/test_delivery_empty_fields.py"
SOURCE_SHA256 = "00a2d64470e19838247ca9c89db2162669a1a315f7e3638afb18ab6a064b69c1"
HELPER_SHA256 = {
    "tests/test_process_tail_correctness.py":
        "1fa6fdfcfb7281790748fe5b6ace0cedae94f7c5e36eb9da97ba95413b37f880",
    "tests/test_remote_process_streaming.py":
        "abb4cff59dc49976f34ee9d764fa8cbaa7e0060ac29c886873fe65789470cd50",
}
CORPUS_SELECTIONS = {}
SUITES = {}
SUPPORT_SUITE = {"test_delivery_empty_fields": SOURCE_SHA256}
SUPPORT_CASES = frozenset({
    "test_soak_poll_shape_empty_cursor_with_zero_offset",
    "test_real_process_empty_fields_preserve_default_and_explicit_offset",
    "test_soak_poll_shape_real_cursor_with_zero_offset",
    "test_output_info_empty_cursor_resolves_current_pid_not_retired_generation",
    "test_tool_output_empty_limit_through_executor",
})
DEFERRED_CASES = {
    "test_agent_empty_fields_through_native_dispatch": (
        "Neutral agent paging/authorization contract, not a removed Discord contract. "
        "Inherited dispatcher helper constructs legacy tier PermissionManager and MagicMock "
        "executor/domain owners; an exact real canonical-owner service adapter is not completed."
    ),
    "test_empty_process_fields_do_not_change_mutation_or_authorization": (
        "Inherited assertion requires 'access denied'; the approved production diagnostic "
        "is 'Permission denied'. Preserve both unchanged pending reviewer resolution."
    ),
}


def executor(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700, exist_ok=True)
    return ToolExecutor(ToolsConfig(
        local_working_dir=str(workspace),
        audit_log_path=str(tmp_path / "data" / "audit.jsonl"),
        hosts={"testhost": ToolHost(address="127.0.0.1")},
        ssh_pool={"enabled": False},
    ))


class FixtureImports(ast.NodeTransformer):
    def __init__(self):
        self.hunks = []
        self.reverse = []

    def visit(self, node):
        if isinstance(node, ast.Assert):
            return node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.body = [self.visit(child) for child in node.body]
            node.body = [child for child in node.body if child is not None]
            return node
        before = copy.deepcopy(node)
        after = node
        if isinstance(node, ast.ImportFrom) and node.module in {
            "tests.test_executor_output_retention",
            "tests.test_process_tail_correctness",
            "tests.test_remote_process_streaming",
        }:
            after = ast.copy_location(ast.ImportFrom(
                module=__name__, names=copy.deepcopy(node.names), level=0), node)
        elif isinstance(node, ast.ImportFrom) and node.module == "tests.test_agent_result_pages":
            after = None
        elif isinstance(node, ast.Constant) and node.value == "owner":
            after = ast.copy_location(
                ast.parse("desktop_fixture_owner_id()", mode="eval").body, node)
        if after is not node:
            self.reverse.append((before, after))
            self.hunks.append({
                "line": getattr(before, "lineno", None),
                "before_sha256": digest(dump(before).encode()),
                "after_sha256": digest(dump(after).encode()) if after is not None else None,
                "before_source": ast.unparse(before),
                "after_source": ast.unparse(after) if after is not None else None,
                "operation": "fixture_import_or_canonical_owner_setup",
            })
            return after
        return super().visit(node)


def _verify_complete_reverse(before, after, adapter):
    """Reverse exactly the admitted setup nodes; all other AST is byte-identical."""
    replacements = {id(new): old for old, new in adapter.reverse if new is not None}

    class ReverseSetup(ast.NodeTransformer):
        def visit(self, node):
            if id(node) in replacements:
                return copy.deepcopy(replacements[id(node)])
            return super().visit(node)

    # Work on the original adapted nodes, then copy the restored representation.
    restored = ReverseSetup().visit(after)
    for old, new in adapter.reverse:
        if new is None:
            index = next(i for i, statement in enumerate(before.body) if
                         getattr(statement, "lineno", None) == old.lineno)
            restored.body.insert(index, copy.deepcopy(old))
    if dump(before) != dump(restored):
        raise ValueError("empty-fields complete AST reverse replay failed")


def transformed_tree():
    source = frozen_source(SOURCE_PATH)
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("empty-fields source digest changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    original_cases = {name for name, _, _ in corpus(original)["cases"]}
    if SUPPORT_CASES & DEFERRED_CASES.keys() or original_cases != (
        SUPPORT_CASES | DEFERRED_CASES.keys()
    ):
        raise ValueError("empty-fields support/deferred case partition drift")
    retained = copy.deepcopy(original)
    retained.body = [n for n in retained.body if not (
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in DEFERRED_CASES)]
    adapter = FixtureImports()
    adapted = ast.fix_missing_locations(adapter.visit(copy.deepcopy(retained)))
    if corpus(retained) != corpus(adapted):
        raise ValueError("empty-fields assertion/signature/decorator/parameter drift")
    result = copy.deepcopy(adapted)
    _verify_complete_reverse(retained, adapted, adapter)
    adapted = result
    return original, retained, adapted, adapter.hunks


def _helper(path, symbols):
    source = frozen_source(path)
    if digest(source) != HELPER_SHA256[path]:
        raise ValueError("empty-fields helper digest changed")
    original = ast.parse(source, filename=path)
    tree = ast.Module(body=[copy.deepcopy(n) for n in original.body if (
        isinstance(n, (ast.Import, ast.ImportFrom)) or getattr(n, "name", None) in symbols)],
        type_ignores=[])
    before = copy.deepcopy(tree)
    adapter = FixtureImports()
    adapted = ast.fix_missing_locations(adapter.visit(tree))
    if corpus(before) != corpus(adapted):
        raise ValueError("empty-fields helper corpus drift")
    result = copy.deepcopy(adapted)
    _verify_complete_reverse(before, adapted, adapter)
    adapted = result
    module = ModuleType("empty_fields_" + path.rsplit("/", 1)[-1][:-3])
    module.__dict__["desktop_fixture_owner_id"] = owner_id
    exec(compile(adapted, path, "exec"), module.__dict__)
    return module


# Original transport runs the actual remote supervisor/controller locally.
# No SSH, foreign host or containment implementation is substituted.
_remote_module = _helper("tests/test_remote_process_streaming.py", {"_Lease", "_remote_job"})
_remote_job = _remote_module._remote_job
_tail_module = _helper("tests/test_process_tail_correctness.py", {"job", "delivered", "preview"})
job, delivered, preview = _tail_module.job, _tail_module.delivered, _tail_module.preview


def load(namespace):
    """Do not expose partial support as a restored whole-suite loader."""
    raise RuntimeError("Whole empty-fields suite deferred: " + "; ".join(DEFERRED_CASES.values()))


def load_support(namespace):
    """Register only complete supported cases, never individual parameter slices."""
    original, retained, adapted, hunks = transformed_tree()
    module = ModuleType("empty_fields_partial_support")
    module.__dict__["desktop_fixture_owner_id"] = owner_id
    exec(compile(adapted, SOURCE_PATH, "exec"), module.__dict__)
    register_module(namespace, module, excluded=DEFERRED_CASES)
    return original, retained, adapted, hunks
