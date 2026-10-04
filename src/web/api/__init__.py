"""Neutral management helpers; authenticated command wiring is Phase 2.

The exact-copy commit f6170072 preserves the domain operation baseline. No
HTTP route inventory, listener, browser login or remote client is published.
"""


class Phase2UnavailableError(RuntimeError):
    """A required authenticated service boundary has not been implemented."""


Phase2Unavailable = Phase2UnavailableError


def require_phase2(operation: str) -> None:
    raise Phase2Unavailable(f"{operation} requires authenticated Desktop service wiring (Phase 2)")


def create_api_routes(*args, **kwargs):
    require_phase2("Management commands")


def setup_api(*args, **kwargs):
    require_phase2("Management commands")
