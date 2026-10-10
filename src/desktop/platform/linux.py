"""Linux: the existing implementations, unchanged."""
from __future__ import annotations

from collections.abc import Mapping
from functools import cached_property
from pathlib import Path


class LinuxPlatform:
    name = "linux"

    @cached_property
    def ipc(self):
        """The app ↔ engine transport: an owner-only Unix socket."""
        from .linux_ipc import LinuxIpc

        return LinuxIpc()

    def profile_paths(
        self,
        profile_id: str = "default",
        *,
        environ: Mapping[str, str] | None = None,
        home: Path | str | None = None,
    ):
        from ..paths import ProfilePaths

        return ProfilePaths.from_xdg(profile_id, environ=environ, home=home)
