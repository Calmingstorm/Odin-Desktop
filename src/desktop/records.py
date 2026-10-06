"""Read-only, profile-bound adapters for Odin's observability stores.

The HTTP routes, not the app's synthetic fixture, define these result shapes.
In particular unsigned audit history is not verified, and turn observation
never constructs a TurnStateStore (whose startup sweep is a write).
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path

from ..audit.logger import DEFAULT_MAX_FILES, AuditLogger
from ..audit.signer import AuditSigner
from ..observability.diagnostics import scrub_diagnostic
from .management import MethodError

METHODS = frozenset({
    "audit.query", "audit.verify", "health.get", "logs.search", "turn_state.list",
})
READ_METHODS = METHODS
_MAX_TEXT = 4000
_MAX_COLLECTION = 500
_MAX_DEPTH = 20
_MAX_NODES = 100000


def _diagnostic_copy(value):
    """Bound collections before scrubbing, but scrub full strings before capping.

    A traversal budget also bounds wide nested manager-provided diagnostics.
    The original store result is never modified.
    """
    remaining = _MAX_NODES

    def collections(item, depth=0):
        nonlocal remaining
        if remaining <= 0 or depth > _MAX_DEPTH:
            return "[omitted: diagnostic limit]"
        remaining -= 1
        if isinstance(item, dict):
            return {str(key): collections(child, depth + 1)
                    for key, child in islice(item.items(), _MAX_COLLECTION)}
        if isinstance(item, (list, tuple)):
            return [collections(child, depth + 1)
                    for child in islice(item, _MAX_COLLECTION)]
        return item

    def strings(item):
        if isinstance(item, str):
            if len(item) > _MAX_TEXT:
                return item[:_MAX_TEXT - 14] + "...[truncated]"
            return item
        if isinstance(item, dict):
            return {key: strings(child) for key, child in item.items()}
        if isinstance(item, list):
            return [strings(child) for child in item]
        return item

    return strings(scrub_diagnostic(collections(value)))


def _limit(params, default, maximum):
    # Pinned _safe_int_param falls back for malformed values and clamps bounds.
    try:
        return max(1, min(int(params.get("limit", default)), maximum))
    except (TypeError, ValueError, OverflowError):
        return default


def _filter(params, key):
    value = params.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise MethodError("bad_request", f"{key} must be a string")
    return value


async def _result(value):
    return await value if inspect.isawaitable(value) else value


class _AuditReader(AuditLogger):
    """Reuse audit read algorithms without the writer's directory creation.

    Only read-side state is initialized. Never initialize or resume a writer's
    chain, even for a missing path or an unsettled append marker.
    """

    def __init__(self, path, hmac_key):
        self.path = Path(path)
        self._signer = AuditSigner(hmac_key) if hmac_key else None
        self._persist_lock = asyncio.Lock()
        self._max_files = DEFAULT_MAX_FILES
        self.repair_required = self.path.with_name(self.path.name + ".repair-required").exists()
        self.durability_degraded = self.repair_required


class RecordsService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, paths, *, settings=None, get_audit_path=None, audit=None,
                 health=None, logs=None, turn_state=None):
        self.paths = paths
        self._settings = settings
        self._get_audit_path = get_audit_path
        self._audit = audit
        self._audit_reader = None
        self._audit_binding = None
        self._health = health
        self._logs = logs
        self._turn_state = turn_state

    @property
    def audit(self):
        # Explicit backends remain authoritative test/runtime injection seams.
        if self._audit is not None:
            return self._audit
        config = self._settings.config if self._settings is not None else None
        hmac_key = config.audit.hmac_key if config is not None else ""
        resolve_key = getattr(self._settings, "audit_signing_key", None)
        if callable(resolve_key):
            hmac_key = resolve_key()
        return self._bind_audit(hmac_key)

    async def _read_audit(self):
        if self._audit is not None:
            return self._audit
        from .secrets import secret_call

        config = self._settings.config if self._settings is not None else None
        hmac_key = config.audit.hmac_key if config is not None else ""
        resolve_key = getattr(self._settings, "audit_signing_key", None)
        if callable(resolve_key):
            # Keep round-2 signing authority without reintroducing synchronous
            # keyring I/O in round-3's async management composition. Construct
            # the reader and its asyncio lock only after returning to the loop.
            hmac_key = await secret_call(resolve_key)
        return self._bind_audit(hmac_key)

    def _bind_audit(self, hmac_key):
        config = self._settings.config if self._settings is not None else None
        if self._get_audit_path is not None:
            path = Path(self._get_audit_path())
        else:
            path = Path(config.tools.audit_log_path) if config is not None else (
                self.paths.data_dir / "audit.jsonl")
        binding = (path, hmac_key)
        if binding != self._audit_binding:
            self._audit_reader = _AuditReader(path, hmac_key)
            self._audit_binding = binding
        return self._audit_reader

    @staticmethod
    def _method(backend, name):
        operation = getattr(backend, name, None)
        if not callable(operation):
            raise MethodError("capability_unavailable", "Records manager is unavailable")
        return operation

    async def handle(self, method: str, params: dict):
        if method not in METHODS:
            raise MethodError("method_not_found", "Unknown records method")
        if not isinstance(params, dict):
            raise MethodError("bad_request", "params must be an object")
        try:
            return _diagnostic_copy(await self._handle(method, params))
        except MethodError:
            raise
        except Exception:
            # Manager exceptions may contain secrets, SQL, paths or credentials.
            raise MethodError("unavailable", "Records read is unavailable") from None

    async def _handle(self, method, params):
        if method == "audit.query":
            filters = {name: _filter(params, key) for name, key in (
                ("tool_name", "tool"), ("user", "user"), ("host", "host"),
                ("keyword", "q"), ("date", "date"),
            )}
            error_only = params.get("error_only", False)
            error_only = (error_only is True or str(error_only).lower() in {"1", "true", "yes"})
            limit = _limit(params, 50, 200)
            operation = self._method(await self._read_audit(), "search")
            entries = await _result(operation(**filters, has_error=True if error_only else None,
                                              limit=limit))
            return entries[:limit]
        if method == "audit.verify":
            return await _result(self._method(await self._read_audit(), "verify_integrity")())
        if method == "logs.search":
            level = _filter(params, "level")
            if level and level not in {"error", "info", "all"}:
                raise MethodError("bad_request", "level must be 'error', 'info', or 'all'")
            filters = {name: _filter(params, key) for name, key in (
                ("start_time", "start"), ("end_time", "end"),
                ("keyword", "q"), ("tool_name", "tool"),
            )}
            limit = _limit(params, 100, 500)
            backend = self._logs if self._logs is not None else await self._read_audit()
            entries = await _result(self._method(backend, "search_logs")(
                level=level, **filters, limit=limit))
            entries = entries[:limit]
            return {"entries": entries, "count": len(entries)}
        if method == "health.get":
            if self._health is None:
                raise MethodError("capability_unavailable", "Health checker is unavailable")
            if callable(self._health):
                return await _result(self._health())
            from ..health.checker import check_all

            return await asyncio.to_thread(check_all, self._health)
        return await self._turn_snapshot(params)

    async def _turn_snapshot(self, params):
        from ..turn_state.observer import read_turn_snapshot

        envelope = {"schema_version": 1, "availability": "not_enabled",
                    "observed_at": datetime.now(UTC).isoformat(), "data": {}}
        limit = _limit(params, 100, 200)
        try:
            if self._turn_state is not None:
                path = Path(self._turn_state.db_path)
            else:
                path = self.paths.data_dir / "turn_state" / "turns.sqlite3"
                if not path.exists():
                    return envelope
            # Even an injected writer contributes only its path, never its
            # methods or connection. The observer opens mode=ro/query_only.
            data = await asyncio.to_thread(read_turn_snapshot, str(path), limit)
        except Exception:
            envelope["availability"] = "unavailable"
            return envelope
        envelope.update(availability="available", data=data, limit=limit)
        return envelope
