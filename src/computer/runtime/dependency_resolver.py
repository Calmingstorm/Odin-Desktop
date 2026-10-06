"""Optional GI discovery confined to retained native worker entrypoints.

No interpreter search-path or environment mutation, site-package activation,
installation, bus activation or main-process GI import. This is dependency
placement, not native-backend qualification or human input authority.
"""
from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import stat
import sys
from pathlib import Path


def _worker_process() -> bool:
    main = getattr(sys.modules.get("__main__"), "__file__", None)
    if not isinstance(main, str):
        return False
    try:
        entry = Path(main).resolve(strict=True)
        root = Path(__file__).resolve(strict=True).parent
        return entry.parent == root and entry.name in {
            "worker.py", "x11_attached_worker.py", "x11_guardian.py",
        }
    except (OSError, RuntimeError):
        return False


def load_gi():
    """Load GI only in a worker, exposing no unrelated distro packages."""
    if not _worker_process():
        raise ImportError("gi_worker_only")
    try:
        return importlib.import_module("gi")
    except ModuleNotFoundError as exc:
        if exc.name != "gi":
            raise
    directory = Path("/usr/lib/python3/dist-packages")
    for path in (directory, *directory.parents):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ImportError("untrusted_distro_gi_path")
    spec = importlib.machinery.PathFinder.find_spec("gi", [str(directory)])
    if spec is None or spec.loader is None:
        raise ImportError("distro_gi_unavailable")
    before = {name: module for name, module in sys.modules.items()
              if name == "gi" or name.startswith("gi.")}
    module = importlib.util.module_from_spec(spec)
    sys.modules["gi"] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        for name in tuple(sys.modules):
            if name == "gi" or name.startswith("gi."):
                sys.modules.pop(name, None)
        sys.modules.update(before)
        raise
    return module
