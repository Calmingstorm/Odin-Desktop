"""The Mac app's guardian lane: app/packaging/macos/guardian, compiled beside the interpreter.

The installed app runs the engine under it (app/src/main/platform/macos-launch.ts). It is built
here with the platform's own compiler from the reviewed source, once per stage; the source, build
script and binary hashes and the compiler are recorded.
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
from pathlib import Path

GUARDIAN = Path(__file__).resolve().parents[1] / "macos" / "guardian"


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage_guardian(bundle_root: Path, cache_dir: Path) -> dict:
    """Build ``bundle_root/odin-guardian`` (bundle_root is resources/runtime)."""
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("The guardian lane builds on Apple silicon only")
    target = Path(bundle_root) / "odin-guardian"
    if target.exists() or target.is_symlink():
        raise ValueError("The guardian is staged once; stage a new bundle root")
    subprocess.run([str(GUARDIAN / "build.sh"), str(target)], check=True)
    if not target.is_file() or target.stat().st_mode & 0o111 == 0:
        raise ValueError("The guardian build left no executable")
    compiler = subprocess.run(["xcrun", "clang", "--version"], capture_output=True, text=True,
                              check=True).stdout.splitlines()[0]
    return {"name": "odin-guardian", "source": "app/packaging/macos/guardian/odin-guardian.c",
            "source_sha256": _sha256(GUARDIAN / "odin-guardian.c"),
            "build_script_sha256": _sha256(GUARDIAN / "build.sh"),
            "executable": "odin-guardian", "executable_sha256": _sha256(target),
            "compiler": compiler, "license": "MIT"}
