"""Profile runtime observations and named reloads, not a second core lifetime.

The transport core owns durable shutdown. Missing engine owners remain missing;
saved model settings are not evidence of a serving model or a healthy provider.
"""
from __future__ import annotations

import inspect
import math
import time
from types import SimpleNamespace

from ..discord.slash_commands import (
    USAGE_RANGES,
    collect_status,
    render_quota,
    render_reload,
    render_status,
    render_usage,
)
from ..observability.diagnostics import scrub_diagnostic
from ..usage.rollup import UsageRollup
from .management import MethodError


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

    @property
    def config(self):
        return self.settings.config

    async def switch_provider(self, provider, *, persist, model_ref):
        switch = getattr(self.llm_gateway, "switch_provider", None)
        if not callable(switch):
            raise MethodError("capability_unavailable", "Provider runtime is not available")
        result = switch(provider, persist=persist, model_ref=model_ref)
        return await result if inspect.isawaitable(result) else result

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
            if all(type(item.get("total")) is int and item["total"] >= 0
                   and not item.get("unknown_generations") for item in values):
                estimated = any(item.get("estimated") or item.get("legacy_estimated")
                                for item in values)
                # Indexed history is not all history while backfill is incomplete.
                estimated |= not summary.get("coverage", {}).get("backfill_complete", False)
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
            return self.status()
        if method == "usage.get":
            return await self._usage(params)
        if method == "runtime.reload":
            return await self._reload(params)
        raise MethodError("capability_unavailable", "Runtime method is not available")
