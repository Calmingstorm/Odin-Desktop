"""Read-only, profile-bound adapters for Odin's observability stores.

The HTTP routes, not the app's synthetic fixture, define these result shapes.
In particular unsigned audit history is not verified, and turn observation
never constructs a TurnStateStore (whose startup sweep is a write).
"""
from __future__ import annotations

import asyncio
import inspect
import os
import secrets
from collections import OrderedDict
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path

from ..audit.logger import DEFAULT_MAX_FILES, AuditLogger
from ..audit.signer import AuditSigner
from ..observability.diagnostics import scrub_diagnostic
from .management import MethodError
from .secrets import SecretStoreError

METHODS = frozenset({
    "audit.query", "audit.verify", "health.get", "logs.search", "turn_state.list",
    "audit.diffs", "audit.failures", "audit.tail", "logs.stats", "logs.tail",
})
READ_METHODS = METHODS
_LOG_TAIL_LINES = 50
_LOG_READ_BLOCK = 8192
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


def _read_log_tail(path: Path, lines_limit: int = _LOG_TAIL_LINES):
    """Pinned v4.13 binary tail algorithm: complete records and UTF-8 only.

    Read backwards in 8192-byte blocks, discarding a potentially enormous
    incomplete final record without retaining it. Memory scales with the
    returned complete records, not the file's total size.
    """
    with path.open("rb") as handle:
        stat = os.fstat(handle.fileno())
        pos = stat.st_size
        complete_pos = 0
        chunks = []
        newlines = 0
        found_end = False
        while pos and newlines <= lines_limit:
            size = min(pos, _LOG_READ_BLOCK)
            pos -= size
            handle.seek(pos)
            block = handle.read(size)
            if not found_end:
                end = block.rfind(b"\n")
                if end < 0:
                    continue
                complete_pos = pos + end + 1
                block = block[:end + 1]
                found_end = True
            chunks.append(block)
            newlines += block.count(b"\n")
        data = b"".join(reversed(chunks))
        if pos:
            data = data[data.find(b"\n") + 1:]
        lines = [line.rstrip("\r") for line in data.decode("utf-8").split("\n")[:-1]]
        return lines[-lines_limit:], complete_pos, (stat.st_dev, stat.st_ino)


def _read_log_updates(path: Path, last_pos: int, identity, lines_limit: int = _LOG_TAIL_LINES):
    """Pinned follow semantics, paged instead of an endless poll.

    Scan incomplete appends in fixed blocks without accumulating them; decode
    only complete records. A cursor advances only past newlines. Inode change
    or truncation restarts at zero. Blank incremental rows match upstream's
    suppression, while initial tails preserve blank rows.
    """
    with path.open("rb") as handle:
        stat = os.fstat(handle.fileno())
        current_identity = (stat.st_dev, stat.st_ino)
        if current_identity != identity or stat.st_size < last_pos:
            last_pos = 0
        handle.seek(last_pos)
        lines = []
        records = 0
        scan_pos = last_pos
        while scan_pos < stat.st_size and records < lines_limit:
            block = handle.read(min(_LOG_READ_BLOCK, stat.st_size - scan_pos))
            if not block:
                break
            end = block.find(b"\n")
            if end < 0:
                scan_pos += len(block)
                continue
            end_pos = scan_pos + end + 1
            handle.seek(last_pos)
            remaining = end_pos - last_pos
            chunks = []
            while remaining:
                raw = handle.read(min(_LOG_READ_BLOCK, remaining))
                if not raw:
                    # A concurrent truncate invalidated the observed complete
                    # record. Never emit a fragment or advance beyond it.
                    return lines, last_pos, current_identity
                chunks.append(raw)
                remaining -= len(raw)
            raw = b"".join(chunks)
            line = raw.decode("utf-8").rstrip("\r\n")
            if line:
                lines.append(line)
            records += 1
            last_pos = scan_pos = end_pos
            handle.seek(scan_pos)
        return lines, last_pos, current_identity


def _signing_key(audit) -> bytes:
    """The key an audit object verifies with; empty when it signs nothing."""
    signer = getattr(audit, "_signer", None)
    return getattr(signer, "_key", b"") if signer is not None else b""


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


class _KeyedWriterView(_AuditReader):
    """The active writer's file, verified under the signing key a read resolved.

    Only the verification authority differs from the writer. Snapshots take the
    writer's own append fence and durability is the writer's live state, never a
    copy taken when the view was bound. Writer paths are not available here.
    """

    def __init__(self, writer, hmac_key):
        self.path = Path(writer.path)
        self._writer = writer
        self._signer = AuditSigner(hmac_key) if hmac_key else None
        self._persist_lock = writer._persist_lock
        self._max_files = getattr(writer, "_max_files", DEFAULT_MAX_FILES)

    @property
    def repair_required(self):
        return self._writer.repair_required

    @property
    def durability_degraded(self):
        return self._writer.durability_degraded


class RecordsService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, paths, *, settings=None, get_audit_path=None, audit=None, audit_getter=None,
                 health=None, logs=None, turn_state=None):
        self.paths = paths
        self._settings = settings
        self._get_audit_path = get_audit_path
        self._audit = audit
        self._audit_getter = audit_getter
        self._audit_reader = None
        self._audit_binding = None
        self._health = health
        self._logs = logs
        self._turn_state = turn_state
        # Ephemeral read leases, never filesystem paths supplied by callers.
        # Tokens are reusable, profile/path-bound and retained for 256 pages.
        self._tail_cursors = OrderedDict()

    @property
    def audit(self):
        # Explicit backends remain authoritative test/runtime injection seams.
        if self._audit is not None:
            return self._audit
        config = self._settings.config if self._settings is not None else None
        hmac_key = config.audit.hmac_key if config is not None else ""
        resolve_key = getattr(self._settings, "audit_signing_key", None)
        if callable(resolve_key):
            try:
                hmac_key = resolve_key()
            except SecretStoreError:
                # Unavailable authority is not proof of integrity. Preserve
                # readable history, but never reuse a cached or config key.
                hmac_key = ""
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
            try:
                hmac_key = await secret_call(resolve_key)
            except SecretStoreError:
                # Match Odin's no-key read contract without changing writer
                # authority or swallowing read failures/cancellation.
                hmac_key = ""
        return self._bind_audit(hmac_key)

    def _bind_audit(self, hmac_key):
        config = self._settings.config if self._settings is not None else None
        if self._get_audit_path is not None:
            path = Path(self._get_audit_path())
        else:
            path = Path(config.tools.audit_log_path) if config is not None else (
                self.paths.data_dir / "audit.jsonl")
        runtime = self._audit_getter() if self._audit_getter is not None else None
        key = hmac_key.encode() if isinstance(hmac_key, str) else (hmac_key or b"")
        if runtime is not None and Path(runtime.path) == path:
            # The configured read source is still the actual writer's active file:
            # share its snapshot lock and live durability. A writer signing under
            # the key this read resolved serves the read itself; otherwise a keyed
            # view verifies with the resolved authority. Relocated history stays a
            # read-only reader until the owning runtime adopts that path.
            if _signing_key(runtime) == key:
                return runtime
            binding = ("writer", id(runtime), path, key)
            if binding != self._audit_binding:
                self._audit_reader = _KeyedWriterView(runtime, hmac_key)
                self._audit_binding = binding
            return self._audit_reader
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
            result = await self._handle(method, params)
            if method in {"audit.diffs", "audit.failures", "audit.tail", "logs.stats", "logs.tail"}:
                # These pinned records are already bounded by their read
                # algorithms. Do not cut valid diffs/UTF-8 lines at 4000 chars.
                return scrub_diagnostic(result)
            return _diagnostic_copy(result)
        except MethodError:
            raise
        except Exception:
            # Manager exceptions may contain secrets, SQL, paths or credentials.
            raise MethodError("unavailable", "Records read is unavailable") from None

    async def _handle(self, method, params):
        if method == "audit.diffs":
            filters = {name: _filter(params, name) for name in ("user", "date")}
            filters["tool_name"] = _filter(params, "tool")
            entries = await _result(self._method(self.audit, "search_diffs")(
                **filters, limit=_limit(params, 20, 100)))
            return {"entries": entries, "count": len(entries)}
        if method == "audit.failures":
            from ..async_utils import to_thread_settled
            from ..observability.aggregates import failure_aggregates

            try:
                hours = max(1, min(int(params.get("window", 24)), 24 * 14))
            except (TypeError, ValueError, OverflowError):
                hours = 24
            audit = self.audit
            snapshot = await _result(self._method(audit, "open_read_snapshot")())
            try:
                return await to_thread_settled(
                    failure_aggregates, str(audit.path), hours, snapshot=snapshot)
            finally:
                for handle, _stat in snapshot:
                    handle.close()
        if method == "logs.stats":
            backend = self._logs if self._logs is not None else self.audit
            return await _result(self._method(backend, "get_log_stats")())
        if method in {"audit.tail", "logs.tail"}:
            return await self._tail_read(method, params)
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

    async def _tail_read(self, method, params):
        path = Path(self.audit.path)
        lines_limit = _limit({"limit": params.get("lines", 50)}, 50, 200)
        token = params.get("cursor")
        binding = (method, str(path))
        last_pos, identity = 0, None
        if token is not None:
            if not isinstance(token, str) or token not in self._tail_cursors:
                raise MethodError("bad_request", "Unknown or expired tail cursor")
            saved_binding, last_pos, identity = self._tail_cursors[token]
            if saved_binding != binding:
                raise MethodError("bad_request", "Tail cursor belongs to another source")
        try:
            if token is None:
                args = (path, lines_limit) if "lines" in params else (path,)
                lines, next_pos, next_identity = await asyncio.to_thread(_read_log_tail, *args)
            else:
                args = (path, last_pos, identity, lines_limit) if "lines" in params else (
                    path, last_pos, identity)
                lines, next_pos, next_identity = await asyncio.to_thread(_read_log_updates, *args)
            reset = token is not None and (next_identity != identity or next_pos < last_pos)
            last_pos, identity = next_pos, next_identity
            availability = "available"
        except FileNotFoundError:
            lines, availability, reset = [], "missing", False
        token = secrets.token_urlsafe(24)
        self._tail_cursors[token] = (binding, last_pos, identity)
        while len(self._tail_cursors) > 256:
            self._tail_cursors.popitem(last=False)
        return {"lines": lines, "cursor": token, "availability": availability,
                "reset": reset, "page_limit": lines_limit,
                "page_full": len(lines) >= lines_limit}

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
