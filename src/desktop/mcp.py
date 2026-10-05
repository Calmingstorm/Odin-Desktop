"""Profile-owned MCP management over the retained supervised control plane.

Composition: construct once, register METHODS with ManagementService, await
start() before advertising management, and await close() during quiescence.
Use get_tool_definitions/has_tool and on_catalog_changed for the model catalog.
Part B calls execute with its *trusted* current dispatch identity; this module
does not interpret MCP instructions, tool arguments or credentials as authority,
deliver results, replay calls, or grant foreground computer consent.

Credentials use the existing profile secret paths. Containers are JSON in the
keyring at mcp.servers.<name>.headers/env, not plaintext config. Endpoint secrets
use mcp.servers.<name>.url; the saved URL is credential-free recognition data.
Only the section controls write these containers. Generic secrets.set is not a
container-JSON API. prepare_settings is the reload composition seam: adoption is
await-free, retirement/reconciliation must subsequently be drained by finish().
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from ..config.persistence import DELETE_CONFIG_PATH, _config_file_lock, _patch_config_paths
from ..config.schema import MCPConfig, MCPServerConfig
from ..tools.mcp.errors import MCPConfigError
from ..tools.mcp.manager import MCPManager, validate_server_config
from ..tools.mcp.outcomes import OUTCOME_FAILED, MCPToolOutcome
from .management import MethodError

METHODS = frozenset({
    "mcp.list", "mcp.status", "mcp.tools", "mcp.save", "mcp.set_enabled",
    "mcp.delete", "mcp.reconnect", "mcp.refresh_tools", "mcp.set_global_enabled",
    "mcp.set_limits",
})
READ_METHODS = frozenset({"mcp.list", "mcp.status", "mcp.tools"})
_PUBLIC_FIELDS = frozenset(MCPServerConfig.model_fields) - {"headers", "env"}
_LIMIT_FIELDS = {"max_published_tools_per_server", "max_published_tools_global"}


def _secret_path(name, field):
    return f"mcp.servers.{name}.{field}"


def _public_url(value):
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))


def _mapping(value):
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not key or any(c in key for c in "\r\n\0")
        or not isinstance(item, str) or "\0" in item
        or re.fullmatch(r"(?:\[REDACTED\])+|[•*]{4,}", item)
        for key, item in value.items()
    ):
        raise MethodError("bad_request", "Invalid MCP credential mapping or redaction mask")
    # Same private-store bound applies to an entire container, not each leaf.
    if len(json.dumps(value).encode()) > 65536:
        raise MethodError("bad_request", "MCP credential mapping exceeds keyring bounds")
    return copy.deepcopy(value)


class MCPService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, settings, *, permissions=None, manager=None, on_catalog_changed=None,
                 reserved_names_provider=None):
        self.settings = settings
        self.permissions = permissions
        self._reserved_names_provider = reserved_names_provider or (lambda: set())
        self._effective_limits = settings.config.mcp.model_copy(deep=True)
        self.manager = manager or MCPManager(
            on_catalog_changed=on_catalog_changed,
            max_published_tools_per_server_provider=(
                lambda: self._effective_limits.max_published_tools_per_server
            ),
            max_published_tools_global_provider=(
                lambda: self._effective_limits.max_published_tools_global
            ),
            reserved_names_provider=reserved_names_provider,
        )
        if manager is not None and on_catalog_changed is not None:
            manager.set_on_catalog_changed(on_catalog_changed)
        self._lock = asyncio.Lock()
        self._started = False
        self._closed = False
        self._startup_error = ""

    def _hydrate(self, config):
        servers = {}
        try:
            for name, row in config.mcp.servers.items():
                value = row.model_dump()
                for field in ("headers", "env"):
                    # Imported plaintext is not silently promoted to a credential.
                    if value[field]:
                        raise ValueError("plaintext MCP credentials require explicit migration")
                    stored = self.settings.secrets.get(_secret_path(name, field))
                    value[field] = _mapping(json.loads(stored)) if stored is not None else {}
                stored_url = self.settings.secrets.get(_secret_path(name, "url"))
                if value["url"] and _public_url(value["url"]) != value["url"]:
                    raise ValueError("plaintext MCP endpoint credentials")
                if stored_url is not None:
                    if _public_url(stored_url) != value["url"]:
                        raise ValueError("MCP endpoint keyring binding changed")
                    value["url"] = stored_url
                servers[name] = value
        except Exception:
            raise MethodError(
                "capability_unavailable", "MCP configuration or keyring is unavailable",
            ) from None
        return servers

    async def start(self, *, wait_for_first_attempt=False):
        """Configured startup; probes stay bounded and supervisor-owned."""
        async with self._lock:
            if self._closed:
                raise MethodError("capability_unavailable", "MCP service is closed")
            if self._started:
                return
            try:
                servers = self._hydrate(self.settings.config)
            except MethodError as exc:
                # Keep management usable while publishing/starting nothing.
                self._startup_error = exc.message
                return
            await self.manager.load_desired_state(
                enabled=self.settings.config.mcp.enabled, servers=servers,
            )
            self._effective_limits = self.settings.config.mcp.model_copy(deep=True)
            await self.manager.start(wait_for_first_attempt=wait_for_first_attempt)
            self._started = True
            self._startup_error = ""

    async def close(self):
        # Fence before awaiting the service lock or an in-flight management op.
        self._closed = True
        await self.manager.shutdown()

    shutdown = close

    def get_tool_definitions(self):
        if self._closed:
            return []
        reserved = self._reserved_names_provider()
        return [row for row in self.manager.get_tool_definitions() if row["name"] not in reserved]

    def has_tool(self, name):
        return (not self._closed and name not in self._reserved_names_provider()
                and self.manager.has_tool(name))

    def set_on_catalog_changed(self, callback):
        self.manager.set_on_catalog_changed(callback)

    async def execute(self, name, tool_input, *, owner_id):
        """Part-B dispatch seam. Never promote server text to a caller identity.

        The request owner context must already be installed by the trusted
        dispatcher. This retains typed media/outcome/provenance and NEVER retries.
        Non-owner/background admission belongs to Part B, not server credentials.
        """
        if self.permissions is None or not self.permissions.is_owner(owner_id):
            return MCPToolOutcome(
                status=OUTCOME_FAILED, text="MCP caller authority is unavailable",
                server="", tool=name,
            )
        if name in self._reserved_names_provider():
            return MCPToolOutcome(
                status=OUTCOME_FAILED, text="MCP tool name is reserved", server="", tool=name,
            )
        return await self.manager.execute(name, tool_input)

    def _status(self):
        status = self.manager.get_status()
        status.update(started=self._started and not self._closed, closed=self._closed,
                      startup_error=self._startup_error, revision=self.settings.revision)
        status["configured_server_count"] = len(self.settings.config.mcp.servers)
        status["configured_servers"] = list(self.settings.config.mcp.servers)
        return status

    def _name(self, params):
        name = params.get("name")
        # This also makes existing profile secret paths unambiguous.
        try:
            if not isinstance(name, str):
                raise MCPConfigError("invalid name")
            validate_server_config(name, {"transport": "stdio", "command": "configured"})
        except MCPConfigError:
            raise MethodError("bad_request", "Invalid MCP server name") from None
        return name

    def _check_revision(self, params):
        self.settings._check_revision(params.get("expected_revision"))

    async def handle(self, method, params):
        if method not in METHODS:
            raise MethodError("not_found", "Unknown MCP method")
        if not isinstance(params, dict):
            raise MethodError("bad_request", "params must be an object")
        async with self._lock:
            if method in {"mcp.list", "mcp.status"}:
                if params:
                    raise MethodError("bad_request", "MCP status accepts no parameters")
                return self._status()
            if self._closed:
                raise MethodError("capability_unavailable", "MCP service is closed")
            if method == "mcp.tools":
                if set(params) != {"name"}:
                    raise MethodError("bad_request", "MCP tools requires name")
                name = self._name(params)
                self._require_server(name)
                return {"name": name, "tools": self.manager.server_tools(name)}
            self._check_revision(params)
            if method in {"mcp.reconnect", "mcp.refresh_tools"}:
                if set(params) - {"name", "expected_revision"}:
                    raise MethodError("bad_request", "Unexpected MCP operation field")
                name = self._name(params)
                self._require_server(name)
                if not self._started:
                    raise MethodError(
                        "capability_unavailable", "MCP startup requires a usable keyring",
                    )
                operation = (self.manager.reconnect_server if method == "mcp.reconnect"
                             else self.manager.refresh_server_tools)
                await operation(name)
                return self._status()
            return await self._mutate(method, params)

    def _require_server(self, name):
        if name not in self.settings.config.mcp.servers:
            raise MethodError("not_found", "MCP server not found")
        if name not in self.manager.server_names:
            raise MethodError("capability_unavailable", "MCP server is not adopted")

    async def _mutate(self, method, params):
        desired = self.settings.config.model_copy(deep=True)
        vault = {}
        path = ("mcp",)
        # A keyring relock cannot prevent revocation of already-adopted servers.
        revoke_unstarted = (not self._started and method == "mcp.set_global_enabled"
                            and params.get("enabled") is False)
        if revoke_unstarted:
            # No adopted transports or tools exist. Disabling desired startup
            # needs no credential read. Do not mark this partial state started.
            runtime = {}
        else:
            runtime = (self.manager.desired_servers() if self._started
                       else self._hydrate(self.settings.config))
        if method == "mcp.set_global_enabled":
            if (set(params) - {"enabled", "expected_revision"}
                    or type(params.get("enabled")) is not bool):
                raise MethodError("bad_request", "enabled must be a boolean")
            desired.mcp.enabled = params["enabled"]
            path = ("mcp", "enabled")
        elif method == "mcp.set_limits":
            values = {key: params[key] for key in _LIMIT_FIELDS if key in params}
            if not values or set(params) - (_LIMIT_FIELDS | {"expected_revision"}):
                raise MethodError("bad_request", "Provide MCP publication limits")
            try:
                desired.mcp = MCPConfig.model_validate(desired.mcp.model_dump() | values)
            except ValidationError:
                raise MethodError(
                    "bad_request", "MCP publication limits are outside retained bounds",
                ) from None
        else:
            name = self._name(params)
            existing = name in desired.mcp.servers
            if method in {"mcp.delete", "mcp.set_enabled"} and not existing:
                raise MethodError("not_found", "MCP server not found")
            if method == "mcp.delete":
                if set(params) - {"name", "expected_revision"}:
                    raise MethodError("bad_request", "Unexpected MCP deletion field")
                del desired.mcp.servers[name]
                runtime.pop(name, None)
                for field in ("headers", "env", "url"):
                    vault[_secret_path(name, field)] = None
            else:
                value = copy.deepcopy(runtime[name]) if existing else MCPServerConfig().model_dump()
                self._patch_server(method, params, value)
                try:
                    row = MCPServerConfig.model_validate(value)
                    validate_server_config(name, row.model_dump())
                except (ValidationError, MCPConfigError, ValueError):
                    raise MethodError("bad_request", "Invalid MCP server configuration") from None
                runtime[name] = row.model_dump()
                public = row.model_dump()
                for field in ("headers", "env"):
                    if method != "mcp.set_enabled":
                        vault[_secret_path(name, field)] = (
                            json.dumps(public[field]) if public[field] else None
                        )
                    public[field] = {}
                raw_url = public["url"]
                try:
                    public["url"] = _public_url(raw_url) if raw_url else ""
                except ValueError:
                    raise MethodError("bad_request", "Invalid MCP endpoint") from None
                if len(raw_url.encode()) > 65536:
                    raise MethodError("bad_request", "MCP endpoint exceeds keyring bounds")
                if method != "mcp.set_enabled":
                    vault[_secret_path(name, "url")] = (
                        raw_url if raw_url != public["url"] else None
                    )
                desired.mcp.servers[name] = MCPServerConfig.model_validate(public)
            path = ("mcp", "servers", name)

        # Secret containers are persisted empty by their owning section. The
        # generic settings helper correctly rejects this route's secret leaves,
        # so use its same lock/writer/publish primitives, never a second YAML writer.
        value = desired.mcp.model_dump() if path == ("mcp",) else (
            desired.mcp.enabled if path == ("mcp", "enabled") else
            desired.mcp.servers[path[-1]].model_dump()
            if path[-1] in desired.mcp.servers else DELETE_CONFIG_PATH
        )
        changes = [(path, value)]
        if method == "mcp.set_limits":
            changes = [(("mcp", key), getattr(desired.mcp, key)) for key in values]
        previous = {}
        touched = []
        with self.settings._lock, _config_file_lock(self.settings.paths.config_file):
            self._check_revision(params)
            if self.settings._transaction_active:
                raise MethodError(
                    "stale_binding", "Settings transaction is in progress", "stale_binding",
                )
            snapshot = self.settings._snapshot()
            write_started = False
            try:
                for key, item in vault.items():
                    previous[key] = self.settings.secrets.get(key)
                    if previous[key] == item:
                        continue
                    touched.append(key)  # failed-after-effect is also rolled back
                    result = (self.settings.secrets.set(key, item) if item is not None
                              else self.settings.secrets.clear(key))
                    if result is False:
                        raise RuntimeError("keyring rejected write")
                if self._closed:
                    raise MethodError("capability_unavailable", "MCP service is closed")
                write_started = True
                _patch_config_paths(changes, path=self.settings.paths.config_file)
            except Exception as exc:
                failed = False
                if write_started:
                    try:
                        self.settings._restore(snapshot)
                    except Exception:
                        failed = True
                for key in reversed(touched):
                    try:
                        result = (self.settings.secrets.set(key, previous[key])
                                  if previous[key] is not None
                                  else self.settings.secrets.clear(key))
                        if result is False:
                            raise RuntimeError("rollback refused")
                    except Exception:
                        failed = True
                if failed:
                    raise MethodError(
                        "internal_error", "MCP settings rollback is unproven", "outcome_unknown",
                    ) from None
                if isinstance(exc, MethodError):
                    raise
                raise MethodError("internal_error", "MCP settings were not saved") from None
            self.settings._publish(desired, changes, True)
            self._effective_limits = desired.mcp.model_copy(deep=True)
            # Durable desired state and synchronous unpublication are committed
            # without an await. Reachability is not a save precondition.
            transition = self.manager.stage_desired_state(
                enabled=desired.mcp.enabled, servers=runtime,
            )
        await self.manager.finish_desired_state(transition)
        if not self._started and not revoke_unstarted:
            await self.manager.start(wait_for_first_attempt=False)
            self._started = True
            self._startup_error = ""
        return {"saved": True, **self._status()}

    @staticmethod
    def _patch_server(method, params, value):
        if method == "mcp.set_enabled":
            if (set(params) - {"name", "enabled", "expected_revision"}
                    or type(params.get("enabled")) is not bool):
                raise MethodError("bad_request", "enabled must be a boolean")
            value["enabled"] = params["enabled"]
            return
        allowed = _PUBLIC_FIELDS | {
            "name", "expected_revision", "headers_set", "headers_remove", "env_set", "env_remove",
        }
        if set(params) - allowed:
            raise MethodError(
                "bad_request", "Unexpected MCP field; use credential patch operations",
            )
        for field in _PUBLIC_FIELDS:
            if field in params:
                item = params[field]
                if field == "enabled" and type(item) is not bool:
                    raise MethodError("bad_request", "enabled must be a boolean")
                if field == "timeout_seconds" and type(item) is not int:
                    raise MethodError("bad_request", "timeout_seconds must be an integer")
                value[field] = item
        for field in ("headers", "env"):
            if field + "_set" in params:
                value[field].update(_mapping(params[field + "_set"]))
            if field + "_remove" in params:
                remove = params[field + "_remove"]
                if (not isinstance(remove, list)
                        or any(not isinstance(key, str) for key in remove)):
                    raise MethodError(
                        "bad_request", "MCP credential removals must be key arrays",
                    )
                for key in remove:
                    value[field].pop(key, None)
            value[field] = _mapping(value[field])

    def prepare_settings(self, desired, changes):
        """Atomic composite-reload seam. Caller owns serialization and finish.

        apply() stages without I/O. Invoke finish() inside the composite apply
        before publishing the shared config. Admission limits follow this token,
        not the still-old settings root. Before apply, rollback is inert; after apply it stages
        the previous snapshot and drains retirement. Never automatically replay
        a tools/call during reload, reconnect, or rollback.
        """
        if self._closed:
            raise MethodError("capability_unavailable", "MCP service is closed")
        if any(
            path and path[0] == "mcp" and len(path) >= 4
            and path[3] in {"headers", "env"}
            for path, _ in changes
        ):
            raise MethodError(
                "bad_request", "MCP credential containers use mcp.save patch operations",
            )
        servers = self._hydrate(desired)
        before_enabled = self.manager.global_enabled
        before_servers = self.manager.desired_servers()
        before_limits = self._effective_limits
        service = self

        class PreparedMCP:
            transition = None
            applied = False

            def apply(self):
                if self.applied:
                    raise RuntimeError("MCP prepared change already applied")
                service._effective_limits = desired.mcp.model_copy(deep=True)
                self.transition = service.manager.stage_desired_state(
                    enabled=desired.mcp.enabled, servers=servers,
                )
                self.applied = True
                return True

            async def finish(self):
                if self.transition is not None:
                    await service.manager.finish_desired_state(self.transition)
                    self.transition = None

            async def rollback(self):
                if self.applied:
                    service._effective_limits = before_limits
                    pending, self.transition = self.transition, None
                    previous = service.manager.stage_desired_state(
                        enabled=before_enabled, servers=before_servers,
                    )
                    if pending is not None:
                        await service.manager.finish_desired_state(pending)
                    await service.manager.finish_desired_state(previous)
                    self.applied = False

        return PreparedMCP()

    def reject_generic_credentials(self, desired, previous, changes):
        """Optional settings-owner hook: containers have a dedicated patch API."""
        raise MethodError(
            "bad_request", "MCP credential containers use mcp.save patch operations",
        )
