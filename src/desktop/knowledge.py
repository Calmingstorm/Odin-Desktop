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
from ..web.api_common import _safe_int_param
from .management import MethodError

METHODS = frozenset({
    "knowledge.list", "knowledge.search", "knowledge.ingest", "knowledge.reingest",
    "knowledge.delete", "knowledge.versions", "knowledge.restore", "knowledge.import",
    "knowledge.chunks", "knowledge.duplicates", "knowledge.merge",
    "knowledge.version", "knowledge.diff",
})
READ_METHODS = frozenset({"knowledge.list", "knowledge.search", "knowledge.versions",
                          "knowledge.chunks", "knowledge.duplicates", "knowledge.version",
                          "knowledge.diff"})


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
            raise MethodError("internal_error", "search failed" if method == "knowledge.search"
                              else "knowledge operation failed",
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
            query = params.get("q", "")
            if not isinstance(query, str) or not query.strip():
                raise MethodError("bad_request", "q parameter required")
            from types import SimpleNamespace
            try:
                limit = _safe_int_param(SimpleNamespace(query=params), "limit", 10, hi=50)
            except ValueError:
                raise MethodError("bad_request", "limit must be an integer") from None
            return await store.search_hybrid(query.strip(), embedder=self.embedder, limit=limit)
        if method == "knowledge.import":
            items = params.get("items")
            if not isinstance(items, list) or not items:
                raise MethodError("bad_request", "items (array) is required")
            batch = await self.importer.import_batch(items, uploader="desktop-api")
            return {"total": batch.total, "succeeded": batch.succeeded,
                    "failed": batch.failed, "skipped": batch.skipped,
                    "results": batch.results}
        if method == "knowledge.duplicates":
            exact = await to_thread_settled(store.find_duplicates)
            try:
                threshold = float(params.get("threshold", "0.5"))
            except (ValueError, TypeError):
                threshold = 0.5
            # The pinned handler does not clamp thresholds, including NaN.
            near = await to_thread_settled(store.find_near_duplicates, threshold)
            return {"exact": exact, "near": near}
        if method == "knowledge.merge":
            keep, remove = params.get("keep_source", ""), params.get("remove_source", "")
            if (not isinstance(keep, str) or not isinstance(remove, str)
                    or not keep.strip() or not remove.strip()):
                raise MethodError("bad_request", "keep_source and remove_source are required")
            keep, remove = keep.strip(), remove.strip()
            removed = await store.merge_sources_async(keep, remove)
            if removed == 0:
                raise MethodError("not_found", "keep_source not found or nothing to merge")
            return {"status": "merged", "kept": keep, "removed": remove,
                    "chunks_removed": removed}
        if method == "knowledge.ingest":
            if (not isinstance(params.get("source"), str) or not params["source"].strip()
                    or not isinstance(params.get("content"), str) or not params["content"].strip()):
                raise MethodError("bad_request", "source and content are required")
            source = _text(params, "source", max_length=100)
        else:
            source = params.get("source")
            # Source path components in Odin are not trimmed or length-bounded.
            if not isinstance(source, str) or not source:
                raise MethodError("bad_request", "source is required")
        if method == "knowledge.chunks":
            chunks = await to_thread_settled(store.get_source_chunks, source)
            if not chunks:
                raise MethodError("not_found", "source not found or empty")
            return chunks
        if method == "knowledge.diff":
            v1, v2 = self._version(params, "v1"), self._version(params, "v2")
            diff = await to_thread_settled(store.get_version_diff, source, v1, v2)
            if not diff:
                raise MethodError("not_found", "one or both versions not found")
            return diff
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
        version = self._version(params, "version")
        previous = await to_thread_settled(store.get_version, source, version)
        if not previous:
            raise MethodError("not_found", "version not found")
        if method == "knowledge.version":
            return previous
        if not previous.get("content"):
            raise MethodError("bad_request", "version has no content snapshot (delete version)")
        chunks = await store.restore_version(source, version, embedder=self.embedder)
        if chunks <= 0 or getattr(chunks, "status", "") in {"failure", "duplicate", "conflict"}:
            raise MethodError("internal_error", "version was not durably restored")
        return {"status": "restored", "source": source, "version": version, "chunks": int(chunks)}

    @staticmethod
    def _version(params, name):
        value = params.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MethodError("bad_request", f"{name} must be a non-negative integer")
        return value
