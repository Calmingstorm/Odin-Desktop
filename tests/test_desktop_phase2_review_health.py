"""PR34 health/executor whole inherited suites and sealed-corpus proofs."""
import ast
import copy
import hashlib
from unittest.mock import AsyncMock

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters.process_cases import temporary_owner
from tests.desktop_adapters.step8_review_health import (
    CORPUS_SELECTIONS,
    AgentPolicyCarrier,
    adapted_tree,
    executor,
    fixture_owner_id,
    fixture_state,
    load,
    records,
    source_tree,
    verify_adaptation,
)


@pytest.fixture(autouse=True)
def review_health_owner(tmp_path_factory):
    with temporary_owner(tmp_path_factory.mktemp("pr34-health-owner")) as owner:
        binding = fixture_state.set(owner)
        try:
            yield owner
        finally:
            fixture_state.reset(binding)


@pytest.mark.parametrize("name", tuple(CORPUS_SELECTIONS))
def test_exact_complete_tree_and_case_counts(name):
    adapted = adapted_tree(name)
    assert verify_adaptation(name, adapted)
    record = next(row for row in records()["entries"] if row["path"] == f"tests/{name}.py")
    original = corpus(source_tree(name))
    assert len(original["cases"]) == record["inherited_counts"]["test_definitions"]
    assert len(original["assertions"]) == record["inherited_counts"]["assertions"]
    assert CORPUS_SELECTIONS[name] is None


@pytest.mark.parametrize("name", tuple(CORPUS_SELECTIONS))
@pytest.mark.parametrize("mutation", ("assertion", "case", "setup"))
def test_complete_guard_rejects_tampering(name, mutation):
    tree = copy.deepcopy(adapted_tree(name))
    if mutation == "assertion":
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.Assert))
        node.test = ast.Constant(value=True)
    elif mutation == "case":
        tree.body = [n for n in tree.body if not (
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
        )]
    else:
        tree.body.append(ast.parse("unledgered_setup = True").body[0])
    with pytest.raises(ValueError, match="undeclared source change"):
        verify_adaptation(name, tree)


def test_all_four_inherited_bytes_and_no_partial_health_restoration():
    rows = records()["entries"]
    assert len(rows) == 4
    assert sum(row["status"] == "restored" for row in rows) == 1
    for row in rows:
        frozen = frozen_source(row["path"])
        assert hashlib.sha256(frozen).hexdigest() == row["inherited_sha256"]
        inherited = corpus(ast.parse(frozen))
        assert len(inherited["cases"]) == row["inherited_counts"]["test_definitions"]
        assert len(inherited["assertions"]) == row["inherited_counts"]["assertions"]
        if row["status"] == "deferred":
            assert "restoration" not in row
            assert row["blocked_on"]


def test_executor_is_authentic_owner_ready_and_foreign_owner_denied(tmp_path, review_health_owner):
    ex = executor(tmp_path)
    assert ex._permission_manager is review_health_owner.manager
    assert review_health_owner.manager.is_owner(fixture_owner_id())
    assert ex.check_permission("get_tool_output", fixture_owner_id()) is None
    assert ex._builtin_policy.is_available("get_tool_output")
    assert not ex._authorize_output("get_tool_output", (), "owner")
    assert ex._authorize_output("get_tool_output", (), fixture_owner_id())


async def test_agent_projection_is_actual_protocol_refusal_without_dispatch():
    persist = AsyncMock(side_effect=AssertionError("no config mutation"))
    async with AgentPolicyCarrier(persist) as carrier:
        response = await carrier.put("/api/agents/model", data="{")
        assert response.desktop_verdict == {"t": "bye", "reason": "protocol_error"}
        assert response.status == 400
        assert carrier.dispatched == []
        assert not carrier.owner.paths.config_file.exists()
    persist.assert_not_called()
    persist.assert_not_awaited()


load(globals())
