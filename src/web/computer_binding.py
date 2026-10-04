"""Phase 2 operator provenance; copied child contexts confer no authority.

The broker must supply exact task/owner/consent generation, target scope,
freshness and revocation with delivery rechecks. No caller-issued grant exists
in Phase 1 and no browser credential becomes native input authority.
"""
from .api import require_phase2


def operator_binding(*args, **kwargs):
    require_phase2("Native operator binding")


def operator_scope(*args, **kwargs):
    require_phase2("Native operator scope")


def operator_context_authorized(context):
    return False
