"""Neutral sensitivity, bounds, masks and serialization helpers.

These helpers do not authenticate callers or publish a server surface.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import yaml

from ..config import sensitivity as _config_sensitivity
from ..llm.secret_scrubber import scrub_output_secrets
from ..odin_log import get_logger
from .api import require_phase2

log = get_logger("web.api")

# One shared sensitivity rule protects settings and metadata readback.
_SENSITIVE_FIELDS = _config_sensitivity.SENSITIVE_FIELDS
_SENSITIVE_KEY_SUBSTRINGS = _config_sensitivity.SENSITIVE_KEY_SUBSTRINGS
_is_sensitive_key = _config_sensitivity.is_sensitive_key


# Input validation limits
_MAX_NAME_LEN = 100
_MAX_CODE_LEN = 50_000
_MAX_CONTENT_LEN = 500_000
_MAX_GOAL_LEN = 2000
_MAX_DESCRIPTION_LEN = 500


def _validate_string(value: str, field: str, max_len: int) -> str | None:
    """Validate a string field. Returns error message or None."""
    if len(value) > max_len:
        return f"{field} exceeds maximum length ({max_len} chars)"
    return None


# Regex: keep only ASCII alphanumeric, hyphen, underscore, period
_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9_.\-]")


def _safe_filename(name: str, max_len: int = 80) -> str:
    """Sanitize a string for use in Content-Disposition filename."""
    return _SAFE_FILENAME_RE.sub("_", name)[:max_len] or "export"


# Validated identity components for the authenticated conversation store.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _scoped_conversation(owner_id: str, conversation_id: str) -> str:
    """Namespace validated components; this helper is not admission authority."""
    if not all(isinstance(value, str) and _SESSION_ID_RE.fullmatch(value)
               for value in (owner_id, conversation_id)):
        raise ValueError("Invalid conversation identity")
    return f"owner:{owner_id}:conversation:{conversation_id}"


def _sanitize_error(msg: str | BaseException) -> str:
    """Scrub secrets from error messages before returning to clients."""
    return scrub_output_secrets(str(msg))


def _safe_int_param(
    request: Any, name: str, default: int, lo: int = 1, hi: int = 500
) -> int:
    """Parse an integer query parameter, clamping to [lo, hi]. Falls back to *default*."""
    raw = request.query.get(name)
    if raw is None:
        return min(max(default, lo), hi)
    try:
        return min(max(int(raw), lo), hi)
    except (ValueError, TypeError):
        return min(max(default, lo), hi)


def _contains_blocked_fields(d: Any, blocked: frozenset[str], *, _depth: int = 0) -> bool:
    """Recursively check if any keys in *d* are in *blocked*.

    Lists are traversed too. Descending only into dicts left every credential
    inside a list unfenced — nested credentials and
    ``outbound_webhooks.targets[].secret`` reached the writer despite both
    names being on the blocked list.
    """
    if _depth > 10:
        return False
    if isinstance(d, list):
        return any(
            _contains_blocked_fields(item, blocked, _depth=_depth + 1) for item in d
        )
    if not isinstance(d, dict):
        return False
    for key, value in d.items():
        if key in blocked:
            return True
        if _contains_blocked_fields(value, blocked, _depth=_depth + 1):
            return True
    return False


def contains_redaction_mask(obj: Any, *, _depth: int = 0) -> bool:
    """Whether a submitted body carries the mask this API hands out.

    A page that renders a masked secret as an editable control round-trips
    ``••••••••`` back on save, overwriting the real credential with eight
    bullets. Nobody sets a secret to that deliberately, so refusing it costs no
    legitimate capability and closes the destruction path wherever it appears.
    """
    if _depth > 10:
        return False
    if isinstance(obj, str):
        return obj == "••••••••"
    if isinstance(obj, dict):
        return any(
            contains_redaction_mask(v, _depth=_depth + 1) for v in obj.values()
        )
    if isinstance(obj, list):
        return any(contains_redaction_mask(v, _depth=_depth + 1) for v in obj)
    return False


def _deep_merge(base: dict, updates: dict, *, _depth: int = 0) -> None:
    """Recursively merge *updates* into *base* in-place."""
    if _depth > 10:
        return
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value, _depth=_depth + 1)
        else:
            base[key] = value


def _mask_subtree(obj: Any, *, _depth: int = 0) -> Any:
    """Mask every scalar beneath *obj*, keeping the shape.

    Used for containers whose child keys are operator-chosen. Keys survive so
    the page can still show WHICH headers or webhooks exist; only values go.
    """
    if _depth > 10:
        return "..."
    if isinstance(obj, dict):
        return {k: _mask_subtree(v, _depth=_depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_subtree(v, _depth=_depth + 1) for v in obj]
    if obj is None or obj == "":
        return obj
    return "••••••••"


def _redact_config(obj: Any, *, _depth: int = 0) -> Any:
    """Recursively redact sensitive fields from config dicts.

    Two rules, because one is not enough. A credential-shaped KEY masks its own
    string value. A credential CONTAINER masks everything underneath it,
    because its child keys are named by the operator — `headers.Authorization`
    and `webhook_urls.ops` look ordinary and used to be served verbatim.
    """
    if _depth > 10:
        return "..."
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if _config_sensitivity.is_opaque_container_key(k):
                out[k] = _mask_subtree(v, _depth=_depth + 1)
            elif _is_sensitive_key(k) and isinstance(v, str) and v:
                out[k] = "••••••••"
            else:
                out[k] = _redact_config(v, _depth=_depth + 1)
        return out
    if isinstance(obj, list):
        return [_redact_config(v, _depth=_depth + 1) for v in obj]
    return obj


def _write_config(path: Path | str, data: dict) -> None:
    """Write config dict to YAML file."""
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)


def _write_env_file(path: Path, content: str) -> None:
    """Credential publication requires the Desktop secure-settings boundary."""
    require_phase2("Secure credential publication")


# Guards concurrent writes to the Codex credential files. Module-level so
# every registrar (and the composition root) shares ONE lock — the same
# semantics the old single-closure table provided (RFC-003 P2).
_codex_creds_lock = asyncio.Lock()


def owner_gate(*args, **kwargs):
    """Do not infer owner authority from absent credentials or local callers."""
    require_phase2("Owner admission")
