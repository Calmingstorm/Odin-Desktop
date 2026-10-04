"""Runtime-derived paths shared by prompt and filesystem safety wiring."""

from __future__ import annotations

import os
from pathlib import Path


def runtime_install_root() -> Path:
    """Return the lexical absolute root containing the running ``src`` package."""
    return Path(__file__).absolute().parent.parent


def runtime_profile_paths():
    """Resolve desktop profile paths without provisioning or importing state."""
    from .desktop.paths import ProfilePaths

    return ProfilePaths.from_xdg(os.environ.get("ODIN_DESKTOP_PROFILE", "default"))
