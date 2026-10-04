"""Neutral operator error/validation policy; native admission is Phase 2.

Require exact owner/task/consent/scope/freshness/revocation on each operation
and readback, private no-store evidence and unknown-effect receipts. Never
turn failed cleanup into permission to retry or accept a local caller by default.
"""
import re
from datetime import UTC, datetime

from . import require_phase2

_OPAQUE = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,99}\Z")
_PRIVATE = {
    "Cache-Control": "no-store, private",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

_PUBLIC_ERRORS = {
    "not_found": (404, "Not found or no longer authorized", "check_authorization"),
    "operator_surface_required": (404, "Not found or no longer authorized", "check_authorization"),
    "stale_generation": (409, "Session generation changed. Refresh status and use "
                         "session_generation, not runtime generation.", "refresh_status"),
    "recovery_unavailable": (409, "Recovery requires a quarantined session without a "
                             "live controller. Refresh status; no cleanup was performed.",
                             "refresh_status"),
    "legacy_acknowledgment_unavailable": (
        409, "Legacy acknowledgment requires a quarantined session with no recorded "
        "runtime identity and no live controller. Inspect the recorded workload instead.",
        "inspect_recorded_workload"),
    "explicit_acknowledgment_required": (
        400, "Explicit acknowledgment must exactly match ACKNOWLEDGE UNVERIFIED CLEANUP "
        "followed by a space and the selected session ID.", "correct_acknowledgment"),
    "disabled": (
        503, "Computer use is disabled. Status and recovery remain available.", "refresh_status"
    ),
    "hyprland_recovery_unavailable": (409, "Native release recovery requires the retained "
                                     "Hyprland session. Use the operator setup recovery command "
                                     "if the controller is gone.", "inspect_recorded_workload"),
    "grant_revoked": (
        409, "Input authority was revoked. Refresh status before continuing.", "refresh_status"
    ),
    "runtime_identity_required": (
        409, "No recorded runtime identity is available. Use the legacy acknowledgment "
        "flow as the session owner after independently inspecting cleanup.",
        "inspect_legacy_cleanup"),
}


def _expiry(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp <= datetime.now(UTC):
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise TimeoutError from None
    return value


def _opaque(value):
    if not isinstance(value, str) or not _OPAQUE.fullmatch(value):
        raise ValueError
    return value


def register_computer(*args, **kwargs):
    require_phase2("Native operator commands and private evidence")
