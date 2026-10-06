"""Explicit partial inherited PR34 LLM-admin selection, not whole-suite credit."""
import aiohttp
import pytest_asyncio

from tests.desktop_adapters import step8_review_llm as adapter


@pytest_asyncio.fixture(autouse=True)
async def _real_private_graph(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("LLM-admin restoration may not contact live endpoints")
    monkeypatch.setattr(aiohttp, "ClientSession", forbidden)
    async for graph in adapter.isolated_graph(tmp_path):
        yield graph


adapter.load(globals())


def test_exact_reversible_hunks_and_complete_frozen_corpus():
    original = adapter.source_tree()
    adapted = adapter.adapted_tree()
    assert adapter.corpus(original) == adapter.corpus(adapted)


def test_explicit_selection_and_exclusions_partition_inherited_definitions():
    import ast
    import json
    record = json.loads(adapter.RECORD.read_text())
    partial = record["entries"][0]["partial"]
    inherited = {
        symbol.replace(".", "::") for symbol, node in adapter.nodes(adapter.source_tree())
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }
    selected = set(partial["selectors"])
    excluded = {row["selector"] for row in partial["excluded"]}
    assert not selected & excluded
    assert selected | excluded == inherited
    assert len(inherited) == 122
    assert record["entries"][0]["status"] == "deferred"
