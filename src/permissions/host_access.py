"""Profile host policy. Missing authenticated owner always denies."""
from __future__ import annotations

import contextvars
import json
import os
import stat
from pathlib import Path

from ..json_store import StoreCorruptError, load_json_store, load_json_store_safe
from ..runtime_paths import runtime_profile_paths
from .persistence import write_private_atomic

_scope = contextvars.ContextVar("profile_host_scope", default=None)
_default = contextvars.ContextVar("profile_default_host", default="")

def _validate(data):
    hosts, default = data.get("allowed_hosts", []), data.get("default_host", "")
    if (
        set(data) - {"allowed_hosts", "default_host"}
        or not isinstance(hosts, list)
        or any(not isinstance(host, str) or not host for host in hosts)
        or not isinstance(default, str)
        or (default and default not in hosts)
    ):
        raise StoreCorruptError("invalid profile host policy")

class HostAccessEntry:
    def __init__(self, allowed_hosts=None, default_host=""):
        self.allowed_hosts, self.default_host = list(allowed_hosts or []), default_host
    def to_dict(self):
        return {"allowed_hosts": list(self.allowed_hosts), "default_host": self.default_host}

class HostAccessManager:
    def __init__(
        self,
        path=None,
        available_hosts=None,
        available_hosts_provider=None,
        *,
        permission_manager=None,
    ):
        self._path = (
            Path(path)
            if path is not None
            else runtime_profile_paths().config_dir / "host-policy.json"
        )
        self._permission_manager = permission_manager
        self._available_hosts = list(available_hosts or [])
        self._available_hosts_provider = available_hosts_provider
        self.durability_degraded = False
        data, ok = load_json_store_safe(self._path, validate=_validate, what="profile host policy")
        self._store_corrupt = not ok
        self._policy = HostAccessEntry(
            data.get("allowed_hosts", []) if ok else [],
            data.get("default_host", "") if ok else "",
        )
    @property
    def available_hosts(self):
        return (
            list(self._available_hosts_provider())
            if self._available_hosts_provider
            else list(self._available_hosts)
        )
    def set_available_hosts(self, hosts):
        self._available_hosts = list(hosts)
    @property
    def default_policy(self):
        return HostAccessEntry(self._policy.allowed_hosts, self._policy.default_host)
    @staticmethod
    def set_request_host_scope(hosts):
        return _scope.set(tuple(hosts))
    @staticmethod
    def reset_request_host_scope(token):
        _scope.reset(token)
    @staticmethod
    def set_request_default_host(host):
        return _default.set(host)
    @staticmethod
    def reset_request_default_host(token):
        _default.reset(token)
    def get_allowed_hosts(self, owner_id):
        if (
            self._store_corrupt
            or self._permission_manager is None
            or not self._permission_manager.is_owner(owner_id)
        ):
            return []
        try:
            fd = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_size > 65536
                ):
                    return []

                def unique(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError("duplicate profile host policy key")
                        result[key] = value
                    return result

                data = json.load(stream, object_pairs_hook=unique)
            _validate(data)
            self._policy = HostAccessEntry(
                data.get("allowed_hosts", []), data.get("default_host", "")
            )
        except (OSError, ValueError, TypeError, StoreCorruptError):
            return []
        available, scope = self.available_hosts, _scope.get()
        return [
            host
            for host in self._policy.allowed_hosts
            if host in available and (scope is None or host in scope)
        ]
    def get_default_host(self, owner_id):
        default = _default.get() or self._policy.default_host
        return default if default in self.get_allowed_hosts(owner_id) else ""
    def is_host_allowed(self, owner_id, host):
        return host in self.get_allowed_hosts(owner_id)
    async def set_policy(self, owner_id, allowed_hosts, default_host="") -> bool:
        if self._permission_manager is None or not self._permission_manager.is_owner(owner_id):
            raise PermissionError("authenticated profile owner required")
        candidate = {"allowed_hosts": allowed_hosts, "default_host": default_host}
        _validate(candidate)
        if any(h not in self.available_hosts for h in allowed_hosts):
            raise ValueError("host is not configured")
        load_json_store(self._path, validate=_validate)
        durable = write_private_atomic(self._path, json.dumps(candidate, indent=2))
        self._policy = HostAccessEntry(allowed_hosts, default_host)
        self._store_corrupt = False
        self.durability_degraded = not durable
        return durable
        return durable
