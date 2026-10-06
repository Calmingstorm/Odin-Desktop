"""Private management adapters for model, personality and tool settings.

Persistence belongs to SettingsService. Main-model adoption belongs to an
injected real gateway implementing ``switch_provider(provider, persist=...,
model_ref=...)``: it must settle persistence and restore runtime on failure.
Optional ``tool_catalog`` and ``prompt_builder`` references on that owner are
the actual caches, never stand-in managers. Inventory readiness comes only
from the executor's live built-in policy, not from installed definitions.
"""
from __future__ import annotations

import asyncio
import copy
import re
from collections.abc import Mapping
from typing import Any

import aiohttp

from ..config.schema import OpenAICompatibleConfig, PersonalityConfig, PersonalityPreset
from ..llm.model_ref import parse_model_ref
from ..llm.system_prompt import PERSONALITY_PRESETS, register_user_presets
from ..tools.builtin_policy import BUILTIN_TOOL_NAMES, normalize_disabled_tools
from ..tools.defs.computer import computer_definitions
from ..tools.registry import get_documentation_tool_definitions
from ..web.api.llm_admin import _validate_ollama_url
from .secrets import secret_call

METHODS = frozenset({
    "models.main.set", "models.agents.get", "models.agents.set", "models.discover",
    "personality.get", "personality.set", "personality.presets.save",
    "personality.presets.delete", "tools.list", "tools.set_enabled",
    "tools.timeouts.get", "tools.timeouts.set",
})
READ_METHODS = frozenset({
    "models.agents.get", "models.discover", "personality.get", "tools.list",
    "tools.timeouts.get",
})


def _error(code: str, message: str, disposition: str = "rejected"):
    # Management composes this private module; avoid the circular import.
    from .management import MethodError
    return MethodError(code, message, disposition=disposition)


class ModelSettingsService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, settings, *, executor=None, provider=None):
        self.settings = settings
        self.executor = executor
        self.provider = provider
        self._lock = asyncio.Lock()

    async def handle(self, method: str, params: dict[str, Any]) -> Any:
        if method not in METHODS:
            raise _error("unknown_method", f"Unknown management method: {method}")
        if not isinstance(params, dict):
            raise _error("bad_request", "expected JSON object")
        async with self._lock:
            self._persisted = False
            try:
                if method == "models.main.set":
                    return await self._main_set(params)
                if method == "models.discover":
                    return await self._discover(params)
                if method == "models.agents.get":
                    return self._agents_get()
                if method == "models.agents.set":
                    submitted = {k: params[k] for k in (
                        "model", "thinking_mode", "auto_model_allowlist", "model_selection_hints"
                    ) if k in params}
                    candidate = self._candidate("agents", submitted).agents
                    dumped = candidate.model_dump(mode="json")
                    changes = [(("agents", k), dumped[k]) for k in submitted]
                    self._save(changes, method, params)
                    if submitted:
                        self._invalidate_catalog()
                        if getattr(self.provider, "tool_catalog", None) is not None:
                            self._confirm(changes)
                    return {"status": "updated", **self._agents_get()}
                if method == "personality.get":
                    return self._personality_get()
                if method.startswith("personality."):
                    return self._personality_set(method, params)
                if method == "tools.list":
                    return self._inventory()
                if method == "tools.set_enabled":
                    return self._tool_set(params)
                if method == "tools.timeouts.get":
                    return self._timeouts_get()
                return self._timeouts_set(params)
            except (ValueError, TypeError, AttributeError) as exc:
                # Never serialize validation input values: these may include
                # credentials through a whole-config cross-field validator.
                if self._persisted:
                    raise _error("internal", "Saved settings could not be applied",
                                 "outcome_unknown") from exc
                raise _error("bad_request", "Invalid model, personality or tool settings") from exc

    def _candidate(self, section, updates):
        values = self.settings.config.model_dump()
        values[section].update(updates)
        return type(self.settings.config).model_validate(values)

    def _save(self, changes, method, params):
        result = self.settings.save_changes(
            changes, method=method, expected_revision=params.get("expected_revision")
        )
        self._persisted = True
        return result

    def _invalidate_catalog(self):
        catalog = getattr(self.provider, "tool_catalog", None)
        if catalog is not None:
            catalog.invalidate()

    def _confirm(self, changes):
        confirm = getattr(self.settings, "confirm_applied", None)
        if callable(confirm):
            confirm(changes)

    async def _main_set(self, params):
        parsed = parse_model_ref(params.get("model"), allow_auto=False)
        if not parsed.is_concrete:
            raise _error("bad_request", "model must be a concrete model reference")
        model = parsed.render()
        provider = parsed.provider.value
        self._candidate("llm_provider", {"model": model, "active_provider": provider})
        switch = getattr(self.provider, "switch_provider", None)
        if not callable(switch):
            raise _error("unavailable", "Main-model runtime owner is unavailable")
        changes = [
            (("llm_provider", "model"), model),
            (("llm_provider", "active_provider"), provider),
        ]
        from .management import MethodError

        persist_error = None

        def persist():
            nonlocal persist_error
            try:
                return self._save(changes, "models.main.set", params)
            except MethodError as exc:
                # The owner drains persistence and rolls back its unpublished
                # graph before returning a deliberately generic failure. Keep
                # the protocol classification without bypassing that cleanup.
                persist_error = exc
                raise

        result = await switch(
            provider,
            persist=persist,
            model_ref=model,
        )
        if not isinstance(result, dict):
            raise _error("unavailable", "Main-model runtime owner returned no result")
        if "error" in result:
            if persist_error is not None:
                raise persist_error
            code = "internal_error" if "persist failed" in str(result["error"]) else "bad_request"
            # Owner messages may contain endpoint auth; keep protocol safe.
            raise _error(code, "Main-model switch failed")
        self._confirm(changes)
        return {**result, "main_model": model, "configured_provider": provider}

    def _agents_get(self):
        cfg = self.settings.config.agents
        dumped = cfg.model_dump(mode="json")
        return {k: dumped[k] for k in (
            "model", "thinking_mode", "auto_model_allowlist", "model_selection_hints",
            "iteration_timeout_seconds",
        )}

    def _personality_get(self):
        cfg = self.settings.config.personality
        user = {k: v.model_dump() for k, v in cfg.user_presets.items()}
        return {
            "preset": cfg.preset, "custom_name": cfg.custom_name,
            "custom_identity": cfg.custom_identity, "custom_voice": cfg.custom_voice,
            "presets": copy.deepcopy({**PERSONALITY_PRESETS, **user}),
            "builtin_presets": list(PERSONALITY_PRESETS), "user_presets": list(user),
        }

    def _personality_set(self, method, params):
        current = self.settings.config.personality
        rebuild = True
        if method == "personality.set":
            desired = PersonalityConfig(
                **{k: params.get(k, "odin" if k == "preset" else "") for k in (
                    "preset", "custom_name", "custom_identity", "custom_voice"
                )}, user_presets=current.user_presets,
            )
            result = {"status": "updated", "preset": desired.preset}
        else:
            presets = dict(current.user_presets)
            name = params.get("name")
            if not isinstance(name, str):
                raise _error("bad_request", "name is required")
            if method.endswith("save"):
                name = name.strip().lower().replace(" ", "_")
                if not re.fullmatch(r"[a-z0-9_-]+", name):
                    raise _error("bad_request", "invalid preset name")
                if name in PERSONALITY_PRESETS:
                    raise _error("bad_request", f"cannot overwrite built-in preset '{name}'")
                if not params.get("identity") and not params.get("voice"):
                    raise _error("bad_request", "identity or voice is required")
                presets[name] = PersonalityPreset(
                    name=params.get("display_name", name),
                    identity=params.get("identity", ""), voice=params.get("voice", ""),
                )
                result = {"status": "saved", "name": name}
            else:
                if name in PERSONALITY_PRESETS:
                    raise _error("bad_request", f"cannot delete built-in preset '{name}'")
                if name not in presets:
                    raise _error("not_found", "preset not found")
                del presets[name]
                result = {"status": "deleted", "name": name}
            rebuild = current.preset == name
            update = {"user_presets": presets}
            if method.endswith("delete") and rebuild:
                update["preset"] = "odin"
            desired = PersonalityConfig.model_validate({**current.model_dump(), **update})
        dumped = desired.model_dump(mode="json")
        changes = [(("personality", k), v) for k, v in dumped.items()]
        self._save(changes, "settings.set", params)
        register_user_presets(dumped["user_presets"])
        if rebuild:
            prompt = getattr(self.provider, "prompt_builder", None)
            if prompt is not None:
                prompt.invalidate()
            self._invalidate_catalog()
            if prompt is not None:
                prompt.rebuild_default()
                self._confirm(changes)
        return result

    def _inventory(self):
        cfg = self.settings.config.tools
        disabled = set(normalize_disabled_tools(cfg.disabled_tools))
        policy = getattr(self.executor, "_builtin_policy", None)
        definitions = [
            *get_documentation_tool_definitions(cfg.command_shell), *computer_definitions(),
        ]
        tools = []
        for tool in definitions:
            name = tool["name"]
            enabled = name not in disabled
            if not enabled:
                state = "disabled"
            elif not cfg.enabled:
                state = "global_disabled"
            elif policy is None or not policy.is_available(name):
                state = "unavailable"
            else:
                state = "available"
            tools.append({
                "name": name, "description": tool.get("description", ""),
                "is_core": tool.get("is_core", False), "enabled": enabled, "state": state,
                "input_schema": copy.deepcopy(tool.get("input_schema", {})),
            })
        return {
            "global_enabled": bool(cfg.enabled), "disabled_count": len(disabled), "tools": tools,
        }

    def _tool_set(self, params):
        name = params.get("name")
        if not isinstance(name, str) or name not in BUILTIN_TOOL_NAMES:
            raise _error("not_found", "not a built-in tool")
        if not isinstance(params.get("enabled"), bool):
            raise _error("bad_request", "enabled must be a boolean")
        extra = sorted(set(params) - {"name", "enabled", "expected_revision"})
        if extra:
            raise _error("bad_request", "only 'name' and 'enabled' are accepted on this route")
        current = normalize_disabled_tools(self.settings.config.tools.disabled_tools)
        desired = ([n for n in current if n != name] if params["enabled"] else
                   current if name in current else [*current, name])
        if desired != current:
            changes = [(("tools", "disabled_tools"), desired)]
            self._save(changes, "tools.set_enabled", params)
            self._invalidate_catalog()
            if getattr(self.executor, "_builtin_policy", None) is not None:
                self._confirm(changes)
        return self._inventory()

    def _timeouts_get(self):
        cfg = self.settings.config.tools
        return {
            "default_timeout": cfg.command_timeout_seconds, "overrides": dict(cfg.tool_timeouts),
        }

    def _timeouts_set(self, params):
        overrides = params.get("overrides")
        default = params.get("default_timeout")
        if overrides is not None:
            if not isinstance(overrides, dict):
                raise _error("bad_request", "overrides must be a dict")
            if any(not isinstance(k, str) or not k or isinstance(v, bool)
                   or not isinstance(v, int) or v <= 0 for k, v in overrides.items()):
                raise _error("bad_request", "timeouts must be positive integers")
        if default is not None and (
            isinstance(default, bool) or not isinstance(default, int) or default <= 0
        ):
            raise _error("bad_request", "default_timeout must be a positive integer")
        cfg = self.settings.config.tools
        changes = []
        if overrides is not None and overrides != cfg.tool_timeouts:
            changes.append((("tools", "tool_timeouts"), overrides))
        if default is not None and default != cfg.command_timeout_seconds:
            changes.append((("tools", "command_timeout_seconds"), default))
        if changes:
            self._save(changes, "tools.timeouts.set", params)
        # Repeated writes also reconcile a pointer left behind by config reload.
        executor_config = getattr(self.executor, "config", None)
        if executor_config is not None:
            if overrides is not None:
                executor_config.tool_timeouts = dict(overrides)
            if default is not None:
                executor_config.command_timeout_seconds = default
            if changes:
                self._confirm(changes)
        return self._timeouts_get()

    async def _discover(self, params):
        provider = params.get("provider")
        if provider not in ("ollama", "compat"):
            raise _error("bad_request", "provider must be 'ollama' or 'compat'")
        cfg = getattr(
            self.settings.config, "ollama" if provider == "ollama" else "openai_compatible",
        )
        base_url = params.get("base_url") or cfg.base_url
        if not isinstance(base_url, str):
            raise _error("bad_request", "base_url must be a string")
        base_url = base_url.rstrip("/")
        headers = {}
        if provider == "ollama":
            base_url = _validate_ollama_url(base_url)
            endpoint = f"{base_url}/api/tags"
        else:
            base_url = OpenAICompatibleConfig.model_validate({
                **cfg.model_dump(), "base_url": base_url,
            }).base_url
            # Credential owner is injected. A vault failure never falls back to
            # an on-disk secret or an enabled client's stale credential.
            key = await secret_call(self.settings.secrets.get, "openai_compatible.api_key")
            if key:
                headers["Authorization"] = f"Bearer {key}"
            headers["Content-Type"] = "application/json"
            endpoint = f"{base_url}/models"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(endpoint, headers=headers) as response:
                    if response.status != 200:
                        raise _error("unavailable", "Invalid API key" if response.status == 401
                                     and provider == "compat" else f"HTTP {response.status}")
                    data = await response.json()
            if not isinstance(data, Mapping):
                raise _error("unavailable", "Invalid model catalogue response")
            if provider == "ollama":
                return {"models": data.get("models", [])}
            records = data.get("data", [])
            if not isinstance(records, list):
                raise _error("unavailable", "Invalid model catalogue response")
            models = [m.get("id", "") for m in records
                      if isinstance(m, dict) and isinstance(m.get("id"), str)]
            return {"models": models, "active_model": cfg.model}
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise _error("unavailable", "Model endpoint discovery failed") from exc
