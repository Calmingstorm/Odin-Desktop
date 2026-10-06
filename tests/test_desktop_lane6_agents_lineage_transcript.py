"""Frozen whole-suite transcript and trajectory qualification, no listeners."""
import asyncio

import pytest
import pytest_asyncio

from src.agents.manager import AgentManager
from src.desktop.requests import EngineRequest, RequestService
from src.desktop.work import WorkService
from src.discord.tool_loop import ToolLoopRunner
from src.discord.turn_recorder import TurnRecorder
from src.llm.types import LLMResponse
from tests.desktop_adapters import lane6_agents_lineage_transcript as lane6_agents_lineage_adapter


@pytest_asyncio.fixture(autouse=True)
async def lane6_agents_lineage_owner_graph(tmp_path):
    with lane6_agents_lineage_adapter.owner_fixture(tmp_path) as owner:
        state = lane6_agents_lineage_adapter.lane6_agents_lineage_graph(owner)
        binding = lane6_agents_lineage_adapter.lane6_agents_lineage_state.set(state)
        try:
            yield state
        finally:
            for task in list(state.work._watched):
                if not task.done():
                    task.cancel()
            await asyncio.gather(*state.work._watched, return_exceptions=True)
            await state.engine.deps.loop_manager.shutdown()
            state.engine.deps.knowledge_store.close()
            state.store.close()
            lane6_agents_lineage_adapter.lane6_agents_lineage_state.reset(binding)


lane6_agents_lineage_adapter.load(globals())


def test_lane6_agents_lineage_frozen_hash_and_whole_corpus():
    evidence = lane6_agents_lineage_adapter.lane6_agents_lineage_evidence
    assert set(evidence) == {
        "tests/test_agent_transcript_contract.py", "tests/test_trajectory_completeness.py"}
    assert evidence["tests/test_agent_transcript_contract.py"]["original_cases"] == evidence[
        "tests/test_agent_transcript_contract.py"]["retained_cases"]
    assert evidence["tests/test_trajectory_completeness.py"]["original_cases"] == evidence[
        "tests/test_trajectory_completeness.py"]["retained_cases"]
    assert all(row["whole_suite"] for row in evidence.values())


@pytest.mark.asyncio
async def test_lane6_agents_lineage_canonical_bridge_identity_and_real_spawn(lane6_agents_lineage_owner_graph):
    state = lane6_agents_lineage_owner_graph
    assert type(state.engine.deps.agent_manager) is AgentManager
    assert type(state.requests) is RequestService
    assert type(state.work) is WorkService
    assert type(state.engine.runner) is ToolLoopRunner
    assert type(state.engine.deps.turn_recorder) is TurnRecorder
    assert state.native._agent_manager is state.work.agents is state.engine.deps.agent_manager
    assert state.native._background_admission is state.work.requests is state.requests
    assert state.native._work_service is state.work
    assert state.native._tool_loop is state.engine.runner
    assert state.native._turn_recorder is state.engine.deps.turn_recorder
    observed = []

    async def lane6_agents_lineage_generate(_client, **kwargs):
        message = state.requests.current_bound_request()
        assert type(message) is EngineRequest
        assert message.owner_id == state.owner.authority.owner_id
        observed.append(message)
        return LLMResponse(text="A complete hermetic result.")

    state.native._agent_generate = lane6_agents_lineage_generate
    parent = state.requests._register_background("task", "canonical-parent", "run once",
        state.cid, state.owner.authority.owner_id)
    async with state.requests.background_execution(parent):
        result = await state.native._handle_spawn_agent(parent, {"label": "test", "goal": "run once"})
        assert "spawned" in result
        agent = next(iter(state.engine.deps.agent_manager._agents.values()))
        records = state.work.list()["items"]
        assert len(records) == 1
        assert records[0]["owner_id"] == parent.owner_id
        assert records[0]["conversation_id"] == parent.conversation_id
    await asyncio.wait_for(agent._task, timeout=10)
    await asyncio.sleep(0)
    assert observed and agent.result == "A complete hermetic result."
    assert records[0]["run_id"] == observed[0].request_id
    assert state.requests.get_request(observed[0].request_id)["state"] == "completed"
    assert state.work.list()["items"][0]["settlement"]["state"] == "settled"
    assert list((state.owner.paths.data_dir / "agent_trajectories").glob("**/*.json"))
