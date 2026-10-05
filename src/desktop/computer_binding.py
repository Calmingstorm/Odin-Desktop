"""Admitted foreground lineage for the retained computer facade.

This is the step-6B seam, composed with step-6A's management service by
``bind_foreground``. Management and model input remain different identities.
Neither constructing a RequestContext nor possessing an IPC token grants input.
Native qualification, vision, consent, freshness and release remain downstream.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from types import SimpleNamespace

from ..computer.integration import ComputerIntegration, _grant
from ..computer.models import RequestContext
from ..tools.output_authorization import tool_scope_allows


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
        self.controller.authorize = self._authorize

    @property
    def published_available(self):
        # An exercised stub binding is not platform or accessibility evidence.
        return False

    def enter_request(self, message):
        self.requests.assert_request(message)
        if self._background(message):
            raise PermissionError("Background work cannot acquire foreground computer authority")
        if self._requests.get() is not None:
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
    Its published_available/readiness remain unqualified; binding is not proof
    of a working platform. Dependency resolver placement remains worker-only.
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
