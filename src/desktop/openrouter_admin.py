"""OpenRouter administration against the profile's real settings/runtime owners.

Public catalogue and auth-scoped endpoint caches are the retained Odin helpers.
Selection only adopts routing policy, not a new transport or main-model switch.
Remote awaits precede the owner locks; policy is rebuilt after those awaits.
"""
from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

import aiohttp
from aiohttp import web
from pydantic import ValidationError

from ..config.schema import OpenAICompatibleModelProfile
from ..llm.context_budget import compatible_agent_unavailable_reason
from ..llm.openrouter import conservative_profile, is_openrouter_base_url, openrouter_variant
from ..observability.diagnostics import safe_text, scrub_diagnostic
from ..web.api import llm_admin
from .management import MethodError
from .secrets import SecretStoreError, secret_call

METHODS = frozenset({
    "openrouter.catalogue", "openrouter.endpoints", "openrouter.select",
    "providers.compat.diagnostic",
    "models.status", "models.provider.get", "models.provider.set",
})
READ_METHODS = METHODS - {"openrouter.select", "models.provider.set"}


class OpenRouterAdminService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, settings, *, provider=None, usage=None):
        self.settings = settings
        self.provider = provider
        self.usage = usage

    def _config(self):
        cfg = self.settings.config.openai_compatible
        return cfg if is_openrouter_base_url(cfg.base_url) else None

    async def _key(self, cfg):
        try:
            key = await secret_call(self.settings.secrets.get, "openai_compatible.api_key")
        except SecretStoreError:
            raise MethodError("unavailable", "Profile keyring is unavailable or locked") from None
        # Already-hydrated profile config is legitimate, never files/env/another
        # transport's stale credential. Vault failures do not fall back.
        return key if key is not None else cfg.api_key

    async def _safe_result(self, value):
        """Scrub diagnostic copies only; policy/model inputs remain untouched."""
        result = scrub_diagnostic(value)
        # Credential-presence flags are public metadata, not credential values.
        # The generic diagnostic suffix rule intentionally cannot infer that.
        def presence(original, scrubbed):
            if isinstance(original, dict) and isinstance(scrubbed, dict):
                for key, child in original.items():
                    if key == "has_api_key" and isinstance(child, bool):
                        scrubbed[key] = child
                    elif key in scrubbed:
                        presence(child, scrubbed[key])
            elif isinstance(original, list) and isinstance(scrubbed, list):
                for child, clean_child in zip(original, scrubbed):
                    presence(child, clean_child)
        presence(value, result)
        client = getattr(self.provider, "compatible_client", None)
        credentials = [self.settings.config.openai_compatible.api_key,
                       getattr(client, "api_key", None)]
        try:
            credentials.append(await secret_call(
                self.settings.secrets.get, "openai_compatible.api_key",
            ))
        except SecretStoreError:
            pass
        secrets = {item for item in credentials if isinstance(item, str) and item}

        def clean(item):
            if isinstance(item, str):
                for secret in secrets:
                    item = item.replace(secret, "[REDACTED]")
                return item
            if isinstance(item, dict):
                return {clean(key): clean(child) for key, child in item.items()}
            if isinstance(item, list):
                return [clean(child) for child in item]
            return item
        return clean(result)

    async def handle(self, method: str, params: dict[str, Any]):
        if method not in METHODS:
            raise MethodError("unknown_method", f"Unknown management method: {method}")
        if not isinstance(params, dict):
            raise MethodError("bad_request", "expected JSON object")
        try:
            if method == "models.status":
                return await self._model_status()
            if method == "models.provider.get":
                return self._provider_get()
            if method == "models.provider.set":
                return await self._provider_set(params)
            if method == "providers.compat.diagnostic":
                return await self._diagnostic()
            cfg = self._config()
            if cfg is None:
                raise MethodError("not_found", "OpenRouter endpoint not recognized")
            if method == "openrouter.catalogue":
                return await self._catalogue(cfg)
            model = params.get("model")
            if not isinstance(model, str):
                raise ValueError("OpenRouter model id must be a namespaced vendor/model id")
            # Same encoding and validation as Odin's endpoint helper.
            from ..llm.openrouter import model_detail_path
            model_detail_path(model)
            if method == "openrouter.endpoints":
                rows = await llm_admin._openrouter_endpoint_rows(model, api_key=await self._key(cfg))
                return await self._safe_result({
                    "model": model, "endpoints": rows,
                    "effective_profile": conservative_profile(rows, cfg.openrouter, model=model),
                })
            return await self._select(cfg, model, params)
        except web.HTTPBadGateway as exc:
            raise MethodError("unavailable", safe_text(exc.text)) from None
        except ValidationError:
            # Pydantic's repr includes submitted values and possibly auth.
            raise MethodError("bad_request", "Invalid OpenRouter model policy") from None
        except ValueError as exc:
            raise MethodError("bad_request", await self._safe_result(safe_text(exc))) from None
        except (aiohttp.ClientError, TimeoutError, OSError, RuntimeError) as exc:
            raise MethodError(
                "unavailable", f"{type(exc).__name__}: OpenRouter request failed"
            ) from None

    async def _catalogue(self, cfg):
        models, stale, error = await llm_admin._openrouter_models(cfg)
        configured = cfg.model_profiles
        derived_profiles = cfg.openrouter.catalogue_profiles
        requested = set(cfg.openrouter.model_pins)
        requested.update(
            ref.removeprefix("compat:")
            for item in self.settings.config.agents.auto_model_allowlist
            for ref in [item if isinstance(item, str) else item.model]
            if ref.startswith("compat:")
        )
        requested.add(cfg.model)
        requested = {model for model in requested if any(row["id"] == model for row in models)}
        details = {}
        for model in requested:
            try:
                details[model] = await llm_admin._openrouter_endpoint_rows(
                    model, api_key=await self._key(cfg)
                )
            except MethodError:
                raise
            except Exception:
                # Endpoint enrichment is advisory. No exception contents enter
                # the result or logs, matching the catalogue's best-effort shape.
                pass
        projected = []
        for model in models:
            item = dict(model)
            profile = configured.get(model["id"])
            derived_profile = derived_profiles.get(model["id"])
            derived = derived_profile.model_dump() if derived_profile is not None else None
            override = profile.model_dump() if profile is not None else None
            item["profile"] = override or derived
            item["profile_source"] = (
                "operator" if override else "openrouter_catalogue" if derived else None
            )
            item["profile_conflict"] = bool(override and derived and (
                override["total_window_tokens"] != derived["total_window_tokens"]
                or override["max_output_tokens"] != derived["max_output_tokens"]
            ))
            item["endpoints"] = details.get(model["id"], [])
            if item["variant"] == "standard" and item["supports_tools"]:
                preview = profile or derived_profile
                if (preview is None and model.get("context_length")
                        and model.get("max_completion_tokens")):
                    preview = OpenAICompatibleModelProfile(
                        total_window_tokens=model["context_length"],
                        max_output_tokens=model["max_completion_tokens"],
                    )
                preview_cfg = cfg.model_copy(
                    update={"model_profiles": {**configured, model["id"]: preview}}
                ) if preview is not None else cfg
                reason = compatible_agent_unavailable_reason(model["id"], preview_cfg)
                item["agent_eligible"] = reason is None
                item["agent_unavailable_reason"] = reason
            projected.append(item)
        from ..tools.model_hints import MODEL_HINT_CATALOGUE
        quick = []
        for key in MODEL_HINT_CATALOGUE:
            if len(quick) >= 8:
                break
            if key not in {"openrouter/auto", "openrouter/auto-beta"} and any(
                item["id"] == key and item["agent_eligible"] for item in projected
            ):
                quick.append(f"compat:{key}")
        measured = []
        usage = self.usage() if callable(self.usage) else self.usage
        if usage is not None:
            try:
                measured = (await usage.summary("30d")).get("upstream_cache", [])
            except Exception:
                pass
        return await self._safe_result({
                "recognized": True, "fetched_at": llm_admin._openrouter_cache.get("fetched_at"),
                "stale": stale, "refresh_error": error, "models": projected,
                "quick_add": quick, "routing": cfg.openrouter.model_dump(),
                "measured_cache": measured})

    @staticmethod
    def _candidate(cfg, model, pin, rows, catalogue_model):
        routing = cfg.openrouter.model_dump()
        pins = dict(cfg.openrouter.model_pins)
        if pin:
            pins[model] = pin
        else:
            pins.pop(model, None)
        routing["model_pins"] = pins
        policy = type(cfg.openrouter).model_validate(routing)
        profile = conservative_profile(rows, policy, model=model, require_reasoning=True)
        if profile is None:
            raise ValueError("no tool-capable endpoint can provide a safe model profile")
        value = OpenAICompatibleModelProfile(
            total_window_tokens=profile["total_window_tokens"],
            max_output_tokens=profile["max_output_tokens"], supports_thinking_mode=False,
            supports_reasoning=bool(catalogue_model.get("supports_reasoning")),
            supported_efforts=catalogue_model.get("supported_efforts") or [],
        )
        derived = dict(cfg.openrouter.catalogue_profiles)
        derived[model] = value
        routing["catalogue_profiles"] = {name: item.model_dump() for name, item in derived.items()}
        return type(cfg.openrouter).model_validate(routing), value, profile

    async def _select(self, cfg, model, params):
        if openrouter_variant(model) != "standard":
            raise ValueError("free and batch variants are not eligible for ordinary agents")
        pin = str(params.get("provider_tag") or "").strip()
        rows = await llm_admin._openrouter_endpoint_rows(model, api_key=await self._key(cfg))
        if pin and pin not in {str(row.get("tag")) for row in rows}:
            raise ValueError("provider_tag must be an endpoint tag returned by OpenRouter")
        # Preserve the early unsafe-profile error before the catalogue await.
        self._candidate(cfg, model, pin, rows, {})
        models, _, _ = await llm_admin._openrouter_models(cfg)
        catalogue_model = next((item for item in models if item["id"] == model), None)
        if catalogue_model is None:
            raise ValueError("model is absent from the OpenRouter catalogue")
        async with AsyncExitStack() as locks:
            await locks.enter_async_context(self.settings._async_lock)
            if self.provider is not None:
                await locks.enter_async_context(self.provider.provider_lock)
            cfg = self._config()
            if cfg is None:
                raise MethodError(
                    "stale_binding", "OpenRouter configuration changed", "stale_binding"
                )
            candidate, value, profile = self._candidate(cfg, model, pin, rows, catalogue_model)
            changes = [(("openai_compatible", "openrouter"), candidate.model_dump())]
            try:
                self.settings.save_changes(changes, method="providers.compat.set",
                                           expected_revision=params.get("expected_revision"))
            except MethodError as exc:
                if exc.code == "stale_binding":
                    raise
                raise MethodError("internal_error", "OpenRouter model policy not saved") from None
            # No await after persistence until routing adoption and confirmation.
            client = getattr(self.provider, "compatible_client", None)
            if client is not None:
                client.openrouter_routing = self.settings.config.openai_compatible.openrouter
                effective = getattr(self.provider, "_effective_config", None)
                if effective is not None:
                    effective.openai_compatible.openrouter = client.openrouter_routing
                self.settings.confirm_applied(changes)
            catalog = getattr(self.provider, "tool_catalog", None)
            if catalog is not None:
                catalog.invalidate()
        return await self._safe_result({
                "model": model, "provider_tag": pin or None, "profile": value.model_dump(),
                "effective_profile": profile})

    async def _diagnostic(self):
        client = getattr(self.provider, "compatible_client", None)
        if client is None:
            raise MethodError("unavailable", "OpenAI-compatible provider not configured")
        health = await client.health_check()
        # Retain unhealthy evidence rather than erase it behind a generic error.
        return await self._safe_result({"configured": True,
            "provider": getattr(client, "provider_name", "openai_compatible"),
            "base_url": client.base_url, "model": client.model,
            "health": health, "stats": client.pool_stats()})

    def _provider_get(self):
        configured = self.settings.config.llm_provider.active_provider
        serving = self.provider.capture_serving_identity() if self.provider is not None else None
        live = serving is not None and serving.client is not None
        return {"active_provider": configured, "configured_provider": configured,
                "serving_provider": serving.provider if live else None,
                "active_model": serving.model if live else None}

    async def _provider_set(self, params):
        from ..llm.model_ref import parse_model_ref
        from .model_settings import ModelSettingsService

        provider = params.get("provider", "")
        if provider == "openai_compatible":
            provider = "compat"
        if provider not in ("codex", "ollama", "compat"):
            raise ValueError("provider must be 'codex', 'ollama', or 'compat'")
        config = self.settings.config
        default = {"codex": config.openai_codex.model,
                   "ollama": f"ollama:{config.ollama.model}",
                   "compat": f"compat:{config.openai_compatible.model}"}[provider]
        parsed = parse_model_ref(params.get("model") or default, allow_auto=False)
        if parsed.provider.value != provider:
            raise ValueError("model provider does not match provider")
        return await ModelSettingsService(self.settings, provider=self.provider).handle(
            "models.main.set", {**params, "model": parsed.render()})

    async def _model_status(self):
        """Retained status fields, sourced from the real profile and provider graph."""
        from types import SimpleNamespace

        from ..llm.compatible_presets import HOSTED_PROVIDER_PRESETS, LOCAL_BASE_URL_EXAMPLES

        config = self.settings.config
        owner = self.provider
        codex = config.openai_codex
        ollama = config.ollama
        compat = config.openai_compatible
        codex_client = getattr(owner, "codex_client", None)
        ollama_client = getattr(owner, "ollama_client", None)
        compatible_client = getattr(owner, "compatible_client", None)
        # This concrete bundle only supplies retained pure projection helpers;
        # it does not implement or stand in for any runtime behavior.
        projection = SimpleNamespace(config=config, llm_gateway=owner,
                                     boot_config_snapshot=self.settings._boot)
        if is_openrouter_base_url(compat.base_url):
            try:
                await llm_admin._openrouter_models(compat)
            except web.HTTPException:
                pass
        desired_pool = codex.connection_pool.model_dump()
        desired_compression = codex.context_compression.model_dump()
        effective_pool, pool_pending = llm_admin._boot_codex_group_status(
            projection, "connection_pool", desired_pool)
        effective_compression, compression_pending = llm_admin._boot_codex_group_status(
            projection, "context_compression", desired_compression)
        result = {**self._provider_get(), "main_model": config.llm_provider.model,
            "codex": {"configured": codex_client is not None, "enabled": codex.enabled,
                "model": codex.model, "reasoning_effort": codex.reasoning_effort,
                "active_reasoning_effort": getattr(codex_client, "reasoning_effort", None),
                "agent_reasoning_effort": codex.agent_reasoning_effort,
                "effective_agent_reasoning_effort": codex.agent_reasoning_effort
                    if codex.agent_reasoning_effort not in (None, "auto")
                    else getattr(codex_client, "reasoning_effort", None),
                "agent_model": codex.agent_model,
                "effective_agent_model": codex.agent_model
                    if codex.agent_model not in (None, "auto") else codex.model,
                "request_timeout_seconds": codex.request_timeout_seconds,
                "stream_stall_timeout_seconds": codex.stream_stall_timeout_seconds,
                "retry": codex.retry.model_dump(), "connection_pool": desired_pool,
                "effective_connection_pool": effective_pool,
                "connection_pool_pending_restart": pool_pending,
                "context_compression": desired_compression,
                "effective_context_compression": effective_compression,
                "context_compression_pending_restart": compression_pending,
                "context_budget_overrides": dict(codex.context_budget_overrides),
                "context_utilization": codex.context_utilization},
            "ollama": {"configured": ollama_client is not None, "enabled": ollama.enabled,
                "model": ollama.model, "base_url": ollama.base_url,
                "max_tokens": ollama.max_tokens, "num_ctx": ollama.num_ctx,
                "timeout": ollama.timeout, "has_api_key": bool(ollama.api_key)},
            "openai_compatible": {"configured": compatible_client is not None,
                "enabled": compat.enabled, "model": compat.model, "base_url": compat.base_url,
                "max_tokens": compat.max_tokens,
                "request_timeout_seconds": compat.request_timeout_seconds,
                "stream_stall_timeout_seconds": compat.stream_stall_timeout_seconds,
                "reasoning_effort": compat.reasoning_effort, "preset": compat.preset,
                "preset_catalogue": HOSTED_PROVIDER_PRESETS,
                "local_base_url_examples": LOCAL_BASE_URL_EXAMPLES,
                "model_profiles": {name: profile.model_dump()
                                   for name, profile in compat.model_profiles.items()},
                "context_utilization": compat.context_utilization,
                "openrouter": compat.openrouter.model_dump(),
                "openrouter_recognized": is_openrouter_base_url(compat.base_url),
                "has_api_key": bool(await self._key(compat))},
            "auxiliary": llm_admin._auxiliary_status(projection),
            "model_choices": {
                "codex": {"configured": codex_client is not None, "models": [codex.model]},
                "compat": {"configured": compatible_client is not None,
                           "models": [f"compat:{compat.model}"]},
                "ollama": {"configured": ollama_client is not None,
                           "models": [f"ollama:{ollama.model}"]}},
            "model_catalogue": llm_admin._model_catalogue(projection,
                codex_configured=codex_client is not None,
                ollama_configured=ollama_client is not None)}
        serving = owner.capture_serving_identity() if owner is not None else None
        if serving is not None and serving.client is not None:
            result["active_model"] = serving.model
            result["active_provider_name"] = serving.provider
        return await self._safe_result(result)
