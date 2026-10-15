"""Version management for Odin.

Prefers pyproject.toml from the source tree (the service imports src/
from the checkout, so that file describes the code actually running),
falling back to installed package metadata for site-packages installs.
Installed metadata can go stale after a self-update — a stale
odin_bot.egg-info / dist-info kept reporting the previous version, so
the updater re-offered the release it had already applied.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_FALLBACK_VERSION = "0.0.0-dev"


def _version_from_pyproject() -> str | None:
    """Version from the pyproject.toml next to the running source tree."""
    try:
        toml_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
        if toml_path.is_file():
            text = toml_path.read_text(encoding="utf-8")
            match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


_RELEASE_VERSION = re.compile(r"\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?")


def _version_from_bundle() -> str | None:
    """The release a packaged engine shipped in: the bundle manifest beside the runtime the
    app launched it from (ODIN_DESKTOP_BUNDLE_ROOT), as the app's own version is."""
    root = os.environ.get("ODIN_DESKTOP_BUNDLE_ROOT")
    if not root:
        return None
    try:
        manifest = json.loads((Path(root).parent / "bundle-manifest.json").read_text(
            encoding="utf-8"))
        value = manifest["product"]["version"]
    except Exception:
        return None
    return value if type(value) is str and _RELEASE_VERSION.fullmatch(value) else None


def _version_from_metadata() -> str | None:
    """Version from installed package metadata (pip / .deb installs)."""
    try:
        from importlib.metadata import version

        return version("odin-desktop-engine")
    except Exception:
        return None


def get_version() -> str:
    """Return the Odin version string.

    Resolution order:
    1. pyproject.toml in the project root — the code actually running
    2. the packaged release's bundle manifest — a Desktop install
    3. importlib.metadata — installed without a source checkout
    4. Fallback to "0.0.0-dev"
    """
    return (_version_from_pyproject() or _version_from_bundle() or _version_from_metadata()
            or _FALLBACK_VERSION)
