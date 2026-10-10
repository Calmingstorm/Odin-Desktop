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

    def resolve_local_shell(self, mode: str = "auto"):
        """The local command shell: bash when available, otherwise /bin/sh."""
        from ...tools import command_shell

        return command_shell.resolve_local_shell(mode)

    async def create_local_shell(self, command, **options):
        """A supervised local command, run by the Linux supervisor worker.

        Looked up at call time, so a test that replaces the supervisor still reaches it.
        """
        from ...tools import local_supervisor

        return await local_supervisor.create_supervised_shell(command, **options)

    def secret_backend(self):
        """The profile keyring: the desktop session's Secret Service."""
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
