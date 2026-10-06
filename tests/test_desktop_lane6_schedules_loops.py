"""Execute exact frozen loop/reflection corpus through canonical services."""
from types import SimpleNamespace

import pytest_asyncio

from tests.desktop_adapters.lane6_schedules_loops_bridge import CURRENT
from tests.desktop_adapters.lane6_schedules_loops_cases import load


@pytest_asyncio.fixture(autouse=True)
async def lane6_schedules_loops_graphs(tmp_path):
    state = SimpleNamespace(root=tmp_path / "graphs", graphs=[], latest=None)
    token = CURRENT.set(state)
    try:
        yield
    finally:
        for graph in reversed(state.graphs):
            await graph.close()
        CURRENT.reset(token)


load(globals())
