"""All six pinned heartbeat cases and request-backed admission authenticity."""
import ast
import hashlib

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from tests.desktop_adapters import step8_heartbeat
from tests.desktop_adapters.step8_heartbeat import load

load(globals())


@pytest.fixture(autouse=True)
async def step8_heartbeat_owner(request, tmp_path):
    if not request.node.name.startswith("test_step8_heartbeat_"):
        yield
        return
    async with step8_heartbeat.owner_fixture(tmp_path) as state:
        yield state


def test_heartbeat_loader_complete_corpus():
    original, adapted = step8_heartbeat.adapt(frozen_source(step8_heartbeat.SOURCE_PATH))
    assert corpus(original) == corpus(adapted)
    assert len(corpus(original)["cases"]) == 6
    assert len(corpus(original)["assertions"]) == 10
    assert step8_heartbeat.CORPUS_SELECTIONS == {"test_turn_durability_heartbeat": None}
    assert step8_heartbeat.CORPUS_EXCLUSIONS == {}
    assert len(step8_heartbeat.SETUP_HUNKS) == 2


def test_heartbeat_loader_changed_bytes():
    with pytest.raises(ValueError, match="bytes changed"):
        step8_heartbeat.adapt(frozen_source(step8_heartbeat.SOURCE_PATH) + b"\n")


def test_heartbeat_loader_rejects_wrong_duplicate_and_assertion_hunks():
    source = frozen_source(step8_heartbeat.SOURCE_PATH)
    line, column, digest, replacement = step8_heartbeat.SETUP_HUNKS[0]
    with pytest.raises(ValueError, match="exact admitted"):
        step8_heartbeat.adapt(source, hunks=[(line + 1, column, digest, replacement)])
    with pytest.raises(ValueError, match="duplicate"):
        step8_heartbeat.adapt(source, hunks=step8_heartbeat.SETUP_HUNKS * 2)
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Assert))
    rule = (node.lineno, node.col_offset, hashlib.sha256(dump(node).encode()).hexdigest(),
            "False")
    with pytest.raises(ValueError, match="exact admitted"):
        step8_heartbeat.adapt(source, hunks=[rule])


def test_heartbeat_loader_collateral_reverse_replay(monkeypatch):
    original_put = step8_heartbeat._put

    def corrupt(tree, path, node):
        original_put(tree, path, node)
        tree.body.append(ast.parse("unadmitted = 1").body[0])

    monkeypatch.setattr(step8_heartbeat, "_put", corrupt)
    with pytest.raises(ValueError, match="complete AST reverse replay"):
        step8_heartbeat.adapt(frozen_source(step8_heartbeat.SOURCE_PATH))


async def test_heartbeat_helper_requires_authentic_owner(tmp_path):
    from tests.fakes import FakeMessage

    with pytest.raises(RuntimeError, match="authenticated temporary owner"):
        await step8_heartbeat.request_admit(None, message=FakeMessage("hello"), system_prompt="s",
                                          tools=[], session_snapshot=None)


async def test_heartbeat_authentic_store_binding_and_gate(tmp_path):
    from src.turn_state import TurnStateStore
    from tests.fakes import FakeMessage

    store = TurnStateStore(tmp_path / "original.sqlite3", blob_dir=tmp_path / "blobs")
    async with step8_heartbeat.owner_fixture(tmp_path) as state:
        fake = FakeMessage("heartbeat authority is not a message attribute")
        handle = await step8_heartbeat.request_admit(
            store, message=fake, system_prompt="s", tools=[], session_snapshot=None)
        graph = state.graphs[0]
        observation = graph.observation
        assert handle.enabled and handle._store is store
        assert handle._heartbeat_task is not None
        assert handle.lease.key == observation.message.turn_key
        assert handle.lease.key.source == "conversation"
        row = graph.requests.get_request(graph.request_id)
        assert row["owner"] == state.authority.owner_id != str(fake.author.id)
        assert row["state"] == "running"
        assert row["ledger_generation"] == handle.lease.generation
        assert observation.message.request_id == row["request_id"]
        assert any(not task.done() for task in graph.tasks)
        for foreign in (fake, observation.message,
                        graph.requests.fetch_request(graph.cid, graph.request_id)):
            with pytest.raises(PermissionError, match="current admitted request owner"):
                await observation.engine._admit_turn(
                    foreign, system_prompt="s", tools=[], session_snapshot=None)
        await handle.settle_terminal(cancelled=False, is_error=False)
        assert handle._heartbeat_task is None


async def test_heartbeat_closed_original_store_real_refusal(tmp_path):
    from src.turn_state import TurnStateStore
    from tests.fakes import FakeMessage

    store = TurnStateStore(tmp_path / "closed.sqlite3", blob_dir=tmp_path / "blobs")
    store.close()
    async with step8_heartbeat.owner_fixture(tmp_path) as state:
        handle = await step8_heartbeat.request_admit(
            store, message=FakeMessage("hello"), system_prompt="s", tools=[], session_snapshot=None)
        graph = state.graphs[0]
        assert graph.observation.deps.turn_store is store
        assert handle.enabled is False and handle.blocked == "admission_error"
        assert handle._heartbeat_task is None
        row = graph.requests.get_request(graph.request_id)
        assert row["state"] == "running" and row["ledger_generation"] is None
