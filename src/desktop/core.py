"""Owner-authenticated conversation and management services with supervised lifetime."""
from __future__ import annotations

import asyncio
import inspect
import json
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from ..discord.turn_resume import TurnResumeManager
from ..permissions.manager import PermissionManager
from .artifacts import ArtifactStore, ResultReadError
from .attachments import AttachmentError, AttachmentService
from .authority import OwnerAuthority
from .commands import CommandJournal, JournalStorageError, JournalStore
from .controls import ControlService
from .conversations import ConversationError, ConversationStore
from .delivery import ArtifactPublisher, DurableDelivery, PublicationEventJournal
from .ipc import IpcServer
from .ipc_auth import load_token
from .lifecycle import CoreLifetime
from .management import ManagementService
from .paths import ProfilePaths
from .reports import ReportBinding, ReportDelivery, ReportService
from .requests import RequestService
from .resource_cleanup import ResourceCleanupJournal
from .search import TranscriptSearch
from .secrets import secret_call
from .services import build_engine_services
from .tool_details import ToolDetailsStore
from .transcript import TranscriptStore

VERSION = "0.1.0.dev1"
CONVERSATION_METHODS = frozenset({
    "conversations.list", "conversations.create", "conversations.update",
    "conversations.delete", "conversations.reset_context", "conversations.mark_read",
})
TRANSCRIPT_METHODS = frozenset({"messages.list", "conversation.snapshot"})
SEARCH_METHODS = frozenset({"search.query", "messages.around"})
ATTACHMENT_METHODS = frozenset({"attachments.begin", "attachments.chunk",
                                "attachments.commit", "attachments.cancel"})
RESULT_METHODS = frozenset({"artifacts.read", "tool.detail", "tool.output"})
CONTROL_METHODS = frozenset({"control.stop", "control.steer", "control.resume", "work.control"})
WORK_METHODS = frozenset({"work.list", "reports.page", "turn_state.list"})
SCHEDULE_METHODS = frozenset({"schedules.list", "schedules.save", "schedules.delete",
    "schedules.run", "schedules.reset_failures", "schedules.history", "schedules.validate_cron"})
CAPABILITIES = ("status.get", "events.subscribe", "runtime.shutdown",
                "submission.send", "notifications.ack",
                *sorted(CONVERSATION_METHODS | TRANSCRIPT_METHODS | SEARCH_METHODS
                        | ATTACHMENT_METHODS | RESULT_METHODS | CONTROL_METHODS
                        | WORK_METHODS | SCHEDULE_METHODS))
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


class _PublicationStore(JournalStore):
    """Wake publication after a root transaction containing event writes commits.

    SQLite is event-loop confined and transactions never cross an await.
    The rollback-safe delivery outbox, not this wake signal, owns event content.
    """

    def __init__(self, *args, committed, **kwargs):
        self._frames = None
        self._committed = committed
        super().__init__(*args, **kwargs)

    @contextmanager
    def transaction(self):
        outer = self._depth == 0
        if outer:
            self._frames = []
        frames = self._frames
        try:
            with super().transaction() as db:
                yield db
            if outer and frames:
                self._committed()
        finally:
            if outer:
                self._frames = None


class _CoreEvents(PublicationEventJournal):
    def _append(self, *args, **kwargs):
        frame = super()._append(*args, **kwargs)
        self.store._frames.append(frame)
        return frame


def profile_config(paths: ProfilePaths):
    """Profile-bound defaults without loading ambient files or credentials.

    An explicit config_provider may use this test/default-binding helper.
    Normal startup loads persisted settings through the profile settings owner.
    """
    from ..config import Config

    return Config.model_validate({
        "context": {"directory": str(paths.data_dir / "context")},
        "sessions": {"persist_directory": str(paths.data_dir / "sessions")},
        "tools": {
            "ssh_key_path": str(paths.secrets_dir / "id_ed25519"),
            "ssh_known_hosts_path": str(paths.secrets_dir / "known_hosts"),
            "audit_log_path": str(paths.data_dir / "audit.jsonl"),
            "trajectory_path": str(paths.data_dir / "trajectories"),
            "local_working_dir": str(paths.data_dir.parent.parent / "odin-desktop-workspaces"
                                     / paths.profile_id),
            "ssh_pool": {"socket_dir": str(paths.cache_dir / "ssh-sockets")},
        },
        "logging": {"directory": str(paths.data_dir / "logs")},
        "usage": {"directory": str(paths.data_dir / "usage")},
        "openai_codex": {"credentials_path": str(paths.secrets_dir / "codex_auth.json")},
        "search": {"search_db_path": str(paths.data_dir / "search")},
        "turn_state": {"db_path": str(paths.data_dir / "turn_state" / "turns.sqlite3")},
        "attachments": {"temp_directory": str(paths.cache_dir / "attachments")},
        "computer": {"storage_dir": str(paths.data_dir / "computer")},
    })


async def _resolve(value):
    return await value if inspect.isawaitable(value) else value


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
        "artifacts.read": {"ref": str, "offset": int, "length": int},
        "tool.detail": {"request_id": str, "invocation_id": str},
        "tool.output": {"cursor": str, "limit": int},
        "notifications.ack": {"dedupe_key": str, "outcome": str},
        "reports.page": {"report_id": str, "page": int},
        "work.control": {"control_command_id": str, "kind": str, "id": str, "action": str},
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
        *, release_runtime_on_close: bool = True, config_provider=None, runtime_provider=None,
        secret_backend=None,
    ) -> None:
        self.paths = paths
        self.socket_path = Path(socket_path)
        self.token_file = Path(token_file)
        self.phase = "starting"
        self.authority: OwnerAuthority | None = None
        self.store: JournalStore | None = None
        self.commands: CommandJournal | None = None
        self.events: PublicationEventJournal | None = None
        self.conversations: ConversationStore | None = None
        self.transcript: TranscriptStore | None = None
        self.search: TranscriptSearch | None = None
        self.server: IpcServer | None = None
        self.permissions: PermissionManager | None = None
        self.config_provider = config_provider
        self.runtime_provider = runtime_provider
        self.settings = None
        self.webhooks = None
        self.engine = None
        self.requests = None
        self.controls = None
        self.resume_manager = None
        self.delivery = None
        self.attachments = None
        self.artifacts = None
        self.tool_details = None
        self.work = None
        self.reports = None
        self.report_delivery = None
        self.schedules = None
        self.turn_state = None
        self.computer_foreground = None
        self.computer_unavailable_reason = None
        self.lifetime = CoreLifetime()
        self._serial = asyncio.Lock()
        self._closed = False
        self._quiescing_persisted = False
        self._release_runtime_on_close = release_runtime_on_close
        self._receipt_pruner: asyncio.Task | None = None
        self._publication_task: asyncio.Task | None = None
        self._publication_ready = asyncio.Event()
        self._published_seq = 0
        self.management: ManagementService | None = None
        self.resource_cleanup: ResourceCleanupJournal | None = None
        self._secret_backend = secret_backend
        self.capabilities = CAPABILITIES
        self.start_time = time.monotonic()
        # The admitted attachment service supplies the actual protocol limits.
        self.limits = {}

    def status(self) -> dict:
        if self.management is not None:
            return {
                **self.management.runtime.status(),
                "limits": self.limits,
                "diagnostics": self.engine.diagnostics(),
                "computer": {"published_available": False,
                             "reason": self.computer_unavailable_reason or "native_unqualified"},
            }
        return {
            "phase": self.phase,
            "core_instance_id": self.authority.runtime_id,
            "version": VERSION,
            "capabilities": list(self.capabilities),
            "limits": self.limits,
            "diagnostics": self.engine.diagnostics(),
            "computer": {"published_available": False,
                         "reason": self.computer_unavailable_reason or "native_unqualified"},
        }

    def welcome(self) -> dict:
        return {
            "core": {"instance_id": self.authority.runtime_id, "version": VERSION},
            "capabilities": list(self.capabilities),
            "features": [],
            "event_high": self.events.high,
        }

    async def start(self, stdin_fd: int = 0) -> None:
        # The app creates the credential. Validate it before bootstrap adopts any state.
        load_token(self.token_file)
        self.authority = OwnerAuthority(self.paths, app_bootstrap=True)
        self.authority.acquire_runtime()
        self.permissions = PermissionManager(self.authority)
        self.store = _PublicationStore(
            self.paths.data_dir / "transport.sqlite3", self.paths.profile_id,
            identity=f"{self.authority.installation_id}:{self.authority.owner_id}",
            committed=self._committed,
        )
        self.commands = CommandJournal(self.store)
        self.events = _CoreEvents(self.store)
        self.resource_cleanup = ResourceCleanupJournal(
            self.paths.data_dir / "resource-cleanup.json",
        )
        self.conversations = ConversationStore(self.store, self.events)
        self.transcript = TranscriptStore(self.store, self.events, self.conversations)
        self.search = TranscriptSearch(self.transcript, self.events)
        self.attachments = AttachmentService(
            self.store, self._require_attachment_conversation)
        self.limits = self.attachments.limits
        self.delivery = DurableDelivery(
            self.store, self.events, transcript_commit=self.transcript.commit,
            assert_context=self._assert_delivery_context)
        settings = ManagementService.profile_settings(
            self, secret_backend=self._secret_backend,
            config=(await _resolve(self.config_provider(self.paths))
                    if self.config_provider is not None else None))
        self.settings = settings
        await secret_call(settings.hydrate_secrets)
        runtime = (await _resolve(self.runtime_provider(self.config, self.paths, self.permissions))
                   if self.runtime_provider is not None else None)
        self.engine = build_engine_services(self.config, self.paths, self.permissions,
                                            delivery=self.delivery, runtime_context=runtime,
                                            settings=settings)
        executor = self.engine.deps.tool_executor
        output_store = executor._ensure_output_store()
        self.artifacts = ArtifactStore(self.store, output_store=output_store,
                                       authorize=executor._authorize_output,
                                       chunk_bytes=self.attachments.chunk_bytes)
        self.tool_details = ToolDetailsStore(self.store, output_store=output_store,
                                             artifacts=self.artifacts,
                                             authorize=executor._authorize_output)
        self.delivery.artifact_converter = ArtifactPublisher(self.artifacts, self.events)
        self.delivery.tool_details = self.tool_details
        self.requests = RequestService(
            self.store, self.conversations, self.transcript, engine=self.engine,
            permissions=self.permissions, authority=self.authority, delivery=self.delivery,
            attachments=self.attachments)
        self.engine.bind_requests(self.requests)
        deps = self.engine.deps
        if deps.turn_store is not None:
            self.resume_manager = TurnResumeManager(
                store=deps.turn_store, tool_loop=self.engine.runner, llm_gateway=deps.llm_gateway,
                channel_state=deps.channel_state, sessions=deps.sessions, delivery=self.delivery,
                permissions=self.permissions, tool_catalog=deps.tool_catalog,
                get_config=deps.get_config, fetch_message=self.requests.fetch_message,
                assert_preserved_request=self.requests.assert_preserved_request,
                auto_resume_enabled=self.config.turn_state.auto_resume,
                resume_ttl_hours=self.config.turn_state.resume_ttl_hours,
                launch_auto_resume=self.requests.launch_auto_resume)
            self.engine.runner._on_turn_suspended = self.resume_manager.on_turn_suspended
        self.controls = ControlService(
            self.store, self.events, self.requests, deps.channel_state,
            authority=self.authority, permissions=self.permissions,
            resume_manager=self.resume_manager)
        self._bind_background_services()
        self.conversations.delete_hooks += (
            self._require_no_scheduled_destination,
            self.requests.delete_conversation, self.delivery.delete_conversation,
            self.artifacts.delete_conversation, self.tool_details.delete_conversation,
            self.reports.delete_conversation,
            lambda cid: self.attachments.delete_conversation(self.store.connection, cid),
        )
        self.requests.recover_interrupted()
        self.controls.recover_after_restart()
        await self.schedules.recover()
        await self.delivery.recover()
        self.management = ManagementService.compose(self, settings=settings)
        from .webhooks import WebhookIngress
        self.webhooks = WebhookIngress(settings, self.engine.deps.scheduler,
            self.store, self.transcript, owner_id=self.authority.owner_id,
            admitting=lambda: self.lifetime.admitting and self.phase == "ready",
            permissions=self.permissions)
        self.schedules.ingress = self.webhooks
        settings.ingress = self.webhooks
        await self.webhooks.recover()
        # Compose-time test injection shares this same settings owner. All
        # hydration and startup vault reads remain off the event loop.
        await secret_call(settings.hydrate_secrets)
        await self.engine.initialize_profile_provider()
        self.capabilities = (*CAPABILITIES[:5],
                             *sorted((set(CAPABILITIES) | set(self.management.methods))
                                     - set(CAPABILITIES[:5])))
        self.server = IpcServer(
            self.socket_path, self.token_file, self.paths.profile_id,
            self.authority, self.welcome, self.dispatch,
        )
        self.lifetime.watch_parent(stdin_fd)
        self.lifetime.watch_signals()
        self.phase = "ready"
        async with self._serial:
            self.commands.prune(time.time() - RECEIPT_RETENTION)
            await self._status_event()
            await self._flush_publications()
        # Hydration/status now await workers. Commit the initial event before
        # admitting any handshake, preserving welcome/catch-up's high watermark.
        await self.server.start()
        self._receipt_pruner = asyncio.create_task(self._prune_receipts())
        self._publication_task = asyncio.create_task(self._publication_loop())
        schedule_owner = self.authority.authenticate_local(peer_uid=self.authority.owner_uid)
        schedule_token = self.permissions.set_request_owner(schedule_owner)
        try:
            # The real scheduler task inherits sealed installation authority,
            # not whichever IPC connection happened to open the window.
            self.engine.deps.scheduler.start(self._scheduled_handlers._on_scheduled_task,
                self._scheduled_handlers._on_schedule_failure)
        finally:
            self.permissions.reset_request_owner(schedule_token)
        await self.requests.after_commit()
        await self.webhooks.start()

    def _bind_background_services(self):
        from ..discord.scheduled_events import ScheduledEventHandlers, ScheduledEventsDeps
        from .computer_binding import create_foreground
        from .schedules import ScheduleService
        from .turn_state import TurnStateService
        from .work import WorkService

        deps = self.engine.deps
        self.schedules = ScheduleService(deps.scheduler, authority=self.authority,
            conversations=self.conversations, assert_request=self.requests.assert_bound_request)
        self.work = WorkService(self.store, self.events, authority=self.authority,
            permissions=self.permissions, requests=self.requests, conversations=self.conversations,
            agents=deps.agent_manager, tasks=deps.channel_state.background_tasks,
            loops=deps.loop_manager, processes=deps.tool_executor._ensure_process_registry(),
            scheduler=deps.scheduler, display_config=self.settings, controls=self.controls)
        self.controls.work = self.work
        self.work.authorize_process = self._authorize_process
        self.reports = ReportService(self.store, events=self.events,
            authorize=self._authorize_stored_report, assert_binding=self._assert_report_binding)
        self.report_delivery = ReportDelivery(self.reports, self.delivery)
        deps.scheduler.set_known_report_formats_provider(lambda: self.reports.registry.formats)
        self.turn_state = TurnStateService(self.permissions, self.authority,
            store_provider=lambda: deps.turn_store,
            # Restart-only desired config must not hide the retained live ledger.
            enabled=lambda: deps.durability_reason != "disabled_by_config")
        from ..computer.provisioning import ComputerProvisioningError

        try:
            self.computer_foreground = create_foreground(self.requests, self.config)
        except ComputerProvisioningError as error:
            # Computer storage has stricter retained native requirements than
            # the profile transport. Do not weaken those, chmod the profile, or
            # break ordinary chat because an unqualified subsystem cannot start.
            self.computer_unavailable_reason = error.code
        if self.computer_foreground is not None:
            self.requests.computer_foreground = self.computer_foreground
            deps.native_owners["computer"] = self.computer_foreground
        agents = deps.native_owners["agents"]
        agents._background_admission = self.requests
        agents._work_service = self.work
        agents._publish_background = self._publish_background
        deps.tool_executor.system_tools._desktop_process_admitted = self._register_process
        deps.tool_executor.system_tools._desktop_process_control = self._control_process
        scheduling = deps.native_owners["scheduling"]
        scheduling.service_provider = lambda: self.schedules
        scheduling.request_provider = lambda message=None: (
            message if message is not None else self.requests.current_bound_request())
        self._scheduled_handlers = ScheduledEventHandlers(ScheduledEventsDeps(
            get_config=deps.get_config, tool_executor=deps.tool_executor, audit=deps.audit,
            llm_gateway=deps.llm_gateway, tool_loop=self.engine.runner, agent_task_tools=agents,
            host_registry=deps.host_registry, admit_schedule=self._admit_schedule,
            publish_notice=self._publish_scheduled_notice,
            publish_report=self._publish_scheduled_report,
            admit_notice=self._admit_schedule_notice,
            dispatch_tool=self._dispatch_scheduled_tool))
        from ..scheduler.scheduler import ConnectionAvailability, ConnectionReason

        deps.scheduler.set_connection_state_provider(lambda: ConnectionAvailability(
            self.lifetime.admitting and self.phase == "ready" and
            self.permissions.is_owner(self.authority.owner_id),
            ConnectionReason.AVAILABLE if self.phase == "ready" and self.lifetime.admitting
            else ConnectionReason.UNAVAILABLE, 1))
        deps.background_work_ready = True
        deps.tool_catalog.invalidate()

    def _authorize_stored_report(self, _tool, _hosts, owner):
        # D17 durable report pages are stored receipts, not live evidence cursors.
        return owner == self.authority.owner_id and self.permissions.is_owner(owner)

    def _require_no_scheduled_destination(self, cid):
        if any(item.get("channel_id") == cid for item in self.engine.deps.scheduler.list_all()):
            raise ConversationError("busy", "Conversation is a scheduled work destination",
                                    "not_dispatched")

    def _assert_report_binding(self, binding: ReportBinding):
        row = self.requests.binding(binding.conversation_id, binding.request_id, binding.generation)
        background = self.store.connection.execute(
            "SELECT run_id FROM desktop_background_requests WHERE request_id=?",
            (binding.request_id,)).fetchone()
        if row is None or row["owner"] != binding.owner_id or background is None:
            raise PermissionError("Report requires an admitted background run")
        if background["run_id"] != binding.run_id:
            raise PermissionError("Report run identity differs from admission")

    @asynccontextmanager
    async def _admit_schedule(self, schedule, *, notice_id=None):
        deps = self.engine.deps
        binding = deps.scheduler.assert_run_binding(schedule)
        cid, owner = binding["conversation_id"], binding["owner_id"]
        self.conversations.get(cid)
        run_id = binding["run_id"] if notice_id is None else binding["run_id"] + ":" + notice_id
        if notice_id is None:
            self.work.register_schedule(schedule)
        message = self.requests._register_background("schedule", run_id,
            schedule.get("description", "Scheduled work"), cid, owner)
        async with self.requests.background_execution(message):
            yield message

    def _admit_schedule_notice(self, schedule, consecutive):
        return self._admit_schedule(schedule, notice_id=f"failure:{consecutive}")

    async def _publish_scheduled_notice(self, message, text):
        return await self.delivery.send(message.channel, text)

    async def _publish_background(self, message, text, kind=None):
        self.requests.assert_bound_request(message)
        return await self.delivery.send(message.channel, text)

    def _register_process(self, info):
        message = self.requests.current_bound_request()
        return self.work.register("process", info.pid, message)

    def _authorize_process(self, info):
        from ..tools.output_authorization import (
            host_binding,
            request_host_authorizer,
            request_scope_id,
            tool_scope_allows,
        )

        executor = self.engine.deps.tool_executor
        alias = info.host_alias or info.host
        target = executor.host_registry.get(alias, targetable_only=True)
        live_hosts = request_host_authorizer.get()
        return bool(info.owner_id == self.authority.owner_id and
            self.permissions.is_owner(info.owner_id) and tool_scope_allows("manage_process") and
            not executor.check_permission("manage_process", info.owner_id) and
            info.scope_id == request_scope_id.get() and
            (live_hosts is None or live_hosts(alias)) and target is not None and
            host_binding(target) == info.host_binding and
            (executor._host_access is None or executor._host_access.is_host_allowed(
                info.owner_id, alias)))

    async def _control_process(self, pid):
        message = self.requests.current_bound_request()
        result = await self.work.control_native(message, "process", str(pid), "stop")
        return result if isinstance(result, str) else json.dumps(result)

    async def _dispatch_scheduled_tool(self, message, tool_name, tool_input):
        self.requests.assert_request(message)
        return await self.engine.runner.dispatch_loop_tool(
            tool_name, tool_input, message, message.owner_id)

    async def _publish_scheduled_report(self, message, report_format, output, tool_name):
        self.requests.assert_bound_request(message)
        row = self.store.connection.execute(
            "SELECT run_id FROM desktop_background_requests WHERE request_id=?",
            (message.request_id,)).fetchone()
        binding = ReportBinding(message.owner_id, message.conversation_id, message.request_id,
            row[0], message.generation, tool_name)
        return await self.report_delivery.publish_output(output, report_format=report_format,
            binding=binding, tool=tool_name)

    @property
    def config(self):
        return self.settings.config if self.settings is not None else None

    def _assert_delivery_context(self, context):
        if self.requests is None:
            raise PermissionError("Delivery requires the admitted request service")
        self.requests.assert_delivery_context(context)

    def _require_attachment_conversation(self, _db, cid):
        # No nested domain transaction: its exception would poison the upload
        # transaction before AttachmentService can persist a typed refusal.
        try:
            return self.conversations._row(cid)
        except ConversationError as error:
            raise AttachmentError(error.code, str(error), error.disposition) from None

    def _committed(self):
        self._publication_ready.set()

    async def _flush_publications(self):
        # The journal trigger captures every frame in the originating domain
        # transaction, even with max_events=0. Savepoint rollback removes it.
        # IPC is volatile: don't mark the durable sink's records as delivered.
        while True:
            row = self.store.connection.execute(
                "SELECT event_seq,payload FROM desktop_delivery_outbox "
                "WHERE event_seq>? ORDER BY event_seq LIMIT 1", (self._published_seq,)
            ).fetchone()
            if row is None:
                break
            await self._publish(json.loads(row["payload"]))
            self._published_seq = row["event_seq"]
        self._publication_ready.clear()

    async def _publication_loop(self):
        try:
            while True:
                await self._publication_ready.wait()
                async with self._serial:
                    await self._flush_publications()
        except JournalStorageError:
            self.lifetime.request_stop("storage_unavailable")

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
        status = (await self.management.runtime.status_async()
                  if self.management is not None else self.status())
        status.update(limits=self.limits, diagnostics=self.engine.diagnostics(),
                      computer={"published_available": False,
                                "reason": self.computer_unavailable_reason or "native_unqualified"})
        self.events.append(
            "runtime.status", {"kind": "runtime", "id": self.authority.runtime_id}, status,
        )
        await self._flush_publications()

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
            elif method == "submission.send":
                return self.requests.handle(method, params)
            elif method in ATTACHMENT_METHODS:
                return self.attachments.handle(method, params)
            elif method == "notifications.ack":
                return self.delivery.notifications.handle(method, params)
            elif method == "work.list":
                result = self.work.list(params)
                return result if "ok" in result else {"ok": True, "result": result}
            elif method == "reports.page":
                result = self.reports.handle(method, params, owner=self.authority.owner_id)
            elif method in RESULT_METHODS:
                owner = self.authority.owner_id
                if method == "artifacts.read":
                    result = self.artifacts.read(**params, owner=owner)
                elif method == "tool.detail":
                    result = self.tool_details.detail(**params, owner=owner)
                else:
                    result = self.tool_details.output(**params, owner=owner)
            else:
                return failure("capability_unavailable", "Service is not available yet")
            return {"ok": True, "result": result}
        except ConversationError as error:
            return error.response()
        except ResultReadError as error:
            return failure(error.code, str(error))
        except TypeError:
            return failure("bad_request", "Invalid method parameters")

    async def dispatch(self, connection, request: dict) -> dict | None:
        owner = self.permissions.set_request_owner(connection.owner_context)
        committed = []
        try:
            if request["method"] in SCHEDULE_METHODS | {"turn_state.list"}:
                async def invoke_service():
                    if not self.permissions.is_owner(self.authority.owner_id):
                        return failure("unauthorized",
                                       "Current profile owner authority is required")
                    if not self.lifetime.admitting and request["method"] not in READ_METHODS:
                        return failure("busy", "Core is quiescing")
                    try:
                        if request["method"] == "turn_state.list":
                            value = await self.turn_state.handle(
                                request["method"], request["params"])
                        else:
                            value = await self.schedules.invoke(
                                request["method"], request["params"],
                                owner=connection.owner_context)
                            for schedule in self.engine.deps.scheduler.list_all():
                                if schedule.get("requester_id") == self.authority.owner_id:
                                    self.work.register_schedule(schedule)
                        return {"ok": True, "result": value}
                    except ConversationError as error:
                        return error.response()
                    except PermissionError:
                        return failure("unauthorized",
                                       "Current profile owner authority is required")
                    except (TypeError, ValueError):
                        return failure("bad_request", "Invalid method parameters")

                if request["method"] in READ_METHODS:
                    result = self.commands.check(
                        request["id"], request["method"], request["params"])
                    if result is None or result.get("error", {}).get("code") != "id_conflict":
                        result = await invoke_service()
                else:
                    result = await self.commands.execute_async(request["id"], request["method"],
                        request["params"], invoke_service)
                async with self._serial:
                    await self._flush_publications()
                return {"t": "res", "id": request["id"], **result}
            if request["method"] in CONTROL_METHODS or request["method"] == "submission.send":
                async def admit_control():
                    invalid = validate_params(request["method"], request["params"])
                    if invalid:
                        return invalid
                    if not self.lifetime.admitting:
                        return failure("busy", "Core is quiescing")
                    if request["method"] == "submission.send":
                        return await self.requests.handle_async(
                            request["method"], request["params"], controls=self.controls)
                    return await self.controls.dispatch(request["method"], request["params"])

                result = await self.commands.execute_async(
                    request["id"], request["method"], request["params"], admit_control)
                if request["method"] == "submission.send":
                    await self._after_command_commit(request["method"], request["params"], result)
                async with self._serial:
                    await self._flush_publications()
                return {"t": "res", "id": request["id"], **result}
            response = await self._dispatch(connection, request, committed=committed)
            # Fresh commands alone run this seam, after journal/event commit
            # and outside _serial. Step four can attach asynchronous controls
            # without blocking reads or Stop behind engine/provider effects.
            for method, params, result in committed:
                await self._after_command_commit(method, params, result)
            return response
        finally:
            self.permissions.reset_request_owner(owner)

    async def _after_command_commit(self, method, params, result):
        if method == "submission.send" and result.get("ok") and self.lifetime.admitting:
            await self.requests.after_commit()

    async def _dispatch(self, connection, request: dict, *, committed=None) -> dict | None:
        async with self._serial:
            command_id, method, params = request["id"], request["method"], request["params"]
            if not self.permissions.is_owner(self.authority.owner_id):
                raise PermissionError("profile owner authority is no longer current")
            # Existing identities win even if their method is no longer served.
            # Unknown capabilities must not reserve IDs or persist refusal bodies.
            fresh_read = (method in READ_METHODS or method == "attachments.chunk"
                          or (self.management is not None
                              and method in self.management.read_methods))
            try:
                bound = (self.management.check(command_id, method, params)
                         if self.management is not None
                         else self.commands.check(command_id, method, params))
            except (ValueError, TypeError, RecursionError):
                return {"t": "res", "id": command_id, **failure(
                    "bad_request", "Expected finite JSON parameters",
                )}
            # Existing command IDs still conflict with differently-bound reads.
            # A read/chunk result itself is never replayed from a receipt.
            if bound is not None and (not fresh_read
                                      or bound.get("error", {}).get("code") == "id_conflict"):
                return {"t": "res", "id": command_id, **bound}
            if method not in self.capabilities:
                return {"t": "res", "id": command_id, **failure(
                    "capability_unavailable", "Service is not available yet",
                )}
            if method == "events.subscribe":
                invalid = validate_params(method, params)
                if invalid:
                    return {"t": "res", "id": command_id, **invalid}
                await self._flush_publications()
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
            if method == "status.get":
                result = validate_params(method, params)
                if result is None:
                    if self.management is not None:
                        await self.management.runtime.status_async()
                    result = {"ok": True, "result": self.status()}
                return {"t": "res", "id": command_id, **result}
            if self.management is not None and method in self.management.methods:
                if method in self.management.read_methods:
                    result = await self.management.invoke(method, params)
                elif not self.lifetime.admitting:
                    result = failure("busy", "Core is quiescing")
                else:
                    result = await self.management.execute(
                        command_id, method, params,
                        unlock_serial=self._serial if method == "secrets.unlock" else None,
                    )
                return {"t": "res", "id": command_id, **result}
            if method in READ_METHODS:
                result = validate_params(method, params)
                if result is None:
                    if method == "status.get":
                        result = {"ok": True, "result": self.status()}
                    else:
                        result = self._domain(method, params)
                return {"t": "res", "id": command_id, **result}

            if method == "attachments.chunk":
                result = (self.attachments.handle(method, params) if self.lifetime.admitting
                          else failure("busy", "Core is quiescing"))
                return {"t": "res", "id": command_id, **result}

            fresh_shutdown = False
            fresh_command = False

            def execute() -> dict:
                nonlocal fresh_shutdown, fresh_command
                fresh_command = True
                invalid = validate_params(method, params)
                if invalid:
                    return invalid
                if not self.lifetime.admitting:
                    return failure("busy", "Core is quiescing")
                if method == "runtime.shutdown":
                    fresh_shutdown = True
                    self.events.append(
                        "runtime.status", {"kind": "runtime", "id": self.authority.runtime_id},
                        {**self.status(), "phase": "quiescing"},
                    )
                    return {"ok": True, "result": {"disposition": "accepted"}}
                return self._domain(method, params)

            result = self.commands.execute(command_id, method, params, execute)
            if fresh_command and committed is not None:
                committed.append((method, params, result))
            response = {"t": "res", "id": command_id, **result}
            if fresh_shutdown and result.get("ok"):
                # Only new acceptance is an effect. Replayed receipt never stops a new runtime.
                self.phase = "quiescing"
                self._quiescing_persisted = True
                self.lifetime.request_stop("runtime.shutdown")
                try:
                    await connection.send(response)
                finally:
                    await self._flush_publications()
                return None
            # Publish only after the domain, event and receipt transaction committed.
            # A duplicate receipt has appended nothing and cannot repeat an event.
            await self._flush_publications()
            return response

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.lifetime.request_stop("startup_failed")
        self.lifetime.close()
        try:
            if self.webhooks is not None:
                await self.webhooks.close()
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
            # Failed cleanup must not release ownership beneath a surviving
            # execution task. The caller's containment exit remains the barrier.
            try:
                if self.resume_manager is not None:
                    await self.resume_manager.close()
                if self.requests is not None:
                    if self.engine is not None:
                        await self.engine.deps.scheduler.stop()
                    await self.requests.close()
                if self.engine is not None:
                    try:
                        await self.engine.close()
                    except Exception:
                        # Requests are settled, but execution cleanup failed.
                        # Persist its uncertainty and attempt independent
                        # management cleanup without releasing graph ownership.
                        self._engine_cleanup_failed = True
                        try:
                            if self.management is not None:
                                await self.management.close()
                            elif self.resource_cleanup is not None:
                                self.resource_cleanup.finish({
                                    **getattr(self.engine, "execution_cleanup_results", {}),
                                    "engine_services": {"state": "unknown"},
                                })
                        except Exception:
                            pass  # The original engine failure remains authoritative.
                        raise
            finally:
                if self._publication_task is not None:
                    self._publication_task.cancel()
                    try:
                        await self._publication_task
                    except asyncio.CancelledError:
                        pass
            try:
                try:
                    if self.management is not None:
                        await self.management.close()
                finally:
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
