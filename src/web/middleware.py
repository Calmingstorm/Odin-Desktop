"""Privacy-preserving command-boundary shaping, without a network adapter."""
from .api import require_phase2


def public_error() -> dict[str, str]:
    """Unhandled failures expose no raw exception, path, input or credential."""
    return {"error": "Internal server error"}


def request_logger(*args, **kwargs):
    require_phase2("Private command-boundary logging")


def error_handler(*args, **kwargs):
    require_phase2("Private command-boundary errors")
