"""Exact partial support projection; whole empty-fields suite remains deferred."""
import ast
import copy

import pytest

from scripts.maintenance.fixture_corpus import corpus
from tests.desktop_adapters import step8_6a_empty_fields as adapter
from tests.desktop_adapters.tools_cases import owner_fixture


@pytest.fixture(autouse=True)
def _empty_fields_canonical_owner(tmp_path):
    with owner_fixture(tmp_path):
        yield


_original, _retained, _adapted, _hunks = adapter.load_support(globals())


def test_empty_fields_frozen_corpus_identity():
    assert corpus(_retained) == corpus(_adapted)
    assert len(corpus(_original)["cases"]) == 7
    assert len(corpus(_retained)["cases"]) == 5
    projection = copy.deepcopy(_original)
    projection.body = [node for node in projection.body if not (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in adapter.DEFERRED_CASES
    )]
    assert corpus(_retained) == corpus(projection)
    assert {name for name, _, _ in corpus(_retained)["cases"]} == adapter.SUPPORT_CASES
    assert not adapter.CORPUS_SELECTIONS
    assert not adapter.SUITES
    assert adapter.SUPPORT_SUITE == {"test_delivery_empty_fields": adapter.SOURCE_SHA256}


def test_empty_fields_support_registration_excludes_exact_deferred_cases(monkeypatch):
    calls = []
    original_register = adapter.register_module

    def tracked_register(namespace, module, *, excluded):
        calls.append(set(excluded))
        original_register(namespace, module, excluded=excluded)

    monkeypatch.setattr(adapter, "register_module", tracked_register)
    namespace = {"__name__": __name__}
    adapter.load_support(namespace)
    assert calls == [set(adapter.DEFERRED_CASES)]
    assert {name for name in namespace if name.startswith("test_")} == adapter.SUPPORT_CASES
    assert not (namespace.keys() & adapter.DEFERRED_CASES.keys())


def test_empty_fields_whole_loader_remains_deferred():
    namespace = {"__name__": __name__}
    with pytest.raises(RuntimeError, match="Whole empty-fields suite deferred"):
        adapter.load(namespace)
    assert namespace == {"__name__": __name__}
