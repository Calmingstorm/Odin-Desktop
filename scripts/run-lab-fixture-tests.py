#!/usr/bin/env python3
"""Run the fixed offline lab corpus through the unchanged bounded PID launcher."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "tests/test_desktop_qualification_lab.py",
    "tests/test_lab_common.py",
    "tests/test_lab_cinnamon.py",
    "tests/test_lab_gnome.py",
    "tests/test_lab_guest_smoke.py",
    "tests/test_lab_hyprland.py",
    "tests/test_lab_kde.py",
    "tests/test_lab_fixture_userns.py",
)


def main(argv: list[str] | None = None) -> int:
    if os.getuid() == 0 or os.geteuid() == 0:
        raise SystemExit("Refusing root host launcher; invoke as a non-root user")
    arguments = sys.argv[1:] if argv is None else argv
    if arguments not in ([], ["--collect-only"]):
        raise SystemExit("Only --collect-only is supported; test selection is fixed")
    # Replace this process, not an extra child that could outlive cancellation.
    # The launcher's env -i sanitizes pytest; it owns the namespace group and
    # signal cleanup directly. Output and its exact exit status stay observable.
    os.execv(str(ROOT / ".venv/bin/python"),
        [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/run-phase1-tests.py"),
         *TESTS, "-rs", *arguments])
    raise RuntimeError("execv unexpectedly returned")


if __name__ == "__main__":
    raise SystemExit(main())
