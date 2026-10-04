"""Phase 2: UI/core admission sessions, distinct from conversation history.

Require OS-peer authenticity, issuer provenance, secure key publication,
expiry/revocation and revalidation before delivery. No browser login store.
"""
from .api import require_phase2


class SessionManager:
    def __init__(self, *args, **kwargs):
        require_phase2("UI/core admission sessions")
