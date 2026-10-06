"""Retained learned-context CRUD, independent of automatic generation policy.

Inject the runtime reflector to share its retained store and write lock.
Standalone profiles use that same implementation with generation disabled.
No model-facing prompt text is changed here.
"""
from __future__ import annotations

from ..storage_redaction import _deep_scrub_strings
from .management import MethodError

METHODS = frozenset({"learned.list", "learned.update", "learned.delete"})
READ_METHODS = frozenset({"learned.list"})


class LearnedContextService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, paths, *, reflector=None, reflector_getter=None, learning_getter=None):
        self.paths = paths
        self._reflector = reflector
        self._reflector_getter = reflector_getter
        self._learning_getter = learning_getter

    @property
    def reflector(self):
        if self._reflector_getter is not None:
            runtime = self._reflector_getter()
            if runtime is not None:
                return runtime
        if self._reflector is None:
            from ..learning.reflector import ConversationReflector

            learning = self._learning_getter() if self._learning_getter else None
            self._reflector = ConversationReflector(
                str(self.paths.data_dir / "learned.json"), enabled=False,
                max_entries=getattr(learning, "max_entries", 150),
                consolidation_target=getattr(learning, "consolidation_target", 120),
                injection_token_budget=getattr(learning, "injection_token_budget", 4000),
            )
        return self._reflector

    async def handle(self, method, params):
        if method not in METHODS:
            raise MethodError("method_not_found", "unknown learned-context method")
        if not isinstance(params, dict):
            raise MethodError("bad_request", "params must be an object")
        try:
            return _deep_scrub_strings(await self._handle(method, params))
        except MethodError:
            raise
        except Exception:
            raise MethodError("internal_error", "learned-context operation failed",
                              disposition="rejected" if method in READ_METHODS
                              else "outcome_unknown") from None

    async def _handle(self, method, params):
        reflector = self.reflector
        if method == "learned.list":
            return {"entries": reflector.get_all_entries(), **reflector.get_metadata()}
        key = params.get("key")
        if not isinstance(key, str) or not key:
            raise MethodError("bad_request", "key is required")
        if method == "learned.delete":
            if await reflector.delete_entry_async(key):
                return {"status": "deleted", "key": key}
            raise MethodError("not_found", "entry not found")
        if not {"content", "category"}.intersection(params):
            raise MethodError("bad_request", "content or category is required")
        for name in ("content", "category"):
            if name in params and not isinstance(params[name], str):
                raise MethodError("bad_request", f"{name} must be a string")
        updated = await reflector.update_entry_async(
            key, content=params.get("content"), category=params.get("category"),
        )
        if updated:
            return updated
        raise MethodError("not_found", "entry not found")
