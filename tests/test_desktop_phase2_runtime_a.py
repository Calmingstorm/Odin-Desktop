"""Batch A whole-suite restoration and exact setup guard regressions."""
import ast
from types import SimpleNamespace

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src.desktop.management import MethodError
from tests.desktop_adapters.step8_runtime_a import (
    CORPUS_SELECTIONS,
    fixture_executor,
    fixture_owner_id,
    fixture_state,
    load,
    records,
    state_put_handler,
    transformed_source,
    verify_source,
)
from tests.desktop_adapters.tools_cases import owner_fixture


@pytest.fixture(autouse=True)
def batch_a_owner(tmp_path_factory):
    with owner_fixture(tmp_path_factory.mktemp("step8-runtime-a")) as state:
        token = fixture_state.set(state)
        try:
            yield state
        finally:
            fixture_state.reset(token)


@pytest.mark.parametrize("name", tuple(CORPUS_SELECTIONS))
def test_complete_inherited_corpus_and_reverse_hunks(name):
    source = transformed_source(name)
    assert corpus(verify_source(name, source)) == corpus(
        ast.parse(frozen_source(f"tests/{name}.py")))


@pytest.mark.parametrize("name", tuple(CORPUS_SELECTIONS))
def test_reverse_guard_rejects_unledgered_setup_and_assertion_changes(name):
    source = transformed_source(name)
    with pytest.raises(ValueError, match="undeclared source change"):
        verify_source(name, source + "\nunledgered_setup = True\n")
    with pytest.raises(ValueError, match="undeclared source change"):
        verify_source(name, source.replace("assert ", "assert False and ", 1))


def test_all_twenty_two_assigned_originals_match_source_hashes():
    import hashlib
    rows = records()["decisions"]
    entries = records()["entries"]
    assert len(rows) == 22
    assert len(entries) == 22
    assert [entry["path"] for entry in entries] == [row["path"] for row in rows]
    assert sum(entry["status"] == "restored" for entry in entries) == 3
    assert [row["assigned_index"] for row in rows] == list(range(0, 85, 4))
    for row in rows:
        assert hashlib.sha256(frozen_source(row["path"])).hexdigest() == row["inherited_sha256"]


async def test_state_projection_uses_committed_success_and_real_domain_refusal():
    executor = fixture_executor()
    put = state_put_handler(executor)

    def request(scope):
        async def body():
            return {"value": "retained"}
        return SimpleNamespace(match_info={"scope": scope, "key": "proof"}, json=body)

    result = await put(request("global"))
    assert result.status == 200
    assert result.body == {"status": "saved", "scope": "global", "key": "proof"}
    assert executor._load_all_memory()["global"]["proof"] == "retained"
    with pytest.raises(MethodError) as refused:
        await put(request("user_not-the-authenticated-owner"))
    assert refused.value.code == "forbidden"


async def test_multi_host_refusal_is_real_ready_authenticated_dispatch(batch_a_owner):
    executor = fixture_executor()
    assert executor._permission_manager is batch_a_owner.manager
    assert batch_a_owner.manager.is_owner(fixture_owner_id())
    assert executor._builtin_policy.is_available("run_command_multi")
    assert executor.check_permission("run_command_multi", fixture_owner_id()) is None
    result = await executor.execute(
        "run_command_multi", {"hosts": ["definitely-not-a-host"], "command": "echo hi"},
        user_id=fixture_owner_id(),
    )
    assert result.ok is False
    assert result.error not in {"tool_unavailable", "tool_disabled", "permission_denied"}
    assert ("Unknown or disallowed host" in result.output
            or "Host access denied" in result.output)


load(globals())
