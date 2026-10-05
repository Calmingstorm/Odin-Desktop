"""Explicit knowledge commands backed by Odin's durable knowledge engine.

Source labels are not import instructions: ingest accepts text, reingest uses
the current full-document snapshot, and import is a separate explicit command.
Nothing is detached or acknowledged before the store's committed result.
Embeddings are injected through the importer; lazy profiles use local search.
"""
from __future__ import annotations

from ..async_utils import to_thread_settled
from ..search.errors import InvalidSearchQuery
from ..storage_redaction import _deep_scrub_strings
from ..web.api.knowledge_mem import _ingest_result_response
from .management import MethodError

METHODS = frozenset({
    "knowledge.list", "knowledge.search", "knowledge.ingest", "knowledge.reingest",
    "knowledge.delete", "knowledge.versions", "knowledge.restore", "knowledge.import",
})
READ_METHODS = frozenset({"knowledge.list", "knowledge.search", "knowledge.versions"})


def _text(params: dict, name: str, *, max_length: int | None = None,
          strip: bool = True) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise MethodError("bad_request", f"{name} is required")
    if strip:
        value = value.strip()
    if max_length is not None and len(value) > max_length:
        raise MethodError("bad_request", f"{name} exceeds maximum length ({max_length} chars)")
    return value


class KnowledgeService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, paths, *, store=None, importer=None):
        if (store is not None and importer is not None
                and getattr(importer, "_store", store) is not store):
            raise ValueError("importer must use the same knowledge store")
        self.paths = paths
        self._store = store if store is not None else getattr(importer, "_store", None)
        self._importer = importer
        self._owns_store = self._store is None

    @property
    def store(self):
        if self._store is None:
            from ..knowledge.store import KnowledgeStore

            self.paths.data_dir.mkdir(parents=True, exist_ok=True)
            self._store = KnowledgeStore(str(self.paths.data_dir / "knowledge.db"))
        return self._store

    @property
    def importer(self):
        if self._importer is None:
            from ..knowledge.importer import BulkImporter

            # Admitted roots come from composition, never HOME or source labels.
            self._importer = BulkImporter(self.store)
        return self._importer

    @property
    def embedder(self):
        return getattr(self._importer, "_embedder", None)

    def close(self):
        """Release only the standalone store, never a graph-owned injected store."""
        if self._owns_store and self._store is not None:
            self._store.close()

    async def handle(self, method: str, params: dict):
        if method not in METHODS:
            raise MethodError("method_not_found", "unknown knowledge method")
        if not isinstance(params, dict):
            raise MethodError("bad_request", "params must be an object")
        try:
            if not self.store.available:
                raise MethodError("unavailable", "knowledge store not available")
            return _deep_scrub_strings(await self._handle(method, params))
        except MethodError:
            raise
        except InvalidSearchQuery:
            raise MethodError("bad_request", "invalid query") from None
        except Exception:
            raise MethodError("internal_error", "knowledge operation failed",
                              disposition="rejected" if method in READ_METHODS
                              else "outcome_unknown") from None

    @staticmethod
    def _ingested(source, chunks, *, reingest=False):
        result, status = _ingest_result_response(
            source, chunks,
            failure_message="document was not durably reingested" if reingest
            else "document was not durably ingested",
            created_status=200 if reingest else 201,
        )
        if status >= 400:
            raise MethodError("internal_error", result["error"])
        # Pinned fresh-success route returns {source, chunks}; fixture adds
        # status/outcome fields. The route is authoritative under D17.
        return result

    async def _handle(self, method: str, params: dict):
        store = self.store
        if method == "knowledge.list":
            return await to_thread_settled(store.list_sources)
        if method == "knowledge.search":
            query = _text(params, "q")
            try:
                limit = int(params.get("limit", 10))
            except (TypeError, ValueError):
                limit = 10  # Odin's _safe_int_param falls back, then clamps.
            return await store.search_hybrid(query, embedder=self.embedder,
                                             limit=min(max(limit, 1), 50))
        if method == "knowledge.import":
            items = params.get("items")
            if not isinstance(items, list) or not items:
                raise MethodError("bad_request", "items (array) is required")
            batch = await self.importer.import_batch(items, uploader="desktop-api")
            return {"total": batch.total, "succeeded": batch.succeeded,
                    "failed": batch.failed, "skipped": batch.skipped,
                    "results": batch.results}
        source = _text(params, "source",
                       max_length=100 if method == "knowledge.ingest" else None,
                       strip=method == "knowledge.ingest")
        if method == "knowledge.ingest":
            content = _text(params, "content", max_length=500_000)
            return self._ingested(source, await store.ingest(
                content, source, embedder=self.embedder, uploader="desktop-api"))
        if method == "knowledge.delete":
            count = await store.delete_source_async(source)
            if not count:
                raise MethodError("not_found", "source not found")
            return {"status": "deleted", "chunks_removed": count}
        if method == "knowledge.reingest":
            content = await to_thread_settled(store.get_source_snapshot, source)
            if content is None:
                if not await to_thread_settled(store.get_source_chunks, source):
                    raise MethodError("not_found", "source not found")
                raise MethodError(
                    "conflict",
                    "No current full-document snapshot; refusing reconstruction from chunks",
                )
            return self._ingested(source, await store.ingest(
                content, source, embedder=self.embedder, uploader="desktop-reingest"),
                reingest=True)
        if method == "knowledge.versions":
            return await to_thread_settled(store.get_versions, source)
        version = params.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise MethodError("bad_request", "version must be a non-negative integer")
        previous = await to_thread_settled(store.get_version, source, version)
        if not previous:
            raise MethodError("not_found", "version not found")
        if not previous.get("content"):
            raise MethodError("bad_request", "version has no content snapshot (delete version)")
        chunks = await store.restore_version(source, version, embedder=self.embedder)
        if chunks <= 0 or getattr(chunks, "status", "") in {"failure", "duplicate", "conflict"}:
            raise MethodError("internal_error", "version was not durably restored")
        return {"status": "restored", "source": source, "version": version, "chunks": int(chunks)}
