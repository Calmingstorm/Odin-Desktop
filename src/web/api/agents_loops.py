"""Phase 2: owner/conversation-scoped jobs with private event delivery.

Require real manager/cancellation/history/model provenance, bounded readback,
validated destinations and explicit autonomous execution authority.
"""
from . import require_phase2


def register_loops(*args, **kwargs):
    require_phase2("Autonomous loop commands")


def register_agents(*args, **kwargs):
    require_phase2("Agent commands")


def register_processes(*args, **kwargs):
    require_phase2("Owned process commands")
