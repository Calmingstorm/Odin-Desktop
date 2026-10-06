"""Non-root container-only entry point for the fixed offline fixture corpus."""

import os
import sys
from pathlib import Path

TESTS = (
    "tests/test_lab_common.py",
    "tests/test_lab_cinnamon.py",
    "tests/test_lab_gnome.py",
    "tests/test_lab_guest_smoke.py",
    "tests/test_lab_hyprland.py",
    "tests/test_lab_kde.py",
)


def main():
    if os.getuid() != 1000 or os.getgid() != 1000 or os.getgroups():
        raise SystemExit("Fixture pytest requires UID/GID 1000 and no supplementary groups")
    if sys.argv[1:] not in ([], ["--collect-only"]):
        raise SystemExit("Only --collect-only is supported")
    if Path.cwd() != Path("/fixture") or os.environ.get("HOME") != "/home/testuser/private":
        raise SystemExit("Fixture working directory or private HOME missing")
    print("Offline lab fixtures: non-root UID 1000, private container; not VM qualification",
          flush=True)
    os.execv(sys.executable, [sys.executable, "-m", "pytest", "-c",
                             "/fixture/scripts/qualification/lab/ci/pytest.ini",
                             "--rootdir=/fixture", "--noconftest", *TESTS,
                             "--tb=short", *sys.argv[1:]])


if __name__ == "__main__":
    main()
