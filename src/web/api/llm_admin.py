"""Neutral provider validation and provenance helpers; commands await Phase 2.

Require owner-authenticated settings, SSRF/credential fences, serialized
validate-persist-adopt-reconcile/reload and truthful desired/effective state.
Baseline operation closures remain at exact-copy commit f6170072.
"""
from __future__ import annotations

import hashlib
import ipaddress as _ipaddress
import time
import urllib.parse as _urlparse
from typing import Any

import aiohttp
from aiohttp import web
from pydantic import TypeAdapter, ValidationError

from ...config.schema import CODEX_REASONING_EFFORTS
from . import require_phase2

_OPENROUTER_CACHE_TTL_SECONDS = 300
_openrouter_cache: dict[str, Any] = {
    "models": None,
    "fetched_at": 0.0,
    "error": None,
    "details": {},
}


async def _openrouter_models(config) -> tuple[list[dict[str, Any]], bool, str | None]:
    """Return fresh public catalogue, or bounded stale evidence on failure."""
    from ...llm.openrouter import fetch_json, normalize_model_catalogue

    now = time.time()
    cached = _openrouter_cache.get("models")
    fetched_at = float(_openrouter_cache.get("fetched_at") or 0)
    if isinstance(cached, list) and now - fetched_at < _OPENROUTER_CACHE_TTL_SECONDS:
        return cached, False, None
    try:
        async with aiohttp.ClientSession() as session:
            payload = await fetch_json(session, "/api/v1/models")
        models = normalize_model_catalogue(payload)
        if not models:
            raise ValueError("OpenRouter catalogue contains no usable models")
        _openrouter_cache.update(models=models, fetched_at=now, error=None, details={})
        return models, False, None
    except Exception as exc:
        error = f"{type(exc).__name__}: catalogue refresh failed"
        _openrouter_cache["error"] = error
        if isinstance(cached, list):
            return cached, True, error
        raise web.HTTPBadGateway(text=error) from None


async def _openrouter_endpoint_rows(model_id: str, *, api_key: str = "") -> list[dict[str, Any]]:
    """Fetch and cache route-level facts needed for truthful profiles and pins."""
    from ...llm.openrouter import fetch_json, model_detail_path, normalize_endpoint_rows

    now = time.time()
    auth_scope = (
        hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16] if api_key else "anonymous"
    )
    cache_key = f"{model_id}\0{auth_scope}"
    details = _openrouter_cache.setdefault("details", {})
    cached = details.get(cache_key) if isinstance(details, dict) else None
    if isinstance(cached, dict) and now - float(cached.get("fetched_at") or 0) < 300:
        rows = cached.get("rows")
        if isinstance(rows, list):
            return rows
    async with aiohttp.ClientSession() as session:
        payload = await fetch_json(
            session,
            model_detail_path(model_id),
            api_key=api_key or None,
        )
    rows = normalize_endpoint_rows(payload)
    details[cache_key] = {"fetched_at": now, "rows": rows}
    return rows


_ALLOWED_OLLAMA_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def _validate_ollama_url(url: str) -> str:
    """Validate Ollama base_url — restrict to local/private networks to prevent SSRF."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    parsed = _urlparse.urlparse(url)
    host = parsed.hostname or ""
    if host in _ALLOWED_OLLAMA_HOSTS:
        return url
    try:
        addr = _ipaddress.ip_address(host)
        if addr.is_link_local:
            raise ValueError(f"Link-local addresses not allowed: {host}")
        if addr.is_private or addr.is_loopback:
            return url
        raise ValueError(f"Public IP not allowed for Ollama: {host}")
    except ValueError as e:
        if "not allowed" in str(e) or "Public IP" in str(e):
            raise
    except Exception:
        pass
    try:
        import socket

        resolved = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        if not resolved:
            raise ValueError(f"Could not resolve hostname: {host}")
        for _, _, _, _, sockaddr in resolved:
            addr = _ipaddress.ip_address(sockaddr[0])
            if addr.is_link_local:
                raise ValueError(f"Link-local address not allowed: {sockaddr[0]}")
            if not (addr.is_private or addr.is_loopback):
                raise ValueError(
                    f"All resolved addresses must be private/local, got public: {sockaddr[0]}"
                )
        return url
    except ValueError:
        raise
    except Exception:
        pass
    raise ValueError(f"Ollama base_url must point to a local/private network address, got: {host}")


def _parse_int(val, name: str, lo: int = 1, hi: int = 262000) -> int:
    try:
        v = int(val)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")
    if v < lo or v > hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return v


def _compatible_client(bot):
    """Return the neutral client, tolerating the short-lived legacy member."""
    gateway = getattr(bot, "llm_gateway", None)
    # Read the instance dictionary first. Permissive test doubles manufacture
    # arbitrary attributes via __getattr__, which must not count as a client.
    values = getattr(gateway, "__dict__", {})
    if "compatible_client" in values:
        return values["compatible_client"]
    if "kimi_client" in values:
        return values["kimi_client"]
    return getattr(gateway, "compatible_client", None)


async def _reload_openai_compatible(bot) -> dict:
    """Reload through the neutral gateway API, with a rolling-upgrade fallback."""
    gateway = bot.llm_gateway
    values = getattr(gateway, "__dict__", {})
    reload_fn = values.get("reload_openai_compatible") or gateway.reload_openai_compatible
    return await reload_fn()


def _auxiliary_status(bot) -> dict:
    """Configured vs effective auxiliary state.

    ``enabled``/``model`` are the persisted config; the ``effective_*`` fields
    describe the live runtime wrapper (present only when config produced a
    working client). ``unavailable_reason`` is set when enabled config could
    NOT produce a live client (e.g. no auth). The four background jobs route
    to this model when enabled — there is no per-task configuration.
    """
    aux_cfg = getattr(bot.config.openai_codex, "auxiliary", None)
    live = getattr(bot.llm_gateway, "auxiliary_llm_client", None)
    configured_enabled = bool(aux_cfg and aux_cfg.enabled)
    unavailable_reason = None
    if configured_enabled and live is None:
        unavailable_reason = "enabled but selected auxiliary provider is unavailable"
    return {
        "enabled": configured_enabled,
        "model": aux_cfg.model if aux_cfg else "",
        "effective_enabled": live is not None,
        "effective_model": getattr(live, "model", None)
        or getattr(getattr(live, "aux_client", None), "model", None),
        "effective_provider": getattr(live, "provider", None),
        "unavailable_reason": unavailable_reason,
    }


def _model_catalogue(
    bot: Any, *, codex_configured: bool, ollama_configured: bool
) -> dict[str, list[dict[str, Any]]]:
    """Build the model-first status contract without hiding broken config."""
    compatible_cfg = getattr(bot.config, "openai_compatible", None)
    ollama_cfg = getattr(bot.config, "ollama", None)
    agents_cfg = getattr(bot.config, "agents", None)
    codex_names = [
        "gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna",
        "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
    ]
    if bot.config.openai_codex.model not in codex_names:
        codex_names.insert(0, bot.config.openai_codex.model)

    policy_refs = [
        item if isinstance(item, str) else item.model
        for item in (getattr(agents_cfg, "auto_model_allowlist", []) or [])
    ]
    fixed_agent = getattr(agents_cfg, "model", None)
    if fixed_agent not in (None, "auto"):
        policy_refs.append(fixed_agent)
    for ref in policy_refs:
        if ref and ":" not in ref and ref not in codex_names:
            codex_names.append(ref)

    from ...llm.context_budget import (
        compatible_agent_unavailable_reason,
        compatible_model_profile,
    )
    from ...tools.model_hints import catalogue_hint_metadata

    def entry(ref, provider, name, available, reason, capability, **extra):
        return {
            "ref": ref,
            "provider": provider,
            "name": name,
            "available": available,
            "unavailable_reason": reason,
            "capability": capability,
            "hint_metadata": catalogue_hint_metadata(ref, bot.config),
            **extra,
        }

    compatible_names = list((compatible_cfg.model_profiles if compatible_cfg else {}).keys())
    if compatible_cfg and compatible_cfg.preset == "openrouter":
        for name in compatible_cfg.openrouter.catalogue_profiles:
            if name not in compatible_names:
                compatible_names.append(name)
    if compatible_cfg and compatible_cfg.model not in compatible_names:
        compatible_names.insert(0, compatible_cfg.model)
    if compatible_cfg and compatible_cfg.preset == "openrouter":
        cached_models = _openrouter_cache.get("models")
        if isinstance(cached_models, list):
            for item in cached_models:
                name = item.get("id") if isinstance(item, dict) else None
                if isinstance(name, str) and name not in compatible_names:
                    compatible_names.append(name)
    ollama_names = [ollama_cfg.model] if ollama_cfg and ollama_cfg.model else []
    for ref in policy_refs:
        if ref.startswith("compat:"):
            name = ref.removeprefix("compat:")
            if name not in compatible_names:
                compatible_names.append(name)
        elif ref.startswith("ollama:"):
            name = ref.removeprefix("ollama:")
            if name not in ollama_names:
                ollama_names.append(name)
    compatible_available = bool(
        compatible_cfg and compatible_cfg.enabled and _compatible_client(bot)
    )

    def compatible_entry(name: str) -> dict[str, Any]:
        from ...tools.agent_tool_policy import model_reasoning_dialect

        agent_reason = compatible_agent_unavailable_reason(name, compatible_cfg)
        profile = compatible_model_profile(name, compatible_cfg)
        cached_model = next(
            (
                item
                for item in (_openrouter_cache.get("models") or [])
                if isinstance(item, dict) and item.get("id") == name
            ),
            None,
        )
        is_openrouter = bool(compatible_cfg and compatible_cfg.preset == "openrouter")
        dialect = model_reasoning_dialect(bot.config, f"compat:{name}")
        supports_openrouter_reasoning = bool(
            cached_model and cached_model.get("supports_reasoning")
        ) or getattr(profile, "supports_reasoning", False)
        if is_openrouter and isinstance(cached_model, dict):
            variant = cached_model.get("variant")
            if variant != "standard":
                agent_reason = f"{variant} variant is not offered for ordinary agents"
            elif profile is None:
                agent_reason = "select the model to auto-fill its route-derived profile"
        return entry(
            f"compat:{name}",
            "compat",
            name,
            compatible_available,
            None
            if compatible_available
            else (
                "disabled" if compatible_cfg and not compatible_cfg.enabled else "not configured"
            ),
            (
                "reasoning"
                if dialect == "effort" and (not is_openrouter or supports_openrouter_reasoning)
                else "thinking"
                if dialect == "thinking"
                else "none"
            ),
            agent_available=compatible_available and agent_reason is None,
            agent_unavailable_reason=(None if not compatible_available else agent_reason),
            profile=profile.model_dump() if profile is not None else None,
            efforts=(cached_model or {}).get("supported_efforts")
            or getattr(profile, "supported_efforts", None)
            or [],
        )

    return {
        "codex": [
            entry(
                name,
                "codex",
                name,
                codex_configured,
                None if codex_configured else "not configured",
                "reasoning",
                agent_available=codex_configured,
                agent_unavailable_reason=None if codex_configured else "not configured",
                efforts=list(CODEX_REASONING_EFFORTS),
            )
            for name in codex_names
        ],
        "compat": [compatible_entry(name) for name in compatible_names],
        "ollama": [
            entry(
                f"ollama:{name}",
                "ollama",
                name,
                ollama_configured,
                None
                if ollama_configured
                else ("disabled" if ollama_cfg and not ollama_cfg.enabled else "not configured"),
                "none",
                agent_available=ollama_configured,
                agent_unavailable_reason=None if ollama_configured else "not configured",
            )
            for name in ollama_names
        ],
    }


def _boot_codex_group_status(
    bot: Any,
    group: str,
    desired: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool | None]:
    """Return boot-effective values and whether desired differs.

    Connection-pool and context-compression objects are captured by runtime
    components at boot. The desired config object is therefore not evidence
    of what this process uses. ``None`` is deliberate when the boot snapshot
    is unavailable: unknown is more honest than inventing an applied state.
    """
    # Read concrete state rather than allowing proxies to invent a snapshot.
    boot = getattr(bot, "__dict__", {}).get("boot_config_snapshot")
    if not isinstance(boot, dict):
        return None, None
    codex_boot = boot.get("openai_codex")
    if not isinstance(codex_boot, dict):
        return None, None
    effective = codex_boot.get(group)
    if not isinstance(effective, dict):
        return None, None
    normalized = {key: effective.get(key) for key in desired}
    return normalized, normalized != desired


def _set_fields(obj, values: dict[str, object]) -> None:
    for key, value in values.items():
        setattr(obj, key, value)


def _provider_changes(
    section: str, desired: dict[str, object], body: dict
) -> list[tuple[tuple[str, ...], Any]]:
    return [((section, key), desired[key]) for key in desired if key in body]


def _parse_codex_advanced(body: dict, cfg) -> tuple[list, list, bool] | web.Response:
    """Validate merged schema values; replace submodels rather than mutating them."""
    from ...config.schema import (
        ConnectionPoolConfig,
        ContextCompressionConfig,
        RetryConfig,
    )

    integer_adapter = TypeAdapter(int)

    def _schema_int(value: Any, name: str, lo: int, hi: int) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be an integer")
        try:
            parsed = integer_adapter.validate_python(value)
        except ValidationError as exc:
            raise ValueError(f"{name} must be an integer") from exc
        if not lo <= parsed <= hi:
            raise ValueError(f"{name} must be between {lo} and {hi}")
        return parsed

    persist: list[tuple[tuple[str, ...], Any]] = []
    ops: list[tuple[str, Any]] = []
    wants_reload = False
    try:
        if "request_timeout_seconds" in body:
            value = _schema_int(
                body["request_timeout_seconds"], "request_timeout_seconds", 60, 86400
            )
            persist.append((("openai_codex", "request_timeout_seconds"), value))
            ops.append(("request_timeout_seconds", value))
            wants_reload = True
        if "stream_stall_timeout_seconds" in body:
            value = _schema_int(
                body["stream_stall_timeout_seconds"],
                "stream_stall_timeout_seconds",
                10,
                3600,
            )
            persist.append((("openai_codex", "stream_stall_timeout_seconds"), value))
            ops.append(("stream_stall_timeout_seconds", value))
            wants_reload = True
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    groups = (
        ("retry", RetryConfig, True),
        ("connection_pool", ConnectionPoolConfig, False),
        ("context_compression", ContextCompressionConfig, False),
    )
    for group, model_cls, live in groups:
        if group not in body:
            continue
        submitted = body[group]
        if not isinstance(submitted, dict):
            return web.json_response(
                {"error": f"{group} must be an object of settings"}, status=400
            )
        unknown = set(submitted) - set(model_cls.model_fields)
        if unknown:
            return web.json_response(
                {"error": f"unknown {group} field(s): {', '.join(sorted(unknown))}"},
                status=400,
            )
        current = getattr(cfg, group)
        try:
            merged = model_cls(**{**current.model_dump(), **submitted})
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(part) for part in first.get("loc", ()))
            return web.json_response(
                {"error": f"{group}.{loc}: {first.get('msg', 'invalid value')}"},
                status=400,
            )
        ops.append((group, merged))
        persist.extend((("openai_codex", group, key), getattr(merged, key)) for key in submitted)
        wants_reload = wants_reload or live
    try:
        candidate_payload = cfg.model_dump()
        if "context_budget_overrides" in body:
            candidate_payload["context_budget_overrides"] = body["context_budget_overrides"]
        if "context_utilization" in body:
            candidate_payload["context_utilization"] = body["context_utilization"]
        if "context_budget_overrides" in body or "context_utilization" in body:
            from ...config.schema import OpenAICodexConfig

            candidate = OpenAICodexConfig(**candidate_payload)
            for field in ("context_budget_overrides", "context_utilization"):
                if field not in body:
                    continue
                value = getattr(candidate, field)
                persist.append((("openai_codex", field), value))
                ops.append((field, value))
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(part) for part in first.get("loc", ()))
        return web.json_response(
            {"error": f"{loc}: {first.get('msg', 'invalid value')}"},
            status=400,
        )
    return persist, ops, wants_reload


def _apply_ops(cfg: Any, ops: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    """Apply ``(attribute, value)`` ops on cfg; return inverse ops.

    Nested groups arrive as whole model objects and REPLACE the previous
    object — the inverse holds the prior object by identity, so rollback
    restores exactly what boot-time captors still reference.
    """
    inverse: list[tuple[str, Any]] = []
    for attr, value in ops:
        inverse.append((attr, getattr(cfg, attr)))
        setattr(cfg, attr, value)
    return inverse


def register_connection_pools(*args, **kwargs):
    require_phase2("Provider pool management")


def register_llm_provider(*args, **kwargs):
    require_phase2("Provider selection and effective state")


def register_provider_config(*args, **kwargs):
    require_phase2("Provider settings and validated reload")


def register_context_windows(*args, **kwargs):
    require_phase2("Observed context-window settings")


def register_ollama_admin(*args, **kwargs):
    require_phase2("Local provider administration")


def register_openai_compatible_admin(*args, **kwargs):
    require_phase2("Compatible provider administration")
