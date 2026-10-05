"""Visible, durable transcript search and request-bound model history readers.

App navigation intentionally follows the fixture's literal substring search.
Model retrieval reuses Odin's literal-AND FTS and optional reciprocal-rank fusion,
but never trusts an index as the source of visible content or authorization.
Neither path reads compactable LLM sessions.
"""
from __future__ import annotations

import inspect
import re
from datetime import datetime

from ..llm.secret_scrubber import scrub_output_secrets
from ..search.errors import InvalidSearchQuery, SearchExecutionError, validate_search_query
from .conversations import ConversationError, domain_transaction


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConversationError("bad_request", f"Invalid or missing parameter: {label}")
    try:
        validate_search_query(value)
    except InvalidSearchQuery:
        raise ConversationError("bad_request", f"Invalid parameter: {label}") from None
    return value


def _count(params: dict, key: str, default: int, minimum: int, maximum: int) -> int:
    value = params.get(key, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConversationError("bad_request", f"{key} must be between {minimum} and {maximum}")
    return value


def _scrub(value):
    """Scrub complete strings before any snippets, paging or model formatting."""
    if isinstance(value, str):
        return scrub_output_secrets(value)
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    return value


def _snippet(text: str, start: int, length: int) -> str:
    left, right = max(0, start - 60), min(len(text), start + length + 60)
    return (("…" if left else "") + " ".join(text[left:right].split())
            + ("…" if right < len(text) else ""))


def _searchable_text(message: dict) -> str:
    return "\n".join([message["text"], *(item["name"]
                       for item in message.get("artifacts", []))])


class TranscriptSearch:
    def __init__(self, transcript, events, *, current_conversation=None, semantic_search=None):
        self.transcript = transcript
        self.events = events
        # These are composition-root seams, never model-supplied selectors.
        self.current_conversation = current_conversation
        self.semantic_search = semantic_search

    def _snapshot(self, conversation_id: str | None = None) -> tuple[list[dict], str]:
        with domain_transaction(self.transcript.store):
            if conversation_id is not None:
                self.transcript.conversations.get(conversation_id)
            return _scrub(self.transcript.all_messages(conversation_id)), self.events.high

    def handle(self, method: str, params: dict) -> dict:
        if type(params) is not dict:
            raise ConversationError("bad_request", "Method params must be an object")
        if method == "search.query":
            return self.query(params)
        if method == "messages.around":
            return self.around(params)
        raise ConversationError("capability_unavailable", "Service is not available")

    def query(self, params: dict) -> dict:
        query = _text(params.get("query"), "query").strip()
        limit = _count(params, "limit", 20, 1, 50)
        cursor = params.get("cursor")
        if cursor is None:
            offset = 0
        elif isinstance(cursor, str) and re.fullmatch(r"0|[1-9][0-9]{0,18}", cursor):
            offset = int(cursor)
        else:
            raise ConversationError("bad_request", "Invalid search cursor")
        only = params.get("conversation_id")
        if only is not None:
            only = _text(only, "conversation_id")
        messages, watermark = self._snapshot(only)
        needle = query.lower()
        hits = []
        for message in messages:
            texts = [message["text"], *(item["name"] for item in message.get("artifacts", []))]
            for text in texts:
                at = text.lower().find(needle)
                if at >= 0:
                    hits.append({"conversation_id": message["conversation_id"],
                                 "message_id": message["id"], "role": message["role"],
                                 "snippet": _snippet(text, at, len(needle)),
                                 "created_at": message["created_at"]})
                    break
        hits.sort(key=lambda hit: hit["created_at"], reverse=True)
        page = hits[offset:offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(hits) else None
        return {"hits": page, "next_cursor": next_cursor, "watermark": watermark}

    def around(self, params: dict) -> dict:
        cid = _text(params.get("conversation_id"), "conversation_id")
        mid = _text(params.get("message_id"), "message_id")
        before, after = _count(params, "before", 20, 0, 50), _count(params, "after", 20, 0, 50)
        # Navigation is a transcript read, not a derived search result. Preserve
        # the same public message payload as messages.list/snapshot; only search
        # snippets and model history are scrubbed projections.
        messages = self.transcript.all_messages(cid)
        index = next((index for index, message in enumerate(messages)
                      if message["id"] == mid), None)
        if index is None:
            raise ConversationError("not_found", "Message not found")
        start, end = max(0, index - before), min(len(messages), index + after + 1)
        return {"items": [self.transcript.public(message) for message in messages[start:end]],
                "has_before": start > 0, "has_after": end < len(messages)}

    def _current(self, request) -> str:
        if request is None or self.current_conversation is None:
            raise PermissionError("No authenticated conversation context")
        cid = self.current_conversation(request)
        if not isinstance(cid, str) or not cid:
            raise PermissionError("No authenticated conversation context")
        return cid

    def for_request(self, request):
        """Bound sessions façade for existing KnowledgeTools, no foreign-ID input."""
        self._current(request)
        return _RequestHistory(self, request)

    async def read_visible_history(self, request, *, limit: int = 10) -> list[str]:
        limit = _count({"limit": limit}, "limit", 10, 1, 100)
        cid = self._current(request)
        with domain_transaction(self.transcript.store):
            messages = _scrub(self.transcript.list(cid, limit=limit)["items"])
        return [f"[{item['created_at']}] ({item['role']}): {item['text']}"
                for item in messages]

    async def read_conversation(self, request, *, limit: int = 10) -> list[str]:
        return await self.read_visible_history(request, limit=limit)

    async def search_history(self, request, query: str, *, limit: int = 10) -> list[dict]:
        """Retrieve only the request's committed transcript, not archived sessions."""
        from ..search.fts import FullTextIndex
        from ..search.hybrid import reciprocal_rank_fusion

        try:
            query = _text(query, "query").strip()
            limit = _count({"limit": limit}, "limit", 10, 1, 20)
        except ConversationError:
            raise InvalidSearchQuery("Invalid history query or limit") from None
        cid = self._current(request)
        messages, _ = self._snapshot(cid)
        visible = {item["id"]: item for item in messages}
        index = FullTextIndex(":memory:")
        try:
            if not index.available:
                raise SearchExecutionError("Transcript search is unavailable")
            for message in messages:
                text = _searchable_text(message)
                if not index.index_session(message["id"], text, cid,
                                           _timestamp(message["created_at"])):
                    raise SearchExecutionError("Transcript search is unavailable")
            lexical = index.search_sessions(query, limit=limit * 2, channel_id=cid)
        except InvalidSearchQuery:
            raise
        except Exception:
            raise SearchExecutionError("Transcript search is unavailable") from None
        finally:
            if index._conn is not None:
                index._conn.close()
        semantic = []
        if self.semantic_search is not None:
            try:
                candidates = self.semantic_search(cid, query, limit=limit * 2)
                if inspect.isawaitable(candidates):
                    candidates = await candidates
                seen = set()
                for item in candidates:
                    mid = item.get("message_id", item.get("doc_id"))
                    if (mid in visible and item.get("conversation_id", cid) == cid
                            and mid not in seen):
                        semantic.append({"doc_id": mid})
                        seen.add(mid)
            except Exception:
                raise SearchExecutionError("Transcript search is unavailable") from None
        ranked = reciprocal_rank_fusion(lexical, semantic, limit=limit)
        # Awaiting semantic retrieval permits deletion or a new durable revision.
        # Re-read before delivery, discard stale/deleted hits, and never deliver
        # payloads supplied by a derived index.
        if self._current(request) != cid:
            raise PermissionError("Authenticated conversation context changed")
        fresh, _ = self._snapshot(cid)
        visible = {item["id"]: item for item in fresh}
        result = []
        for item in ranked:
            message = visible.get(item["doc_id"])
            if message is None:
                continue
            result.append({"conversation_id": cid, "message_id": message["id"],
                           "content": _searchable_text(message),
                           "timestamp": _timestamp(message["created_at"]),
                           "type": message["role"], "rrf_score": item["rrf_score"]})
        return result


def _timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


class _RequestHistory:
    def __init__(self, search: TranscriptSearch, request):
        self.search = search
        self.request = request

    async def search_history(self, query: str, limit: int = 10) -> list[dict]:
        return await self.search.search_history(self.request, query, limit=limit)

    async def read_conversation(self, limit: int = 10) -> list[str]:
        return await self.search.read_visible_history(self.request, limit=limit)
