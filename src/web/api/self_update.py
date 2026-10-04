"""Phase 2: signed package update, rollback and supervised-core handoff.

Require package-aware publication and proven worker settlement before relaunch.
No Git/install-tree updater and no independent service lifecycle authority.
"""
from . import require_phase2


def register_self_update(*args, **kwargs):
    require_phase2("Packaged update and handoff")
