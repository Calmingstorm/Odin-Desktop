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


class Platform(Protocol):
    name: str
    ipc: IpcTransport

    def profile_paths(
        self,
        profile_id: str = "default",
        *,
        environ: Mapping[str, str] | None = None,
        home: Path | str | None = None,
    ) -> ProfilePaths:
        """The profile's config, data and cache roots on this system."""
