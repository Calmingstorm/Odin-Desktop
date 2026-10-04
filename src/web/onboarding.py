"""Phase 2: fresh-profile provider sign-in and durable settings publication.

Require serialized validate/persist/adopt/reconcile and recovery over Desktop
paths. No prior-user import, listener configuration or transport credential.
"""
from .api import require_phase2


class OnboardingError(RuntimeError):
    pass


class OnboardingCoordinator:
    def __init__(self, *args, **kwargs):
        require_phase2("Fresh-profile onboarding")
