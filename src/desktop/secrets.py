"""Profile-only private secret storage. No server inventory or import."""
from __future__ import annotations

import os
import re
import stat

from ..permissions.persistence import write_private_atomic
from .paths import ProfilePaths


class ProfileSecretStore:
    def __init__(self, paths: ProfilePaths):
        paths.create_private()
        self.paths = paths
        self.durability_degraded = False
    def _name(self, name):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
            raise ValueError("invalid secret identifier")
        return name
    def set(self, name, value) -> bool:
        if not isinstance(value, str) or len(value.encode("utf-8")) > 65536:
            raise ValueError("secret must be a bounded string")
        durable = write_private_atomic(
            self.paths.secrets_dir / self._name(name), value
        )
        self.durability_degraded = not durable
        return durable
    def get(self, name):
        self.paths.create_private()
        try:
            fd = os.open(self.paths.secrets_dir / self._name(name), os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > 65536
            ):
                raise PermissionError("unsafe secret record")
            return stream.read(65537)
