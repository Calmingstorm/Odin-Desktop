"""Exact frozen whole-suite agent restoration, with isolated real engine owners."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from tests.desktop_adapters.tools_cases import owner_fixture
from tests.desktop_adapters.lane6_agents_core import (
    load, lane6_agents_core_state, lane6_agents_core_engine,
)


@pytest_asyncio.fixture(autouse=True)
async def lane6_agents_core_owner(tmp_path, request):
    with owner_fixture(tmp_path / "owner") as owner:
        state = SimpleNamespace(owner=owner, root=tmp_path / "engines", engines=[])
        token = lane6_agents_core_state.set(state)
        try:
            if "model_admission" in request.node.name:
                state.model_engine = lane6_agents_core_engine()
                requests = state.model_engine.requests
                cid = requests.conversations.create()["conversation"]["id"]
                state.model_message = requests._register_background(
                    "workflow", "model-admission-root", "harmless admission check", cid,
                    owner.authority.owner_id)
                yield state
            else:
                yield state
        finally:
            for engine in state.engines:
                tasks = [a._task for a in engine.deps.agent_manager._agents.values()
                         if a._task is not None and not a._task.done()]
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await engine.requests.close()
                await engine.close()
                engine.lane6_agents_core_store.close()
            lane6_agents_core_state.reset(token)


load(globals())


@pytest.mark.asyncio
async def test_lane6_agents_core_model_admission_spy_preserves_real_owner():
    """Admission spy observes the real manager, registry, durable work and request."""
    from tests.desktop_adapters.lane6_agents_core import (
        lane6_agents_core_model_tools, lane6_agents_core_message,
    )
    from tests.test_native_agents_tasks import _cfg, _fake_gateway

    state = lane6_agents_core_state.get()
    engine = state.model_engine
    cfg = _cfg()
    cfg.agents.model = "auto"
    cfg.agents.auto_model_allowlist = ["gpt-5.6-luna"]
    cfg.openai_codex = SimpleNamespace(enabled=True, model="gpt-5.6-sol",
        agent_model="gpt-5.6-sol", agent_reasoning_effort="auto", reasoning_effort="high")
    tools = lane6_agents_core_model_tools(get_config=lambda: cfg,
        llm_gateway=_fake_gateway(SimpleNamespace(model="gpt-5.6-sol", reasoning_effort="high")))
    await tools._handle_spawn_agent(lane6_agents_core_message(),
        {"label": "admission", "goal": "harmless calculation", "model": "gpt-5.6-luna"})
    manager = engine.deps.agent_manager
    assert tools._agent_manager is engine.lane6_agents_core_work.agents is manager
    assert manager.spawn._mock_wraps.__self__ is manager
    item = next(iter(manager._agents.values()))
    assert item.model_override == "gpt-5.6-luna"
    assert item.requester_id == state.owner.authority.owner_id
    work = engine.lane6_agents_core_work.list()["items"][0]
    assert work["manager_id"] == item.id
    assert engine.requests.get_request(work["request_id"])["state"] == "admitted"


@pytest.mark.asyncio
async def test_lane6_agents_core_failed_wait_visibility_supplement():
    """Retained half of the inseparable retired HTTP/wait visibility case."""
    engine = lane6_agents_core_engine()
    manager = engine.deps.agent_manager
    manager.set_completion_classifier(SimpleNamespace(
        classify=AsyncMock(return_value=(False, "checks remain"))))
    callback = AsyncMock(side_effect=[
        {"text": "", "tool_calls": [{"id": "t1", "name": "noop", "input": {}}]},
        {"text": "not done yet", "tool_calls": []},
        {"text": "", "tool_calls": [{"id": "t2", "name": "noop", "input": {}}]},
    ])
    owner = lane6_agents_core_state.get().owner.authority.owner_id
    cid = engine.requests.conversations.create()["conversation"]["id"]
    aid = manager.spawn(label="bounded", goal="finish the calculation", channel_id=cid,
                        requester_id=owner, requester_name="Owner", iteration_callback=callback,
                        tool_executor_callback=AsyncMock(return_value="ok"), max_iterations=3)
    waited = await manager.wait_for_agents([aid], timeout=10, poll_interval=0.01)
    assert waited[aid]["state"] == "failed"
    assert waited[aid]["status"] == "failed"
    assert "incomplete at iteration cap" in waited[aid]["state_history"][-1]["reason"]
    result = manager.get_results(aid)
    assert result is not None and result["state"] == "failed"
    assert result["result"]
    native = engine.deps.native_owners["agents"]
    collected = json.loads(await native._handle_get_agent_results(
        {"agent_id": aid}, user_id=owner, channel_id=cid))
    assert collected["status"] == "failed"
    assert "checks remain" in collected["preview"]
    assert native._agent_manager is engine.lane6_agents_core_work.agents is manager
    assert native._background_admission is engine.requests
