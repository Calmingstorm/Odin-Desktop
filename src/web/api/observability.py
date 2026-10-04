"""Phase 2: bounded private inspection of actual engine state/accounting.

Preserve desired-versus-executor adoption truth, passive observations, safe
errors, tool metadata and scoped retained evidence. No grant/tier metadata.
"""
from . import require_phase2


def register_observability(*args, **kwargs):
    require_phase2("Private engine inspection")
