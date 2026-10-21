"""The frozen native knowledge suite with the three cases Odin 4.20.0 superseded retired.

Odin 4.20.0 (PR #671) reads search_audit calls from the audit stream
(``iter_entries_newest_first``), so three frozen TestSearchAudit cases, whose double answers
only ``search``, no longer reach the handler. Their 4.20.0 versions run in
tests/test_desktop_odin_4200_cases.py. The retired definitions stay compiled with unchanged
assertions and are only not exported to pytest. Every other case runs from the immutable
v4.13.0 source, unchanged.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from scripts.maintenance.fixture_corpus import register_module as export_module

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = "tests/test_native_knowledge.py"
SOURCE_SHA256 = "418046d5ffe538ac586ccc89fa17b2430347fca1838c3dcbb5b404e556c25bac"
CORPUS_SELECTIONS = {"test_native_knowledge": None}
CORPUS_EXCLUSIONS = {
    "test_native_knowledge": [
        {
            "case": "TestSearchAudit.test_formats_entries",
            "reviewer": "Claude, Odin Desktop 1.4.0 carry of Odin 4.20.0 (PR #671)",
            "reason": (
                "Odin 4.20.0 reads search_audit calls from the audit stream, so this case's "
                "search double never reaches the handler; its 4.20.0 version runs in "
                "tests/test_desktop_odin_4200_cases.py"),
            "source_path": "tests/test_native_knowledge.py",
            "source_sha256": "418046d5ffe538ac586ccc89fa17b2430347fca1838c3dcbb5b404e556c25bac",
        },
        {
            "case": "TestSearchAudit.test_renders_agent_attribution_and_tool_input",
            "reviewer": "Claude, Odin Desktop 1.4.0 carry of Odin 4.20.0 (PR #671)",
            "reason": (
                "Odin 4.20.0 reads search_audit calls from the audit stream, so this case's "
                "search double never reaches the handler; its 4.20.0 version runs in "
                "tests/test_desktop_odin_4200_cases.py"),
            "source_path": "tests/test_native_knowledge.py",
            "source_sha256": "418046d5ffe538ac586ccc89fa17b2430347fca1838c3dcbb5b404e556c25bac",
        },
        {
            "case": "TestSearchAudit.test_renders_audit_metadata",
            "reviewer": "Claude, Odin Desktop 1.4.0 carry of Odin 4.20.0 (PR #671)",
            "reason": (
                "Odin 4.20.0 reads search_audit calls from the audit stream, so this case's "
                "search double never reaches the handler; its 4.20.0 version runs in "
                "tests/test_desktop_odin_4200_cases.py"),
            "source_path": "tests/test_native_knowledge.py",
            "source_sha256": "418046d5ffe538ac586ccc89fa17b2430347fca1838c3dcbb5b404e556c25bac",
        },
    ]
}


def source_tree():
    data = frozen_source(SOURCE_PATH)
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("inherited source hash changed")
    return ast.parse(data)


def compiled_cases(module) -> list[str]:
    """Every test case the compiled module defines, as corpus symbols."""
    cases = []
    for key, value in vars(module).items():
        if key.startswith("test_") and callable(value):
            cases.append(key)
        elif key.startswith("Test") and isinstance(value, type):
            cases.extend(f"{key}.{name}" for name in vars(value) if name.startswith("test_"))
    return cases


def register_module(namespace, module, *, prefix, excluded):
    """Export all and only nonretired definitions from the intact compiled module."""
    expected = [row["case"] for row in CORPUS_EXCLUSIONS[prefix]]
    if excluded != expected:
        raise ValueError("unreviewed inherited export exclusion")
    export_module(namespace, module, prefix=prefix, excluded=excluded)


def load(namespace):
    for name in CORPUS_SELECTIONS:
        tree = source_tree()
        if corpus(tree) != corpus(source_tree()):
            raise ValueError("inherited assertion/signature/decorator meaning changed")
        module = ModuleType(f"desktop_odin_4200_{name}")
        module.__file__ = str(ROOT / SOURCE_PATH)
        exec(compile(tree, module.__file__, "exec"), module.__dict__)
        expected = [case for case, _, _ in corpus(tree)["cases"]]
        if sorted(compiled_cases(module)) != sorted(expected):
            raise ValueError("incomplete inherited suite compilation")
        register_module(namespace, module, prefix=name,
                        excluded=[item['case'] for item in CORPUS_EXCLUSIONS.get(name, ())])
        for key, value in vars(module).items():
            if type(value).__name__ == "FixtureFunctionDefinition":
                namespace[key] = value
