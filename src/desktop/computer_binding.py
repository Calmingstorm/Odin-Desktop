"""Authenticated owner-only native task management, not foreground admission.

Phase 2 step 6A deliberately grants no conversation, turn, pixels or input.
The retained controller/store own cleanup uncertainty and recovery. A native
backend's presence/configuration never implies qualification or usability.
"""
from __future__ import annotations

import asyncio
import contextvars
from types import SimpleNamespace

from ..computer.models import ComputerError, ManagementContext
from .management import MethodError


class ComputerBindingService:
    METHODS = frozenset({
        "computer.status", "computer.pause", "computer.stop", "computer.cancel",
        "computer.close", "computer.reconcile", "computer.reconcile_hyprland_owner",
        "computer.acknowledge_legacy_recovery", "computer.operator_reconcile",
        "computer.release_owned_input",
        "computer.activation.set",
    })
    READ_METHODS = frozenset({"computer.status"})

    def __init__(self, core, settings, *, controller=None, backend_factory=None):
        self.core, self.settings = core, settings
        self.authority, self.permissions = core.authority, core.permissions
        self.controller = controller
        self._backend_factory = backend_factory
        self._integration = None
        self._started = False
        self._closed = False
        self._bindings = contextvars.ContextVar("desktop_computer_management", default=None)
        self._lifecycle = asyncio.Lock()

    @property
    def published_available(self):
        # Step 3 foreground delivery and Phase 3 native qualification are gates,
        # not promises inferred from a configured backend or a successful stub.
        return False

    def readiness(self):
        return {"management_available": self._started and not self._closed,
                "foreground_available": False, "native_qualified": False,
                "input_supported": False, "dispatch": "none",
                "reason": "foreground_binding_and_native_qualification_pending"}

    async def start(self):
        """Open private durable state only. Never start a native desktop/helper."""
        async with self._lifecycle:
            if self._closed:
                raise MethodError("capability_unavailable", "Computer management is closed")
            if self._started:
                return
            if self.controller is None:
                from ..computer.integration import ComputerIntegration

                integration = ComputerIntegration(SimpleNamespace(config=self.settings.config))
                self._integration = integration
                self.controller = integration.controller
            self.controller.authorize = self._authorize
            self.controller.enabled = bool(self.settings.config.computer.enabled)
            if self._backend_factory is not None:
                self.controller.backend_factory = self._backend_factory
            self._started = True

    def _authorize(self, context):
        binding = self._bindings.get()
        return bool(
            self._started and not self._closed and type(context) is ManagementContext
            and binding is not None and binding[0] is context
            and not binding[2].done()
            and (binding[2] is asyncio.current_task() or asyncio.current_task() in
                 getattr(self.controller, "_recoveries", {}).values())
            and self.authority.accepts(binding[1])
            and self.permissions.get_request_owner() is binding[1]
            and context.owner_id == binding[1].owner_id and context.host_id == "localhost"
        )

    @staticmethod
    def _params(method, params):
        if type(params) is not dict:
            raise MethodError("invalid_params", "Computer parameters must be an object")
        if method == "computer.status":
            allowed, required = set(), set()
        else:
            allowed = required = {"session_id", "generation"}
            if method in {"computer.acknowledge_legacy_recovery", "computer.operator_reconcile"}:
                allowed = required = allowed | {"acknowledgment"}
        if set(params) - allowed or required - set(params):
            raise MethodError("invalid_params", "Unexpected or missing computer parameters")
        if required and (
            type(params["session_id"]) is not str or not params["session_id"]
            or len(params["session_id"]) > 128 or type(params["generation"]) is not int
            or not 1 <= params["generation"] < 2**63
        ):
            raise MethodError("invalid_params", "Exact session and generation are required")
        if "acknowledgment" in params and (
            type(params["acknowledgment"]) is not str or len(params["acknowledgment"]) > 256
        ):
            raise MethodError("invalid_params", "Explicit cleanup acknowledgment is required")

    async def handle(self, method, params):
        if method not in self.METHODS:
            raise MethodError("unknown_method", "Computer foreground admission is unavailable")
        owner = self.permissions.get_request_owner()
        if owner is None or not self.authority.accepts(owner):
            raise MethodError("permission_denied", "Authenticated profile owner required")
        if method == "computer.activation.set":
            return await self.settings.handle(method, params)
        self._params(method, params)
        if not self._started or self._closed:
            raise MethodError("capability_unavailable", "Computer management is not running")
        context = ManagementContext(owner.owner_id, "localhost")
        token = self._bindings.set((context, owner, asyncio.current_task()))
        try:
            operation = method.removeprefix("computer.")
            if operation in {"status", "pause", "stop", "cancel", "close"}:
                result = await self.controller.operator_session(context, operation, **params)
            else:
                target = {
                    "reconcile": "reconcile_recovery",
                    "reconcile_hyprland_owner": "reconcile_hyprland_owner",
                    "acknowledge_legacy_recovery": "acknowledge_legacy_recovery",
                    "operator_reconcile": "operator_reconcile",
                    "release_owned_input": "operator_release_owned_input",
                }[operation]
                result = await getattr(self.controller, target)(context, **params)
            if not self._authorize(context):
                raise MethodError("permission_denied", "Computer management authority expired")
            return {"session": {**result, "input_supported": False,
                                "input_readiness": "foreground_unavailable"},
                    "readiness": self.readiness()}
        except ComputerError as exc:
            if method == "computer.status" and exc.code == "not_found":
                if not self._authorize(context):
                    raise MethodError("permission_denied", "Computer management authority expired")
                return {"session": None, "readiness": self.readiness()}
            raise MethodError(exc.code, "Computer management did not complete") from None
        finally:
            self._bindings.reset(token)

    def prepare_settings(self, desired, changes):
        """Activation/revocation only; never adopt unqualified native settings."""
        paths = {".".join(path) if not isinstance(path, str) else path for path, _ in changes}
        if paths != {"computer.enabled"}:
            raise MethodError("capability_unavailable",
                              "Native runtime configuration requires qualification")
        if self.permissions.get_request_owner() is None or not self._started or self._closed:
            raise MethodError("permission_denied", "Authenticated running owner required")
        service = self
        old = self.controller.enabled
        target = bool(desired.computer.enabled)

        class Activation:
            async def apply(self):
                if service.permissions.get_request_owner() is None:
                    raise MethodError("permission_denied", "Computer authority expired")
                await service.controller.set_enabled(target)
                # Enabled means the retained activation flag, not qualified input.
                return True

            async def rollback(self):
                # Restoration cannot resume a stopped task or restore its consent.
                await service.controller.set_enabled(old)

        return Activation()

    async def close(self):
        async with self._lifecycle:
            if self._closed:
                return
            if self._started:
                if self._integration is not None:
                    await self._integration.close()
                else:
                    await self.controller.close()
                    if getattr(self.controller, "_live", None):
                        raise RuntimeError("Computer cleanup incomplete; runtime retained")
            self._closed, self._started = True, False


# Stable seam for the management composer; no second service implementation.
ComputerService = ComputerBindingService
