#!/usr/bin/env python3
"""Run an explicitly classified test selection behind the required PID boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Use the repository Python 3.12 environment")
    state = ROOT / ".test-state"
    state.mkdir(mode=0o700, exist_ok=True)
    for name in ("home", "config", "data", "cache", "runtime"):
        (state / name).mkdir(mode=0o700, exist_ok=True)
    arguments = sys.argv[1:]
    if not any(not argument.startswith("-") for argument in arguments):
        plan = json.loads((ROOT / "maintenance/test-plan.json").read_text())
        selected = plan["safe_pass_now"]
        if not selected:
            raise SystemExit("Refusing an unclassified full-suite invocation")
        arguments.extend(selected)
        arguments.extend(
            str(path.relative_to(ROOT))
            for path in sorted((ROOT / "tests").glob("test_desktop_*.py"))
        )
    if not any(not argument.startswith("-") for argument in arguments):
        raise SystemExit("Refusing an unclassified full-suite invocation")
    environment = {
        "PATH": f"{ROOT / '.venv/bin'}:/usr/bin:/bin",
        "HOME": str(state / "home"),
        "XDG_CONFIG_HOME": str(state / "config"),
        "XDG_DATA_HOME": str(state / "data"),
        "XDG_CACHE_HOME": str(state / "cache"),
        "LANG": "C.UTF-8",
        "PYTHONPATH": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    # env -i excludes credentials, display/socket paths and live config overrides.
    command = [
        "sudo", "-n", "unshare", "--mount", "--pid", "--fork", "--mount-proc",
        "--kill-child", "sudo", "-n", "-u", os.environ.get("USER", "root"),
        "env", "-i", *(f"{key}={value}" for key, value in environment.items()),
        str(ROOT / ".venv/bin/python"), "-c",
        "import subprocess,sys; raise SystemExit(subprocess.call(sys.argv[1:]))",
        str(ROOT / ".venv/bin/pytest"), "-p", "pytest_asyncio.plugin",
        "-p", "pytest_cov.plugin", "-p", "pytest_timeout", "--timeout=90",
        "--timeout-method=signal", "-q", *arguments,
    ]
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
