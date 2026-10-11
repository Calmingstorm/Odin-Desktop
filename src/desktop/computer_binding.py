"""Separate authenticated management and admitted foreground computer identities.

This is the step-6B seam, composed with step-6A's management service by
``bind_foreground``. Management and model input remain different identities.
Neither constructing a RequestContext nor possessing an IPC token grants input.
Native qualification, vision, consent, freshness and release remain downstream.
Phase 2 step 6A deliberately grants no conversation, turn, pixels or input.
The retained controller/store own cleanup uncertainty and recovery. A native
backend's presence/configuration never implies qualification or usability.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
import sys
import uuid
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from ..computer.integration import ComputerIntegration, _grant
from ..computer.models import ComputerError, ManagementContext, RequestContext
from ..tools.output_authorization import tool_scope_allows
from .management import MethodError
from .platform.variants import windows_variant


@dataclass(eq=False)
class _RequestBinding:
    message: object
    task: asyncio.Task
    context: RequestContext
    active: bool = True
    turn: object = None


class ComputerForegroundBinding(ComputerIntegration):
    """Use the actual RequestService execution, including its runner children.

    ``enter_request`` is called by the admitted root task after assert_request;
    ``leave_request`` runs in its finally before that request context is reset.
    Children may use a grant for their own call, not inherit a parent's call.
    The shared active latch fences children even when ContextVars outlive a turn.
    """

    def __init__(self, requests, *, config, controller=None, management_authorize=None):
        super().__init__(SimpleNamespace(config=config), controller=controller)
        self.requests = requests
        self._management_authorize = management_authorize
        self._requests = ContextVar("desktop_computer_request", default=None)
        self._active_requests = {}
        self._readiness = None
        self.controller.authorize = self._authorize

    @property
    def enabled(self):
        return not self._closed and bool(getattr(self.controller, "enabled",
                                               self.bot.config.computer.enabled))

    @property
    def published_available(self):
        return bool(not self._closed and self.enabled and self._readiness
                    and self._readiness()["foreground_available"])

    def _backend(self, app=None):
        if not self.published_available:
            raise ComputerError("desktop_x11_backend_unavailable")
        return super()._backend(app)

    def enter_request(self, message):
        self.requests.assert_request(message)
        if self._background(message):
            raise PermissionError("Background work cannot acquire foreground computer authority")
        inherited = self._requests.get()
        if inherited is not None and inherited.active and not inherited.task.done():
            raise PermissionError("Computer request already bound")
        row = self.requests.binding(message.conversation_id, message.request_id,
                                    message.generation)
        if row is None or row["state"] != "running":
            raise PermissionError("Foreground request is not running")
        # A resumed request is a new input lineage. It cannot reuse old consent
        # or observations simply because its durable request_id did not change.
        context = RequestContext(message.owner_id, message.conversation_id,
                                 f"{message.request_id}:{message.generation}", "localhost")
        binding = _RequestBinding(message, asyncio.current_task(), context)
        key = message.conversation_id
        if key in self._active_requests:
            raise PermissionError("Conversation already has a foreground request")
        self._active_requests[key] = binding
        return self._requests.set(binding)

    def _background(self, message):
        check = getattr(self.requests, "is_background", None)
        if check is not None:
            return check(message) is not False
        # Parent composition may install background admission after this facade
        # is constructed. Recheck its durable registry, never the model's origin.
        db = self.requests.store.connection
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='desktop_background_requests'").fetchone()
        return bool(exists and db.execute("SELECT 1 FROM desktop_background_requests "
                    "WHERE request_id=?", (message.request_id,)).fetchone())

    def _binding(self, *, cleanup=False):
        binding = self._requests.get()
        if binding is None or not binding.active or binding.task.done():
            raise PermissionError("No active admitted computer request")
        message = binding.message
        # Computer authority rejects background lineage before publication
        # validation, which has its own independent background task latch.
        if self._background(message):
            raise PermissionError("Computer request lineage expired")
        self.requests.assert_bound_request(message)
        row = self.requests.binding(message.conversation_id, message.request_id,
                                    message.generation)
        if (self._active_requests.get(message.conversation_id) is not binding
                or row is None or row["owner"] != message.owner_id
                or self._background(message)
                or (not cleanup and row["state"] != "running")):
            raise PermissionError("Computer request lineage expired")
        return binding

    def _context(self, st, *, cleanup=False):
        binding = self._binding(cleanup=cleanup)
        message = binding.message
        trajectory = getattr(st, "_trajectory", None)
        if (getattr(st, "message", None) is not message
                or (binding.turn is not None and binding.turn is not st)
                or getattr(st, "user_id", None) != message.owner_id
                or getattr(st, "_ch_id", None) != message.conversation_id
                or getattr(st, "_req_id", None) != message.request_id
                or getattr(trajectory, "source", None) != "conversation"
                or getattr(trajectory, "message_id", None) != message.request_id
                or getattr(trajectory, "channel_id", None) != message.conversation_id
                or (not cleanup and getattr(st, "_cancel", None) is not None
                    and st._cancel.is_set())):
            raise PermissionError("Computer use requires the admitted foreground turn")
        binding.turn = st
        return binding.context

    def _authorize(self, context):
        if type(context) is not RequestContext:
            return bool(self._management_authorize and self._management_authorize(context))
        try:
            binding = self._binding()
        except PermissionError:
            return False
        if binding.turn is None:
            return False
        try:
            self._context(binding.turn)
        except PermissionError:
            return False
        grant = _grant.get()
        current = asyncio.current_task()
        return bool(
            self.enabled and context is binding.context and grant is not None
            and grant.context is context and not grant.task.done()
            and (grant.task is current or current in
                 getattr(self.controller, "_recoveries", {}).values())
            and tool_scope_allows(grant.tool_name)
        )

    async def finish_turn(self, st):
        # Retained runner's cancellation observer is a child of this request.
        # Cleanup never becomes a fresh observation or input authorization.
        return await self.controller.finish_turn(self._context(st, cleanup=True))

    async def leave_request(self, token):
        binding = self._requests.get()
        if binding is None or binding.task is not asyncio.current_task():
            raise PermissionError("Only the admitted root may retire its computer request")
        binding.active = False
        if self._active_requests.get(binding.message.conversation_id) is binding:
            self._active_requests.pop(binding.message.conversation_id)
        try:
            # Cleanup uses the already-recorded exact lineage, even after owner
            # revocation, cancellation or terminal persistence. Never a replay.
            return await self.controller.finish_turn(binding.context)
        finally:
            self._requests.reset(token)


def bind_foreground(service, requests):
    """Compose step-6A's single store/controller, without creating native input.

    Call after service.start(). Return this facade as native_owners['computer']
    and get_computer's owner. Keep the management service for protocol methods.
    Publication follows the management owner's read-only X11 startup probe.
    Dependency resolver placement remains worker-only.
    """
    if not service._started or service._closed or service.controller is None:
        raise RuntimeError("Computer management must be started before binding requests")
    if isinstance(service._integration, ComputerForegroundBinding):
        if service._integration.requests is not requests:
            raise RuntimeError("Computer request owner cannot be rebound")
        return service._integration
    old = service._integration
    facade = ComputerForegroundBinding(requests, controller=service.controller,
        config=service.settings.config, management_authorize=service._authorize)
    if old is not None:
        # Preserve store ownership and the retained runtime-generation snapshot.
        facade._owns_store = old._owns_store
        facade.settings = old.settings
    service.controller.authorize = facade._authorize
    facade._readiness = getattr(service, "readiness", None)
    if getattr(service, "_backend_factory", None) is None:
        service.controller.backend_factory = facade._backend
    service._integration = facade
    return facade


def create_foreground(requests, config):
    """Standalone step-6B composition until the management stack lands.

    ComputerIntegration opens only config.computer.storage_dir's private store;
    it does not create a backend before explicit retained session admission.
    The caller owns close(). This does not publish a native capability. Later
    PartA composition uses bind_foreground to share its controller/store instead.
    """
    return ComputerForegroundBinding(requests, config=config)
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
        self._startup_error = None
        self._x11_ready = False
        self._probe_backend = None
        self._native_reason = "computer_not_started"
        self._bindings = contextvars.ContextVar("desktop_computer_management", default=None)
        self._lifecycle = asyncio.Lock()

    @property
    def published_available(self):
        return self.readiness()["foreground_available"]

    def readiness(self):
        running = self._started and not self._closed
        enabled = bool(self.settings.config.computer.enabled)
        active = bool(running and self.controller.enabled
                      and not getattr(self._integration, "_closed", False))
        available = bool(active and enabled and self._x11_ready)
        reason = (self._startup_error or ("computer_closed" if self._closed else
                  "computer_disabled" if not enabled or running and not active else
                  "computer_not_started" if not running else self._native_reason))
        return {"management_available": running,
                "foreground_available": available, "native_qualified": False,
                "input_supported": available, "dispatch": "x11" if available else "none",
                "reason": "available_on_x11" if available else reason}

    async def _prepare_x11(self, enabled):
        """Probe only metadata/capabilities, never pixels, focus, or input.

        An actual task still starts its own backend after foreground admission and
        consent. This short-lived backend creates no devices and is fully drained
        before publication. Session settings are runtime-only, not persisted.
        """
        self._x11_ready = False
        if self._probe_backend is not None:
            self._native_reason = "x11_probe_cleanup_unverified"
            return
        if not enabled:
            self._native_reason = "computer_disabled"
            return
        if (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
                or os.environ.get("WAYLAND_DISPLAY")):
            self._native_reason = "wayland_computer_use_requires_1_1"
            return
        display = os.environ.get("DISPLAY", "")
        # Same explicit-local-display boundary as Odin's attached X11 backend.
        if not re.fullmatch(r":[0-9]{1,5}", display):
            self._native_reason = "local_x11_display_required"
            return
        backend = None
        try:
            environment = dict(os.environ)
            authority = environment.get("XAUTHORITY") or str(Path.home() / ".Xauthority")
            environment["XAUTHORITY"] = authority
            child = await asyncio.create_subprocess_exec(
                sys.executable, "-B", "-I", str(Path(__file__).with_name("x11_probe.py")),
                display, env=environment, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            try:
                output, _ = await asyncio.wait_for(child.communicate(), 5)
            finally:
                if child.returncode is None:
                    child.kill()
                await child.wait()
            if child.returncode != 0 or len(output) > 4096:
                raise RuntimeError("X11 discovery failed")
            names = json.loads(output)
            from ..computer.runtime.x11_attached import X11AttachedBackend

            backend = X11AttachedBackend(enabled=True, display_name=display,
                xauthority=authority, monitor_names=names, input_enabled=True)
            self._probe_backend = backend
            result = await asyncio.wait_for(backend.start("probe-" + uuid.uuid4().hex), 15)
            if result.get("ok") is not True:
                raise RuntimeError("X11 startup failed")
            cleanup = await backend.detach()
            if not (cleanup.get("stopped") and cleanup.get("released")
                    and cleanup.get("no_inflight_input")):
                raise RuntimeError("X11 probe cleanup incomplete")
            self._probe_backend = None
            integration = self._integration
            if integration is None:
                raise RuntimeError("X11 integration missing")
            runtime = deepcopy(integration.settings)
            runtime.platform, runtime.environment = "x11", "existing_session"
            runtime.display, runtime.xauthority, runtime.monitor_names = display, authority, names
            runtime.runtime_sudo = False
            integration.settings = runtime
            if self._backend_factory is None:
                self.controller.backend_factory = integration._backend
            self._x11_ready = True
            self._native_reason = "available_on_x11"
        except Exception:
            self._native_reason = "x11_backend_unavailable"
        finally:
            if backend is not None:
                cleanup = await backend.detach()
                if (cleanup.get("stopped") and cleanup.get("released")
                        and cleanup.get("no_inflight_input")):
                    self._probe_backend = None

    @property
    def management_methods(self):
        # An unavailable private store must not make the whole transport fail,
        # nor advertise cleanup/activation operations that it cannot perform.
        return self.METHODS if self._started and not self._closed else self.READ_METHODS

    @windows_variant("src.desktop.platform.windows_desktop:computer_binding_start")
    async def start(self):
        """Open private state and, when opted in, read-only native X11 readiness."""
        async with self._lifecycle:
            if self._closed:
                raise MethodError("capability_unavailable", "Computer management is closed")
            if self._started:
                return
            if self.controller is None:
                from ..computer.integration import ComputerIntegration

                try:
                    integration = ComputerIntegration(SimpleNamespace(config=self.settings.config))
                except ComputerError:
                    # Keep the copied storage fence. Do not chmod unrelated XDG
                    # ancestors, follow unsafe aliases or create a second store.
                    self._startup_error = "computer_storage_unavailable"
                    return
                self._integration = integration
                self.controller = integration.controller
            self.controller.authorize = self._authorize
            self.controller.enabled = bool(self.settings.config.computer.enabled)
            if self._backend_factory is not None:
                self.controller.backend_factory = self._backend_factory
            self._started = True
            await self._prepare_x11(self.controller.enabled)

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
        if method == "computer.status" and self._startup_error and not self._closed:
            return {"session": None, "readiness": self.readiness()}
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
            return {"session": {**result,
                                **({"input_supported": False,
                                    "input_readiness": "foreground_unavailable"}
                                   if not self.published_available else {})},
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
        """Only the opt-in flag is editable; native settings come from the session."""
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
                await service._prepare_x11(target)
                service._invalidate_catalog()
                return True

            async def rollback(self):
                # Restoration cannot resume a stopped task or restore its consent.
                await service.controller.set_enabled(old)
                await service._prepare_x11(old)
                service._invalidate_catalog()

        return Activation()

    def _invalidate_catalog(self):
        deps = getattr(getattr(self.core, "engine", None), "deps", None)
        catalog = getattr(deps, "tool_catalog", None)
        if catalog is not None:
            catalog.invalidate()

    async def close(self):
        async with self._lifecycle:
            if self._closed:
                return
            self._x11_ready = False
            if self._probe_backend is not None:
                cleanup = await self._probe_backend.detach()
                if not (cleanup.get("stopped") and cleanup.get("released")
                        and cleanup.get("no_inflight_input")):
                    raise RuntimeError("Computer X11 probe cleanup incomplete; runtime retained")
                self._probe_backend = None
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
