"""Linux: the existing implementations, unchanged."""
from __future__ import annotations

from collections.abc import Mapping
from functools import cached_property
from pathlib import Path


class LinuxPlatform:
    name = "linux"
    computer_supported = True

    @cached_property
    def ipc(self):
        """The app ↔ engine transport: an owner-only Unix socket."""
        from .linux_ipc import LinuxIpc

        return LinuxIpc()

    def secret_backend(self, paths=None):
        """The profile keyring: the desktop session's Secret Service, shared by every profile."""
        from .. import secrets

        return secrets._SecretServiceBackend()

    def core_lifetime(self):
        """Signals and the parent pipe, watched on the event loop."""
        from ..lifecycle import CoreLifetime

        return CoreLifetime()

    def profile_paths(
        self,
        profile_id: str = "default",
        *,
        environ: Mapping[str, str] | None = None,
        home: Path | str | None = None,
    ):
        from ..paths import ProfilePaths

        return ProfilePaths.from_xdg(profile_id, environ=environ, home=home)

    def resolve_workspace(self, *args, **kwargs):
        """Odin's pinned resolver itself."""
        from ...tools.workspace import resolve_workspace

        return resolve_workspace(*args, **kwargs)
