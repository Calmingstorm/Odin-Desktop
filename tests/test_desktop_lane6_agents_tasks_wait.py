"""Whole inherited wait-loop corpus with an authenticated real request owner."""
from tests.desktop_adapters.lane6_agents_tasks import load
from tests.test_desktop_lane6_agents_tasks_provider import (
    lane6_agents_tasks_graph,
    lane6_agents_tasks_owner_fixture,
)

load(globals(), "test_wait_stuck_integration")
