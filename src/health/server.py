"""Phase 2: supervised-child health and protected local status commands.

Separately enabled integration ingress must authenticate and normalize each
receiver and preserve scheduler trigger semantics. This is not a listener.
"""
from ..web.api import require_phase2


class HealthServer:
    def __init__(self, *args, **kwargs):
        require_phase2("Supervised-child status and integration ingress")
