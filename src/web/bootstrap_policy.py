"""Phase 2: protected local peer/session admission and fail-closed revocation.

No network bind policy or last-server-credential inventory is retained. The
app-main-process broker must establish peer authenticity before capability
publication. Loopback is not authority and there is no unauthenticated mode.
"""
from .api import require_phase2


def decide_bind(*args, **kwargs):
    require_phase2("Protected local admission")
