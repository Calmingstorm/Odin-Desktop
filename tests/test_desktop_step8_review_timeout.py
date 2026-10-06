"""Frozen timeout candidates and independent exact-adapter integrity checks."""
import ast
import hashlib

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from tests.desktop_adapters import step8_review_timeout as adapter

# The original runtime matrix remains a blocked candidate, not a restored suite.
# Execute it only through the explicit diagnostic module. Qualification may run
# the authenticity checks below without importing known-failing inherited cases.


def test_timeout_loader_complete_corpus():
    original, adapted = adapter.adapt(frozen_source(adapter.SOURCE_PATH))
    assert corpus(original) == corpus(adapted)
    assert len(corpus(original)["cases"]) == 3
    assert len(corpus(original)["assertions"]) == 19
    assert adapter.CORPUS_SELECTIONS == {"test_executor_timeout_durability": None}
    assert adapter.CORPUS_EXCLUSIONS == {}
    assert len(adapter.SETUP_HUNKS) == 7


def test_timeout_loader_changed_bytes():
    with pytest.raises(ValueError, match="bytes changed"):
        adapter.adapt(frozen_source(adapter.SOURCE_PATH) + b"\n")


def test_timeout_loader_wrong_duplicate_and_assertion_hunks():
    source = frozen_source(adapter.SOURCE_PATH)
    line, column, digest, mode, replacement = adapter.SETUP_HUNKS[0]
    with pytest.raises(ValueError, match="exact admitted"):
        adapter.adapt(source, hunks=[(line + 1, column, digest, mode, replacement)])
    with pytest.raises(ValueError, match="duplicate"):
        adapter.adapt(source, hunks=adapter.SETUP_HUNKS * 2)
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Assert))
    rule = (node.lineno, node.col_offset, hashlib.sha256(dump(node).encode()).hexdigest(),
            "eval", "False")
    with pytest.raises(ValueError, match="exact admitted"):
        adapter.adapt(source, hunks=[rule])


def test_timeout_loader_collateral_reverse_replay(monkeypatch):
    original_put = adapter._put

    def corrupt(tree, path, node):
        original_put(tree, path, node)
        tree.body.append(ast.parse("unadmitted = 1").body[0])

    monkeypatch.setattr(adapter, "_put", corrupt)
    with pytest.raises(ValueError, match="complete AST reverse replay"):
        adapter.adapt(frozen_source(adapter.SOURCE_PATH))


async def test_timeout_requires_authentic_worker():
    with pytest.raises(RuntimeError, match="authentic temporary owner request"):
        adapter.current()


async def test_timeout_authentic_identity_and_readiness(tmp_path):
    from src.config.schema import ToolsConfig

    async def inspect(tmp_path):
        graph = adapter.current()
        row = graph.requests.get_request(graph.request_id)
        assert row["state"] == "running"
        assert row["owner"] == graph.owner.authority.owner_id != "timeout-user"
        assert graph.message.author.id == graph.owner.authority.owner_id
        store = adapter.TurnStateStore(tmp_path / "inspection.sqlite3")
        handle = await adapter.request_admit(
            store, message=graph.message, system_prompt="test", tools=[], session_snapshot=None)
        assert handle.enabled and handle._store is store
        assert handle.lease.key.source == "conversation"
        assert handle.lease.key == graph.message.turn_key
        assert handle._heartbeat_task is not None
        executor = adapter.OwnerExecutor(config=ToolsConfig(), memory_path=str(tmp_path / "m.json"))
        assert executor._permission_manager is graph.owner.manager
        assert executor._builtin_policy.is_available("apply_patch")
        assert executor._builtin_policy.is_available("read_file")
        assert not executor._builtin_policy.is_available("wait_for_agents")
        assert not executor._builtin_policy.is_available("future_dynamic_tool")
        dispatched = []

        async def unsupported_handler(_tool_input):
            dispatched.append(True)
            return "unexpected dispatch"

        executor._handle_future_dynamic_tool = unsupported_handler
        unsupported = await executor.execute("future_dynamic_tool", {})
        assert unsupported.ok is False and unsupported.error == "tool_unavailable"
        assert unsupported.uncertain_outcome is False
        assert dispatched == []
        runner = adapter.request_runner(executor, executor.config)
        assert not runner._native_tools.handles("wait_for_agents")
        assert runner._request_admission.__self__ is graph.engine
        assert runner._assert_request.__self__ is graph.engine

        async def foreign_child():
            with pytest.raises(PermissionError, match="current admitted request owner"):
                graph.engine._assert_request(graph.message)

        import asyncio
        await asyncio.create_task(foreign_child())
        await handle.settle_terminal(cancelled=False, is_error=False)
        adapter.defer_close(store)

    await adapter.run_admitted_case(inspect, tmp_path=tmp_path)


async def test_timeout_unavailable_refusal_fails_before_wi3(tmp_path):
    """Expose the production gap without repairing or hiding its checkpoint."""
    from types import SimpleNamespace

    from src.config.schema import ToolsConfig
    from src.turn_state import OpState

    async def inspect(tmp_path):
        graph = adapter.current()
        store = adapter.TurnStateStore(tmp_path / "unavailable.sqlite3")
        handle = await adapter.request_admit(
            store, message=graph.message, system_prompt="test", tools=[], session_snapshot=None)
        executor = adapter.OwnerExecutor(config=ToolsConfig(), memory_path=str(tmp_path / "m.json"))
        calls = []

        async def must_not_dispatch(_input):
            calls.append(True)
            return "unauthorized evidence"

        executor._handle_future_dynamic_tool = must_not_dispatch
        block = SimpleNamespace(name="future_dynamic_tool", input={},
                                id="unavailable-wi3", parse_error=None)
        handle.generation_seq = 1
        store.record_intents_sync(handle.lease, 1, [{
            "tool_call_id": block.id, "tool_name": block.name, "tool_input": {},
            "effect_class": "EXTERNAL_EFFECT_CAPABLE",
        }], iteration=1)
        runner = adapter.request_runner(executor, executor.config)
        with pytest.raises(PermissionError, match="Output capability unavailable"):
            await runner._run_one_tool_with_timeout(adapter.request_state(handle), block)
        assert calls == []
        state, result = store._conn.execute(
            "SELECT state,result FROM operations WHERE tool_call_id=?", (block.id,)
        ).fetchone()
        assert state == OpState.RUNNING
        assert result is None
        # Normal terminal cleanup is not a synthetic WI-3 repair. The blocked
        # operation still carries unknown-effect conservative shutdown behavior.
        await handle.settle_terminal(cancelled=False, is_error=True)
        adapter.defer_close(store)

    await adapter.run_admitted_case(inspect, tmp_path=tmp_path)


async def test_timeout_real_authored_skill_registry_does_not_grant_retention(tmp_path):
    """An actual dynamic loader exists, but is not an executor readiness grant."""
    from src.config.schema import ToolsConfig
    from src.discord.native_tools.registry import NativeToolDispatcher
    from src.tools.execution_outcome import ToolFailure
    from src.tools.runtime_delivery import deliver_runtime_result
    from src.tools.skill_manager import SkillManager

    async def inspect(tmp_path):
        graph = adapter.current()
        store = adapter.TurnStateStore(tmp_path / "skill.sqlite3")
        handle = await adapter.request_admit(
            store, message=graph.message, system_prompt="test", tools=[], session_snapshot=None)
        executor = adapter.OwnerExecutor(config=ToolsConfig(), memory_path=str(tmp_path / "m.json"))
        skills = SkillManager(str(graph.owner.paths.data_dir / "actual-skills"), executor,
                              tool_timeouts={"future_dynamic_tool": 1})
        code = (
            "import asyncio\n"
            "SKILL_DEFINITION = {'name': 'future_dynamic_tool', 'description': 'timeout fixture', "
            "'input_schema': {'type': 'object', 'properties': {}}}\n"
            "calls = 0\n"
            "async def execute(inp, context):\n"
            "    global calls\n"
            "    calls += 1\n"
            "    await asyncio.Event().wait()\n"
        )
        created = skills.create_skill("future_dynamic_tool", code)
        assert skills.has_skill("future_dynamic_tool"), created
        assert not skills.has_skill("wait_for_agents")
        collision = skills.create_skill("wait_for_agents", code)
        assert "reserved" in collision.lower() or "built-in" in collision.lower()
        native = NativeToolDispatcher(owners={}, skill_manager=skills, tool_catalog=None,
                                      prompt_builder=None,
                                      channel_state=graph.engine.deps.channel_state)
        assert native.handles("future_dynamic_tool")
        outcome, _effects = await native.dispatch(
            "future_dynamic_tool", {}, message=graph.message, user_id=graph.message.owner_id,
            skill_file_delivery="stage")
        assert isinstance(outcome, ToolFailure) and outcome.uncertain_outcome
        assert "timed out" in outcome.lower()
        assert skills._skills["future_dynamic_tool"].execute_fn.__globals__["calls"] == 1
        assert not executor._builtin_policy.is_available("future_dynamic_tool")
        with pytest.raises(PermissionError, match="Output capability unavailable"):
            deliver_runtime_result(executor, outcome, tool_name="future_dynamic_tool",
                                   tool_input={}, user_id=graph.message.owner_id)
        await handle.settle_terminal(cancelled=False, is_error=True)
        adapter.defer_close(store)

    await adapter.run_admitted_case(inspect, tmp_path=tmp_path)
