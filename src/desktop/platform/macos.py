"""macOS: the Desktop engine's platform members.

The profile lives under the user's Library: config and data in Application Support's
odin-desktop/<profile>, the cache in Caches' odin-desktop/<profile> (the namespace pairs Linux and
Windows use, so the shared private-folder checks recognize them). The transport is an owner-only
Unix socket in the per-user temporary folder, which macOS creates private to the user and this
engine verifies. Secrets live in the login Keychain. The core's lifetime is Linux's own: asyncio
signal handlers and the parent pipe work the same on macOS.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from functools import cached_property
from pathlib import Path

_PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
SOCKET_PATH_LIMIT = 103  # sun_path is 104 bytes on macOS, including the terminating NUL


def macos_profile_paths(
    profile_id: str = "default",
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | str | None = None,
):
    """``~/Library/Application Support/odin-desktop/<profile>/{config,data}`` and
    ``~/Library/Caches/odin-desktop/<profile>``. Secrets metadata lives under data; values are in
    the Keychain.

    ``home`` stands in for ``~`` as on Linux; ``environ`` is accepted for the shared signature.
    """
    from ..paths import ProfilePaths

    if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("invalid profile identifier")
    home_path = Path(home) if home is not None else Path.home()
    if (
        not home_path.is_absolute()
        or ".." in home_path.parts
        or any(ord(c) < 32 for c in str(home_path))
    ):
        raise ValueError("home must be an absolute local path")
    support = home_path / "Library" / "Application Support" / "odin-desktop" / profile_id
    data = support / "data"
    return ProfilePaths(
        profile_id,
        support / "config",
        data,
        home_path / "Library" / "Caches" / "odin-desktop" / profile_id,
        data / "secrets",
    )


def macos_socket_path(profile_id: str = "default", root: Path | None = None) -> Path:
    """``<per-user temporary folder>/odin-desktop/<profile>/core.sock``, at most 103 bytes.

    The app derives the same path; a path over the limit is refused, never shortened silently.
    """
    from .darwin import user_temp_root

    if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("invalid profile identifier")
    path = (
        (root if root is not None else user_temp_root()) / "odin-desktop" / profile_id / "core.sock"
    )
    if len(os.fsencode(path)) > SOCKET_PATH_LIMIT:
        raise ValueError(f"the socket path is longer than macOS allows ({SOCKET_PATH_LIMIT} bytes)")
    return path


class MacOSPlatform:
    name = "macos"
    computer_supported = False

    @cached_property
    def ipc(self):
        """The app ↔ engine transport: an owner-only Unix socket, peer checked by the kernel."""
        from .macos_ipc import MacOSIpc

        return MacOSIpc()

    def secret_backend(self, paths=None):
        """The login Keychain; one store for every profile, keyed as on Linux."""
        from .macos_secrets import KeychainBackend

        return KeychainBackend()

    def core_lifetime(self):
        """Signals and the parent pipe, watched on the event loop, as on Linux."""
        from ..lifecycle import CoreLifetime

        return CoreLifetime()

    def profile_paths(
        self,
        profile_id: str = "default",
        *,
        environ: Mapping[str, str] | None = None,
        home: Path | str | None = None,
    ):
        return macos_profile_paths(profile_id, environ=environ, home=home)

    def resolve_workspace(self, *args, **kwargs):
        """Odin's pinned resolver; macOS path rules arrive with execution (phase 3)."""
        from ...tools.workspace import resolve_workspace

        return resolve_workspace(*args, **kwargs)
