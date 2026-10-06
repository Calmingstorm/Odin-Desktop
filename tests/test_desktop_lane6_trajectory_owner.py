"""Agent and turn trajectory readers use their actual retained saver contracts."""
from types import SimpleNamespace

import pytest

from src.agents.trajectory import AgentTrajectorySaver
from src.desktop.management import MethodError
from src.desktop.trajectories import TrajectoriesService


@pytest.mark.asyncio
async def test_agent_reader_finder_search_and_no_writer_construction(tmp_path, monkeypatch):
    paths = SimpleNamespace(data_dir=tmp_path)
    service = TrajectoriesService(paths)
    assert not (tmp_path / "agent_trajectories").exists()
    result = await service.handle("trajectories.list", {"kind": "agent"})
    assert result == {"files": [], "count": 0}
    assert not (tmp_path / "agent_trajectories").exists()
    calls = []

    async def find(agent_id):
        calls.append(("find", agent_id))
        return {"agent_id": agent_id, "result": "ordinary result"}

    async def search(**kwargs):
        calls.append(("search", kwargs))
        return [{"agent_id": "agent-a", "result": "ordinary result"}]

    reader = service._agent_reader
    assert isinstance(reader, AgentTrajectorySaver)
    monkeypatch.setattr(reader, "find_by_agent_id", find)
    monkeypatch.setattr(reader, "search", search)
    assert (await service.handle("trajectories.agent", {"agent_id": "agent-a"}))["entry"][
        "agent_id"] == "agent-a"
    result = await service.handle("trajectories.search", {
        "kind": "agent", "channel_id": "conversation-a", "user_id": "owner-a",
        "tool_name": "fetch_url", "state": "completed", "limit": 17,
    })
    assert result["count"] == 1
    assert calls[-1] == ("search", {
        "channel_id": "conversation-a", "requester_id": "owner-a",
        "tool_name": "fetch_url", "state": "completed", "limit": 17,
    })
    with pytest.raises(MethodError, match="Use state"):
        await service.handle("trajectories.search", {"kind": "agent", "errors_only": True})


@pytest.mark.asyncio
async def test_agent_reader_preserves_live_owner_and_filename_guard(tmp_path):
    saver = AgentTrajectorySaver(str(tmp_path / "agent"))
    service = TrajectoriesService(SimpleNamespace(data_dir=tmp_path),
                                  agent_saver_getter=lambda: saver)
    assert service._selected_saver({"kind": "agent"}, "trajectories.list") is saver
    with pytest.raises(MethodError, match="invalid filename"):
        await service.handle("trajectories.read", {"kind": "agent", "filename": "../ordinary"})
    with pytest.raises(MethodError, match="kind"):
        await service.handle("trajectories.list", {"kind": "missing"})
