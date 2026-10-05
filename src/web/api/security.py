"""Phase 2: authenticated broker peer/session admission and revocation.

Owner authority is not an empty caller, a tier, a token inventory or localhost.
No user-grant, login or credential-management registrar is retained.
"""
from . import require_phase2


def require_owner_admission(*args, **kwargs):
    require_phase2("Owner admission")
