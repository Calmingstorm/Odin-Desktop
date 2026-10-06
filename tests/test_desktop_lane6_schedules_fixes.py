"""Production scheduled dispatch preserves task-owned child admission."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock as AsyncMock

import pytest

from src.desktop.core import CoreService
from tests.desktop_adapters.test_phase2_runner_characterization import (
    graph as graph,
)


@pytest.mark.asyncio
async def test_lane6_schedules_concurrent_dispatch_admits_distinct_bound_children(
    graph,
):
    seen = []

    async def effect(name, values, message, owner_id):
        graph.requests.assert_request(message)
        assert owner_id == graph.requests.authority.owner_id
        assert message.conversation_id == graph.cid
        seen.append(message)
        return "sample"

    facade = SimpleNamespace(requests=graph.requests,
        engine=SimpleNamespace(runner=SimpleNamespace(dispatch_loop_tool=effect)))
    parent = graph.requests._register_background("schedule", "scheduled-regression",
        "Harmless concurrent probe", graph.cid, graph.requests.authority.owner_id)
    async with graph.requests.background_execution(parent):
        results = await asyncio.gather(*(
            CoreService._dispatch_scheduled_tool(
                facade, parent, "fetch_url", {"url": "https://example.invalid"}
            )
            for _ in range(3)))
        graph.requests.assert_request(parent)
    assert results == ["sample"] * 3
    assert len({item.request_id for item in seen}) == 3
    assert all(item.request_id != parent.request_id for item in seen)
    for item in seen:
        row = graph.store.connection.execute(
            "SELECT parent_request_id FROM desktop_background_requests WHERE request_id=?",
            (item.request_id,)).fetchone()
        assert row[0] == parent.request_id
        assert graph.requests.get_request(item.request_id)["state"] == "completed"
    with pytest.raises(PermissionError):
        await CoreService._dispatch_scheduled_tool(facade, parent, "fetch_url", {})
