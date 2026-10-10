"""The Desktop engine's operating-system seams.

Each OS-specific piece is chosen here once per process. Linux returns the
existing implementations unchanged; any other system is refused exactly as the
Linux-only profile code refused it before this seam existed.
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
    raise NotImplementedError("desktop provisioning is Linux-only")
