"""Integrated profile-local owners for the retained runner, not a replacement tool loop.

RequestService owns locks, durable admission and guarded publication. Session
accounting is deliberately separate and runs only after that publication.
"""
# ruff: noqa: E501
from __future__ import annotations

import asyncio
import importlib.util
import mimetypes
import time
from collections.abc import Mapping
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace

from ..async_utils import fire_and_forget
from ..discord.channel_state import ChannelStateRegistry
from ..discord.completion import CompletionClassifier
from ..discord.housekeeping import Housekeeping
from ..discord.llm_gateway import LLMGateway
from ..discord.native_tools.registry import (
    NativeToolDispatcher,
    NativeToolEffects,
    register_native_handlers,
)
from ..discord.prompts import PromptBuilder
from ..discord.response_guards import StuckLoopTracker, scrub_response_secrets
from ..discord.tool_catalog import ToolCatalog
from ..discord.tool_loop import ToolLoopDeps, ToolLoopRunner
from ..discord.turn_recorder import TurnRecorder
from ..odin_log import get_logger
from ..sessions.manager import CHAT_RESPONSE_MAX_CHARS, summarize_tool_response
from ..tools.builtin_policy import BuiltinToolPolicy, unavailable_rejection
from ..tools.registry import PHASE1_EXECUTOR_TOOL_NAMES

log = get_logger("desktop.services")


class _ReadyPolicy(BuiltinToolPolicy):
    """Use actual owners and the same live switches at offer and dispatch."""

    def is_available(self, name):
        if self.is_disabled(name):
            return False
        try:
            return self._get_readiness().get(name) is True
        except Exception:
            return False


class _ReadyCatalog(ToolCatalog):
    def __init__(self, *, policy, **kwargs):
        super().__init__(**kwargs)
        self.policy = policy

    def merged_definitions(self, *, cache_result=True):
        from ..tools.agent_tool_policy import apply_agent_axis_policy, apply_agent_limits
        from ..tools.registry import get_documentation_tool_definitions

        existing = super().merged_definitions(cache_result=cache_result)
        cfg = self.get_config()
        hidden = self.backend_hidden_names(cfg)
        builtins = [tool for tool in get_documentation_tool_definitions(cfg.tools.command_shell)
                    if self.policy.is_available(tool["name"]) and tool["name"] not in hidden]
        builtins = apply_agent_limits(apply_agent_axis_policy(builtins, cfg), cfg)
        from ..tools.builtin_policy import BUILTIN_TOOL_NAMES

        taken = {tool["name"] for tool in builtins}
        return builtins + [tool for tool in existing if tool["name"] not in taken
                           and (tool["name"] not in BUILTIN_TOOL_NAMES
                                or self.policy.is_available(tool["name"]))]


class _ReadyDispatcher(NativeToolDispatcher):
    async def dispatch(self, tool_name, tool_input, **kwargs):
        from ..tools.builtin_policy import BUILTIN_TOOL_NAMES

        if tool_name in BUILTIN_TOOL_NAMES and not self.builtin_policy.is_available(tool_name):
            return unavailable_rejection(tool_name), NativeToolEffects()
        return await super().dispatch(tool_name, tool_input, **kwargs)


class EngineServices:
    """Real runner and upstream intake/handoff/accounting around it."""

    def __init__(self, deps, runner):
        self.deps, self.runner = deps, runner
        self.requests = None
        self._recorded = set()

    def bind_requests(self, requests):
        if self.requests is not None and self.requests is not requests:
            raise RuntimeError("Engine already belongs to another request service")
        self.requests = requests

    async def initialize_profile_provider(self):
        """Build startup Codex credentials off-loop after profile hydration."""
        from .management import MethodError
        from .secrets import SecretStoreError, secret_call

        gateway = self.deps.llm_gateway
        settings = getattr(gateway, "settings", None)
        if settings is None or gateway.codex_client is not None:
            return
        if not settings.config.openai_codex.enabled:
            return

        def build():
            # An empty or locked vault never becomes a cached empty auth pool.
            if gateway.codex_accounts.vault.read():
                return gateway._build("codex", settings.config)
            return None

        try:
            client = await secret_call(build)
        except (MethodError, SecretStoreError):
            log.warning("Desktop Codex provider unavailable at startup")
            return
        gateway.codex_client = client
        if gateway.active_client is not None:
            gateway.wire_callbacks()

    def diagnostics(self):
        """Public, credential-free runtime state for optional engine services."""
        d = self.deps
        ledger = d.turn_store
        if ledger is None:
            durability = {"state": "off", "reason": d.durability_reason,
                          "message": "Turn durability off; turns run without checkpoints."}
        elif not ledger.available:
            durability = {"state": "unavailable", "reason": "runtime_store_failure",
                          "message": "Turn ledger unavailable; fresh turn admission is refused."}
        else:
            durability = {"state": "on", "reason": None}
        return {"turn_durability": durability,
                "compatible_provider": {
                    "state": "skipped" if d.compatible_skipped else
                             "available" if d.llm_gateway.compatible_client is not None else "off",
                    "reason": "missing_api_key" if d.compatible_skipped else None}}

    async def close(self):
        """Release this profile's transports after request workers are quiesced."""
        from ..llm.client_lifecycle import shutdown_provider_clients

        if getattr(self, "_closed", False):
            return
        self._closed = True
        d = self.deps
        failures = []

        async def release(owner, method):
            if owner is None:
                return
            try:
                callback = getattr(owner, method)
                result = callback()
                if hasattr(result, "__await__"):
                    await result
            except Exception as error:
                failures.append(error)
                log.exception("Desktop cleanup failed: %s", method)

        await release(d.channel_state, "shutdown_steering")
        await release(d.loop_manager, "shutdown")
        await release(d.scheduler, "stop")
        if not getattr(d, "management_owned_mcp", False):
            await release(getattr(d.runtime_context, "mcp_manager", None), "shutdown")
        active = [agent for agent in d.agent_manager._agents.values() if agent._sm.is_active]
        tasks = [agent._task for agent in active if getattr(agent, "_task", None) is not None]
        for agent in active:
            d.agent_manager.kill(agent.id, cascade=True)
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 10.0)
            except TimeoutError as error:
                failures.append(error)
        await release(d.agent_manager, "cleanup")
        await release(getattr(d.tool_executor, "_process_registry", None), "shutdown")
        await release(getattr(d.tool_executor, "ssh_pool", None), "close_all")
        if not getattr(d, "management_owned_browser", False):
            method = "close" if callable(getattr(d.browser_manager, "close", None)) else "shutdown"
            await release(d.browser_manager, method)
        try:
            close = getattr(d.llm_gateway, "close", None)
            if callable(close):
                await close()
            else:
                await shutdown_provider_clients(d.llm_gateway)
        except Exception as error:
            failures.append(error)
        await release(getattr(d.runtime_context, "outbound_webhook_dispatcher", None), "close")
        try:
            await asyncio.to_thread(d.sessions.save)
        except Exception as error:
            failures.append(error)
        await release(getattr(d.runtime_context, "knowledge_store", None), "close")
        await release(d.turn_store, "close")
        if failures:
            raise RuntimeError("Desktop engine cleanup did not fully complete") from failures[0]

    def _assert_request(self, message):
        if self.requests is None:
            raise PermissionError("Durable request admission is not bound")
        self.requests.assert_request(message)

    async def _admit_turn(self, message, **kwargs):
        self._assert_request(message)
        return await self.requests.admit_turn(message, **kwargs)

    async def run(self, message, *, content=None, image_blocks=None):
        self._assert_request(message)
        d = self.deps
        cid, uid = message.conversation_id, message.owner_id
        if not d.permissions.is_owner(uid):
            raise PermissionError("Authenticated profile owner required")
        if d.llm_gateway.active_client is None:
            from .errors import NoLLMProviderError

            raise NoLLMProviderError("No selected LLM provider configured")
        content = message.content if content is None else content
        d.sessions.add_message(cid, "user", f"[{message.owner_name or uid}]: {content}", user_id=uid)
        try:
            trace = d.turn_recorder._new_context_trace()
            if trace is None:
                prompt = d.prompt_builder.build_full_prompt(
                    conversation_id=cid, user_id=uid, query=content)
                history = await d.sessions.get_task_history(cid, max_messages=160, current_query=content)
            else:
                with trace.phase("system_prompt"):
                    prompt = d.prompt_builder.build_full_prompt(
                        conversation_id=cid, user_id=uid, query=content, trace=trace)
                with trace.phase("history"):
                    history = await d.sessions.get_task_history(
                        cid, max_messages=160, current_query=content, trace=trace)
            if image_blocks and history and history[-1]["role"] == "user":
                text = history[-1]["content"]
                history[-1] = {"role": "user", "content": list(image_blocks) + [
                    {"type": "text", "text": text if isinstance(text, str) else str(text)}]}
            response, sent, error, tools, handoff = await self.runner.run(
                message, history, system_prompt_override=prompt, trace=trace)
            if handoff and not error and d.llm_gateway.active_client:
                response, sent, error = await self._handoff(message, content, response)
            return scrub_response_secrets(response), sent, error, tools, handoff
        except BaseException:
            d.channel_state.pending_files.pop(cid, None)
            d.sessions.remove_last_message(cid, "user")
            raise
        finally:
            await d.delivery.set_status(None, task_end=True)

    async def _handoff(self, message, content, response):
        d, cid, uid = self.deps, message.conversation_id, message.owner_id
        prompt = d.prompt_builder.build_chat_prompt(conversation_id=cid, user_id=uid, query=content)
        history = list(d.sessions.get_history(cid)) + [
            {"role": "assistant", "content": f"[Tool result: {response}]"},
            {"role": "user", "content": "Respond to the user based on the tool result above. "
             "Be conversational and helpful."}]
        accepted, error = None, False
        started = time.monotonic_ns()
        try:
            accepted = await d.llm_gateway.chat(messages=history, system=prompt)
            response = accepted or response
        except Exception as exc:
            from ..llm.errors import LLMIncompleteResponseError

            if isinstance(exc, LLMIncompleteResponseError):
                accepted = exc.partial_text
                response = exc.partial_text + "\n\n[Provider marked this response incomplete.]"
                error = True
        if accepted is not None:
            await d.turn_recorder._save_direct_chat_trajectory(
                message_id=f"{message.request_id}:handoff", channel_id=cid,
                user_id=uid, user_name=message.owner_name, user_content=content,
                system_prompt=prompt, history=history, response=accepted,
                final_response=scrub_response_secrets(response), is_error=error,
                duration_ms=(time.monotonic_ns() - started) // 1_000_000)
        return response, False, error

    async def record_result(self, message, result):
        """RequestService calls this only after the guarded delivery commits."""
        if self.requests is None:
            raise PermissionError("Durable request admission is not bound")
        self.requests.assert_request(message, allow_terminal=True)
        identity = (message.request_id, message.generation)
        if identity in self._recorded:
            return
        response, _sent, error, tools, _handoff = result
        response = scrub_response_secrets(response)
        d, cid = self.deps, message.conversation_id
        if not error:
            saved = summarize_tool_response(response, tools) if tools else response[:CHAT_RESPONSE_MAX_CHARS]
        elif (d.turn_store is not None
              and d.turn_store.turn_status_sync(message.turn_key) == "SUSPENDED"):
            note = f" after using tools ({', '.join(tools[:5])})" if tools else ""
            saved = ("[Previous request was interrupted by a model-capacity "
                     f"outage{note}. Its work is PRESERVED and resumable.]")
        elif tools:
            saved = (f"[Previous request used tools ({', '.join(tools[:5])}) "
                     "but encountered an error. The user may ask to retry.]")
        else:
            saved = "[Previous request encountered an error before tool execution.]"
        current_context = self.requests.context_is_current(message)
        if current_context:
            d.sessions.add_message(cid, "assistant", saved)
            d.sessions.prune()
        self._recorded.add(identity)
        if current_context:
            try:
                await asyncio.to_thread(d.sessions.save)
            except Exception as error:
                log.warning("Session save failed after committed delivery: %s", error)
        d.housekeeping.maybe_cleanup()
        if tools:
            details = d.channel_state.last_op_details.pop(cid, None)
            fire_and_forget(d.turn_recorder._operational_reflection(
                message.content, tools, response, error, message.owner_id, tool_details=details),
                name="operational_reflection")


def build_engine_services(config, paths, permissions, *, delivery, request_service=None,
                          codex_client=None, ollama_client=None, compatible_client=None,
                          codex_auth=None, runtime_context=None, readiness_gate=None,
                          session_manager=None, turn_store=None, channel_state=None,
                          native_owners=None, settings=None):
    """Compose explicit profile settings or injected runtime owners.

    readiness_gate is a live zero-argument Mapping[str, bool] provider. It may
    narrow real handler readiness, never invent absent owners. Credential
    resolution belongs to the profile runtime before this function is called.
    """
    from ..agents import AgentManager
    from ..agents.trajectory import AgentTrajectorySaver
    from ..audit import AuditLogger
    from ..context import ContextLoader
    from ..discord.native_tools.agents_tasks import AgentTaskDeps, AgentTaskTools
    from ..discord.native_tools.channel_ops import ChannelOpsTools
    from ..discord.native_tools.knowledge import KnowledgeTools
    from ..discord.native_tools.media import MediaTools
    from ..discord.native_tools.scheduling import SchedulingTools
    from ..health.subsystem_guard import SubsystemGuard
    from ..learning import ConversationReflector
    from ..learning.loop_reflection import LoopReflectionGate
    from ..llm import CodexChatClient, OllamaClient, OpenAICompatibleClient
    from ..llm.codex_auth import CodexAuthPool
    from ..llm.cost_tracker import CostTracker
    from ..llm.model_breaker import ModelBreakerRegistry
    from ..llm.recovery import RecoveryPolicy
    from ..permissions.host_access import HostAccessManager
    from ..scheduler import Scheduler
    from ..sessions import SessionManager
    from ..tools import SkillManager, ToolExecutor
    from ..tools.autonomous_loop import LoopManager
    from ..tools.hosts import HostRegistry
    from ..tools.time_parser import set_default_timezone
    from ..trajectories.saver import TrajectorySaver
    from ..turn_state import TurnStateStore

    runtime = runtime_context or SimpleNamespace()
    get_config = (lambda: settings.config) if settings is not None else getattr(runtime, "get_config", lambda: config)
    cfg = get_config()
    set_default_timezone(cfg.timezone)
    paths.create_private()
    state = channel_state or getattr(runtime, "channel_state", None) or ChannelStateRegistry()
    reflector = getattr(runtime, "reflector", None) or ConversationReflector(
        str(paths.data_dir / "learned.json"), max_entries=cfg.learning.max_entries,
        consolidation_target=cfg.learning.consolidation_target,
        injection_token_budget=cfg.learning.injection_token_budget,
        enabled=cfg.learning.enabled, enabled_provider=lambda: get_config().learning.enabled)
    context = getattr(runtime, "context_loader", None) or ContextLoader(cfg.context.directory)
    context.load()
    knowledge, embedder = getattr(runtime, "knowledge_store", None), getattr(runtime, "embedder", None)
    sessions = session_manager or getattr(runtime, "sessions", None)
    if sessions is None:
        sessions = SessionManager(max_history=cfg.sessions.max_history,
            max_age_hours=cfg.sessions.max_age_hours, persist_dir=str(paths.data_dir / "sessions"),
            reflector=reflector, vector_store=getattr(runtime, "vector_store", None), embedder=embedder,
            token_budget=cfg.sessions.token_budget, adaptive_compaction=cfg.sessions.adaptive_compaction,
            archive_max_bytes=cfg.sessions.archive_max_bytes, archive_max_files=cfg.sessions.archive_max_files,
            context_token_budget=cfg.sessions.context_token_budget,
            context_budget_overrides=cfg.sessions.context_budget_overrides)
        sessions.load()
    hosts = getattr(runtime, "host_registry", None) or HostRegistry(cfg.tools.hosts,
        profile_paths=paths, key_path=cfg.tools.ssh_key_path,
        legacy_known_hosts_path=cfg.tools.ssh_known_hosts_path, default_host=cfg.tools.default_host)
    access = getattr(runtime, "host_access_manager", None) or HostAccessManager(
        path=paths.config_dir / "host-preferences.json", available_hosts_provider=hosts.active_aliases,
        permission_manager=permissions)
    browser = getattr(runtime, "browser_manager", None)
    if browser is None and settings is not None:
        from .browser_runtime import BrowserRuntime

        browser = BrowserRuntime(settings, paths)
    elif browser is None and cfg.browser.enabled:
        from ..tools.browser import BrowserManager

        browser = BrowserManager(cdp_url=cfg.browser.cdp_url,
            default_timeout_ms=cfg.browser.default_timeout_ms,
            max_wait_timeout_seconds=cfg.browser.max_wait_timeout_seconds,
            viewport_width=cfg.browser.viewport_width, viewport_height=cfg.browser.viewport_height,
            allow_private_targets=cfg.browser.allow_private_targets)
    executor = getattr(runtime, "tool_executor", None) or ToolExecutor(cfg.tools,
        memory_path=str(paths.data_dir / "memory.json"), app_config=cfg, profile_paths=paths,
        browser_manager=browser if cfg.browser.enabled else None,
        host_registry=hosts, host_access_manager=access,
        permission_manager=permissions, email_config=cfg.email)
    executor._command_shell_config = lambda: get_config().tools.command_shell
    skill_config_store = None
    if settings is not None:
        from .skills import _ConfigStore

        skill_config_store = _ConfigStore(settings.secrets, paths.data_dir / "skills" / "config")
    skills = getattr(runtime, "skill_manager", None) or SkillManager(
        str(paths.data_dir / "skills"), tool_executor=executor,
        memory_path=str(paths.data_dir / "memory.json"), tool_timeouts=cfg.tools.tool_timeouts,
        allowed_urls=tuple(cfg.tools.skill_allowed_urls), config_store=skill_config_store)
    scheduler = getattr(runtime, "scheduler", None) or Scheduler(str(paths.data_dir / "schedules.json"))
    skills.set_services(knowledge_store=knowledge, embedder=embedder, session_manager=sessions, scheduler=scheduler)
    audit = getattr(runtime, "audit", None) or AuditLogger(path=str(paths.data_dir / "audit.jsonl"),
        hmac_key=cfg.audit.hmac_key, classify_failures=cfg.observability.audit_failure_classification)
    agents = getattr(runtime, "agent_manager", None) or AgentManager(
        max_concurrent_agents_provider=lambda: get_config().agents.max_concurrent_agents)
    loops = getattr(runtime, "loop_manager", None) or LoopManager(agents_enabled=True)
    trajectories = getattr(runtime, "trajectory_saver", None) or TrajectorySaver(str(paths.data_dir / "trajectories"))
    agent_trajectories = getattr(runtime, "agent_trajectory_saver", None) or AgentTrajectorySaver(
        str(paths.data_dir / "agent_trajectories"))
    # D17: feature-off or failed-open is Odin's legacy, uncheckpointed run.
    # Keep a successfully opened owner attached: later failure must refuse
    # admission, not silently convert the runtime to legacy execution.
    ledger = None
    durability_reason = None
    if not cfg.turn_state.enabled:
        durability_reason = "disabled_by_config"
        log.info("Desktop turn durability off: disabled by configuration")
    else:
        ledger = turn_store if turn_store is not None else getattr(runtime, "turn_store", None)
        if ledger is None:
            try:
                ledger = TurnStateStore(paths.data_dir / "turn_state" / "turns.db")
            except Exception as error:
                log.warning("Desktop turn ledger failed to open: %s", type(error).__name__)
        if ledger is None or not ledger.available:
            ledger = None
            durability_reason = "store_open_failed"
            log.warning("Desktop turn durability off: ledger failed to open; running legacy turns")
    codex_client = codex_client or getattr(runtime, "codex_client", None)
    ollama_client = ollama_client or getattr(runtime, "ollama_client", None)
    compatible_client = compatible_client or getattr(runtime, "compatible_client", None)
    injected_gateway = getattr(runtime, "llm_gateway", None)
    if settings is not None and injected_gateway is not None:
        # Retain injected concrete generations and recovery owners while the
        # profile-owned gateway remains the single administrative boundary.
        codex_client = codex_client or injected_gateway.codex_client
        ollama_client = ollama_client or injected_gateway.ollama_client
        compatible_client = compatible_client or injected_gateway.compatible_client
    cc = cfg.openai_codex
    if codex_client is None and cc.enabled and settings is None:
        auth = codex_auth
        if auth is None:
            credential_path = Path(cc.credentials_path)
            if not credential_path.is_absolute():
                raise ValueError("Codex credentials require an explicit absolute profile path")
            auth = CodexAuthPool(str(credential_path))
        if auth.is_configured():
            codex_client = CodexChatClient(auth=auth, model=cc.model,
                reasoning_effort=cc.reasoning_effort, max_retries=cc.retry.max_retries,
                retry_base_delay=cc.retry.base_delay, retry_max_delay=cc.retry.max_delay,
                pool_max_connections=cc.connection_pool.max_connections,
                pool_keepalive_timeout=cc.connection_pool.keepalive_timeout,
                request_timeout=cc.request_timeout_seconds,
                stream_stall_timeout=cc.stream_stall_timeout_seconds)
    oc = cfg.ollama
    if ollama_client is None and oc.enabled:
        ollama_client = OllamaClient(base_url=oc.base_url, model=oc.model,
            max_tokens=oc.max_tokens, num_ctx=oc.num_ctx, timeout=oc.timeout, api_key=oc.api_key)
    pc = cfg.openai_compatible
    compatible_skipped = compatible_client is None and pc.enabled and not pc.api_key
    if compatible_skipped:
        log.warning("Desktop compatible provider skipped: enabled without an API key")
    if compatible_client is None and pc.enabled and pc.api_key:
        from ..llm.openai_compatible import KIMI_TOOL_ENFORCEMENT, preset_context_overflow_pattern
        from ..reasoning import compatible_reasoning_dialect

        quirks = ({"sanitize_schema": True, "reasoning_content_placeholder": True,
            "tool_enforcement": KIMI_TOOL_ENFORCEMENT, "force_temperature_model_substring": "k2.6",
            "temperature_range": (0.0, 1.0), "ignore_request_model": True} if pc.preset == "kimi" else {})
        compatible_client = OpenAICompatibleClient(api_key=pc.api_key, model=pc.model,
            base_url=pc.base_url, provider_name="compat", max_tokens=pc.max_tokens,
            request_timeout_seconds=pc.request_timeout_seconds,
            stream_stall_timeout_seconds=pc.stream_stall_timeout_seconds, tool_quirks=quirks,
            context_overflow_pattern=preset_context_overflow_pattern(pc.preset),
            reasoning_dialect=compatible_reasoning_dialect(pc), glm_clear_thinking=pc.glm_clear_thinking,
            reasoning_content_feedback_policy=pc.reasoning_content_feedback_policy,
            openrouter_routing=pc.openrouter if pc.preset == "openrouter" else None,
            model_profiles=pc.model_profiles)
    guard = getattr(runtime, "subsystem_guard", None) or SubsystemGuard()
    for provider in ("codex", "ollama", "compat"):
        guard.register(f"llm_{provider}")
    lr = cfg.llm_recovery
    gateway_dependencies = dict(get_config=get_config,
        codex_client=codex_client, ollama_client=ollama_client, kimi_client=None,
        compatible_client=compatible_client, subsystem_guard=guard,
        auxiliary_llm_client=getattr(runtime, "auxiliary_llm_client", None),
        cost_tracker=getattr(runtime, "cost_tracker", None) or CostTracker(), sessions=sessions,
        reflector=reflector, model_breakers=ModelBreakerRegistry(
            generation_threshold=lr.breaker_generation_threshold,
            cooldown_base=lr.breaker_cooldown_base_seconds, cooldown_cap=lr.breaker_cooldown_cap_seconds),
        recovery_policy_source=lambda: RecoveryPolicy(
            deadline_seconds=get_config().llm_recovery.generation_deadline_seconds,
            backoff_cap=get_config().llm_recovery.backoff_cap_seconds))
    if settings is not None:
        from .codex_accounts import CodexAccountsService
        from .providers import ProviderOwner

        if injected_gateway is not None:
            for name in ("subsystem_guard", "auxiliary_llm_client", "cost_tracker",
                         "model_breakers"):
                gateway_dependencies[name] = getattr(injected_gateway, name)
            gateway_dependencies["recovery_policy_source"] = injected_gateway._recovery_policy_source
        codex = CodexAccountsService(settings)
        gateway = ProviderOwner(settings, codex, executor=executor, **gateway_dependencies)
        codex.providers = gateway
        # The async core initializes this vault-backed client off-loop after
        # composition, retaining one provider/account owner for request work.
    else:
        gateway = getattr(runtime, "llm_gateway", None) or LLMGateway(**gateway_dependencies)
    if gateway.active_client is not None:
        gateway.wire_callbacks()
    owners = dict(native_owners or getattr(runtime, "native_owners", {}) or {})

    def readiness():
        ready = {name: callable(executor._resolve_handler(name))
                 for name in PHASE1_EXECUTOR_TOOL_NAMES}
        for name in ("browser_read_page", "browser_read_table", "browser_click", "browser_fill", "browser_evaluate"):
            available = getattr(browser, "available", None)
            ready[name] = (available() if callable(available)
                           else browser is not None and get_config().browser.enabled)
        for name in ("email_send", "email_search", "email_read", "email_list_recent"):
            ready[name] = bool(executor._email_config and executor._email_config.enabled)
        ready["analyze_pdf"] = importlib.util.find_spec("fitz") is not None
        ready.update({"parse_time": True, "search_history": True, "search_audit": True,
                      "read_conversation": engine.requests is not None,
                      "generate_file": engine.requests is not None,
                      "post_file": engine.requests is not None})
        for name in ("search_knowledge", "ingest_document", "bulk_ingest_knowledge", "list_knowledge", "delete_knowledge"):
            ready[name] = knowledge is not None and bool(get_config().search.enabled)
        extra = getattr(runtime, "native_readiness", None)
        if extra is not None:
            supplied = extra() if callable(extra) else extra
            if isinstance(supplied, Mapping):
                ready.update({name: value is True for name, value in supplied.items()
                              if dispatcher.handles(name)})
        if readiness_gate is not None:
            try:
                supplied = readiness_gate()
            except Exception:
                return {}
            ready = {name: value and isinstance(supplied, Mapping) and supplied.get(name) is True
                     for name, value in ready.items()}
        return ready

    policy = _ReadyPolicy(get_config, get_readiness=readiness)
    executor.set_builtin_policy(policy)
    prompt = PromptBuilder(get_config=get_config, context_loader=context, reflector=reflector,
        skill_manager=skills, tool_executor=executor, channel_state=state,
        get_codex_client=lambda: gateway.codex_client, host_registry=hosts, host_access_manager=access)
    mcp = getattr(runtime, "mcp_manager", None)
    catalog = _ReadyCatalog(policy=policy, get_config=get_config, skill_manager=skills,
        get_mcp_definitions=mcp.get_tool_definitions if mcp else None,
        computer_available=lambda: bool(getattr(owners.get("computer"), "enabled", False)),
        get_email_config=lambda: executor._email_config)
    if settings is not None:
        gateway.tool_catalog, gateway.prompt_builder = catalog, prompt
    gateway.on_provider_switch = catalog.invalidate
    if mcp is not None:
        mcp.set_on_catalog_changed(catalog.invalidate)
    recorder = TurnRecorder(get_config=get_config, trajectory_saver=trajectories,
        reflector=reflector, outbound_webhook_dispatcher=getattr(runtime, "outbound_webhook_dispatcher", None),
        loop_reflection_gate=LoopReflectionGate(cooldown_hours=cfg.learning.loop_reflection_cooldown_hours,
            max_per_hour=cfg.learning.loop_reflection_max_per_hour))
    completion = CompletionClassifier(get_llm_client=lambda: gateway.active_client,
        get_auxiliary_llm_client=lambda: gateway.auxiliary_llm_client)
    agents.set_completion_classifier(completion)

    async def read_history(message, *, limit):
        engine.requests.assert_bound_request(message)
        rows = engine.requests.transcript.read_conversation(message.conversation_id, limit=limit)
        return [f"{row['role']}: {row['text']}" for row in rows]

    def current_conversation(message):
        engine.requests.assert_bound_request(message)
        return message.conversation_id

    class TranscriptHistoryTools:
        async def search_history(self, message, inp):
            from .search import TranscriptSearch

            search = TranscriptSearch(engine.requests.transcript, engine.requests.events,
                                      current_conversation=current_conversation)
            bound = KnowledgeTools(sessions=search.for_request(message),
                get_knowledge_store=lambda: knowledge, embedder=embedder, audit=audit)
            return await bound._handle_search_history(inp)

    owners.setdefault("channel_ops", ChannelOpsTools(read_visible_history=read_history))
    owners.setdefault("scheduling", SchedulingTools(scheduler=scheduler, tool_catalog=catalog))
    owners.setdefault("knowledge", KnowledgeTools(sessions=sessions,
        get_knowledge_store=lambda: knowledge, embedder=embedder, audit=audit))
    publication_tool = ContextVar("desktop_media_publication_tool", default=None)

    class DesktopMediaTools(MediaTools):
        """Adapt only the copied media handler's durable-publication seam."""

        def _delivery_available(self):
            return engine.requests is not None

        async def _publish_attachment(self, message, data, filename, caption=""):
            from ..tools.output_authorization import accessed_hosts
            from .delivery import ArtifactPost

            engine.requests.assert_bound_request(message)
            tool = publication_tool.get()
            if tool is None:
                raise PermissionError("No admitted artifact producer")
            mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            artifact = ArtifactPost(data, filename, mime,
                "image" if mime.startswith("image/") else "file", tool,
                tuple((accessed_hosts.get() or {}).values()))
            return await delivery.send(message.channel, caption, files=[artifact])

        async def _handle_generate_file(self, message, inp):
            token = publication_tool.set("generate_file")
            try:
                return await super()._handle_generate_file(message, inp)
            finally:
                publication_tool.reset(token)

        async def _handle_post_file(self, message, inp):
            token = publication_tool.set("post_file")
            try:
                return await super()._handle_post_file(message, inp)
            finally:
                publication_tool.reset(token)

    owners.setdefault("media", DesktopMediaTools(
        get_config=get_config, browser_manager=browser, tool_executor=executor))
    owners["transcript_history"] = TranscriptHistoryTools()
    dispatcher = _ReadyDispatcher(owners=owners, skill_manager=skills, tool_catalog=catalog,
        prompt_builder=prompt, channel_state=state, builtin_policy=policy)
    compression = getattr(runtime, "context_compressor", cc.context_compression if cc.context_compression.enabled else None)
    d = SimpleNamespace(get_config=get_config, paths=paths, permissions=permissions,
        sessions=sessions, tool_executor=executor, channel_state=state, turn_store=ledger,
        durability_reason=durability_reason, compatible_skipped=compatible_skipped,
        llm_gateway=gateway, prompt_builder=prompt, tool_catalog=catalog, native_tools=dispatcher,
        delivery=delivery, turn_recorder=recorder, completion_classifier=completion,
        skill_manager=skills, audit=audit, agent_manager=agents, loop_manager=loops,
        host_registry=hosts, host_access_manager=access, scheduler=scheduler, reflector=reflector,
        context_loader=context, browser_manager=browser, readiness=readiness, runtime_context=runtime)
    engine = EngineServices(d, None)
    runner = ToolLoopRunner(ToolLoopDeps(get_config=get_config,
        get_default_system_prompt=lambda: prompt.default_prompt, get_context_compressor=lambda: compression,
        get_compression_stats=lambda: getattr(runtime, "compression_stats", None),
        llm_gateway=gateway, prompt_builder=prompt, tool_catalog=catalog, channel_state=state,
        delivery=delivery, turn_recorder=recorder, completion_classifier=completion,
        native_tools=dispatcher, tool_executor=executor, permissions=permissions,
        skill_manager=skills, audit=audit, loop_manager=loops, stuck_loop_tracker_cls=StuckLoopTracker,
        turn_store=ledger, window_observer=getattr(runtime, "window_observer", None), mcp_manager=mcp,
        kill_agents_for_turn=agents.kill_for_turn, get_computer=lambda: owners.get("computer"),
        assert_request=engine._assert_request, request_admission=engine._admit_turn))
    engine.runner = runner
    owners.setdefault("agents", AgentTaskTools(AgentTaskDeps(get_config=get_config,
        llm_gateway=gateway, channel_state=state, tool_executor=executor, skill_manager=skills,
        get_knowledge_store=lambda: knowledge, embedder=embedder, audit=audit, agent_manager=agents,
        loop_manager=loops, agent_trajectory_saver=agent_trajectories,
        get_context_compressor=lambda: compression, tool_loop=runner, turn_recorder=recorder,
        prompt_builder=prompt, tool_catalog=catalog, mcp_manager=mcp)))
    register_native_handlers(dispatcher)
    # Keep the upstream formatter but bind its sessions façade to this exact
    # admitted request's durable transcript, never compacted session history.
    dispatcher._handlers["search_history"] = ("transcript_history", "search_history", "msg_input")
    d.housekeeping = Housekeeping(get_config=get_config, sessions=sessions, channel_state=state,
        prompt_builder=prompt, agent_manager=agents, channel_logger=None, fts_index=None, turn_store=ledger)
    prompt.rebuild_default()
    if request_service is not None:
        engine.bind_requests(request_service)
    return engine
