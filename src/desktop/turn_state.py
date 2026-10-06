"""Owner-only read posture; inspection never resumes or mutates a turn."""
from __future__ import annotations

import asyncio
import sqlite3

from ..turn_state.observer import read_turn_snapshot
from ..web.api.turn_state import _TURNS_DEFAULT_LIMIT, _TURNS_MAX_LIMIT, _envelope
from .conversations import ConversationError


class TurnStateService:
    METHODS = frozenset({"turn_state.list"})

    def __init__(self, permissions, authority, *, store_provider, enabled=lambda: True):
        self.permissions, self.authority = permissions, authority
        self.store_provider, self.enabled = store_provider, enabled

    def _owner(self):
        if not self.permissions.is_owner(self.authority.owner_id):
            raise ConversationError("permission_denied", "Authenticated profile owner required")

    async def handle(self, method, params):
        self._owner()
        if method not in self.METHODS:
            raise ConversationError("unknown_method", "Turn posture is read-only")
        if type(params) is not dict or set(params) - {"limit"}:
            raise ConversationError("invalid_params", "Only a bounded limit is accepted")
        limit = params.get("limit", _TURNS_DEFAULT_LIMIT)
        if type(limit) is not int or not 1 <= limit <= _TURNS_MAX_LIMIT:
            raise ConversationError("invalid_params", "Invalid turn posture limit")
        if not self.enabled():
            return _envelope("not_enabled")
        store = self.store_provider()
        if store is None or not store.available:
            return _envelope("unavailable")
        try:
            # No TurnStateStore constructor, boot sweep, checkpoint decoding,
            # shared writer connection, or effect runner on this read path.
            data = await asyncio.to_thread(read_turn_snapshot, store.db_path, limit)
        except (OSError, sqlite3.Error):
            self._owner()
            return _envelope("unavailable")
        self._owner()
        if not self.enabled() or self.store_provider() is not store or not store.available:
            return _envelope("unavailable")
        return _envelope("available", data)
