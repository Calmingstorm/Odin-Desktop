"""Owner-authenticated agent policy composition over canonical settings services.

An optional async persistence gate lets storage settle readiness, failures and
cancellation before the synchronous settings transaction. The gate never
validates, writes or publishes configuration. Those operations remain with
ModelSettingsService and SettingsService.
"""
from __future__ import annotations

import asyncio

from .management import MethodError
from .model_settings import ModelSettingsService


class WorkPolicyService:
    methods = frozenset({"models.agents.get", "models.agents.set"})

    def __init__(self, settings, *, authority, model_settings=None, persistence_gate=None):
        self.settings = settings
        self.authority = authority
        self.models = model_settings or ModelSettingsService(settings)
        if self.models.settings is not settings:
            raise ValueError("Model and work policy must share the settings owner")
        self.persistence_gate = persistence_gate
        self._lock = asyncio.Lock()

    async def invoke(self, method, params, *, owner):
        if not self.authority.accepts(owner):
            raise PermissionError("Authenticated profile owner required")
        if method not in self.methods or type(params) is not dict:
            raise MethodError("bad_request", "Unknown agent policy method or parameters")
        async with self._lock:
            if method == "models.agents.get":
                return await self.models.handle(method, params)
            # Delegate preflight to the same candidate owner used at commit.
            # The settings transaction still performs its own revalidation.
            submitted = {key: params[key] for key in (
                "model", "thinking_mode", "auto_model_allowlist", "model_selection_hints"
            ) if key in params}
            try:
                self.models._candidate("agents", submitted)
            except (ValueError, TypeError, AttributeError):
                # Never expose credential-bearing Config validation inputs or
                # arbitrary validator exception text through the work protocol.
                raise MethodError("bad_request", "invalid agent policy") from None
            if self.persistence_gate is not None:
                try:
                    outcome = await self.persistence_gate()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    raise MethodError("internal_error", "Configuration not saved") from None
                if (not isinstance(outcome, tuple) or len(outcome) != 2
                        or type(outcome[1]) is not bool):
                    raise MethodError("internal_error", "Invalid persistence settlement")
                error, cancelled = outcome
                if cancelled:
                    raise asyncio.CancelledError
                if error is not None:
                    raise MethodError("internal_error", "Configuration not saved")
            # No async operation occurs inside the canonical disk transaction.
            # Failed or cancelled gates therefore never publish a candidate.
            if not self.authority.accepts(owner):
                raise PermissionError("Profile authority changed before settings commit")
            return await self.models.handle(method, params)
