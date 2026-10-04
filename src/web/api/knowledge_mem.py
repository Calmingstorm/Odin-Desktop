"""Neutral ingestion outcome shaping; protected store commands await Phase 2.

Require profile-local store/search/duplicate semantics, scope, native ingestion
and separately authorized destructive operations. No multi-user selector.
"""
from . import require_phase2


def _ingest_result_response(source, chunks, *, failure_message, created_status):
    """Map typed durable-store outcomes to transport-neutral result/status pairs."""
    outcome = getattr(chunks, "status", "")
    if outcome == "unchanged":
        return {"source": source, "chunks": int(chunks),
                "status": "already stored, unchanged", "outcome": outcome}, 200
    if outcome == "duplicate":
        existing = getattr(chunks, "duplicate_of", "")
        message = (
            f"Identical content is already stored as '{existing}'; no new source was created."
            if existing else
            "Identical content is already stored under another source; no new source was created."
        )
        return {"source": source, "status": "identical content already stored elsewhere; not ingested",
                "outcome": outcome, "duplicate_of": existing, "message": message}, 200
    if outcome == "conflict":
        existing = getattr(chunks, "duplicate_of", "")
        message = (
            f"Near-duplicate content conflicts with '{existing}'; the new content was not stored."
            if existing else
            "Near-duplicate content conflicts with existing knowledge; the new content was not stored."
        )
        return {"source": source, "status": "near-duplicate conflict; new content not stored",
                "outcome": outcome, "duplicate_of": existing, "message": message}, 200
    if outcome == "failure" or chunks <= 0:
        return {"error": failure_message}, 500
    return {"source": source, "chunks": int(chunks)}, created_status


def register_knowledge(*args, **kwargs):
    require_phase2("Knowledge management")


def register_memory_notes(*args, **kwargs):
    require_phase2("Profile memory management")


def register_learned_context(*args, **kwargs):
    require_phase2("Learned context management")
