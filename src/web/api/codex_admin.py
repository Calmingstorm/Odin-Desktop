"""Phase 2: provider/device sign-in over Desktop vault and owned lifecycle.

Require private credentials, serialized publication/reload, truthful effective
state and owner-authenticated commands. No gateway activation or browser flow.
"""
from . import require_phase2


def register_codex_oauth(*args, **kwargs):
    require_phase2("Provider sign-in and reload")
