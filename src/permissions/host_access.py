"""Authenticated owner host access and a separate default-host preference.

D17 grants the owner every live, targetable enrolled host. A preference is not
an access policy: missing or damaged preferences never narrow that inventory.
Legacy host-policy.json files are neither read nor migrated.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from ..desktop.platform.variants import windows_variant
from ..json_store import StoreCorruptError, load_json_store
from ..runtime_paths import runtime_profile_paths
from .persistence import write_private_atomic


def _validate(data):
    if (
        not isinstance(data, dict)
        or set(data) - {"default_host"}
        or not isinstance(data.get("default_host", ""), str)
    ):
        raise StoreCorruptError("invalid default-host preference")


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate default-host preference key")
        result[key] = value
    return result


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
            else runtime_profile_paths().config_dir / "host-preferences.json"
        )
        self._permission_manager = permission_manager
        self._available_hosts = list(available_hosts or [])
        self._available_hosts_provider = available_hosts_provider
        self.durability_degraded = False

    @property
    def available_hosts(self):
        # Do not cache enrollment, retirement or revocation between requests.
        return (
            list(self._available_hosts_provider())
            if self._available_hosts_provider is not None
            else list(self._available_hosts)
        )

    def set_available_hosts(self, hosts):
        self._available_hosts = list(hosts)

    @property
    @windows_variant("src.desktop.platform.windows_engine:host_access_default_host")
    def default_host(self):
        """Read the preference, never an owner grant or a host trust decision."""
        try:
            fd = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_size > 65536
                ):
                    return ""
                data = json.load(stream, object_pairs_hook=_unique_keys)
            _validate(data)
            return data.get("default_host", "")
        except (OSError, ValueError, TypeError, StoreCorruptError):
            return ""

    def get_allowed_hosts(self, owner_id):
        if self._permission_manager is None or not self._permission_manager.is_owner(owner_id):
            return []
        return self.available_hosts

    def get_default_host(self, owner_id):
        hosts = self.get_allowed_hosts(owner_id)
        default = self.default_host if hosts else ""
        return default if default in hosts else ""

    def is_host_allowed(self, owner_id, host):
        return host in self.get_allowed_hosts(owner_id)

    async def set_default_host(self, owner_id, default_host="") -> bool:
        if self._permission_manager is None or not self._permission_manager.is_owner(owner_id):
            raise PermissionError("authenticated profile owner required")
        candidate = {"default_host": default_host}
        _validate(candidate)
        if default_host and default_host not in self.available_hosts:
            raise ValueError("host is not configured or available")
        load_json_store(self._path, validate=_validate)
        durable = write_private_atomic(self._path, json.dumps(candidate, indent=2))
        self.durability_degraded = not durable
        return durable
