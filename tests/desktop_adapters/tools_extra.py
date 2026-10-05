"""Audited neutral inherited tools with authentic module-local Desktop setup.

Only imports and the synthetic reader identity are transformed. Assertions,
test signatures and parameter decorators remain the frozen upstream corpus.
"""

from __future__ import annotations

import ast
from types import ModuleType

from tests.desktop_adapters.tools_cases import (
    ROOT,
    corpus,
    frozen_source,
    owner_id,
)
from tests.desktop_adapters.tools_cases import (
    ToolExecutor as OwnerExecutor,
)

CORPUS_SELECTIONS = {
    "test_read_file_ranges": None,
    "test_read_file_delivery_budget": None,
    "test_output_delivery_retention": None,
    "test_backoff": None,
    "test_successful_retry_provenance": [
        "test_real_run_command_internal_ssh_retry_settlement",
        "test_real_read_file_executor_recovery_settlement",
        "test_real_read_file_error_like_content_does_not_recover",
        "test_real_run_command_exhausted_timeouts_remain_failed",
    ],
    "test_output_authorization": [
        "test_nested_capture_collects_child_hosts_without_leaking",
        "test_static_tool_scope_intersects_live_scope",
    ],
    "test_bulkhead": ["TestExecutorBulkheadIntegration"],
    "test_tool_timeouts": ["TestExecutorPerToolTimeout"],
}


class ToolExecutor(OwnerExecutor):
    """Retain real owner, sealed permissions and explicit persisted host grants."""


class ImportSurfaces(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        if node.module != "src.tools.executor":
            return node
        executor = [alias for alias in node.names if alias.name == "ToolExecutor"]
        other = [alias for alias in node.names if alias.name != "ToolExecutor"]
        result = []
        if executor:
            result.append(
                ast.ImportFrom(
                    module="tests.desktop_adapters.tools_extra",
                    names=executor,
                    level=0,
                )
            )
        if other:
            result.append(ast.ImportFrom(module=node.module, names=other, level=0))
        return [ast.copy_location(item, node) for item in result]

    def visit_keyword(self, node):
        if (
            node.arg == "user_id"
            and isinstance(node.value, ast.Constant)
            and node.value.value == "reader"
        ):
            node.value = ast.Call(
                func=ast.Name(id="desktop_fixture_owner_id", ctx=ast.Load()),
                args=[],
                keywords=[],
            )
        return self.generic_visit(node)


def adapted_tree(name):
    """Verify complete source corpus before selecting the audited cases."""
    if name not in CORPUS_SELECTIONS:
        raise ValueError("suite has not been audited")
    path = f"tests/{name}.py"
    source = frozen_source(path)
    original = ast.parse(source, filename=path)
    transformed = ImportSurfaces().visit(ast.parse(source, filename=path))
    if corpus(original) != corpus(transformed):
        raise AssertionError("assertion or parameter/case corpus changed")
    selection = CORPUS_SELECTIONS[name]
    if selection is not None:
        transformed.body = [
            node
            for node in transformed.body
            if not (
                isinstance(node, ast.ClassDef)
                and node.name.startswith("Test")
                or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            )
            or node.name in selection
        ]
    return ast.fix_missing_locations(transformed)


def load_suite(name):
    tree = adapted_tree(name)
    module = ModuleType(f"desktop_extra_frozen_{name}")
    module.__file__ = str(ROOT / f"tests/{name}.py")
    module.desktop_fixture_owner_id = owner_id
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    return module


def export_suite(namespace, name):
    module = load_suite(name)
    for key, value in vars(module).items():
        if key.startswith("test_"):
            namespace[f"test_{name}_{key[5:]}"] = value
        elif key.startswith("Test"):
            namespace[f"Test_{name}_{key}"] = value
