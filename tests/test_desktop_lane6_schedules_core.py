"""Frozen scheduler adapters with exact case-level retirement/defer accounting."""
from tests.desktop_adapters.lane6_schedules_core import graph as graph
from tests.desktop_adapters.lane6_schedules_core import (
    lane6_schedules_core_graph as lane6_schedules_core_graph,
)
from tests.desktop_adapters.lane6_schedules_core import load

load(globals())
