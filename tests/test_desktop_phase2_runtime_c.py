"""Step8 part2 batch C: whole-module provenance and authentic ingestion roots."""

import ast as _ast
import copy as _copy

import pytest as _pytest

from scripts.maintenance.fixture_corpus import corpus as _corpus
from scripts.maintenance.fixture_corpus import dump as _dump
from tests.desktop_adapters import step8_runtime_c as _adapter
from tests.desktop_adapters.step8_runtime_c import load


@_pytest.mark.parametrize("path", list(_adapter.SOURCE_DIGESTS))
def test_runtime_c_original_source_digest_and_complete_corpus(path):
    original = _adapter.source_tree(path)
    if path == _adapter.INGEST_PATH:
        adapted = _adapter.adapted_tree()
        assert _adapter.verify_adaptation(original, adapted)
        assert _corpus(original) == _corpus(adapted)
        assert len(_corpus(adapted)["assertions"]) == 98
        assert len(_corpus(adapted)["cases"]) == 25
        assert len(_corpus(adapted)["classes"]) == 4
    else:
        # These two are executed directly, with no AST or fixture adaptation.
        assert _corpus(original)["cases"]


def test_runtime_c_only_exact_setup_hunks_are_admitted():
    original = _adapter.source_tree(_adapter.INGEST_PATH)
    adapted = _adapter.adapted_tree()
    assert len(_adapter.SETUP_HUNKS) == 7
    assert _adapter.CORPUS_SELECTIONS == {"test_knowledge_ingest_outcomes": None}
    assert _adapter.CORPUS_EXCLUSIONS == {}
    assert _adapter.SUITES == {
        "test_knowledge_ingest_outcomes": _adapter.SOURCE_DIGESTS[_adapter.INGEST_PATH],
    }
    assert len(original.body) == len(adapted.body)
    for before, after in zip(original.body, adapted.body, strict=True):
        if isinstance(before, _ast.ClassDef) and before.name == "TestImporterOutcomes":
            assert len(before.body) == len(after.body)
        else:
            assert _dump(before) == _dump(after)
    mutated = _copy.deepcopy(adapted)
    # A changed assertion, even one that remains true, is not an adaptation.
    assertion = next(node for node in _ast.walk(mutated) if isinstance(node, _ast.Assert))
    assertion.test = _ast.Constant(value=True)
    with _pytest.raises(AssertionError):
        _adapter.verify_adaptation(original, mutated)


@_pytest.mark.parametrize("symbol,line", _adapter.SETUP_HUNKS)
def test_runtime_c_setup_guard_rejects_missing_or_changed_hunks(symbol, line):
    original = _adapter.source_tree(_adapter.INGEST_PATH)
    mutated = _copy.deepcopy(original)
    call = next(node for owner, node in _adapter.nodes(mutated)
                if owner == symbol and getattr(node, "lineno", None) == line
                and isinstance(node, _ast.Call) and _dump(node) == _dump(_adapter.BEFORE_CALL))
    call.args = [_ast.Name(id="other_store", ctx=_ast.Load())]
    with _pytest.raises(AssertionError):
        _adapter.verify_adaptation(mutated, _adapter.adapted_tree())


def test_runtime_c_whole_module_exports_all_inherited_definitions():
    namespace = {"__name__": "whole_ingest_export_probe"}
    exported = _adapter.export_whole_suite(namespace)
    tree = _adapter.source_tree(_adapter.INGEST_PATH)
    for node in tree.body:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            assert node.name in exported
            if isinstance(node, _ast.ClassDef):
                for method in node.body:
                    if isinstance(method, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                        assert method.name in vars(exported[node.name])
    assert "_store" in exported and "_long_doc" in exported and "_close" in exported


@_pytest.mark.parametrize("change", ["root_keyword", "drop_helper", "drop_case"])
def test_runtime_c_setup_guard_rejects_any_other_module_change(change):
    original = _adapter.source_tree(_adapter.INGEST_PATH)
    mutated = _adapter.adapted_tree()
    if change == "root_keyword":
        call = next(node for node in _ast.walk(mutated)
                    if isinstance(node, _ast.Call) and _dump(node) == _dump(_adapter.AFTER_CALL))
        call.keywords[0].value.elts = [_ast.Name(id="untrusted_root", ctx=_ast.Load())]
    elif change == "drop_helper":
        mutated.body = [node for node in mutated.body if getattr(node, "name", None) != "_close"]
    else:
        cls = next(node for node in mutated.body
                   if isinstance(node, _ast.ClassDef) and node.name == "TestImporterOutcomes")
        cls.body.pop()
    with _pytest.raises(AssertionError):
        _adapter.verify_adaptation(original, mutated)


async def test_runtime_c_admitted_roots_use_real_guard_and_deny_outside(tmp_path):
    from src.knowledge.importer import BulkImporter
    from src.knowledge.store import KnowledgeStore

    admitted = tmp_path / "admitted"
    admitted.mkdir()
    inside = admitted / "inside.md"
    inside.write_text("admitted ingestion content", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("unadmitted ingestion content", encoding="utf-8")
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    try:
        importer = BulkImporter(store, admitted_roots=[admitted])
        assert importer._admitted_roots == (admitted.resolve(),)
        assert (await importer.import_file(str(inside))).status == "ok"
        rejected = await importer.import_file(str(outside))
        assert rejected.status == "error"
        assert "not in allowed import roots" in rejected.error
        assert store.get_source_content(outside.resolve().as_uri()) is None
        assert (await BulkImporter(store).import_file(str(inside))).status == "error"
    finally:
        store.close()


_WHOLE_INGEST_EXPORTS = load(globals())
