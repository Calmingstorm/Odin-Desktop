#!/usr/bin/env python3
"""Launch only the bundled engine in an isolated odq VM task profile."""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path


def prepare(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[4]
    if (
        not root.is_absolute()
        or root.parent != Path("/var/tmp")
        or not root.name.startswith("odq-orca-")
        or root.is_symlink()
    ):
        raise RuntimeError("Real core requires its private qualification artifact root")
    if os.geteuid() == 0:
        raise RuntimeError("Real core must run as the unprivileged guest task user")
    if subprocess.check_output(["systemd-detect-virt"], text=True).strip() not in ("kvm", "qemu"):
        raise RuntimeError("Real core wrapper requires a VM")
    hostname = subprocess.check_output(["hostname"], text=True).strip()
    if hostname not in ("odq-cinnamon", "odq-gnome", "odq-kde"):
        raise RuntimeError("Real core wrapper requires a named qualification guest")
    home = Path(os.environ.get("HOME", "/"))
    if home.is_symlink() or home.parent != root or not home.name.startswith("task-"):
        raise RuntimeError("Real core requires a fresh per-task HOME")
    for key, leaf in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
    ):
        if os.environ.get(key) != str(home / leaf):
            raise RuntimeError("Real core requires task-private XDG paths")
    engine = root / "engine"
    dependencies = engine / "site-packages"
    if not (engine / "src/__main__.py").is_file() or not dependencies.is_dir():
        raise RuntimeError("Bundled engine/source dependencies missing; no fixture fallback")
    stdlib = [
        path
        for path in sys.path
        if path
        and (path.startswith("/usr/lib/python") or path.startswith("/usr/lib64/python"))
        and "site-packages" not in path
        and "dist-packages" not in path
    ]
    sys.path[:] = [str(engine), str(dependencies), *stdlib]
    os.chdir(engine)
    os.environ.pop("PYTHONPATH", None)
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    return engine


def main():
    prepare()
    sys.dont_write_bytecode = True
    runpy.run_module("src", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
