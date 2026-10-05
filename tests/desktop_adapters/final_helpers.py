"""Exact local fixture provenance, never a privileged dispatch replacement."""

from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, nodes

CASE_MAP = {}
ERROR_CASES = {
    "TestStructuredReason": {
        "test_controls_stripped_from_reason",
        "test_mentions_neutralized_in_reason",
        "test_format_chars_stripped_from_reason",
    },
    "TestSecretScrubbing": {"test_reason_phrase_is_scrubbed"},
}
SETUP_RULES = {
    "test_apply_registry": {
        "TestEffectiveIsNeverGuessed.test_a_re_read_field_is_effective_immediately": {
            "discord.respond_to_bots": "turn_state.payload_retention_days",
        },
        "TestRevisionIsNotAnOracle.test_effective_revision_is_not_published_as_a_raw_boot_diff": {
            "discord": "turn_state",
            "respond_to_bots": "payload_retention_days",
        },
    },
}


def verified_tree(name):
    """Freeze full assertions/signatures/decorators and exact setup-only hunks."""
    path = f"tests/{name}.py"
    original = ast.parse(frozen_source(path))
    tree = copy.deepcopy(original)
    changes = []
    rules = SETUP_RULES[name]
    for symbol, node in nodes(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            replacement = rules.get(symbol, {}).get(node.value)
            if replacement is not None:
                before = dump(node)
                node.value = replacement
                changes.append((symbol, node.lineno, before, dump(node)))
    # Independently rebuild the complete expected tree. No broad transformer.
    expected = copy.deepcopy(original)
    for symbol, line, before, after in changes:
        matches = [
            node
            for owner, node in nodes(expected)
            if owner == symbol and getattr(node, "lineno", None) == line and dump(node) == before
        ]
        assert len(matches) == 1
        target = matches[0]
        assert isinstance(target, ast.Constant)
        target.value = rules[symbol][target.value]
        assert dump(target) == after
    assert changes
    assert hashlib.sha256(repr(changes).encode()).hexdigest() == (
        "d2b0b62d73bd2ed44272fdeb1381f6c31461009afc01c18031c6d0211f2d487e"
    )
    assert corpus(original) == corpus(tree)
    assert dump(expected) == dump(tree)
    return tree, changes


def export_exact(namespace):
    name = "test_apply_registry"
    tree, _ = verified_tree(name)
    # Only definitions needed by these two cases are executed. The discarded
    # WebUI helper is not called or emulated.
    tree.body = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        or isinstance(node, ast.ClassDef)
        and node.name
        in {
            "TestEffectiveIsNeverGuessed",
            "TestRevisionIsNotAnOracle",
        }
    ]
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            node.body = [
                method
                for method in node.body
                if f"{node.name}.{getattr(method, 'name', '')}" in SETUP_RULES[name]
            ]
    module = ModuleType("desktop_final_exact_helpers")
    exec(compile(ast.fix_missing_locations(tree), f"tests/{name}.py", "exec"), module.__dict__)
    for source in SETUP_RULES[name]:
        cls, method = source.split(".")
        exported = f"TestFinal_{name}_{cls}"
        if exported not in namespace:
            owner = getattr(module, cls)
            owner.__name__ = exported
            owner.__qualname__ = exported
            owner.__module__ = namespace["__name__"]
            namespace[exported] = owner
        CASE_MAP[f"tests/{name}.py::{cls}::{method}"] = f"{exported}::{method}"


def source_hash(path):
    return hashlib.sha256(frozen_source(path)).hexdigest()


def verified_error_tree():
    original = ast.parse(frozen_source("tests/test_error_presentation.py"))
    tree = copy.deepcopy(original)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_http_exc_with_reason":
            node.body = ast.parse("return RuntimeError(reason)").body
        elif isinstance(node, ast.FunctionDef) and node.name == "_http_500":
            # Unused obsolete annotation cannot import the removed dependency.
            node.returns = None
    tree.body = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.Import) and any(alias.name == "discord" for alias in node.names)
        )
    ]
    expected = copy.deepcopy(original)
    helper = next(
        node
        for node in expected.body
        if isinstance(node, ast.FunctionDef) and node.name == "_http_exc_with_reason"
    )
    helper.body = [
        ast.Return(
            value=ast.Call(
                func=ast.Name(id="RuntimeError", ctx=ast.Load()),
                args=[ast.Name(id="reason", ctx=ast.Load())],
                keywords=[],
            )
        )
    ]
    next(
        node
        for node in expected.body
        if isinstance(node, ast.FunctionDef) and node.name == "_http_500"
    ).returns = None
    expected.body = [
        node
        for node in expected.body
        if not (
            isinstance(node, ast.Import) and any(alias.name == "discord" for alias in node.names)
        )
    ]
    assert corpus(original) == corpus(tree)
    assert dump(expected) == dump(tree)
    assert hashlib.sha256(dump(tree).encode()).hexdigest() == (
        "3c66667116866f267e031fd82e6213e21a774332a2a67ee1db0e6f82e2b12bcf"
    )
    return tree


def export_error_exact(namespace):
    tree = verified_error_tree()
    tree.body = [
        node for node in tree.body if not isinstance(node, ast.ClassDef) or node.name in ERROR_CASES
    ]
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            node.body = [
                method
                for method in node.body
                if getattr(method, "name", None) in ERROR_CASES[node.name]
            ]
    module = ModuleType("desktop_final_error_helpers")
    exec(
        compile(ast.fix_missing_locations(tree), "tests/test_error_presentation.py", "exec"),
        module.__dict__,
    )
    for cls, methods in ERROR_CASES.items():
        owner = getattr(module, cls)
        exported = f"TestFinal_test_error_presentation_{cls}"
        owner.__name__ = exported
        owner.__qualname__ = exported
        owner.__module__ = namespace["__name__"]
        namespace[exported] = owner
        for method in methods:
            CASE_MAP[f"tests/test_error_presentation.py::{cls}::{method}"] = f"{exported}::{method}"
