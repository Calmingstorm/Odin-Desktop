"""Owner-authenticated durable services and app-supervised core lifetime."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from ..permissions.manager import PermissionManager
from .authority import OwnerAuthority
from .commands import CommandJournal, JournalStorageError, JournalStore
from .conversations import ConversationError, ConversationStore
from .events import EventJournal
from .ipc import IpcServer
from .ipc_auth import load_token
from .lifecycle import CoreLifetime
from .paths import ProfilePaths
from .search import TranscriptSearch
from .transcript import TranscriptStore

VERSION = "0.1.0.dev1"
CONVERSATION_METHODS = frozenset({
    "conversations.list", "conversations.create", "conversations.update",
    "conversations.delete", "conversations.reset_context", "conversations.mark_read",
})
TRANSCRIPT_METHODS = frozenset({"messages.list", "conversation.snapshot"})
SEARCH_METHODS = frozenset({"search.query", "messages.around"})
CAPABILITIES = ("status.get", "events.subscribe", "runtime.shutdown",
                *sorted(CONVERSATION_METHODS | TRANSCRIPT_METHODS | SEARCH_METHODS))
READ_METHODS = frozenset({
    "status.get", "events.subscribe", "conversations.list", "messages.list",
    "conversation.snapshot", "usage.get", "work.list", "settings.schema", "search.query",
    # Pending minor-3 protocol names, not invented aliases or promised capabilities.
    "messages.around", "artifacts.read", "reports.page", "tool.detail", "tool.output",
    "codex.accounts.list", "models.agents.get", "models.discover", "personality.get",
    "tools.list", "tools.timeouts.get", "skills.list", "skills.get", "skills.config.get",
    "mcp.list", "mcp.status", "mcp.tools", "webhooks.outbound.list",
    "hosts.list", "hosts.references", "schedules.list", "schedules.history",
    "schedules.validate_cron", "memory.list", "memory.get", "lists.list", "lists.get",
    "knowledge.list", "knowledge.search", "knowledge.versions", "audit.query",
    "audit.verify", "health.get", "logs.search", "turn_state.list", "computer.status",
})
# Receipt bodies are bounded by age; identities and unresolved outcomes are not.
RECEIPT_RETENTION = 7 * 24 * 60 * 60
RECEIPT_PRUNE_INTERVAL = 60 * 60


def failure(code: str, message: str) -> dict:
    return {"ok": False, "error": {
        "code": code, "message": message, "disposition": "rejected",
    }}


def validate_params(method: str, params: object) -> dict | None:
    """Typed service validation is a command result, not a framing disconnect."""
    if not isinstance(params, dict):
        return failure("bad_request", "Method params must be an object")
    if method == "events.subscribe" and "after" not in params:
        return failure("bad_request", "Missing parameter: after")
    required = {
        "runtime.shutdown": {"reason": str},
        "conversations.update": {"id": str, "expected_rev": int},
        "messages.list": {"conversation_id": str, "limit": int},
        "conversation.snapshot": {"conversation_id": str},
        "submission.send": {"client_submission_id": str, "conversation_id": str, "text": str},
        "control.stop": {
            "control_command_id": str, "conversation_id": str,
            "request_id": str, "generation": int,
        },
        "control.steer": {
            "control_command_id": str, "conversation_id": str,
            "request_id": str, "generation": int, "text": str,
        },
    }
    optional = {
        "events.subscribe": {"after": (str, type(None))},
        "conversations.create": {"title": str, "parent_id": (str, type(None))},
        "conversations.update": {"title": str, "archived": bool},
        "messages.list": {"before": (str, type(None))},
        "conversation.snapshot": {"limit": int},
    }
    for key, expected in required.get(method, {}).items():
        if key not in params or type(params[key]) is not expected:
            return failure("bad_request", f"Invalid or missing parameter: {key}")
    for key, expected in optional.get(method, {}).items():
        if key in params:
            types = expected if isinstance(expected, tuple) else (expected,)
            if type(params[key]) not in types:
                return failure("bad_request", f"Invalid parameter: {key}")
    if method in {"messages.list", "conversation.snapshot"} and "limit" in params:
        if not 1 <= params["limit"] <= 100:
            return failure("bad_request", "limit must be between 1 and 100")
    return None


class CoreService:
    """One lifetime profile owner, one journal store, one listener."""

    def __init__(
        self, paths: ProfilePaths, socket_path: Path, token_file: Path,
        *, release_runtime_on_close: bool = True,
    ) -> None:
        self.paths = paths
        self.socket_path = Path(socket_path)
        self.token_file = Path(token_file)
        self.phase = "starting"
        self.authority: OwnerAuthority | None = None
        self.store: JournalStore | None = None
        self.commands: CommandJournal | None = None
        self.events: EventJournal | None = None
        self.conversations: ConversationStore | None = None
        self.transcript: TranscriptStore | None = None
        self.search: TranscriptSearch | None = None
        self.server: IpcServer | None = None
        self.permissions: PermissionManager | None = None
        self.lifetime = CoreLifetime()
        self._serial = asyncio.Lock()
        self._closed = False
        self._quiescing_persisted = False
        self._release_runtime_on_close = release_runtime_on_close
        self._receipt_pruner: asyncio.Task | None = None

    def status(self) -> dict:
        return {
            "phase": self.phase,
            "core_instance_id": self.authority.runtime_id,
            "version": VERSION,
            "capabilities": list(CAPABILITIES),
        }

    def welcome(self) -> dict:
        return {
            "core": {"instance_id": self.authority.runtime_id, "version": VERSION},
            "capabilities": list(CAPABILITIES),
            "features": [],
            "event_high": self.events.high,
        }

    async def start(self, stdin_fd: int = 0) -> None:
        # The app creates the credential. Validate it before bootstrap adopts any state.
        load_token(self.token_file)
        self.authority = OwnerAuthority(self.paths, app_bootstrap=True)
        self.authority.acquire_runtime()
        self.permissions = PermissionManager(self.authority)
        self.store = JournalStore(
            self.paths.data_dir / "transport.sqlite3", self.paths.profile_id,
            identity=f"{self.authority.installation_id}:{self.authority.owner_id}",
        )
        self.commands = CommandJournal(self.store)
        self.events = EventJournal(self.store)
        self.conversations = ConversationStore(self.store, self.events)
        self.transcript = TranscriptStore(self.store, self.events, self.conversations)
        self.search = TranscriptSearch(self.transcript, self.events)
        self.server = IpcServer(
            self.socket_path, self.token_file, self.paths.profile_id,
            self.authority, self.welcome, self.dispatch,
        )
        self.lifetime.watch_parent(stdin_fd)
        self.lifetime.watch_signals()
        await self.server.start()
        self.phase = "ready"
        async with self._serial:
            self.commands.prune(time.time() - RECEIPT_RETENTION)
            await self._status_event()
        self._receipt_pruner = asyncio.create_task(self._prune_receipts())

    async def _prune_receipts(self) -> None:
        """Serialize periodic retention with admission, and fail closed on storage loss."""
        try:
            while self.lifetime.admitting:
                await asyncio.sleep(RECEIPT_PRUNE_INTERVAL)
                async with self._serial:
                    if not self.lifetime.admitting:
                        return
                    self.commands.prune(time.time() - RECEIPT_RETENTION)
        except JournalStorageError:
            self.lifetime.request_stop("storage_unavailable")

    async def _status_event(self) -> None:
        event = self.events.append(
            "runtime.status", {"kind": "runtime", "id": self.authority.runtime_id}, self.status(),
        )
        await self._publish(event)

    async def _publish(self, event: dict) -> None:
        await self.server.publish(event)

    def _domain(self, method: str, params: dict) -> dict:
        try:
            if method in CONVERSATION_METHODS:
                result = self.conversations.handle(method, params)
            elif method in TRANSCRIPT_METHODS:
                result = self.transcript.handle(method, params)
            elif method in SEARCH_METHODS:
                result = self.search.handle(method, params)
            else:
                return failure("capability_unavailable", "Service is not available yet")
            return {"ok": True, "result": result}
        except ConversationError as error:
            return error.response()

    async def dispatch(self, connection, request: dict) -> dict | None:
        owner = self.permissions.set_request_owner(connection.owner_context)
        try:
            return await self._dispatch(connection, request)
        finally:
            self.permissions.reset_request_owner(owner)

    async def _dispatch(self, connection, request: dict) -> dict | None:
        async with self._serial:
            command_id, method, params = request["id"], request["method"], request["params"]
            if not self.permissions.is_owner(self.authority.owner_id):
                raise PermissionError("profile owner authority is no longer current")
            # Existing identities win even if their method is no longer served.
            # Unknown capabilities must not reserve IDs or persist refusal bodies.
            bound = self.commands.check(command_id, method, params)
            if bound is not None:
                return {"t": "res", "id": command_id, **bound}
            if method not in CAPABILITIES:
                return {"t": "res", "id": command_id, **failure(
                    "capability_unavailable", "Service is not available yet",
                )}
            if method == "events.subscribe":
                invalid = validate_params(method, params)
                if invalid:
                    return {"t": "res", "id": command_id, **invalid}
                reset, high, frames = self.events.catchup(params.get("after"))
                await connection.send({
                    "t": "res", "id": command_id, "ok": True,
                    "result": {"event_high": high, "reset_required": reset},
                })
                # Publication and catch-up share this lock; there is no replay/live gap.
                connection.subscribed = True
                connection.event_seq = int(high)
                for frame in frames:
                    if not self.permissions.is_owner(self.authority.owner_id):
                        raise PermissionError("profile owner authority is no longer current")
                    await connection.send(frame)
                return None
            if method in READ_METHODS:
                result = validate_params(method, params)
                if result is None:
                    if method == "status.get":
                        result = {"ok": True, "result": self.status()}
                    else:
                        result = self._domain(method, params)
                return {"t": "res", "id": command_id, **result}

            fresh_shutdown = False
            shutdown_event = None
            before = self.events.high

            def execute() -> dict:
                nonlocal fresh_shutdown, shutdown_event
                invalid = validate_params(method, params)
                if invalid:
                    return invalid
                if not self.lifetime.admitting:
                    return failure("busy", "Core is quiescing")
                if method == "runtime.shutdown":
                    fresh_shutdown = True
                    shutdown_event = self.events.append(
                        "runtime.status", {"kind": "runtime", "id": self.authority.runtime_id},
                        {**self.status(), "phase": "quiescing"},
                    )
                    return {"ok": True, "result": {"disposition": "accepted"}}
                return self._domain(method, params)

            result = self.commands.execute(command_id, method, params, execute)
            response = {"t": "res", "id": command_id, **result}
            if fresh_shutdown and result.get("ok"):
                # Only new acceptance is an effect. Replayed receipt never stops a new runtime.
                self.phase = "quiescing"
                self._quiescing_persisted = True
                self.lifetime.request_stop("runtime.shutdown")
                try:
                    await connection.send(response)
                finally:
                    await self._publish(shutdown_event)
                return None
            # Publish only after the domain, event and receipt transaction committed.
            # A duplicate receipt has appended nothing and cannot repeat an event.
            for event in self.events.between(before):
                await self._publish(event)
            return response

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.lifetime.request_stop("startup_failed")
        self.lifetime.close()
        try:
            if self._receipt_pruner is not None:
                self._receipt_pruner.cancel()
                try:
                    await self._receipt_pruner
                except asyncio.CancelledError:
                    pass
            if self.server is not None:
                await self.server.close_listener()
                try:
                    try:
                        await asyncio.wait_for(self._serial.acquire(), 5)
                    except TimeoutError:
                        # An unresponsive replay client cannot retain profile ownership.
                        # Cancel connection dispatch before touching persistence beneath it.
                        await self.server.shutdown()
                        await self._serial.acquire()
                    try:
                        if self.events is not None and not self._quiescing_persisted:
                            self.phase = "quiescing"
                            await self._status_event()
                    finally:
                        self._serial.release()
                finally:
                    await self.server.shutdown()
        finally:
            try:
                if self.store is not None:
                    self.store.close()
            finally:
                if self._release_runtime_on_close:
                    self.release_runtime()

    def release_runtime(self) -> None:
        """Entry may defer owner release until its containment finalization barrier."""
        if self.authority is not None:
            self.authority.release_runtime()

    async def run(self, stdin_fd: int = 0) -> int:
        try:
            await self.start(stdin_fd)
            await self.lifetime.wait()
            return 0
        finally:
            await self.close()


async def run_core(
    paths: ProfilePaths, socket_path: Path, token_file: Path, stdin_fd: int = 0,
) -> int:
    """Entry seam; process containment and finalization remain in the caller."""
    return await CoreService(paths, socket_path, token_file).run(stdin_fd)
