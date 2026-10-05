"""Phase 2: authenticated local conversations, bounded history and artifacts.

Require explicit principal/conversation/turn identity, invocation isolation,
durable sinks, output authorization and expiry/revocation before readback.
"""
from . import require_phase2


def register_chat(*args, **kwargs):
    require_phase2("Conversation execution")


def register_sessions(*args, **kwargs):
    require_phase2("Conversation management")


def register_trajectories(*args, **kwargs):
    require_phase2("Private trajectory inspection")


def register_agent_trajectories(*args, **kwargs):
    require_phase2("Private agent trajectory inspection")
