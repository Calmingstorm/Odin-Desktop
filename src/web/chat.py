"""Phase 2: authenticated current-conversation turns and durable file delivery.

Require principal/conversation/turn identity, tool fences, truthful capture
failure, the existing attachment cap, cancellation and settlement. No bot shim.
"""
from .api import require_phase2


async def process_web_chat(*args, **kwargs):
    require_phase2("Conversation turns")
