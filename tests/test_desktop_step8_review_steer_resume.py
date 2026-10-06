"""Exact frozen steering/resume cases plus adapter-integrity negatives."""
import ast
import hashlib

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from tests.desktop_adapters import step8_review_steer_resume as adapter

adapter.load(globals())


def test_steer_resume_loader_preserves_all_assertions_and_cases():
    original, adapted = adapter.adapt(frozen_source(adapter.SOURCE_PATH))
    assert corpus(original)["assertions"] == corpus(adapted)["assertions"]
    assert corpus(original)["cases"] == corpus(adapted)["cases"]
    assert len(corpus(original)["cases"]) == 9
    assert adapter.CORPUS_EXCLUSIONS == {}


def test_steer_resume_loader_changed_bytes():
    with pytest.raises(ValueError, match="bytes changed"):
        adapter.adapt(frozen_source(adapter.SOURCE_PATH) + b"\n")


def test_steer_resume_loader_wrong_duplicate_and_assertion_hunks():
    source = frozen_source(adapter.SOURCE_PATH)
    with pytest.raises(ValueError, match="duplicate"):
        adapter.adapt(source, hunks=adapter.SETUP_HUNKS * 2)
    line, column, digest, kind, replacement = adapter.SETUP_HUNKS[0]
    with pytest.raises(ValueError, match="exact admitted"):
        adapter.adapt(source, hunks=[(line + 1, column, digest, kind, replacement)])
    assertion = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Assert))
    with pytest.raises(ValueError, match="exact admitted"):
        adapter.adapt(source, hunks=[(assertion.lineno, assertion.col_offset,
                                     hashlib.sha256(dump(assertion).encode()).hexdigest(),
                                     "statement", "assert False")])


def test_steer_resume_loader_collateral_reverse_replay(monkeypatch):
    original_put = adapter._put

    def corrupt(tree, path, value):
        original_put(tree, path, value)
        tree.body.append(ast.parse("unadmitted = 1").body[0])

    monkeypatch.setattr(adapter, "_put", corrupt)
    with pytest.raises(ValueError, match="complete AST reverse replay"):
        adapter.adapt(frozen_source(adapter.SOURCE_PATH))


def test_steer_resume_setup_requires_admitted_worker():
    with pytest.raises(RuntimeError, match="real admitted worker"):
        adapter.admitted_components(None)


async def test_steer_resume_real_gate_rejects_fake_and_unbound_seal(tmp_path):
    from tests.desktop_adapters.process_cases import temporary_owner
    from tests.fakes import FakeMessage

    with temporary_owner(tmp_path / "negative-owner") as state:
        graph = adapter.Graph(state)
        try:
            with pytest.raises(PermissionError, match="current admitted request owner"):
                await graph.engine.runner.run(FakeMessage("not admitted"), history=[])
            response = graph.requests.submit({"client_submission_id": "queued-only",
                                               "conversation_id": graph.cid, "text": "queued"})
            sealed = graph.requests.fetch_request(graph.cid, response["request_id"])
            with pytest.raises(PermissionError, match="current admitted request owner"):
                await graph.engine.run(sealed)
            assert graph.requests.get_request(response["request_id"])["state"] == "queued"
        finally:
            await graph.requests.close()
            await graph.engine.close()
            graph.journal.close()
