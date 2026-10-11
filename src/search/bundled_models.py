"""Resolve packaged embedding assets without environment or ambient-cache grants."""
from __future__ import annotations

import sys
from pathlib import Path


def bundled_model_roots() -> tuple[Path, ...]:
    """Only a noneditable engine inside the packaged Python gets default roots.

    P4.1 layout is resources/runtime/python plus resources/runtime/models. This
    deliberately ignores HOME, cwd, PATH, model caches and environment overrides.
    Explicit model_roots remain available to admitted callers and isolated tests.
    """
    prefix = Path(sys.prefix).resolve()
    if prefix.name != "python" or prefix.parent.name != "runtime":
        return ()
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    # Windows' standalone CPython keeps its packages in Lib\site-packages, with no version folder.
    installed = (prefix / "Lib" / "site-packages" if sys.platform == "win32"
                 else prefix / "lib" / version / "site-packages")
    try:
        Path(__file__).resolve().relative_to(installed)
    except ValueError:
        return ()
    return (prefix.parent / "models" / "bge-small-en-v1.5",)
