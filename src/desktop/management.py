"""Named profile management and durable, non-replayed asynchronous effects.

Transport authentication supplies authority. This module supplies no Python,
shell or HTTP passthrough. Domain services validate their own Odin-shaped bodies.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import os
import secrets as random_secrets
import stat
import time
from types import SimpleNamespace
from typing import Any

from .commands import JournalStorageError, canonical_json, response_error
from .secrets import secret_call


def _binding_key(paths) -> bytes:
    """Stable transport identity key, not a provider credential or vault fallback."""
    from ..permissions.persistence import write_private_atomic

    path = paths.data_dir / "command-binding.key"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        # Runtime ownership already excludes concurrent profile provisioning.
        key = random_secrets.token_bytes(32)
        if not write_private_atomic(path, key.hex()):
            raise JournalStorageError()
        return key
    with os.fdopen(fd, "r", encoding="ascii") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != 64):
            raise JournalStorageError()
        try:
            key = bytes.fromhex(stream.read(65))
        except ValueError:
            raise JournalStorageError() from None
        if len(key) != 32:
            raise JournalStorageError()
        return key


class MethodError(Exception):
    """A scrubbed domain refusal, suitable for the local protocol."""

    def __init__(self, code: str, message: str, disposition: str = "rejected") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.disposition = disposition

    def response(self) -> dict:
        return response_error(self.code, self.message, self.disposition)


class ManagementService:
    """One set of domain owners attached to the core's authenticated profile."""

    def __init__(self, core, *, services=(), identity_key: bytes) -> None:
        self.core = core
        if not isinstance(identity_key, bytes) or len(identity_key) != 32:
            raise ValueError("A stable profile command-identity key is required")
        self._identity_key = identity_key
        self.services = tuple(services)
        self.methods: dict[str, Any] = {}
        self.read_methods: set[str] = set()
        for service in self.services:
            for method in service.METHODS:
                if method in self.methods:
                    raise ValueError("Duplicate management method")
                self.methods[method] = service
            self.read_methods.update(service.READ_METHODS)

    @classmethod
    def profile_settings(cls, core, *, secret_backend=None, config=None):
        """One persisted profile owner, optionally seeded by the test config seam."""
        from .provisioning import ensure_profile
        from .secrets import ProfileSecretStore
        from .settings import SettingsService

        provisioned = ensure_profile(core.paths, authority=core.authority)
        if core.authority.durability_degraded:
            raise JournalStorageError()
        settings = SettingsService(
            core.paths, ProfileSecretStore(core.paths, backend=secret_backend),
            config=config if config is not None else provisioned)
        # The async core hydrates off-loop before composing provider consumers.
        # Config consumers follow this owner's pointer after later hydration.
        return settings

    @classmethod
    def compose(cls, core, *, secret_backend=None, settings=None):
        """Compose retained domain owners without starting HTTP or a desktop."""
        from ..config.apply_registry import spec_for
        from ..context.loader import ContextLoader
        from ..health.checker import check_all
        from ..llm.system_prompt import register_user_presets
        from ..permissions.host_access import HostAccessManager
        from ..tools.builtin_policy import BUILTIN_TOOL_NAMES, BuiltinToolPolicy
        from ..tools.executor import EXECUTOR_HANDLERS, ToolExecutor
        from .browser_runtime import BrowserRuntime
        from .codex_accounts import CodexAccountsService
        from .computer_binding import ComputerBindingService
        from .hosts import HostsService
        from .integrations import IntegrationsService
        from .knowledge import KnowledgeService
        from .learned_context import LearnedContextService
        from .mcp import MCPService
        from .model_settings import ModelSettingsService
        from .observability import ObservabilityService
        from .openrouter_admin import OpenRouterAdminService
        from .providers import ProviderOwner
        from .records import RecordsService
        from .runtime import RuntimeService
        from .skills import SkillsService
        from .state import StateService
        from .tool_catalog import DesktopToolCatalog
        from .trajectories import TrajectoriesService
        from .workspace_diagnostics import WorkspaceDiagnostics

        settings = settings or getattr(core, "settings", None)
        if settings is None:
            settings = cls.profile_settings(core, secret_backend=secret_backend)
        elif secret_backend is not None:
            # Retain the compose-time isolated keyring injection seam without
            # constructing a second settings owner beside the request engine.
            settings.secrets._backend = secret_backend
        engine = getattr(core, "engine", None)
        deps = engine.deps if engine is not None else None
        if deps is not None:
            executor = deps.tool_executor
            providers = deps.llm_gateway
            codex = providers.codex_accounts
        else:
            executor = ToolExecutor(
                config=settings.config.tools, memory_path=str(core.paths.data_dir / "memory.json"),
                permission_manager=core.permissions, app_config=settings.config,
                email_config=settings.config.email, profile_paths=core.paths,
            )
            executor._command_shell_config = lambda: settings.config.tools.command_shell
            executor._host_access = HostAccessManager(
                path=core.paths.config_dir / "host-preferences.json",
                available_hosts_provider=executor.host_registry.active_aliases,
                permission_manager=core.permissions,
            )
            codex = CodexAccountsService(settings)
            providers = ProviderOwner(settings, codex, executor=executor)
        codex.providers = providers
        for method in providers.METHODS:
            settings.owners[method] = providers

        def apply_generic(desired, previous, changes):
            # Copied generic route publishes live-read config consumers. The
            # executor's restart-only path/connection snapshot remains intact.
            register_user_presets({name: preset.model_dump()
                                   for name, preset in desired.personality.user_presets.items()})
            executor._app_config = desired
            executor._email_config = desired.email
            # Adopt live/new-work tool fields, never startup-only transports.
            for name in type(desired.tools).model_fields:
                mode = spec_for("tools." + name).apply_mode
                if mode in {"live_read", "live_for_new_work"}:
                    setattr(executor.config, name, getattr(desired.tools, name))
            skills.update_runtime_config(executor.config)
            for name in ("tool_catalog", "prompt_builder"):
                owner = getattr(providers, name, None)
                invalidate = getattr(owner, "invalidate", None)
                if callable(invalidate):
                    invalidate()
            return True

        settings.owners["settings.set"] = apply_generic
        hosts = HostsService(settings, executor=executor,
                             registry=deps.host_registry if deps is not None else None,
                             scheduler=deps.scheduler if deps is not None else None)
        browser = (deps.browser_manager if deps is not None
                   and isinstance(deps.browser_manager, BrowserRuntime)
                   else BrowserRuntime(settings, core.paths, executor))
        browser.executor = executor
        skills = SkillsService(settings, executor=executor, owner_id=core.authority.owner_id,
                               permissions=core.permissions,
                               manager=deps.skill_manager if deps is not None else None)
        computer = ComputerBindingService(core, settings)
        bound_mcp = (getattr(deps.runtime_context, "mcp_manager", None)
                     if deps is not None else None)
        mcp = MCPService(settings, permissions=core.permissions,
                         manager=bound_mcp,
                         reserved_names_provider=lambda: {
                             *BUILTIN_TOOL_NAMES,
                             *(tool["name"] for tool in skills.get_tool_definitions()),
                         })

        def tool_readiness():
            ready = {name: True for name in EXECUTOR_HANDLERS}
            for name in ready:
                if name.startswith("browser_"):
                    # This is a qualify-before-use lazy handler. Withdrawing it
                    # after failure would remove the only route to retry.
                    ready[name] = browser.available()
                if name.startswith("email_"):
                    ready[name] = settings.config.email.enabled
            return ready

        if deps is None:
            executor.set_builtin_policy(BuiltinToolPolicy(lambda: settings.config, tool_readiness))
            catalog = DesktopToolCatalog(
                builtin_policy=executor._builtin_policy, get_config=lambda: settings.config,
                skill_manager=skills, get_mcp_definitions=mcp.get_tool_definitions,
                computer_available=lambda: computer.published_available,
                get_email_config=lambda: settings.config.email,
            )
        else:
            # Preserve the request engine's policy, catalog and all consumers.
            catalog = deps.tool_catalog
            catalog.skill_manager = skills
            # Part A management is not a new request-dispatch binding. Only
            # publish MCP through an already bound runtime manager.
            catalog.get_mcp_definitions = (mcp.get_tool_definitions
                                           if bound_mcp is mcp.manager else None)
            catalog.computer_available = lambda: computer.published_available
            deps.management_owned_browser = browser is deps.browser_manager
            deps.management_owned_mcp = bound_mcp is mcp.manager
            # The retained manager is a producer, not just a late transport.
            # Its management wrapper remains the single close owner, but the
            # engine must await it before declaring producers quiesced.
            deps.management_mcp_service = mcp if deps.management_owned_mcp else None
        skills.set_on_catalog_changed(catalog.invalidate)
        mcp.set_on_catalog_changed(catalog.invalidate)
        catalog.invalidate()
        executor.tool_catalog = providers.tool_catalog = catalog
        settings.owners["computer.activation.set"] = computer
        settings.owners["mcp.save"] = mcp.reject_generic_credentials

        class ReloadOwner:
            async def prepare_settings(self, desired, changes):
                change = await providers.prepare_reload_async(desired, changes)
                try:
                    mcp_changes = [(path, value) for path, value in changes if path[0] == "mcp"]
                    mcp_change = (await secret_call(mcp.prepare_settings, desired, mcp_changes)
                                  if mcp_changes else None)
                    computer_changes = [(path, value) for path, value in changes
                                        if path[0] == "computer"]
                    computer_change = (computer.prepare_settings(desired, computer_changes)
                                       if computer_changes else None)
                    staged = hosts.registry.stage(desired.tools.hosts,
                                                  default_host=desired.tools.default_host)
                except BaseException:
                    await change.rollback()
                    raise
                old_app, old_email = executor._app_config, executor._email_config
                old_tools = executor.config

                class ReloadToken:
                    committed = False

                    async def apply(self):
                        try:
                            async with providers.provider_lock:
                                await change.qualify()
                                if mcp_change is not None:
                                    mcp_change.apply()
                                    await mcp_change.finish()
                                if computer_change is not None:
                                    await computer_change.apply()
                                if hosts.registry.generation != staged.expected_generation:
                                    raise MethodError("stale_binding", "Host generation changed")
                                apply_generic(desired, settings.config, changes)
                                adopted_tools = desired.tools.model_copy(deep=True)
                                # Keep startup-only paths and existing connection policy.
                                for name in ("local_working_dir", "ssh_key_path",
                                             "ssh_known_hosts_path", "ssh_pool"):
                                    setattr(adopted_tools, name, getattr(old_tools, name))
                                executor.config = adopted_tools
                                skills.update_runtime_config(executor.config)
                                hosts.registry.publish_staged(staged)
                                change.publish()
                                self.committed = True
                            return True
                        except BaseException:
                            await self.rollback()
                            raise

                    async def rollback(self):
                        if not self.committed:
                            executor._app_config, executor._email_config = old_app, old_email
                            executor.config = old_tools
                            skills.update_runtime_config(old_tools)
                            register_user_presets({
                                name: preset.model_dump()
                                for name, preset in settings.config.personality.user_presets.items()
                            })
                            await change.rollback()
                            if computer_change is not None:
                                await computer_change.rollback()
                            if mcp_change is not None:
                                await mcp_change.rollback()

                return ReloadToken()

        settings.owners["runtime.reload"] = ReloadOwner()
        state = StateService(core.paths, core.authority.owner_id, memory=executor, lists=executor)
        runtime_context = getattr(deps, "runtime_context", None)
        knowledge_store = getattr(deps, "knowledge_store", None)
        if knowledge_store is not None:
            from ..knowledge.importer import BulkImporter

            knowledge = KnowledgeService(
                core.paths, store=knowledge_store,
                importer=BulkImporter(knowledge_store,
                                      embedder=getattr(deps, "embedder", None)),
            )
        else:
            knowledge = KnowledgeService(core.paths)
        observed = SimpleNamespace(config=settings.config, llm_gateway=providers,
                                   tool_executor=executor, knowledge_store=None,
                                   skill_manager=skills, mcp_manager=mcp.manager)
        diagnostics = WorkspaceDiagnostics(lambda: executor)

        async def health():
            observed.config = settings.config
            observed.knowledge_store = knowledge._store
            # Sample the current composed owner on every read. A compose-time
            # boolean would remain healthy after request/store/core shutdown.
            observed.delivery_readiness = getattr(core, "delivery_readiness", False)
            observed.delivery_readiness_reason = getattr(
                core, "delivery_readiness_reason", "delivery_not_composed")
            result = check_all(observed)
            result["workspace"] = await diagnostics.snapshot()
            result["browser"] = browser.status()
            result["computer"] = computer.readiness()
            return result

        records = RecordsService(core.paths, health=health, settings=settings,
                                 get_audit_path=lambda: settings.config.tools.audit_log_path,
                                 audit_getter=lambda: getattr(deps, "audit", None))
        context = (deps.context_loader if deps is not None
                   else ContextLoader(settings.config.context.directory))
        runtime = RuntimeService(core, settings, llm=providers, context=context,
                                 skills=skills,
                                 usage=getattr(runtime_context, "usage_rollup", None))
        models = ModelSettingsService(settings, executor=executor, provider=providers)
        integrations = IntegrationsService(settings)
        learned = LearnedContextService(
            core.paths, reflector_getter=lambda: getattr(providers, "reflector", None),
            learning_getter=lambda: settings.config.learning,
        )
        trajectories = TrajectoriesService(
            core.paths, get_directory=lambda: settings.config.tools.trajectory_path,
            saver_getter=lambda: getattr(getattr(deps, "turn_recorder", None),
                                         "_trajectory_saver", None),
        )
        observations = ObservabilityService(
            executor=executor, gateway=providers, config=lambda: settings.config,
            model_breakers=providers.model_breakers, graph=lambda: manager,
        )
        def usage_source():
            from .runtime import _ProfileUsageReader

            return runtime.usage or _ProfileUsageReader(settings.config.usage.directory)

        observations.usage_getter = usage_source
        openrouter = OpenRouterAdminService(settings, provider=providers, usage=usage_source)
        manager = cls(core, services=[settings, codex, hosts, state, knowledge,
                                     records, runtime, models, integrations,
                                     learned, trajectories, observations, openrouter,
                                     skills, mcp, computer],
                      identity_key=_binding_key(core.paths))
        manager.lifecycle_services = (*manager.services, browser)
        manager.settings, manager.executor, manager.providers = settings, executor, providers
        manager.runtime, manager.hosts, manager.codex = runtime, hosts, codex
        manager.records, manager.knowledge = records, knowledge
        manager.learned, manager.trajectories = learned, trajectories
        manager.observations, manager.openrouter = observations, openrouter
        manager.skills, manager.mcp = skills, mcp
        manager.browser, manager.computer = browser, computer
        manager.tool_catalog, manager.workspace_diagnostics = catalog, diagnostics
        manager._engine_owned = deps is not None
        return manager

    def identity_params(self, params: Any) -> dict:
        """Bind exact semantics without storing write-only secrets in receipts.

        The original request is never persisted here. Even validation refusals
        bind the submitted finite JSON, so reconnect cannot alter an admitted ID.
        """
        encoded = canonical_json(params).encode("utf-8")
        return {"hmac_sha256": hmac.new(self._identity_key, encoded, hashlib.sha256).hexdigest()}

    def check(self, command_id: str, method: str, params: Any) -> dict | None:
        """Replay keyed records while retaining step-one plaintext identities.

        The stored scheme tag selects the comparison, not a request-shaped
        object that could impersonate a hashed parameter envelope.
        """
        row = self.core.store.connection.execute(
            "SELECT * FROM command_receipts WHERE command_id=?", (command_id,),
        ).fetchone()
        if row is None:
            return None
        if row["binding"].startswith("hmac-v1:"):
            binding = "hmac-v1:" + canonical_json([
                self.core.store.profile_id, method, self.identity_params(params),
            ])
            return self.core.commands._replay(row, binding)
        return self.core.commands.check(command_id, method, params)

    async def invoke(self, method: str, params: Any) -> dict:
        if type(params) is not dict:
            return response_error("bad_request", "Method params must be an object")
        service = self.methods.get(method)
        if service is None:
            return response_error("capability_unavailable", "Service is not available yet")
        try:
            result = service.handle(method, params)
            if inspect.isawaitable(result):
                result = await result
            canonical_json(result)
            return {"ok": True, "result": result}
        except MethodError as exc:
            return exc.response()
        except (ValueError, TypeError, KeyError):
            # Never reflect a provider's exception or the submitted field value.
            return response_error("bad_request", "Invalid management parameters")
        except Exception:
            return response_error("internal", "Management operation failed", "outcome_unknown")

    async def execute(
        self, command_id: str, method: str, params: Any, *, unlock_serial=None,
    ) -> dict:
        """Reserve before awaiting an effect; final receipt/events commit together.

        Domain stores and keyring operations cannot join the SQLite transaction.
        A crash after reservation therefore leaves an unknown outcome, never a
        readmission or an exactly-once external-effect claim. No SQLite write
        transaction is held across a network or keyring await.
        """
        store = self.core.store
        admitted = False
        try:
            identity = self.identity_params(params)
            replay = self.check(command_id, method, params)
            if replay is not None:
                return replay
            binding = "hmac-v1:" + canonical_json([store.profile_id, method, identity])
            with store.transaction() as connection:
                connection.execute(
                    "INSERT INTO command_receipts "
                    "(command_id,binding,state,created_at) VALUES (?,?,'pending',?)",
                    (command_id, binding, time.time()),
                )
            admitted = True
            settings = getattr(self, "settings", None)
            previous_fields = ({field["path"]: field for field in
                                await secret_call(settings.get_fields)}
                               if settings is not None else {})
            previous_revision = settings.revision if settings is not None else None
            if unlock_serial is None:
                answer = await self.invoke(method, params)
            else:
                # Durable admission precedes the prompt. Only the prompt runs
                # outside serialization: no config mutation or SQLite write
                # transaction crosses this gap. Ordinary writes retain order.
                unlock_serial.release()
                try:
                    try:
                        if type(params) is not dict:
                            raise MethodError("bad_request", "Method params must be an object")
                        await settings.unlock_prompt(params)
                        answer = None
                    except MethodError as exc:
                        answer = exc.response()
                finally:
                    # The outer core async-with still owns this lock envelope.
                    # Repeated cancellation must not let its __aexit__ release
                    # another dispatch's lock while reacquisition is pending.
                    acquiring = asyncio.create_task(unlock_serial.acquire())
                    reacquire_cancelled = False
                    while True:
                        try:
                            await asyncio.shield(acquiring)
                            break
                        except asyncio.CancelledError:
                            reacquire_cancelled = True
                            if acquiring.cancelled():
                                acquiring = asyncio.create_task(unlock_serial.acquire())
                            elif acquiring.done():
                                break
                    if reacquire_cancelled:
                        raise asyncio.CancelledError
                # Other ordered mutations may have completed during the prompt.
                # Snapshot again so their changes aren't attributed to Retry.
                previous_fields = {field["path"]: field for field in settings.get_fields()}
                previous_revision = settings.revision
                if answer is None:
                    try:
                        answer = {"ok": True, "result": await settings.finish_unlock()}
                        codex = getattr(self, "codex", None)
                        if codex is not None:
                            await codex.refresh_pool_if_initialized()
                    except MethodError as exc:
                        answer = exc.response()
            event = None
            with store.transaction() as connection:
                if answer["ok"]:
                    if settings is not None and settings.revision != previous_revision:
                        # Derive metadata solely from validated domain records.
                        # Unknown request extras never enter an event or log.
                        fields = [field for field in settings.get_fields()
                                  if previous_fields.get(field["path"]) != field]
                        paths = [field["path"] for field in fields]
                        event = self.core.events.append(
                            "settings.changed", {"kind": "settings", "id": store.profile_id},
                            {"rev": settings.revision, "paths": paths,
                             "restart_required": any(field.get("pending_restart")
                                                     for field in fields)},
                        )
                unknown = not answer["ok"] and answer["error"]["disposition"] == "outcome_unknown"
                connection.execute(
                    "UPDATE command_receipts SET state='final',response=?,finished_at=?,"
                    "unknown_outcome=? WHERE command_id=?",
                    (canonical_json(answer), time.time(), int(unknown), command_id),
                )
            if event is not None:
                flush = getattr(self.core, "_flush_publications", None)
                if flush is None:
                    await self.core._publish(event)
                else:
                    # Request workers can commit while management awaits an effect.
                    # Publish the entire pending prefix before advancing a subscriber
                    # cursor past it with the newer settings frame.
                    await flush()
            return json.loads(canonical_json(answer))
        except (ValueError, TypeError, RecursionError):
            if admitted:
                return response_error("internal", "Management outcome is unknown",
                                      "outcome_unknown")
            return response_error("bad_request", "Expected finite JSON parameters")
        except JournalStorageError:
            return response_error("storage_unavailable", "Durable command storage is unavailable",
                                  "outcome_unknown")
        except Exception:
            return response_error("internal", "Management outcome is unknown", "outcome_unknown")

    async def close(self) -> None:
        from .resource_cleanup import ResourceCleanupError, close_existing_execution_owners

        # Retained barriers keep ambiguous native owners and independently prove
        # whole process sessions before releasing their transports.
        resources = await close_existing_execution_owners(self.core, self)
        engine = getattr(self.core, "engine", None)
        if engine is not None and not getattr(engine, "producers_quiesced", False):
            # Never close shared services beneath unresolved engine producers.
            resources["services"] = {"state": "unknown", "reason": "producers_not_quiesced"}
            journal = getattr(self.core, "resource_cleanup", None)
            if journal is not None:
                journal.finish(resources)
            raise ResourceCleanupError("Runtime producers are still settling")
        failed = False
        # Teardown of one owner cannot strand the other supervised transports.
        owners = [*reversed(getattr(self, "lifecycle_services", self.services)),
                  (getattr(self, "providers", None)
                   if not getattr(self, "_engine_owned", False) else None)]
        for service in owners:
            close = getattr(service, "close", None)
            if close is not None:
                try:
                    result = close()
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    failed = True
        executor = getattr(self, "executor", None)
        pool = getattr(executor, "ssh_pool", None)
        if pool is not None and not getattr(self, "_engine_owned", False):
            close = getattr(pool, "close", None)
            if close is not None:
                try:
                    result = close()
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    failed = True
        resources["services"] = {"state": "unknown" if failed else "released"}
        journal = getattr(self.core, "resource_cleanup", None)
        if journal is not None:
            journal.finish(resources)
        elif failed or any(row["state"] == "unknown" for row in resources.values()):
            raise ResourceCleanupError("Runtime resource cleanup is unverified")

    async def start(self) -> None:
        """Qualify configured service owners before the core publishes methods."""
        for service in getattr(self, "lifecycle_services", self.services):
            start = getattr(service, "start", None)
            if callable(start):
                result = start()
                if inspect.isawaitable(result):
                    await result
        # Optional store qualification may leave observation usable while its
        # native management effects are unavailable. Do not publish those.
        self.methods = {method: service for service in self.services
                        for method in getattr(service, "management_methods", service.METHODS)}
        self.read_methods = {method for service in self.services
                             for method in service.READ_METHODS if method in self.methods}
