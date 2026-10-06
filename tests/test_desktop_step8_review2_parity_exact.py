"""Round-2 inherited parity export and exact transformation guards."""
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
    modified = list(adapter.SETUP_HUNKS)
    line, column, digest, replacement = modified[1]
    modified[1] = (line, column, digest, replacement + "\n    return 'fake'")
    with pytest.raises(ValueError, match="exact parity setup"):
        adapter.adapt(source, hunks=modified)


def test_inline_literal_goldens_remain_unmodified():
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


def test_export_retires_only_tier_denial_case():
    names = sorted(name for name in globals() if name.startswith("test_review_parity_exact_"))
    assert names == [
        "test_review_parity_exact_unsteered_chat_runtime_trace_return_and_guard_parity",
        "test_review_parity_exact_unsteered_guard_checkpoint_trace_matches_pre_steer_runtime",
        "test_review_parity_exact_unsteered_tool_checkpoint_trace_matches_pre_steer_runtime",
    ]
    assert adapter.CORPUS_SELECTIONS == {"test_chat_steering_parity": None}
    assert adapter.CORPUS_EXCLUSIONS["test_chat_steering_parity"][0]["reviewer"] == (
        "Claude, review of #35, round 2")


def _observation():
    return {
        "events": ["guard.entry", "permission:read_only:real-owner", "delivery:real-owner"],
        "generations": [(1, [{"content": "real-owner"}], "real-owner")],
        "permissions": [("read_only", "real-owner")],
        "dispatches": [("read_only", {"path": "real-request"}, "real-owner", "real-owner", False)],
        "bindings": [("real-request", True, False)],
        "inbox_bindings": [None, ("real-owner", True)],
        "active_requests": {"channel": "real-request"},
        "result": ("real-owner real-request", False),
        "messages": [{"content": "real-owner real-request"}],
        "checkpoints": [("wi4", "real-request")],
    }


def test_identity_projection_changes_only_named_owner_and_request_fields():
    raw = _observation()
    expected = _observation()
    expected.update({
        "events": ["guard.entry", "permission:read_only:requester-1", "delivery:real-owner"],
        "generations": [(1, [{"content": "real-owner"}], "requester-1")],
        "permissions": [("read_only", "requester-1")],
        "dispatches": [("read_only", {"path": "real-request"},
                        "requester-1", "requester-1", False)],
        "bindings": [("request-1", True, False)],
        "inbox_bindings": [None, ("requester-1", True)],
        "active_requests": {"channel": "request-1"},
    })
    assert adapter.normalize_identities(raw, owner="real-owner", request="real-request") == expected
    assert raw == _observation()


@pytest.mark.parametrize("field", ["events", "generations", "permissions", "dispatches",
                                   "bindings", "inbox_bindings", "active_requests"])
def test_identity_projection_rejects_nonbijective_or_foreign_identity(field):
    raw = _observation()
    foreign = {
        "events": ["permission:read_only:second-owner"],
        "generations": [(0, [], "second-owner")],
        "permissions": [("read_only", "second-owner")],
        "dispatches": [("read_only", {}, "second-owner", "real-owner", False)],
        "bindings": [("second-request", True, False)],
        "inbox_bindings": [("second-owner", True)],
        "active_requests": {"channel": "second-request"},
    }
    raw[field] = foreign[field]
    with pytest.raises(ValueError, match="unexpected identity"):
        adapter.normalize_identities(raw, owner="real-owner", request="real-request")
    with pytest.raises(ValueError, match="distinct allocated"):
        adapter.normalize_identities(_observation(), owner="same", request="same")


async def test_real_native_read_readiness_owner_and_delivery_fences(tmp_path):
    from src.tools.runtime_delivery import deliver_runtime_output

    async for _state in adapter.admitted.owner_fixture(tmp_path):
        graph, _llm = adapter.admitted._graph([])
        adapter.wire_native_read(graph)
        executor = graph.runner._tool_executor
        kwargs = {"tool_name": "read_only", "tool_input": {"path": "/tmp/x"},
                  "channel_id": graph.cid}
        owner = adapter.admitted.owner_id()
        assert executor.check_permission("read_only", owner) is None
        assert executor.check_permission("read_only", "requester-1") is not None
        with pytest.raises(PermissionError):
            deliver_runtime_output(executor, "evidence", user_id="requester-1", **kwargs)
        assert graph.native_read.reads == []
        assert await graph.native_read.read({"path": "/tmp/x"}) == "read:/tmp/x"
        assert graph.native_read.reads == [b"read:/tmp/x"]
        assert deliver_runtime_output(executor, "evidence", user_id=owner, **kwargs) == "evidence"
        with pytest.raises(ValueError, match="unexpected parity fixture"):
            await graph.native_read.read({"path": "/etc/passwd"})
        graph.native_read.target.unlink()
        assert graph.engine.deps.readiness()["read_only"] is False
        with pytest.raises(PermissionError, match="Output capability unavailable"):
            deliver_runtime_output(executor, "evidence", user_id=owner, **kwargs)
        assert graph.native_read.reads == [b"read:/tmp/x"]
