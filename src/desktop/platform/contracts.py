"""What each operating system provides to the engine.

A platform is chosen once by ``current_platform()``. Linux's members are the
existing implementations, so Linux behaviour cannot change through this seam.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import asyncio

    from ..paths import ProfilePaths


class IpcEndpoint(Protocol):
    """The engine's listener, owner-only on this system."""

    async def listen(self, accept) -> asyncio.AbstractServer: ...

    def close(self) -> None:
        """Remove what ``listen`` created that is still ours."""


class IpcTransport(Protocol):
    """How the app and the engine reach each other on this system."""

    owner: object

    def load_token(self, token_file: Path | str) -> str: ...

    def endpoint(self, path: Path | str) -> IpcEndpoint: ...

    async def connect(
        self, path: Path | str,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]: ...

    def peer(self, writer: asyncio.StreamWriter) -> object:
        """The connected process's owner, from the OS, never from the client."""


class SecretBackend(Protocol):
    """The OS keyring holding the profile's secrets."""

    def get_password(self, service: str, name: str) -> str | None: ...

    def set_password(self, service: str, name: str, value: str) -> None: ...

    def delete_password(self, service: str, name: str) -> None: ...

    def unlock(self) -> bool: ...


class CoreLifetime(Protocol):
    """The core's single shutdown edge: OS signals and loss of the app."""

    stopping: asyncio.Event
    reason: str | None

    def watch_signals(self) -> None: ...

    def watch_parent(self, stdin_fd: int) -> None: ...

    def request_stop(self, reason: str) -> None: ...

    async def wait(self) -> None: ...

    def close(self) -> None: ...


class Platform(Protocol):
    name: str
    ipc: IpcTransport

    def secret_backend(self) -> SecretBackend: ...

    def core_lifetime(self) -> CoreLifetime: ...

    def profile_paths(
        self,
        profile_id: str = "default",
        *,
        environ: Mapping[str, str] | None = None,
        home: Path | str | None = None,
    ) -> ProfilePaths:
        """The profile's config, data and cache roots on this system."""
