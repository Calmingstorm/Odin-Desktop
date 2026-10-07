"""Whole inherited corpus seals, exact setup hunks and complete exports."""
import ast
import copy

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump
from tests.desktop_adapters import review_provider_quota as adapter


def test_quota_complete_frozen_corpus_and_reversible_setup_hunks():
    original = adapter.source_tree()
    adapted = adapter.adapted_tree()
    assert adapter.verify_adaptation(original, adapted)
    assert corpus(original) == corpus(adapted)
    assert {key: len(value) for key, value in corpus(adapted).items()} == {
        "assertions": 45, "cases": 10, "classes": 4,
    }
    assert dump(adapter.reverse_adaptation(adapted)) == dump(original)
    assert len(adapter.HUNKS) == 7
    assert adapter.SUITES == {"test_codex_quota_check": adapter.SOURCE_SHA256}
    assert adapter.CORPUS_SELECTIONS == {"test_codex_quota_check": None}
    assert adapter.CORPUS_EXCLUSIONS == {}


@pytest.mark.parametrize("change", ["assertion", "helper", "case", "setup", "decorator"])
def test_quota_complete_seal_rejects_semantic_or_setup_changes(change):
    original = adapter.source_tree()
    altered = copy.deepcopy(adapter.adapted_tree())
    if change == "assertion":
        assertion = next(node for node in ast.walk(altered) if isinstance(node, ast.Assert))
        assertion.test = ast.Constant(True)
    elif change in {"helper", "case"}:
        name = ("Pool" if change == "helper"
                else "test_hot_reload_mid_refresh_never_records_to_retired_pool")
        altered.body = [node for node in altered.body if getattr(node, "name", None) != name]
    elif change == "setup":
        call = next(node for node in ast.walk(altered)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "CodexQuotaCheckService")
        call.args = [ast.Constant(None)]
    else:
        case = next(node for node in altered.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name.startswith("test_"))
        case.decorator_list = []
    with pytest.raises(AssertionError):
        adapter.verify_adaptation(original, altered)


def test_quota_loader_exports_all_inherited_tests_and_helpers():
    namespace = {"__name__": "quota_whole_export_probe"}
    exported = adapter.load(namespace)
    for node in adapter.source_tree().body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name in exported
            if isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        assert method.name in vars(exported[node.name])
    assert len([name for name in exported if name.startswith("test_")]) == 10


@pytest.mark.parametrize("index", range(7))
def test_quota_exact_setup_hunks_fail_closed_on_changed_original(index):
    original = adapter.source_tree()
    symbol, line, before_hash, _ = adapter.HUNKS[index]
    target = next(node for owner, node in adapter.nodes(original)
                  if owner == symbol and getattr(node, "lineno", None) == line
                  and adapter.hashlib.sha256(dump(node).encode()).hexdigest() == before_hash)
    if isinstance(target, ast.ImportFrom):
        target.module = "unapproved.fixture"
    elif isinstance(target, ast.Attribute):
        target.attr = "unapproved_reload"
    else:
        target.value = ast.Constant(None)
    with pytest.raises(AssertionError):
        adapter.verify_adaptation(original, adapter.adapted_tree())
