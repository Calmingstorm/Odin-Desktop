"""Retained provider cases, with setup-only Desktop fixture adaptation.

This loader never changes an assertion, a test signature, or a parametrization.
Documentation catalogues are appropriate to converter tests; they do not grant
runtime readiness or permission to execute any catalogue entry.
"""

from __future__ import annotations

import ast
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, frozen_source


class DesktopProviderSetup(ast.NodeTransformer):
    """Remove only the obsolete dummy Discord config fixture and imports."""

    def visit_Assert(self, node):
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "Config":
            for keyword in list(node.keywords):
                if keyword.arg == "discord":
                    if ast.dump(keyword.value, include_attributes=False) != ast.dump(
                        ast.parse('{"token": ""}', mode="eval").body,
                        include_attributes=False,
                    ):
                        raise AssertionError("not the audited empty dummy Config fixture")
                    node.keywords.remove(keyword)
        return node

    def visit_Dict(self, node):
        self.generic_visit(node)
        keep = [
            index
            for index, key in enumerate(node.keys)
            if not (isinstance(key, ast.Constant) and key.value == "discord")
        ]
        if len(keep) != len(node.keys):
            for index in set(range(len(node.keys))) - set(keep):
                value = node.values[index]
                if not (
                    isinstance(value, ast.Dict)
                    and len(value.keys) == 1
                    and isinstance(value.keys[0], ast.Constant)
                    and value.keys[0].value == "token"
                    and isinstance(value.values[0], ast.Constant)
                    and value.values[0].value in ("test", "[REDACTED]")
                ):
                    raise AssertionError("not the audited dummy Discord fixture")
            node.keys = [node.keys[index] for index in keep]
            node.values = [node.values[index] for index in keep]
        return node

    def visit_ImportFrom(self, node):
        if node.module in ("src.tools", "src.tools.registry"):
            for alias in node.names:
                if alias.name == "get_tool_definitions":
                    alias.name = "get_documentation_tool_definitions"
                    alias.asname = "get_tool_definitions"
                    node.module = "src.tools.registry"
        if node.module == "src.tools.executor":
            if all(alias.name == "ToolExecutor" for alias in node.names):
                node.module = "tests.desktop_adapters.tools_cases"
        return node


def load_suite(name, selection):
    path = f"tests/test_{name}.py"
    source = frozen_source(path)
    original = ast.parse(source, filename=path)
    adapted = DesktopProviderSetup().visit(ast.parse(source, filename=path))
    if corpus(original) != corpus(adapted):
        raise AssertionError("retained assertion/signature/parameter corpus changed")
    selected = set(selection)
    available = {
        node.name
        for node in original.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith(("test_", "Test"))
    }
    if selected - available:
        raise AssertionError(f"unknown retained selections: {selected - available}")
    adapted.body = [
        node
        for node in adapted.body
        if not (
            isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith(("test_", "Test"))
        )
        or node.name in selected
    ]
    ast.fix_missing_locations(adapted)
    module = ModuleType(f"desktop_frozen_llm_{name}")
    module.__file__ = path
    exec(compile(adapted, path, "exec"), module.__dict__)
    return module


def export_suite(namespace, name, selection):
    module = load_suite(name, selection)
    for key, value in vars(module).items():
        if key.startswith("test_"):
            namespace[f"test_{name}_{key[5:]}"] = value
        elif key.startswith("Test"):
            # The two client suites use distinct original fixtures named client.
            # Keep the original signatures and scope each fixture to its class.
            if hasattr(module, "client"):
                value.client = staticmethod(module.client)
            namespace[f"Test_{name}_{key[4:]}"] = value
