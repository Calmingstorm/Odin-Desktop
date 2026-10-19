"""The frozen wrapper suite with the one case Odin 4.19.2 superseded retired.

Odin 4.19.2 (PR #670) passes the foreground late-ACK opt-in to SupervisedShell by keyword. One
frozen case replaces SupervisedShell with a positional-only test double, which cannot take it;
its 4.19.2 version runs in tests/test_desktop_foreground_late_ack.py. The retired definition
stays compiled with unchanged assertions and is only not exported to pytest. Every other case
runs from the immutable v4.13.0 source, unchanged.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from scripts.maintenance.fixture_corpus import register_module as export_module

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = "tests/test_local_supervisor_wrapper_r10.py"
SOURCE_SHA256 = "d8cf0282d36589fb4bb13780d0acaa74ba46be3b9e650d575e85c6d815e2b629"
CORPUS_SELECTIONS = {"test_local_supervisor_wrapper_r10": None}
CORPUS_EXCLUSIONS = {
    "test_local_supervisor_wrapper_r10": [
        {
            "case": "test_started_shell_cleanup_failure_preserves_launch_error",
            "reviewer": "Claude, Odin Desktop 1.3.3 carry of Odin 4.19.2 (PR #670)",
            "reason": (
                "Odin 4.19.2 passes the foreground late-ACK opt-in to SupervisedShell by keyword; "
                "the frozen positional test double cannot take it, and the case's 4.19.2 version "
                "runs in tests/test_desktop_foreground_late_ack.py"),
            "source_path": "tests/test_local_supervisor_wrapper_r10.py",
            "source_sha256": "d8cf0282d36589fb4bb13780d0acaa74ba46be3b9e650d575e85c6d815e2b629",
        }
    ]
}


def source_tree():
    data = frozen_source(SOURCE_PATH)
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("inherited source hash changed")
    return ast.parse(data)


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
        module = ModuleType(f"desktop_odin_4192_{name}")
        module.__file__ = str(ROOT / SOURCE_PATH)
        exec(compile(tree, module.__file__, "exec"), module.__dict__)
        expected = [case for case, _, _ in corpus(tree)["cases"]]
        actual = [key for key in vars(module) if key.startswith("test_")]
        if sorted(actual) != sorted(expected):
            raise ValueError("incomplete inherited suite compilation")
        register_module(namespace, module, prefix=name,
                        excluded=[item['case'] for item in CORPUS_EXCLUSIONS.get(name, ())])
        for key, value in vars(module).items():
            if type(value).__name__ == "FixtureFunctionDefinition":
                namespace[key] = value
