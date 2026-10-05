"""Neutral bounded read-only posture envelope; command delivery is Phase 2.

Require the dedicated read-only store reader and private owner delivery.
Unavailable is not not-enabled; inspection grants no mutation/resume authority.
"""
from datetime import UTC, datetime

from . import require_phase2

_TURNS_DEFAULT_LIMIT = 100
_TURNS_MAX_LIMIT = 200
_SCHEMA_VERSION = 1


def _observed_at() -> str:
    return datetime.now(UTC).isoformat()


def _envelope(availability: str, data: dict | None = None, **extra) -> dict:
    body = {
        "schema_version": _SCHEMA_VERSION,
        "availability": availability,
        "observed_at": _observed_at(),
        "data": data if data is not None else {},
    }
    body.update(extra)
    return body


def register_turn_state(*args, **kwargs):
    require_phase2("Read-only turn posture")
