"""Whole synthetic corpus plus fail-closed loader proofs; never a live desktop."""
import ast

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from tests.desktop_adapters import step8_controls
from tests.desktop_adapters.step8_controls import load

ORIGINAL, ADAPTED = load(globals())


def test_controls_loader_rejects_changed_source_before_compile():
    with pytest.raises(ValueError, match="baseline bytes"):
        step8_controls.validate_source(frozen_source(step8_controls.SOURCE_PATH) + b"\n")


def test_controls_loader_has_exact_complete_ast_and_no_exclusions():
    assert dump(ORIGINAL) == dump(ADAPTED)
    assert corpus(ORIGINAL) == corpus(ADAPTED)
    assert step8_controls.CORPUS_SELECTIONS == {"test_computer_native_vision_r5": None}
    assert step8_controls.CORPUS_EXCLUSIONS == {}
    inherited = {node.name for node in ORIGINAL.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name.startswith("test_")}
    exported = {name.removeprefix("test_controls_vision_") for name in globals()
                if name.startswith("test_controls_vision_")}
    assert exported == {name.removeprefix("test_") for name in inherited}


def test_controls_loader_rejects_archive_reader_failure(monkeypatch):
    def denied(_path):
        raise ValueError("retained frozen evidence unavailable")

    monkeypatch.setattr(step8_controls, "frozen_source", denied)
    with pytest.raises(ValueError, match="retained frozen evidence unavailable"):
        step8_controls.load({"__name__": "unreachable_controls_module"})
