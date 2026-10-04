"""Frozen owner-sensitive safety cases using authentic, private owner fixtures."""

from __future__ import annotations

import ast
import hashlib
from types import ModuleType

from tests.desktop_adapters.tools_cases import ROOT, corpus, frozen_source, owner_id
from tests.desktop_adapters.tools_cases import ToolExecutor as OwnerExecutor

CORPUS_SELECTIONS = {
    "test_mcp_media_retention_checkpoint": None,
    "test_successful_retry_provenance": [
        "test_nested_success_wrapper_keeps_success_and_uncertainty",
        "test_returned_success_wrapper_keeps_provenance_without_active_context",
    ],
    "test_tool_failure_reporting": None,
    "test_result_validator": ["TestExecutorIntegration"],
    "test_campaign_execution_validation": [
        "test_real_validation_governor_refusal_cannot_pass",
        "test_invalid_probe_never_pins_host_generation",
    ],
    "test_bulkhead": ["TestIsolationSemantics"],
    "test_registry_schema": None,
    "test_handlers_state_lists": None,
    "test_state_handlers": None,
}
CORPUS_EXCLUSIONS = {
    "test_result_validator": ["TestExecutorIntegration.test_unknown_tool_not_validated_as_empty"],
    "test_handlers_state_lists": [
        "TestManageList.test_guards_and_access",
        "TestManageList.test_grocery_migration",
    ],
    "test_state_handlers": [
        "TestManageList.test_personal_ownership_isolation",
        "TestListMigrationAndFormat.test_migrates_old_grocery_file",
    ],
}


class ToolExecutor(OwnerExecutor):
    """Named fixture readiness only, never global publication or policy override."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.readiness.update(
            {
                name: True
                for name in (
                    "http_probe",
                    "manage_process",
                    "analyze_pdf",
                    "browser_read_page",
                )
            }
        )


def _executor(tmp_path, **kwargs):
    from src.config.schema import ToolHost, ToolsConfig
    from src.tools.hosts import HostRegistry

    registry = HostRegistry(
        {"alpha": ToolHost(address="127.0.0.1"), "remote": ToolHost(address="192.0.2.10")},
        default_host="alpha",
        trust_dir=tmp_path / "trust",
    )
    return ToolExecutor(config=ToolsConfig(), host_registry=registry)


def new_executor():
    return ToolExecutor()


class ImportSurfaces(ast.NodeTransformer):
    """Modify setup only; verify assertion and parameter AST before projection."""

    def __init__(self, name):
        self.name = name
        self.symbol = "<module>"
        self.hunks = []
        self.in_assert = False
        self.in_decorator = False

    def _record(self, before, after):
        if ast.dump(before, include_attributes=False) != ast.dump(after, include_attributes=False):
            self.hunks.append(
                {
                    "symbol": self.symbol,
                    "line": getattr(before, "lineno", None),
                    "before_sha256": hashlib.sha256(
                        ast.dump(before, include_attributes=False).encode()
                    ).hexdigest(),
                    "after_sha256": hashlib.sha256(
                        ast.dump(after, include_attributes=False).encode()
                    ).hexdigest(),
                    "review": "pending-independent-review",
                }
            )
        return after

    def visit_Assert(self, node):
        return node

    def visit_ImportFrom(self, node):
        import copy

        before = copy.deepcopy(node)
        if node.module == "src.tools.executor":
            # All selected imports contain ToolExecutor only; preserve mixed imports.
            changed = [a for a in node.names if a.name == "ToolExecutor"]
            retained = [a for a in node.names if a.name != "ToolExecutor"]
            if changed:
                replacement = ast.ImportFrom(module=__name__, names=changed, level=0)
                if retained:
                    return [
                        ast.copy_location(replacement, node),
                        ast.copy_location(
                            ast.ImportFrom(module=node.module, names=retained, level=0), node
                        ),
                    ]
                return ast.copy_location(self._record(before, replacement), node)
        if node.module == "tests.test_hosts_executor_leases":
            node.module = __name__
        return self._record(before, node)

    def visit_FunctionDef(self, node):
        previous = self.symbol
        self.symbol = node.name if previous == "<module>" else previous + "." + node.name
        # Decorators/defaults are frozen parameter data, never visit those.
        node.body = [self.visit(n) for n in node.body]
        node.body = [n for n in node.body if n is not None]
        self.symbol = previous
        return node

    def visit_AsyncFunctionDef(self, node):
        return self.visit_FunctionDef(node)

    def visit_ClassDef(self, node):
        previous = self.symbol
        self.symbol = node.name
        if self.name == "test_mcp_media_retention_checkpoint" and node.name in {
            "Unavailable",
            "Denied",
        }:
            import copy

            before = copy.deepcopy(node)
            node.bases = [ast.Name(id="ToolExecutor", ctx=ast.Load())]
            if node.name == "Unavailable":
                node.body = ast.parse(
                    "def retain_attachments(self, *args, **kwargs):\n"
                    '    raise RetentionError("Binary retention unavailable.")\n'
                ).body
            self._record(before, node)
        node.body = [self.visit(n) for n in node.body]
        self.symbol = previous
        return node

    def visit_Assign(self, node):
        import copy

        before = copy.deepcopy(node)
        # The __new__ integration's old ownerless fixture is replaced, not its assertions.
        if self.name == "test_result_validator" and any(
            isinstance(t, ast.Attribute) and t.attr == "_permission_manager" for t in node.targets
        ):
            node.value = ast.Attribute(
                value=ast.Name(id="exe", ctx=ast.Load()), attr="_permission_manager", ctx=ast.Load()
            )
        return self._record(before, self.generic_visit(node))

    def visit_Attribute(self, node):
        import copy

        before = copy.deepcopy(node)
        if node.attr == "_handle_test_tool":
            node.attr = "_handle_fetch_url"
        return self._record(before, self.generic_visit(node))

    def visit_Call(self, node):
        import copy

        before = copy.deepcopy(node)
        if (
            self.name == "test_result_validator"
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "__new__"
        ):
            node = ast.copy_location(
                ast.Call(
                    func=ast.Name(id="desktop_new_executor", ctx=ast.Load()), args=[], keywords=[]
                ),
                node,
            )
        # Synthetic handler names become existing ready routes, not new built-ins.
        if isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "test_tool"
            ):
                node.args[0] = ast.Constant(value="fetch_url")
        runtime_case = self.name == "test_mcp_media_retention_checkpoint" and self.symbol.split(
            "."
        )[0] in {
            "test_binary_cursor_rechecks_credential_and_host_binding_revocation",
            "test_binary_manifest_pointer_is_retained_even_when_text_quota_is_exhausted",
            "test_media_retention_failure_preserves_mcp_outcome_and_images",
        }
        if runtime_case:
            if isinstance(node.func, ast.Name) and node.func.id == "execution_delivery_scope":
                if (
                    node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "reader"
                ):
                    node.args[0] = ast.Call(
                        func=ast.Name(id="desktop_fixture_owner_id", ctx=ast.Load()),
                        args=[],
                        keywords=[],
                    )
            for keyword in node.keywords:
                if (
                    keyword.arg in {"owner", "user_id"}
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value == "reader"
                ):
                    keyword.value = ast.Call(
                        func=ast.Name(id="desktop_fixture_owner_id", ctx=ast.Load()),
                        args=[],
                        keywords=[],
                    )
                if (
                    keyword.arg == "tool_name"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value == "mcp_fixture_blob"
                ):
                    keyword.value = ast.Constant(value="fetch_url")
                if keyword.arg == "allowed_tools" and isinstance(keyword.value, ast.Set):
                    for item in keyword.value.elts:
                        if isinstance(item, ast.Constant) and item.value == "mcp_fixture_blob":
                            item.value = "fetch_url"
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "read"
                and not any(k.arg == "owner" for k in node.keywords)
            ):
                node.keywords.append(
                    ast.keyword(
                        arg="owner",
                        value=ast.Call(
                            func=ast.Name(id="desktop_fixture_owner_id", ctx=ast.Load()),
                            args=[],
                            keywords=[],
                        ),
                    )
                )
        node = self.generic_visit(node)
        return self._record(before, node)


def transformed_tree(name):
    source = frozen_source(f"tests/{name}.py")
    original = ast.parse(source)
    transformer = ImportSurfaces(name)
    tree = transformer.visit(ast.parse(source))
    if corpus(original) != corpus(tree):
        raise AssertionError("Frozen assertion or parameter corpus changed")
    return tree, transformer.hunks


def export_suite(namespace, name):
    tree, _ = transformed_tree(name)
    selection = CORPUS_SELECTIONS[name]
    tree.body = [
        n
        for n in tree.body
        if not (
            isinstance(n, ast.ClassDef)
            and n.name.startswith("Test")
            or isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("test_")
        )
        or selection is None
        or n.name in selection
    ]
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            node.body = [
                n
                for n in node.body
                if f"{node.name}.{getattr(n, 'name', '')}" not in CORPUS_EXCLUSIONS.get(name, [])
            ]
    module = ModuleType(f"desktop_owner_frozen_{name}")
    module.__file__ = str(ROOT / f"tests/{name}.py")
    module.desktop_fixture_owner_id = owner_id
    module.desktop_new_executor = new_executor
    exec(compile(ast.fix_missing_locations(tree), module.__file__, "exec"), module.__dict__)
    for key, value in vars(module).items():
        if hasattr(value, "_fixture_function_marker") or hasattr(value, "_pytestfixturefunction"):
            namespace[key] = value
        elif key.startswith("test_"):
            namespace[f"test_{name}_{key[5:]}"] = value
        elif key.startswith("Test"):
            namespace[f"Test_{name}_{key}"] = value


def triage_hunks():
    return [
        {
            "suite": name,
            "source_sha256": hashlib.sha256(frozen_source(f"tests/{name}.py")).hexdigest(),
            "hunks": transformed_tree(name)[1],
        }
        for name in CORPUS_SELECTIONS
    ]
