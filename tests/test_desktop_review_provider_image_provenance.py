"""Full original sealed, and unavailable meanings not silently skipped."""

import ast
import hashlib

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters import review_provider_image as adapter


def test_whole_original_bytes_and_corpus_are_preserved():
    source = frozen_source(adapter.PATH)
    assert hashlib.sha256(source).hexdigest() == adapter.SHA256
    original = ast.parse(source)
    assert adapter.inherited_corpus() == corpus(original)
    assert adapter.CORPUS_SELECTIONS == {"test_image_model_config_api": None}
    assert adapter.CORPUS_EXCLUSIONS == {}
    cases = {symbol for symbol, _, _ in corpus(original)["cases"]}
    assert set(adapter.BLOCKERS) <= cases
    assert len(cases) == 11


def test_no_blocked_case_omission_or_fake_export():
    namespace = {}
    with pytest.raises(RuntimeError, match="Whole frozen image suite unavailable"):
        adapter.export_whole_suite(namespace)
    assert namespace == {}


def test_blockers_specific_and_not_a_generic_skip():
    assert "api-token" in adapter.BLOCKERS["test_operation_admin_only"]
    assert "cancelled" in adapter.BLOCKERS["test_cancellation_publishes_only_durable_commit"]
    assert (
        "config_transaction"
        in adapter.BLOCKERS["test_pin_uses_lock_current_state_and_preserves_concurrent_save"]
    )
    assert "diff-tracker" in adapter.BLOCKERS["test_error_branches_and_audit_failure"]


def test_partial_inherited_all_assertions_preserved_and_hunks_reversible():
    import copy

    from scripts.maintenance.fixture_corpus import dump
    from tests.desktop_adapters import review_provider_image_inherited as partial

    original = adapter.source_tree()
    assert corpus(partial.adapted_tree()) == corpus(original)
    assert len(partial.SELECTION) == 5
    tree = copy.deepcopy(partial.adapted_tree())
    for symbol, line, before, after in reversed(partial.hunk_pairs()):
        from scripts.maintenance.fixture_corpus import nodes

        matches = [
            node
            for owner, node in nodes(tree)
            if owner == symbol
            and getattr(node, "lineno", None) == line
            and dump(node) == dump(after)
        ]
        assert len(matches) == 1
        target = matches[0]

        class Undo(ast.NodeTransformer):
            def visit(self, node):
                if node is target:
                    return ast.copy_location(copy.deepcopy(before), node)
                return super().visit(node)

        tree = Undo().visit(tree)
    assert dump(tree) == dump(original)
