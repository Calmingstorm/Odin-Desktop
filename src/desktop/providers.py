"""One retained provider graph, with profile-owned transactional replacement.

Construction does not unlock the keyring, open sessions or probe endpoints.
Settings supply this object as each dedicated provider owner. Preparation builds
unpublished transports; apply qualifies them and atomically replaces the graph.
The copied gateway and concrete clients still own generation leases, streaming,
recovery, quota and auxiliary fallback behavior.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..discord.llm_gateway import LLMGateway
from ..llm import CodexChatClient, OllamaClient, OpenAICompatibleClient
from ..llm.auxiliary import AuxiliaryLLMClient
from ..llm.client_lifecycle import shutdown_provider_clients
from ..llm.model_ref import parse_model_ref
from ..llm.openai_compatible import preset_context_overflow_pattern
from .management import MethodError
from .secrets import SecretStoreError

_ATTRS = {"codex": "codex_client", "ollama": "ollama_client", "compat": "compatible_client"}


def _unavailable(message):
    return MethodError("unavailable", message)


@dataclass
class _ProviderChange:
    owner: ProviderOwner
    config: object
    generation: int
    clients: dict
    auxiliary: object
    created: list = field(default_factory=list)
    probes: list = field(default_factory=list)
    committed: bool = False

    async def qualify(self):
        for kind, client in self.probes:
            reason = await (
                self.owner._probe_openai_compatible(client)
                if kind == "compat"
                else self.owner._probe_aux(client)
            )
            if reason:
                raise _unavailable(reason)

    def publish(self):
        owner = self.owner
        if owner._closed or owner._generation != self.generation:
            raise _unavailable("Provider generation changed; retry settings")
        old = [getattr(owner, name) for name in _ATTRS.values()]
        old.append(owner.auxiliary_llm_client)
        # All fallible qualification and persistence precede this synchronous
        # publication. No event-loop yield can split config/client identity.
        owner._effective_config = self.config
        for name, client in self.clients.items():
            setattr(owner, _ATTRS[name], client)
        owner.auxiliary_llm_client = self.auxiliary
        owner._generation += 1
        self.committed = True
        live = list(self.clients.values()) + [self.auxiliary]
        for client in old:
            if client is not None and not any(client is current for current in live):
                owner._retire(client)
        # Consumer-cache failures cannot turn a committed client publication
        # into a fictitious rollback of already-retired generations.
        try:
            owner.wire_callbacks()
        except Exception:
            from ..odin_log import get_logger

            get_logger("desktop.providers").warning("Provider adopted; callback wiring failed")

    async def apply(self):
        try:
            async with self.owner.provider_lock:
                await self.qualify()
                self.publish()
            return {"committed": True}
        except BaseException:
            await self.rollback()
            raise

    async def rollback(self):
        if self.committed:
            return
        created, self.created = self.created, []
        for client in reversed(created):
            await client.close()


class ProviderOwner(LLMGateway):
    """Profile provider owner. ``codex`` is the lazy CodexAccountsService.

    ``settings.owners[method] = owner`` for each ``providers.*.set`` method.
    ``ensure_ready()`` is explicit runtime admission, never a constructor side
    effect. ``switch_provider`` accepts the model-settings synchronous persist
    callback; false/None means an effective-only switch without a disk write.
    """

    METHODS = frozenset(
        {
            "providers.codex.set",
            "providers.ollama.set",
            "providers.compat.set",
            "providers.auxiliary.set",
        }
    )

    def __init__(self, settings, codex, executor=None, **gateway_dependencies):
        self.settings = settings
        self.codex_accounts = codex
        self.executor = executor
        self._effective_config = settings.config.model_copy(deep=True)
        self._generation = 0
        self._closed = False
        self.tool_catalog = getattr(executor, "tool_catalog", None)
        self.prompt_builder = getattr(executor, "prompt_builder", None)
        dependencies = dict(
            get_config=lambda: self.settings.config,
            codex_client=None,
            ollama_client=None,
            kimi_client=None,
            subsystem_guard=getattr(executor, "subsystem_guard", None),
            auxiliary_llm_client=None,
            cost_tracker=getattr(executor, "cost_tracker", None),
            sessions=getattr(executor, "sessions", None),
            reflector=getattr(executor, "reflector", None),
        )
        dependencies.update(gateway_dependencies)
        super().__init__(**dependencies)

    @property
    def main(self):
        return self.capture_serving_identity().client

    def capture_serving_identity(self, config=None):
        # Dedicated transactions may already have saved desired settings while
        # qualification is pending. Identity remains the adopted graph, never
        # the settings candidate. Other gateway policy reads remain live.
        return super().capture_serving_identity(config or self._effective_config)

    @property
    def codex(self):
        return self.codex_client

    @property
    def ollama(self):
        return self.ollama_client

    @property
    def compat(self):
        return self.compatible_client

    @property
    def auxiliary(self):
        return self.auxiliary_llm_client

    def wire_callbacks(self):
        # Retained callback wiring needs both session consumers. No dummy
        # sessions or copied provider instances are manufactured for step 5.
        if self.sessions is not None and self.reflector is not None:
            super().wire_callbacks()
        for component in (self.tool_catalog, self.prompt_builder):
            invalidate = getattr(component, "invalidate", None)
            if callable(invalidate):
                try:
                    invalidate()
                except Exception:
                    # Cache invalidation cannot roll back an adopted graph.
                    pass

    def _retire(self, client):
        retire = getattr(client, "retire", None)
        if retire is not None:
            retire()
        self._schedule_drain(client)
        for task, owned in self._draining_clients.items():
            if owned is client:
                task.add_done_callback(self._observe_drain)

    @staticmethod
    def _observe_drain(task):
        if not task.cancelled():
            task.exception()

    def _credential(self, path, config, overrides=None):
        if overrides is not None and path in overrides:
            return overrides[path]
        try:
            value = self.settings.secrets.get(path)
        except SecretStoreError:
            raise _unavailable("Profile keyring is unavailable or locked") from None
        # In-memory hydrated values are legitimate; never consult provider
        # credential files, environment variables or another profile.
        section, leaf = path.split(".")
        return value if value is not None else getattr(getattr(config, section), leaf)

    def _build(self, provider, config, *, model=None, auxiliary=False, overrides=None):
        if provider == "codex":
            cfg = config.openai_codex
            if not cfg.enabled:
                return None
            try:
                pool = self.codex_accounts.pool
                if not pool.is_configured():
                    return None
            except SecretStoreError:
                raise _unavailable("Profile keyring is unavailable or locked") from None
            return CodexChatClient(
                auth=pool,
                model=model or cfg.model,
                reasoning_effort=None if auxiliary else cfg.reasoning_effort,
                max_retries=cfg.retry.max_retries,
                retry_base_delay=cfg.retry.base_delay,
                retry_max_delay=cfg.retry.max_delay,
                pool_max_connections=cfg.connection_pool.max_connections,
                pool_keepalive_timeout=cfg.connection_pool.keepalive_timeout,
                request_timeout=cfg.request_timeout_seconds,
                stream_stall_timeout=cfg.stream_stall_timeout_seconds,
            )
        if provider == "ollama":
            cfg = config.ollama
            if not cfg.enabled:
                return None
            return OllamaClient(
                base_url=cfg.base_url,
                model=model or cfg.model,
                max_tokens=cfg.max_tokens,
                num_ctx=cfg.num_ctx,
                timeout=cfg.timeout,
                api_key=self._credential("ollama.api_key", config, overrides),
            )
        cfg = config.openai_compatible
        if not cfg.enabled:
            return None
        key = self._credential("openai_compatible.api_key", config, overrides)
        if not key:
            return None
        return OpenAICompatibleClient(
            api_key=key,
            model=model or cfg.model,
            base_url=cfg.base_url,
            provider_name="compat",
            max_tokens=cfg.max_tokens,
            request_timeout_seconds=cfg.request_timeout_seconds,
            stream_stall_timeout_seconds=cfg.stream_stall_timeout_seconds,
            tool_quirks=self._compatible_quirks(cfg),
            context_overflow_pattern=preset_context_overflow_pattern(cfg.preset),
            reasoning_dialect=self._compatible_reasoning_dialect(cfg),
            glm_clear_thinking=cfg.glm_clear_thinking,
            reasoning_content_feedback_policy=cfg.reasoning_content_feedback_policy,
            openrouter_routing=cfg.openrouter if cfg.preset == "openrouter" else None,
            model_profiles=cfg.model_profiles,
        )

    def _prepare_graph(
        self,
        config,
        targets,
        *,
        require=None,
        overrides=None,
        strict_aux=False,
        allow_unconfigured=False,
    ):
        if self._closed:
            raise _unavailable("Provider owner is closed")
        clients = {name: getattr(self, attr) for name, attr in _ATTRS.items()}
        change = _ProviderChange(self, config, self._generation, clients, None)
        try:
            main = parse_model_ref(config.llm_provider.model, allow_auto=False)
            for provider in targets:
                model = main.model if main.provider.value == provider else None
                client = self._build(provider, config, model=model, overrides=overrides)
                section = {
                    "codex": config.openai_codex,
                    "ollama": config.ollama,
                    "compat": config.openai_compatible,
                }[provider]
                clearing = (
                    overrides is not None
                    and overrides.get(
                        {"ollama": "ollama.api_key", "compat": "openai_compatible.api_key"}.get(
                            provider
                        )
                    )
                    == ""
                )
                if client is None and (
                    require == provider
                    or (section.enabled and not clearing and not allow_unconfigured)
                ):
                    raise _unavailable(f"{provider} is not configured")
                clients[provider] = client
                if client is not None:
                    change.created.append(client)
                    if provider == "compat":
                        change.probes.append(("compat", client))
            if require and clients.get(require) is None:
                raise _unavailable(f"{require} is not configured")
            aux_cfg = config.openai_codex.auxiliary
            if aux_cfg.enabled:
                aux_ref = parse_model_ref(aux_cfg.model, allow_auto=False)
                provider = aux_ref.provider.value
                primary = clients.get(main.provider.value)
                if primary is None:
                    if strict_aux:
                        raise _unavailable("Auxiliary primary provider is unavailable")
                    return change  # saved auxiliary intent, explicitly unavailable
                if provider == "codex":
                    client = self._build("codex", config, model=aux_ref.model, auxiliary=True)
                    if client is not None:
                        change.created.append(client)
                else:
                    client = clients.get(provider)
                if client is None:
                    if strict_aux:
                        raise _unavailable("Selected auxiliary provider is unavailable")
                    return change
                change.auxiliary = AuxiliaryLLMClient(
                    client,
                    primary,
                    self.cost_tracker,
                    provider=provider,
                    model=aux_ref.model,
                    owns_aux_client=provider == "codex",
                    primary_model=main.model,
                )
                if provider == "codex":
                    change.probes.append(("aux", client))
                else:
                    from types import SimpleNamespace

                    probe = SimpleNamespace(
                        chat=lambda messages, system, **kw: client.chat(
                            messages, system, model=aux_ref.model, **kw
                        )
                    )
                    change.probes.append(("aux", probe))
            return change
        except BaseException:
            # Constructors have not opened sessions. Drain lazily on the loop
            # to keep prepare synchronous for the settings transaction seam.
            for client in change.created:
                self._retire(client)
            raise

    def prepare_settings(self, candidate, changes):
        paths = [".".join(path) if not isinstance(path, str) else path for path, _ in changes]
        targets = set()
        for prefix, name in (
            ("openai_codex.", "codex"),
            ("ollama.", "ollama"),
            ("openai_compatible.", "compat"),
        ):
            if any(
                path.startswith(prefix) and not path.startswith("openai_codex.auxiliary")
                for path in paths
            ):
                targets.add(name)
        overrides = {
            path: value
            for path, (_, value) in zip(paths, changes)
            if path in {"ollama.api_key", "openai_compatible.api_key"}
        }
        return self._prepare_graph(
            candidate.model_copy(deep=True),
            targets,
            overrides=overrides,
            strict_aux=any(path.startswith("openai_codex.auxiliary") for path in paths),
        )

    def prepare_reload(self, candidate, changes):
        """Prepare one graph for a composition-owned whole-config reload.

        The composite must qualify under provider_lock, apply its other owners
        with rollback on failure, then publish synchronously. Calling separate
        dedicated provider applies is not atomic. This token exposes qualify,
        publish and rollback expressly for that single composition transaction.
        """
        paths = [".".join(path) if not isinstance(path, str) else path for path, _ in changes]
        targets = {
            name
            for prefix, name in (
                ("openai_codex.", "codex"),
                ("ollama.", "ollama"),
                ("openai_compatible.", "compat"),
            )
            if any(
                path.startswith(prefix) and not path.startswith("openai_codex.auxiliary")
                for path in paths
            )
        }
        main = parse_model_ref(candidate.llm_provider.model, allow_auto=False).provider.value
        switching = any(path.startswith("llm_provider.") for path in paths)
        if switching:
            targets.add(main)
        overrides = {
            path: value
            for path, (_, value) in zip(paths, changes)
            if path in {"ollama.api_key", "openai_compatible.api_key"}
        }
        return self._prepare_graph(
            candidate.model_copy(deep=True),
            targets,
            require=main if switching else None,
            overrides=overrides,
            strict_aux=any(path.startswith("openai_codex.auxiliary") for path in paths),
        )

    async def ensure_ready(self):
        """Explicit admission after provisioning, not a network startup hook."""
        async with self.provider_lock:
            config = self.settings.config.model_copy(deep=True)
            provider = parse_model_ref(config.llm_provider.model, allow_auto=False).provider.value
            targets = {
                name
                for name in _ATTRS
                if getattr(self, _ATTRS[name]) is None
                and getattr(
                    config,
                    {"codex": "openai_codex", "ollama": "ollama", "compat": "openai_compatible"}[
                        name
                    ],
                ).enabled
            }
            change = self._prepare_graph(config, targets, require=provider)
            try:
                await change.qualify()
                change.publish()
            except BaseException:
                await change.rollback()
                raise
        return self.capture_serving_identity()

    async def _reload(self, provider=None, *, auxiliary=False):
        async with self.provider_lock:
            config = self.settings.config.model_copy(deep=True)
            change = self._prepare_graph(
                config,
                {provider} if provider else set(),
                strict_aux=auxiliary,
                allow_unconfigured=provider == "codex",
            )
            try:
                await change.qualify()
                change.publish()
            except BaseException:
                await change.rollback()
                raise
        if auxiliary:
            return {"committed": True, "effective_enabled": self.auxiliary is not None}
        return {"configured": self._provider_client(provider) is not None, "reloaded": True}

    async def reload_codex(self):
        # Never inherit the gateway's credentials_path file constructor.
        return await self._reload("codex")

    async def reload_ollama(self):
        return await self._reload("ollama")

    async def reload_openai_compatible(self):
        return await self._reload("compat")

    reload_kimi = reload_openai_compatible

    async def reload_auxiliary(self, desired=None, persist=None, *, plan=None):
        # Settings own desired-state/persistence transactions. This entry point
        # refreshes the already-saved profile, not an unjournaled second owner.
        if desired is not None or persist is not None or plan is not None:
            raise ValueError("Use the dedicated profile settings transaction")
        return await self._reload(auxiliary=True)

    async def switch_provider(self, provider, persist=False, *, model_ref=None):
        provider = "compat" if provider == "kimi" else provider
        if provider not in _ATTRS:
            return {"error": "Unknown provider"}
        # Match SettingsService ordering: its async transaction gate precedes
        # provider_lock. Otherwise a settings apply holding the file lock and
        # waiting for this provider could deadlock the persist worker.
        async with self.settings._async_lock, self.provider_lock:
            self.switching = True
            change = None
            cancelled = False
            try:
                config = self.settings.config.model_copy(deep=True)
                section = {
                    "codex": config.openai_codex,
                    "ollama": config.ollama,
                    "compat": config.openai_compatible,
                }[provider]
                ref = parse_model_ref(
                    model_ref
                    or (section.model if provider == "codex" else f"{provider}:{section.model}"),
                    allow_auto=False,
                )
                if ref.provider.value != provider:
                    return {"error": "Model reference does not match provider"}
                config.llm_provider.model = ref.render()
                config.llm_provider.active_provider = provider
                change = self._prepare_graph(config, {provider}, require=provider)
                await change.qualify()
                if callable(persist):
                    error, cancelled = await self.run_persist_settled(persist)
                    if error is not None:
                        if cancelled:
                            raise asyncio.CancelledError
                        return {"error": "persist failed"}
                elif persist not in (False, None):
                    return {"error": "Persistence callback required"}
                change.publish()
            except (MethodError, ValueError):
                return {"error": "Selected provider is unavailable or model is invalid"}
            finally:
                self.switching = False
                if change is not None and not change.committed:
                    await change.rollback()
        if cancelled:
            raise asyncio.CancelledError
        serving = self.capture_serving_identity()
        return {"provider": serving.provider, "model": serving.model}

    async def close(self):
        self._closed = True
        await shutdown_provider_clients(self)
