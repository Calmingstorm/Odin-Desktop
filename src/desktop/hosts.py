"""Named managed-host commands backed by Odin's enrollment and lease registry.

No transport/RBAC gate lives here. Management authenticates the profile owner;
Odin's existing SSH trust, connection-test and reference rules live below it.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from ..config.persistence import DELETE_CONFIG_PATH
from ..config.schema import ToolHost
from ..tools.hosts import HostEnrollmentManager, HostRegistry, HostTrustError
from ..tools.hosts.control import public_key_info, scan_host_references
from .management import MethodError

METHODS = frozenset({
    "hosts.list", "hosts.settings", "hosts.prepare", "hosts.test", "hosts.commit",
    "hosts.set_enabled", "hosts.references", "hosts.delete", "hosts.public_key",
    "hosts.force_revoke",
})
READ_METHODS = frozenset({"hosts.list", "hosts.references", "hosts.public_key"})


def _leaf_changes(before: dict, after: dict) -> list:
    changes = []
    for alias in before.keys() - after.keys():
        changes.append((("tools", "hosts", alias), DELETE_CONFIG_PATH))
    for alias in after.keys() - before.keys():
        changes.append((("tools", "hosts", alias), after[alias]))
    for alias in before.keys() & after.keys():
        old, new = before[alias], after[alias]
        for field in old.keys() | new.keys():
            if field not in new:
                changes.append((("tools", "hosts", alias, field), DELETE_CONFIG_PATH))
            elif old.get(field) != new.get(field):
                changes.append((("tools", "hosts", alias, field), new[field]))
    return changes


async def _drain_mutation(operation, *, commit_started: asyncio.Event):
    """Cancel queued work; once persistence begins, drain publication."""
    task = asyncio.create_task(operation, name="desktop-host-mutation")
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not commit_started.is_set():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                raise
            cancelled = True
            current = asyncio.current_task()
            if current is not None:
                while current.cancelling():
                    current.uncancel()
    result = await task
    if cancelled:
        raise asyncio.CancelledError
    return result


class HostsService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, settings, *, registry=None, executor=None, scheduler=None):
        self.settings = settings
        self.executor = executor
        self.scheduler = scheduler
        tools = settings.config.tools
        self.registry = registry or getattr(executor, "host_registry", None) or HostRegistry(
            tools.hosts, profile_paths=settings.paths,
            key_path=tools.ssh_key_path,
            legacy_known_hosts_path=tools.ssh_known_hosts_path,
            default_host=tools.default_host,
        )
        self._lock = asyncio.Lock()
        self.enrollments = HostEnrollmentManager(self.registry, publication_lock=self._lock)

    def _current(self) -> dict:
        return {
            alias: host.model_dump() for alias, host in self.settings.config.tools.hosts.items()
        }

    def _response(self, alias: str, *, saved=False, references=None) -> dict:
        row = next((r for r in self.registry.status_rows() if r["alias"] == alias), None)
        tools = self.settings.config.tools
        result = {
            "saved": saved, "active": bool(row and row["active"]),
            "targetable": bool(row and row["targetable"]),
            "trust_state": row["trust_state"] if row else "removed",
            "last_test": row["last_test"] if row else None,
            "draining": alias in self.registry.draining_aliases(),
            "pending_references": references or [], "registry_generation": self.registry.generation,
            "ssh_paths": {
                "desired_key": tools.ssh_key_path,
                "effective_key": self.registry.effective_key_path,
                "desired_known_hosts": tools.ssh_known_hosts_path,
                "effective_known_hosts": self.registry.effective_legacy_known_hosts_path,
                "restart_pending": tools.ssh_key_path != self.registry.effective_key_path
                or tools.ssh_known_hosts_path != self.registry.effective_legacy_known_hosts_path,
            },
        }
        if row:
            result["host"] = row
        return result

    def _require_host(self, params) -> str:
        alias = params.get("alias")
        if not isinstance(alias, str) or alias not in self.settings.config.tools.hosts:
            raise MethodError("not_found", "host not found")
        return alias

    def _references(self, alias: str) -> list:
        return scan_host_references(
            self.settings.config, alias, scheduler=self.scheduler,
            background_tasks=getattr(self.executor, "_background_tasks", None),
        )

    def _publish(self, alias, before, desired, *, test_result=None) -> dict:
        models = {name: ToolHost(**value) for name, value in desired.items()}
        try:
            staged = self.registry.stage(
                models, default_host=self.settings.config.tools.default_host
            )
        except Exception as exc:
            raise MethodError("internal_error", f"host runtime preparation failed: {exc}") from exc
        # This is synchronous: no cancellation/other request can interleave
        # saving the desired revision and publication of its prepared runtime.
        changes = _leaf_changes(before, desired)
        self.settings.save_changes(
            changes, method="hosts.settings",
            expected_revision=self.settings.revision,
        )
        self.registry.publish_staged(staged)
        if test_result and alias in self.settings.config.tools.hosts:
            self.registry.mark_test_result(alias, test_result)
        if hasattr(self.settings, "confirm_applied"):
            self.settings.confirm_applied(changes)
        return self._response(alias, saved=True)

    async def handle(self, method: str, params: dict[str, Any]) -> dict:
        if method not in METHODS:
            raise MethodError("method_not_found", "unknown hosts method")
        if not isinstance(params, dict):
            raise MethodError("bad_request", "params must be an object")
        try:
            return await self._handle(method, params)
        except (HostTrustError, ValueError, TypeError) as exc:
            raise MethodError("bad_request", str(exc)) from exc

    async def _handle(self, method, params):
        tools = self.settings.config.tools
        if method == "hosts.list":
            return {"hosts": self.registry.status_rows(),
                    "default_host": self.registry.default_host,
                    "configured_default_host": tools.default_host,
                    "generation": self.registry.generation, "tofu_enabled": tools.allow_host_tofu}
        if method == "hosts.public_key":
            info = await public_key_info(self.registry.effective_key_path)
            return {**info, "effective_key_path": self.registry.effective_key_path,
                    "desired_key_path": tools.ssh_key_path,
                    "restart_pending": self.registry.effective_key_path != tools.ssh_key_path}
        if method == "hosts.prepare":
            alias = str(params.get("alias", ""))
            candidate = await self.enrollments.prepare(
                alias, params, allow_tofu=tools.allow_host_tofu, existing=tools.hosts.get(alias)
            )
            return {"candidate_token": candidate.token, "alias": candidate.alias,
                    "host_id": candidate.host_id, "fingerprints": list(candidate.fingerprints),
                    "trust_mode": candidate.trust_mode, "tested": candidate.tested}
        if method == "hosts.test":
            candidate = await self.enrollments.test(params.get("token", ""))
            result = {"candidate_token": candidate.token, "tested": candidate.tested,
                      "last_test": candidate.test_result}
            if not candidate.tested:
                result["error"] = (
                    (candidate.test_result or {}).get("detail") or "connection test failed"
                )
            return result
        if method == "hosts.commit":
            candidate = self.enrollments.get(params.get("token", ""))
            if not candidate.tested:
                raise HostTrustError("candidate must pass the connection test before activation")
            if candidate.trust_mode == "tofu" and not candidate.tofu_confirmed:
                raise HostTrustError(
                    "TOFU candidate requires a second confirmation bound to its exact fingerprints"
                )
            started = asyncio.Event()

            async def commit():
                async with self._lock:
                    before = self._current()
                    definition = (
                        tuple(sorted(before[candidate.alias].items()))
                        if candidate.alias in before else None
                    )
                    if definition != candidate.expected_definition:
                        raise MethodError(
                            "conflict", "host changed after this candidate was prepared"
                        )
                    desired = {**before, candidate.alias: candidate.as_tool_host().model_dump()}
                    started.set()
                    result = self._publish(
                        candidate.alias, before, desired, test_result=candidate.test_result
                    )
                    self.enrollments.discard(candidate.token)
                    return result
            return await _drain_mutation(commit(), commit_started=started)
        if method == "hosts.settings":
            if not params or set(params) - {"default_host", "allow_host_tofu"}:
                raise MethodError(
                    "bad_request", "only default_host and allow_host_tofu may be changed"
                )
            async with self._lock:
                tools = self.settings.config.tools
                default = params.get("default_host", tools.default_host)
                tofu = params.get("allow_host_tofu", tools.allow_host_tofu)
                if not isinstance(default, str):
                    raise MethodError("bad_request", "default_host must be a string")
                default = default.strip()
                if default and default not in tools.hosts:
                    raise MethodError("bad_request", "default_host must name a configured host")
                if not isinstance(tofu, bool):
                    raise MethodError("bad_request", "allow_host_tofu must be boolean")
                changes = []
                if default != tools.default_host:
                    changes.append((("tools", "default_host"), default))
                if tofu != tools.allow_host_tofu:
                    changes.append((("tools", "allow_host_tofu"), tofu))
                staged = self.registry.stage(tools.hosts, default_host=default)
                self.settings.save_changes(
                    changes, method=method, expected_revision=self.settings.revision
                )
                self.registry.publish_staged(staged)
                if hasattr(self.settings, "confirm_applied"):
                    self.settings.confirm_applied(changes)
                return {"saved": True, "default_host": self.registry.default_host,
                        "configured_default_host": default, "tofu_enabled": tofu,
                        "registry_generation": self.registry.generation}
        alias = self._require_host(params)
        if method == "hosts.references":
            return {"alias": alias, "references": self._references(alias)}
        if method == "hosts.force_revoke":
            processes = {"attempted": 0, "killed": 0, "unknown": 0}
            process_registry = getattr(self.executor, "_process_registry", None)
            try:
                if process_registry is not None:
                    processes = await process_registry.force_revoke_host(alias)
            except Exception:
                processes["unknown"] = max(1, processes["unknown"])
            finally:
                # Cleanup uses existing leases; trip their fences afterwards.
                revoked = self.registry.force_revoke_keys(alias)
            return {
                **self._response(alias), "leases_interrupted": len(revoked), "processes": processes
            }
        async with self._lock:
            alias = self._require_host(params)
            before = self._current()
            if method == "hosts.set_enabled":
                if not isinstance(params.get("enabled"), bool):
                    raise MethodError("bad_request", "enabled must be boolean")
                desired = {**before, alias: {**before[alias], "enabled": params["enabled"]}}
            else:
                references = self._references(alias)
                if references:
                    raise MethodError(
                        "conflict", "host deletion is blocked by configured references: "
                        + "; ".join(r["location"] for r in references)
                    )
                desired = dict(before)
                del desired[alias]
            return self._publish(alias, before, desired)
