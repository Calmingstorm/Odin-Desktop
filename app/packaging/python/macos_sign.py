"""Developer ID signing of the installed Mac app's Resources, before its manifest is written.

after-pack-macos.cjs runs this for a signed build only (phase 5). Every Mach-O under
Contents/Resources (found by content, deepest first: macos_macho.list_macho) is signed with the
hardened runtime and a secure timestamp, then verified. Entitlements go by role and nowhere else
(ROLES): the Python interpreter may load libraries another team signed (skill wheels, the first-use
PDF reader), and the browser and Playwright's driver run V8, whose JIT needs allow-jit under the
hardened runtime. electron-builder then signs the rest of the app and ignores Resources
(signIgnore), so the manifest written next records exactly these bytes.
"""
from __future__ import annotations

import plistlib
import re
import subprocess
from pathlib import Path

from macos_macho import list_macho

ENTITLEMENTS = Path(__file__).resolve().parents[1] / "macos"
PYTHON = ENTITLEMENTS / "entitlements.python.plist"
JIT = ENTITLEMENTS / "entitlements.jit.plist"
ROLES = {
    "runtime/python/bin/python3.12": PYTHON,
    "runtime/browser/chromium/chrome-headless-shell-mac-arm64/chrome-headless-shell": JIT,
    "runtime/python/lib/python3.12/site-packages/playwright/driver/node": JIT,
}


class SigningError(RuntimeError):
    pass


def plan(resources: Path) -> list[tuple[Path, Path | None]]:
    """Every Mach-O under resources in signing order, with its entitlements (None: none).

    A role whose file isn't there refuses: a renamed binary would otherwise lose its entitlement
    without notice."""
    files = list_macho(resources)
    named = {path.relative_to(resources).as_posix(): path for path in files}
    missing = sorted(set(ROLES) - set(named))
    if missing:
        raise SigningError(f"Signing roles name files the app lacks: {missing}")
    return [(path, ROLES.get(path.relative_to(resources).as_posix())) for path in files]


def sign(resources: Path, identity: str, keychain: Path | None = None, run=subprocess.run) -> int:
    """Sign every planned file, then verify each; returns how many were signed."""
    steps = plan(resources)
    base = ["/usr/bin/codesign", "--force", "--options", "runtime", "--timestamp",
            "--sign", identity, *(["--keychain", str(keychain)] if keychain else [])]
    for path, entitlements in steps:
        run([*base, *(["--entitlements", str(entitlements)] if entitlements else []), str(path)],
            check=True)
    for path, _ in steps:
        run(["/usr/bin/codesign", "--verify", "--strict", str(path)], check=True)
    return len(steps)


def _entitlements(plist: Path | None) -> dict:
    return plistlib.loads(plist.read_bytes()) if plist else {}


def verify_signed(resources: Path, team: str, run=subprocess.run) -> int:
    """Every Mach-O under resources, as the signed build must leave it: this team's Developer ID
    signature with the hardened runtime and a secure timestamp, and exactly its role's
    entitlements, values and types included (so never get-task-allow, and never an exception
    set to false). Raises SigningError naming the first that isn't. It audits Resources only:
    Electron's executable, helpers and frameworks are left to codesign's own verification."""
    steps = plan(resources)
    for path, entitlements in steps:
        shown = run(["/usr/bin/codesign", "-d", "--verbose=4", str(path)],
                    capture_output=True, text=True, check=True)
        facts = shown.stderr + shown.stdout
        flags = re.search(r"flags=0x([0-9a-f]+)", facts)
        if (f"TeamIdentifier={team}" not in facts or "Timestamp=" not in facts
                or not flags or not int(flags.group(1), 16) & 0x10000):
            raise SigningError(f"{path.relative_to(resources)}: not this team's hardened, "
                               "timestamped signature")
        held = run(["/usr/bin/codesign", "-d", "--entitlements", "-", "--xml", str(path)],
                   capture_output=True, check=True).stdout
        granted = plistlib.loads(held) if held.strip() else {}
        expected = _entitlements(entitlements)
        # bool is an int in Python: compare the types too, so 1 never passes for true.
        if (granted != expected
                or any(type(granted[key]) is not type(value) for key, value in expected.items())):
            raise SigningError(f"{path.relative_to(resources)}: entitlements {granted!r}")
    return len(steps)
