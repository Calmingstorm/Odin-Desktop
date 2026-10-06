"""Passive observations of the real profile owners, never synthetic counters.

The authenticated management transport is the single-owner authorization
boundary. No HTTP server, tier gate, writer construction, breaker acquisition,
or connection creation is performed here. ``graph`` is a lazy getter so owners
composed after management startup remain observable without stale snapshots.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime
from typing import Any

from ..observability.diagnostics import scrub_diagnostic

METHODS = frozenset({
    "observability.stats", "observability.tools", "observability.risk",
    "observability.risk_recent", "observability.governor", "observability.audit_risk",
    "observability.freshness", "observability.freshness_recent",
    "observability.bulkheads", "observability.compression", "observability.validation",
    "observability.affordances", "observability.context", "observability.usage",
    "observability.usage_totals", "observability.subsystems",
    "recovery.stats", "recovery.recent", "capacity.snapshot", "turn_state.snapshot",
    "pools.ssh", "pools.http", "pools.close",
})
READ_METHODS = METHODS - {"pools.close"}


def _error(code, message, disposition="rejected"):
    from .management import MethodError
    return MethodError(code, message, disposition)


def _bounded(params, name="limit", default=20, maximum=100):
    try:
        return max(1, min(int(params.get(name, default)), maximum))
    except (TypeError, ValueError, OverflowError):
        return default


def _envelope(availability, data=None, **extra):
    return {"schema_version": 1, "availability": availability,
            "observed_at": datetime.now(UTC).isoformat(),
            "data": {} if data is None else data, **extra}


async def _settled(value):
    return await value if inspect.isawaitable(value) else value


def _reference(node, name):
    """Read a declared owner reference; dynamic getattr is not availability."""
    try:
        inspect.getattr_static(node, name)
    except AttributeError:
        return None
    return getattr(node, name)


class ObservabilityService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, *, executor=None, audit=None, gateway=None,
                 compression_stats=None, config=None, turn_store=None,
                 model_breakers=None, usage_rollup=None, subsystem_guard=None,
                 graph=None, usage_getter=None):
        self.executor, self.audit, self.gateway = executor, audit, gateway
        self.compression_stats, self.config = compression_stats, config
        self.turn_store, self.model_breakers = turn_store, model_breakers
        self.usage_rollup, self.subsystem_guard = usage_rollup, subsystem_guard
        self.graph = graph
        self.usage_getter = usage_getter

    def _owner(self, name):
        """Resolve references only. Never construct a manager to manufacture data."""
        explicit = getattr(self, name, None)
        if explicit is not None:
            if name == "config" and callable(explicit):
                return explicit()
            return explicit
        if name == "usage_rollup" and self.usage_getter is not None:
            return self.usage_getter()
        root = self.graph() if callable(self.graph) else self.graph
        aliases = {"executor": ("executor", "tool_executor"),
                   "gateway": ("providers", "llm_gateway", "gateway")}.get(name, (name,))
        # Real composition roots differ before/after the request engine joins.
        nodes = [node for node in (root, self.executor, self.gateway) if node is not None]
        index = 0
        # Bounded breadth-first walk handles requests.services and core's late
        # owners without assuming their composition order or retaining copies.
        while index < len(nodes) and index < 64:
            node = nodes[index]
            index += 1
            for child in ("core", "services", "requests", "runtime", "records", "settings",
                          "providers", "engine", "deps", "runtime_context", "llm_gateway"):
                value = _reference(node, child)
                values = value if isinstance(value, (list, tuple)) else (value,)
                for item in values:
                    if item is not None and all(item is not existing for existing in nodes):
                        nodes.append(item)
        for node in nodes:
            for alias in aliases:
                owner = _reference(node, alias)
                if owner is not None:
                    return owner
        return None

    def _executor(self):
        executor = self._owner("executor")
        if executor is None:
            raise _error("unavailable", "executor not available")
        return executor

    async def handle(self, method: str, params: dict[str, Any]):
        if method not in METHODS:
            raise _error("method_not_found", "Unknown observability method")
        if not isinstance(params, dict):
            raise _error("bad_request", "expected JSON object")
        from .management import MethodError
        try:
            return scrub_diagnostic(await self._handle(method, params))
        except MethodError:
            raise
        except Exception:
            # Counter/provider errors can contain credentials and host details.
            if method == "pools.close":
                raise _error("unavailable", "Pool closure outcome is unknown",
                             "outcome_unknown") from None
            raise _error("unavailable", "Observability read is unavailable") from None

    async def _handle(self, method, params):
        if method == "observability.stats":
            from .management import MethodError
            sections = {}
            for key, operation in (("tool_counts", "observability.tools"),
                                   ("risk", "observability.risk"),
                                   ("freshness", "observability.freshness"),
                                   ("bulkheads", "observability.bulkheads"),
                                   ("compression", "observability.compression")):
                try:
                    sections[key] = await self.handle(operation, {})
                except MethodError as exc:
                    sections[key] = {"available": False, "reason": exc.message}
            return sections
        if method == "observability.tools":
            audit = self._owner("audit")
            if audit is None:
                raise _error("unavailable", "audit not available")
            return await _settled(audit.count_by_tool())
        if method == "observability.audit_risk":
            audit = self._owner("audit")
            if audit is None:
                raise _error("unavailable", "audit not available")
            entries = await _settled(audit.search_by_risk(
                risk_level=params.get("level") or None, tool_name=params.get("tool") or None,
                limit=_bounded(params)))
            return {"entries": entries, "count": len(entries)}
        stats = {"observability.risk": "risk_stats", "recovery.stats": "recovery_stats",
                 "observability.freshness": "freshness_stats"}
        if method in stats:
            return getattr(self._executor(), stats[method]).get_summary()
        recent = {"observability.risk_recent": "risk_stats", "recovery.recent": "recovery_stats",
                  "observability.freshness_recent": "freshness_stats"}
        if method in recent:
            freshness = method == "observability.freshness_recent"
            limit = _bounded(params, default=10 if freshness else 20,
                             maximum=50 if freshness else 100)
            return {"entries": getattr(self._executor(), recent[method]).get_recent(limit)}
        if method == "observability.governor":
            governor = getattr(self._executor(), "command_governor", None)
            if governor is None:
                raise _error("unavailable", "command governor not available")
            return governor.stats.get_summary()
        if method == "observability.bulkheads":
            executor = self._owner("executor")
            if executor is None or not hasattr(executor, "bulkheads"):
                raise _error("unavailable", "bulkheads not available")
            return executor.bulkheads.get_all_metrics()
        if method == "observability.validation":
            return self._executor().validation_stats.as_dict()
        if method == "observability.compression":
            tracker = self._owner("compression_stats")
            if tracker is None:
                raise _error("unavailable", "compression stats not available")
            # CompressionStats itself distinguishes no samples/local equality
            # from upstream cache measurement. Never infer remote cache hits.
            return tracker.as_dict()
        if method == "observability.affordances":
            from ..tools.affordances import all_affordances
            return {"affordances": all_affordances()}
        if method == "observability.context":
            config = self._owner("config")
            if config is None:
                raise _error("unavailable", "config not available")
            obs = getattr(config, "observability", None)
            if obs is not None and not obs.prompt_budget_accounting:
                raise _error("unavailable", "prompt budget accounting disabled")
            from ..observability.aggregates import context_aggregates
            directory = getattr(config.tools, "trajectory_path", "./data/trajectories")
            return await asyncio.to_thread(context_aggregates, directory,
                                           _bounded(params, "window", 24, 24 * 14))
        if method in {"observability.usage", "observability.usage_totals"}:
            rollup = self._owner("usage_rollup")
            if rollup is None:
                raise _error("unavailable", "usage history not enabled")
            return await _settled(rollup.totals() if method.endswith("totals")
                                  else rollup.summary(params.get("range", "7d")))
        if method == "observability.subsystems":
            guard = self._owner("subsystem_guard")
            if guard is None:
                raise _error("unavailable", "subsystem guard not available")
            return guard.get_status()
        if method == "capacity.snapshot":
            registry = self._owner("model_breakers")
            if registry is None:
                return _envelope("not_enabled", lifetime="process")
            try:
                snapshot = registry.snapshot()
                breakers = []
                for key in sorted(snapshot):
                    entry = dict(snapshot[key])
                    entry["provider"], _, entry["model"] = key.partition(":")
                    breakers.append(entry)
            except Exception:
                return _envelope("unavailable", lifetime="process")
            return _envelope("available", {"breakers": breakers}, lifetime="process")
        if method == "turn_state.snapshot":
            config = self._owner("config")
            enabled = bool(getattr(getattr(config, "turn_state", None), "enabled", False))
            store = self._owner("turn_store")
            if store is None:
                return _envelope("not_enabled", configured_enabled=enabled)
            limit = _bounded(params, default=100, maximum=200)
            from ..turn_state.observer import read_turn_snapshot
            try:
                data = await asyncio.to_thread(read_turn_snapshot, store.db_path, limit)
            except Exception:
                return _envelope("unavailable", configured_enabled=enabled)
            return _envelope("available", data, configured_enabled=enabled, limit=limit)
        if method == "pools.http":
            gateway = self._owner("gateway")
            result = {}
            if gateway is not None:
                clients = (("codex", "codex_client", "get_pool_metrics"),
                           ("ollama", "ollama_client", "pool_stats"),
                           ("openai_compatible", "compatible_client", "pool_stats"))
                for name, attr, getter in clients:
                    client = getattr(gateway, attr, None)
                    if client is None and attr == "compatible_client":
                        client = getattr(gateway, "openai_compatible_client", None)
                    if client is not None and (name != "codex" or hasattr(client, getter)):
                        result[name] = getattr(client, getter)()
            if not result:
                raise _error("unavailable", "No HTTP pools available")
            return result
        executor = self._owner("executor")
        pool = getattr(executor, "ssh_pool", None) if executor is not None else None
        if pool is None:
            raise _error("unavailable", "SSH pool not available")
        if method == "pools.ssh":
            return pool.get_metrics()
        host = params.get("host")
        if host:
            closed = await pool.close_host(host, params.get("ssh_user", "root"))
            return {"closed": closed, "host": host}
        return {"closed_count": await pool.close_all()}
