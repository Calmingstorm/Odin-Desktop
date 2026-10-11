"""The Desktop engine's operating-system seams.

Each OS-specific piece is chosen here once per process. Linux returns the
existing implementations unchanged. Windows has its own members (its transport
and core lifetime arrive with phase 2b). Any other system is refused exactly as
the Linux-only profile code refused it before this seam existed.
"""
from __future__ import annotations

import sys
from functools import cache

from .contracts import Platform

__all__ = ["Platform", "current_platform"]


@cache
def current_platform() -> Platform:
    if sys.platform.startswith("linux"):
        from .linux import LinuxPlatform

        return LinuxPlatform()
    if sys.platform == "win32":
        from .windows import WindowsPlatform

        return WindowsPlatform()
    raise NotImplementedError("desktop provisioning is Linux-only")
