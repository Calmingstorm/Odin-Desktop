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

    profile = os.environ.get("ODIN_DESKTOP_PROFILE", "default")
    data_dir = os.environ.get("ODIN_DESKTOP_DATA_DIR")
    token_file = os.environ.get("ODIN_DESKTOP_TOKEN_FILE")
    if bool(data_dir) != bool(token_file):
        raise ValueError("desktop app roots must be selected together")
    if data_dir and token_file:
        return ProfilePaths.from_app(
            profile, token_file=Path(token_file), data_dir=Path(data_dir)
        )
    return ProfilePaths.from_xdg(profile)
