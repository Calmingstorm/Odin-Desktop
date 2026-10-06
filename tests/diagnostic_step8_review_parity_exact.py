"""Explicit-only diagnostic candidate, preserving every inherited assertion.

Excluded from default test_ discovery because the complete suite is blocked.
"""
import ast

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters import step8_review_parity_exact as adapter

adapter.load(globals())


@pytest.fixture(autouse=True)
async def parity_owner(request, tmp_path):
    if not request.node.name.startswith("test_review_parity_exact_"):
        yield
        return
    async for state in adapter.admitted.owner_fixture(tmp_path):
        yield state


def test_parity_loader_preserves_all_assertions_and_cases():
    original, tree = adapter.adapt(frozen_source(adapter.SOURCE_PATH))
    assert corpus(original) == corpus(tree)
    assert len(corpus(original)["assertions"]) == 45
    assert len(corpus(original)["cases"]) == 4
    assert sum(isinstance(node, ast.Assert) for node in ast.walk(tree)) == 45


def test_parity_loader_rejects_source_and_hunk_changes():
    source = frozen_source(adapter.SOURCE_PATH)
    with pytest.raises(ValueError, match="bytes changed"):
        adapter.adapt(source + b"\n")
    with pytest.raises(ValueError, match="duplicate"):
        adapter.adapt(source, hunks=adapter.SETUP_HUNKS * 2)
    with pytest.raises(ValueError, match="exact parity setup"):
        adapter.adapt(source, hunks=[])


def test_inline_literal_owner_goldens_are_blockers_not_remapped():
    original, tree = adapter.adapt(frozen_source(adapter.SOURCE_PATH))
    assertions = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    owner_lines = {node.lineno for node in assertions if any(
        isinstance(child, ast.Constant) and child.value == "requester-1"
        for child in ast.walk(node))}
    request_lines = {node.lineno for node in assertions if any(
        isinstance(child, ast.Constant) and child.value == "request-1"
        for child in ast.walk(node))}
    assert owner_lines == {393, 401, 402, 470, 477, 480, 502}
    assert request_lines == {501}
    assert corpus(original) == corpus(tree)
