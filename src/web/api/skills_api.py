"""Phase 2: owner-authenticated skill CRUD/execution commands.

Require schemas, trust/scope/secrets, prompt/catalog invalidation, isolated
execution and truthful settlement. No privileged shim or user grant inventory.
"""
from . import require_phase2


def register_skills(*args, **kwargs):
    require_phase2("Skill management and execution")
