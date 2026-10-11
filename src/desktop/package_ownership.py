"""Bind an installed core to its shipped package lifetime, never ambient code."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .package_state import PackageStateError


def acquire_core_lease(paths, *, source_file=None):
    source = Path(source_file or __file__).resolve()
    resources = None
    for ancestor in source.parents:
        if ancestor.name == "runtime":
            resources = ancestor.parent
            break
    # Development is not an installed package. A bundled core may not opt out
    # with a deleted environment flag or missing shipped ownership module.
    if resources is None:
        return None
    module_path = resources / "ownership.py"
    try:
        kind = ("nsis" if sys.platform == "win32"  # the per-user Windows installation
                else "deb" if resources.parent == Path("/opt/odin-desktop") else "appimage")
        if module_path.is_symlink():
            raise ValueError("Invalid shipped package ownership")
        spec = importlib.util.spec_from_file_location("odin_package_ownership", module_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module.acquire_lifetime(
            module.ownership_paths(kind), "core",
            paths.config_dir.parent / f"{paths.profile_id}-cleanup-state.json",
            paths.data_dir / "resource-cleanup.json", provisional=True)
    except Exception:
        raise PackageStateError(
            "Installed core ownership is unavailable; startup refused") from None
