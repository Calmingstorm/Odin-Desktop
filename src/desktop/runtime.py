"""Profile runtime observations and named reloads, not a second core lifetime.

The transport core owns durable shutdown. Missing engine owners remain missing;
saved model settings are not evidence of a serving model or a healthy provider.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import math
import time
from types import SimpleNamespace

from ..config.apply_registry import flatten, is_secret
from ..config.persistence import _load_document
from ..config.schema import Config
from ..discord.slash_commands import (
    USAGE_RANGES,
    collect_status,
    render_quota,
    render_reload,
    render_status,
    render_usage,
)
from ..llm.model_ref import parse_model_ref
from ..observability.diagnostics import scrub_diagnostic
from ..usage.rollup import UsageRollup
from .management import MethodError
from .provisioning import fresh_config
from .secrets import SecretStoreError, secret_call


def _number(value=None, kind="unknown") -> dict:
    if (type(value) not in (int, float) or not math.isfinite(value)
            or value < 0 or kind not in {"measured", "estimated"}):
        return {"value": None, "kind": "unknown"}
    return {"value": value, "kind": kind}


class _ProfileUsageReader(UsageRollup):
    """Reuse the real rollup's read-only queries without initializing a writer."""

    def __init__(self, directory):
        from pathlib import Path

        self.db_path = Path(directory) / "usage.sqlite3"
        self.available = self.db_path.is_file()
        self.error = None if self.available else "usage history not enabled"
        self._source_scan_errors = 0


class RuntimeService:
    METHODS = frozenset({"status.get", "usage.get", "runtime.reload"})
    READ_METHODS = frozenset({"status.get", "usage.get"})

    def __init__(self, core, settings, *, llm=None, usage=None, context=None,
                 skills=None, quota=None):
        self.core = core
        self.settings = settings
        self.llm_gateway = llm
        self.usage = usage
        self.context = context
        directory = getattr(getattr(settings.config, "context", None), "directory", None)
        if self.context is None and directory:
            from ..context.loader import ContextLoader

            self.context = ContextLoader(directory)
        self.skills = skills
        self.quota = quota
        self.tool_catalog = (getattr(llm, "tool_catalog", None)
                             or getattr(core, "tool_catalog", None))
        self.prompt_builder = (getattr(llm, "prompt_builder", None)
                              or getattr(core, "prompt_builder", None))
        self._first_run_snapshot = {
            "state": "degraded", "reason": "keyring_unavailable", "keyring_unavailable": True,
        }

    @property
    def config(self):
        return self.settings.config

    async def switch_provider(self, provider, *, persist, model_ref):
        switch = getattr(self.llm_gateway, "switch_provider", None)
        if not callable(switch):
            raise MethodError("capability_unavailable", "Provider runtime is not available")
        result = switch(provider, persist=persist, model_ref=model_ref)
        return await result if inspect.isawaitable(result) else result

    def _first_run(self) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self._first_run_snapshot = self._read_first_run()
        return dict(self._first_run_snapshot)

    async def status_async(self):
        self._first_run_snapshot = await secret_call(self._read_first_run)
        return self.status()

    def _read_first_run(self) -> dict:
        """A read-only projection, not an onboarding completion flag or probe.

        Fresh means the bootstrap provider choices still equal this profile's
        defaults and no primary credential exists. Saving those same defaults
        without credentials intentionally remains fresh on every launch. Only
        the retained owner's captured identity establishes effective settings;
        hydrating desired settings never adopts a client. Optional health
        observations can degrade it, but do not impose a new provider probe or
        success-count gate stricter than Odin's existing runtime behavior.
        """
        def result(state, reason, *, keyring=False):
            return {"state": state, "reason": reason, "keyring_unavailable": keyring}

        try:
            paths = self.settings.paths
            defaults = fresh_config(paths)
            document, _ = _load_document(paths.config_file)
            values = defaults.model_dump(mode="json")
            self.settings._merge(values, dict(document))
            saved = Config.model_validate(values, context={"startup": True})
            desired = parse_model_ref(self.config.llm_provider.model, allow_auto=False)
            section_name = {"codex": "openai_codex", "ollama": "ollama",
                            "compat": "openai_compatible"}[desired.provider.value]
            section = getattr(saved, section_name)

            # Read only the profile's keyring. Presence is not authorization or
            # provider health, and no credential bytes become protocol fields.
            raw = self.settings.secrets.get("codex_accounts")
            accounts = json.loads(raw) if raw is not None else []
            if not isinstance(accounts, (dict, list)):
                raise ValueError("Invalid credential state")
            rows = accounts if isinstance(accounts, list) else [accounts]
            codex = any(isinstance(row, dict) and bool(row.get("access_token"))
                        for row in rows)
            compat = bool(self.settings.secrets.get("openai_compatible.api_key"))
            ollama = bool(self.settings.secrets.get("ollama.api_key"))
        except SecretStoreError:
            return result("degraded", "keyring_unavailable", keyring=True)
        except Exception:
            return result("degraded", "credential_state_unavailable")
        if getattr(self.settings, "_keyring_error", None):
            # Presence is not full hydration. Explicit Retry rehydrates before
            # reporting its result, without claiming runtime client adoption.
            return result("degraded", "keyring_unavailable", keyring=True)

        def choices(config):
            values = config.model_dump(mode="json")
            return {path: value for name in
                    ("llm_provider", "openai_codex", "ollama", "openai_compatible")
                    for path, value in flatten(values[name], name) if not is_secret(path)}

        configured = (section.enabled and bool(desired.model)
                      and (desired.provider.value == "ollama" or
                           (codex if desired.provider.value == "codex" else compat))
                      and (desired.provider.value == "codex" or bool(section.base_url)))
        if not configured:
            if choices(saved) == choices(defaults) and not (codex or compat or ollama):
                return result("fresh", "provider_not_configured")
            return result("incomplete", "provider_configuration_incomplete")

        # A runtime-only switch or an uncommitted desired candidate is not setup
        # completion. A successful save alone is not serving readiness either.
        committed = parse_model_ref(saved.llm_provider.model, allow_auto=False)
        if (committed.provider, committed.model) != (desired.provider, desired.model):
            return result("saved", "provider_identity_not_adopted")
        try:
            identity = self.llm_gateway.capture_serving_identity()
        except Exception:
            return result("saved", "provider_runtime_unavailable")
        if getattr(identity, "client", None) is None:
            return result("saved", "provider_runtime_unavailable")
        if (identity.provider, identity.model) != (desired.provider.value, desired.model):
            return result("saved", "provider_identity_not_adopted")
        adopted = getattr(self.llm_gateway, "_effective_config", None)
        if adopted is not None:
            def provider_settings(config):
                return {path: value for path, value in
                        flatten(getattr(config, section_name).model_dump(mode="json"), section_name)
                        if not is_secret(path)}
            if provider_settings(adopted) != provider_settings(self.config):
                return result("saved", "provider_identity_not_adopted")
        if (getattr(self.llm_gateway, "_closed", False)
                or getattr(identity.client, "_generation_retired", False)):
            return result("degraded", "provider_health_degraded")
        guard = getattr(self.llm_gateway, "subsystem_guard", None)
        try:
            if guard is not None:
                usable = guard.is_usable(f"llm_{desired.provider.value}")
                healthy = guard.is_available(f"llm_{desired.provider.value}")
                if usable is False or healthy is False:
                    return result("degraded", "provider_health_degraded")
        except Exception:
            # Unknown optional health observations are not an execution or
            # completion gate. Effective-ready describes adoption, not proof
            # of generation, quota, reachability or a successful network probe.
            pass
        try:
            breaker = getattr(identity.client, "breaker", None)
            if breaker is not None and getattr(breaker, "state", None) != "closed":
                return result("degraded", "provider_health_degraded")
        except Exception:
            pass
        return result("effective-ready", "provider_effective")

    def status(self) -> dict:
        # Never call core.status here: the core delegates back to this service.
        from .core import VERSION

        observed = SimpleNamespace(
            config=self.config, llm_gateway=self.llm_gateway,
            start_time=getattr(self.core, "start_time", None),
            tool_catalog=self.tool_catalog,
            agent_manager=getattr(self.core, "agent_manager", None),
            loop_manager=getattr(self.core, "loop_manager", None),
        )
        facts = collect_status(observed)
        facts["version"] = VERSION
        # An absent client may mean lazy construction, not a disabled setting.
        for name, section in (("codex", "openai_codex"), ("ollama", "ollama"),
                              ("compat", "openai_compatible")):
            client_name = "compatible_client" if name == "compat" else f"{name}_client"
            if getattr(self.llm_gateway, client_name, None) is None:
                enabled = getattr(getattr(self.config, section, None), "enabled", None)
                facts["providers"][name] = "disabled" if enabled is False else "unavailable"
            else:
                guard = getattr(self.llm_gateway, "subsystem_guard", None)
                if guard is not None:
                    try:
                        if not guard.is_usable(f"llm_{name}"):
                            facts["providers"][name] = "unavailable"
                        elif not guard.is_available(f"llm_{name}"):
                            facts["providers"][name] = "degraded"
                    except Exception:
                        facts["providers"][name] = "unknown"
        limits = getattr(self.core, "limits", None) or {}
        return scrub_diagnostic({
            "phase": self.core.phase,
            "core_instance_id": getattr(getattr(self.core, "authority", None), "runtime_id", None),
            "version": VERSION,
            "capabilities": list(getattr(self.core, "capabilities", ())),
            "model": {"main": facts["model"], "effort": facts["reasoning_effort"],
                      "provider": facts["serving_provider"]},
            "providers": [{"name": name, "health": health}
                          for name, health in facts["providers"].items()],
            "limits": {name: limits.get(name) for name in
                       ("chunk_bytes", "attachment_bytes", "attachments_per_turn")},
            "summary": render_status(facts),
            "first_run": self._first_run(),
            "resource_cleanup": (self.core.resource_cleanup.public()
                                 if getattr(self.core, "resource_cleanup", None) else None),
        })

    def _quota(self):
        auth = self.quota
        if auth is None:
            auth = getattr(getattr(self.llm_gateway, "codex_client", None), "auth", None)
        if auth is None or not callable(getattr(auth, "quota_view", None)):
            return [], None
        try:
            view = auth.quota_view()
            labels = {}
            if callable(getattr(auth, "describe_accounts", None)):
                labels = {row["key"]: row["label"] for row in auth.describe_accounts()
                          if row.get("key")}
            snapshots = [(view.current_key, view.current),
                         *((item.account_key, item) for item in view.others)]
            rows = []
            for key, snapshot in snapshots:
                if key is None and snapshot is None:
                    continue
                for name in ("primary", "secondary"):
                    window = getattr(snapshot, name, None)
                    minutes = getattr(window, "window_minutes", None)
                    label = f"{minutes}m" if type(minutes) is int and minutes > 0 else name
                    rows.append({
                        "account": labels.get(key) or key or "current account",
                        "window": label,
                        "used_percent": _number(getattr(window, "used_percent", None), "measured"),
                        # A reset timestamp is not a usage count; the protocol keeps it nullable.
                        "resets_at": getattr(window, "resets_at", None),
                    })
            return scrub_diagnostic(rows), render_quota(view, labels, time.time())
        except Exception:
            return [], ["Codex quota: unavailable (see logs)."]

    async def _usage(self, params):
        period = params.get("period", "7d")
        if type(period) is not str or period not in USAGE_RANGES:
            raise MethodError("bad_request", "usage ranges are 24h, 7d, 30d and all")
        usage = self.usage
        if usage is None:
            # Construct no rollup writer and perform no migration on a read route.
            directory = getattr(getattr(self.config, "usage", None), "directory", None)
            usage = _ProfileUsageReader(directory or self.core.paths.data_dir / "usage")
        try:
            summary = usage.summary(period)
            if inspect.isawaitable(summary):
                summary = await summary
        except Exception:
            summary = {"available": False, "reason": "usage history unavailable"}
        tokens = _number()
        if summary.get("available"):
            work = summary.get("work", {})
            values = [work.get(name, {}) for name in ("input_tokens", "output_tokens")]
            complete = summary.get("coverage", {}).get("backfill_complete", False)
            # A newly composed writer has an empty index before backfill settles.
            # Zero indexed facts is not evidence that actual usage was zero.
            observed = work.get("accepted_generations", 0) > 0 or complete
            if observed and all(type(item.get("total")) is int and item["total"] >= 0
                                and not item.get("unknown_generations") for item in values):
                estimated = any(item.get("estimated") or item.get("legacy_estimated")
                                for item in values)
                # Indexed history is not all history while backfill is incomplete.
                estimated |= not complete
                tokens = _number(sum(item["total"] for item in values),
                                 "estimated" if estimated else "measured")
        context = {"used": _number(), "budget": _number()}
        owner = self.context
        snapshot = getattr(owner, "usage_snapshot", None)
        if callable(snapshot):
            try:
                observed = snapshot()
                if inspect.isawaitable(observed):
                    observed = await observed
                for key in context:
                    value = observed.get(key, {})
                    context[key] = _number(value.get("value"), value.get("kind"))
            except Exception:
                pass
        quota, quota_lines = self._quota()
        return scrub_diagnostic({
            "period": period, "tokens": tokens, "context": context,
            "quota": quota, "summary": render_usage(summary, period, quota_lines),
        })

    async def _reload(self, params):
        scope = params.get("scope", "context")
        if type(scope) is not str or scope not in {"skills", "config", "context"}:
            raise MethodError("bad_request", "scope must be skills, config or context")
        owner = {"skills": self.skills, "config": self.settings, "context": self.context}[scope]
        reload = getattr(owner, "reload", None)
        if not callable(reload):
            raise MethodError("capability_unavailable", f"{scope} reload is not available")
        result = reload()
        if inspect.isawaitable(result):
            result = await result
        if scope == "context":
            # Match /api/reload's post-load invalidation, only for real owners.
            for target, operation in ((self.prompt_builder, "invalidate"),
                                      (self.tool_catalog, "invalidate"),
                                      (self.prompt_builder, "rebuild_default")):
                callback = getattr(target, operation, None)
                if callable(callback):
                    applied = callback()
                    if inspect.isawaitable(applied):
                        await applied
            summary = render_reload(result)
        elif isinstance(result, dict) and isinstance(result.get("summary"), str):
            summary = result["summary"]
        elif scope == "skills" and type(result) is int:
            summary = f"Reloaded {result} skills."
        else:
            summary = f"Reloaded {scope}."
        return scrub_diagnostic({"disposition": "reloaded", "summary": summary})

    async def handle(self, method: str, params: dict):
        if type(params) is not dict:
            raise MethodError("bad_request", "Method params must be an object")
        if method == "status.get":
            return await self.status_async()
        if method == "usage.get":
            return await self._usage(params)
        if method == "runtime.reload":
            return await self._reload(params)
        raise MethodError("capability_unavailable", "Runtime method is not available")
