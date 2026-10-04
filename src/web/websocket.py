"""Phase 2: private correlated events through the app-main-process broker.

Preserve bounded frames, task ownership/cancellation, shutdown settlement,
revocation and output authorization. No renderer socket or network listener.
"""
from .api import require_phase2


def setup_websocket(*args, **kwargs):
    require_phase2("Conversation event delivery")
