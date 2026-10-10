"""Windows: the Desktop engine's platform members.

The profile lives under the user's local (not roaming) AppData. The transport is
an owner-only named pipe with a sealed session. Until the Windows core lifetime
arrives, that member refuses, so a Windows core never starts half-built.
"""
from __future__ import annotations

import ntpath
import os
import re
from collections.abc import Mapping
from functools import cached_property
from pathlib import Path

_PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def windows_profile_paths(profile_id: str = "default", *, environ: Mapping[str, str] | None = None,
                          home: Path | str | None = None):
    """``%LOCALAPPDATA%\\odin-desktop\\<profile>\\{config,data,cache}``; secrets under data.

    ``home`` stands in for the user profile folder when ``LOCALAPPDATA`` is unset,
    as ``home`` stands in for ``~`` on Linux.
    """
    from ..paths import ProfilePaths

    if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("invalid profile identifier")
    env = os.environ if environ is None else environ
    if env.get("LOCALAPPDATA"):
        base = str(env["LOCALAPPDATA"])
    else:
        user_home = str(home) if home is not None else str(Path.home())
        base = ntpath.join(user_home, "AppData", "Local")
    drive, rest = ntpath.splitdrive(base)
    if (len(drive) != 2 or drive[1] != ":" or not rest.startswith(("\\", "/"))
            or ".." in re.split(r"[\\/]", rest) or any(ord(c) < 32 for c in base)):
        raise ValueError("LOCALAPPDATA must be an absolute local path")
    root = Path(ntpath.join(base, "odin-desktop", profile_id))
    return ProfilePaths(profile_id, root / "config", root / "data", root / "cache",
                        root / "data" / "secrets")


class WindowsPlatform:
    name = "windows"
    computer_supported = False

    @cached_property
    def ipc(self):
        """The app ↔ engine transport: an owner-only named pipe with a sealed session."""
        from .windows_ipc import WindowsIpc

        return WindowsIpc()

    def secret_backend(self, paths=None):
        """The profile's DPAPI store; it needs the selected profile's folders."""
        if paths is None:
            raise ValueError("the Windows secret store is bound to a profile")
        from .windows_secrets import DpapiSecretBackend

        return DpapiSecretBackend(paths)

    def core_lifetime(self):
        """Signals through ``signal.signal``; the parent pipe read by a native thread."""
        from .windows_process import WindowsCoreLifetime

        return WindowsCoreLifetime()

    def profile_paths(self, profile_id: str = "default", *,
                      environ: Mapping[str, str] | None = None, home: Path | str | None = None):
        return windows_profile_paths(profile_id, environ=environ, home=home)

    def resolve_workspace(self, *args, **kwargs):
        from .windows_workspace import resolve_workspace

        return resolve_workspace(*args, **kwargs)
