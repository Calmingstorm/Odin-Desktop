"""Frozen steering runtime and exact fail-closed loader proofs."""
import ast
import hashlib

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from tests.desktop_adapters import step8_review_steering as adapter

adapter.load(globals())


@pytest.fixture(autouse=True)
async def review_steering_owner(request, tmp_path):
    if not request.node.name.startswith("test_review_steering_"):
        yield
        return
    async for state in adapter.owner_fixture(tmp_path):
        yield state


def test_loader_complete_runtime_corpus():
    original, tree = adapter.adapt("runtime", frozen_source(adapter.SOURCES["runtime"][0]))
    assert corpus(original) == corpus(tree)
    assert len(corpus(original)["cases"]) == 11
    assert len(adapter.CORPUS_EXCLUSIONS["test_chat_steering_runtime"]) == 1


def test_loader_rejects_changed_bytes_and_hunks():
    source = frozen_source(adapter.SOURCES["runtime"][0])
    with pytest.raises(ValueError, match="bytes changed"):
        adapter.adapt("runtime", source + b"\n")
    with pytest.raises(ValueError, match="duplicate"):
        adapter.adapt("runtime", source, hunks=adapter.SETUP_HUNKS["runtime"] * 2)
    with pytest.raises(ValueError, match="exact admitted"):
        adapter.adapt("runtime", source, hunks=[])
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Assert))
    with pytest.raises(ValueError, match="exact admitted"):
        adapter.adapt("runtime", source, hunks=[(node.lineno, node.col_offset,
            hashlib.sha256(dump(node).encode()).hexdigest(), "assert False", "statement")])


def test_loader_rejects_collateral_ast(monkeypatch):
    original_put = adapter._put
    def corrupt(tree, path, node):
        original_put(tree, path, node)
        tree.body.append(ast.parse("unadmitted = 1").body[0])
    monkeypatch.setattr(adapter, "_put", corrupt)
    with pytest.raises(ValueError, match="complete AST reverse replay"):
        adapter.adapt("runtime", frozen_source(adapter.SOURCES["runtime"][0]))


def test_constructor_requires_canonical_owner():
    with pytest.raises(RuntimeError, match="authenticated temporary owner"):
        adapter._graph([])


async def test_authentic_gate_rejects_fake_and_unbound_seal(tmp_path):
    from tests.fakes import FakeMessage
    async for _state in adapter.owner_fixture(tmp_path):
        graph, _llm = adapter._graph([])
        with pytest.raises(PermissionError, match="current admitted request owner"):
            await graph.runner.run(FakeMessage("unadmitted"), history=[])
        submitted = graph.requests.submit({"client_submission_id": "queued-only",
            "conversation_id": graph.cid, "text": "not executing"})
        sealed = graph.requests.fetch_request(graph.cid, submitted["request_id"])
        with pytest.raises(PermissionError, match="current admitted request owner"):
            await graph.engine.run(sealed)
        assert graph.requests.get_request(submitted["request_id"])["state"] == "queued"
