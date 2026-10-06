#!/usr/bin/env python3
"""Reject new lint findings without modernizing protected upstream algorithms."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INHERITED = {
    ("src/async_utils.py", "UP047", "to_thread_settled"),
    ("src/computer/runtime/x11_guardian.py", "UP040", "InputStep"),
    ("src/llm/recovery.py", "UP047", "_attempt_cancellable"),
    ("src/llm/recovery.py", "UP047", "generate_with_recovery"),
    ("src/llm/recovery.py", "UP047", "_generate_with_recovery"),
    ("src/relevance.py", "UP047", "rank"),
    ("src/tools/browser.py", "UP047", "_await_bounded"),
}


def classify(findings, root=ROOT):
    new = []
    allowed = []
    for finding in findings:
        path = Path(finding["filename"]).relative_to(root).as_posix()
        match = any(
            path == file and finding["code"] == code and f"`{symbol}`" in finding["message"]
            for file, code, symbol in INHERITED
        )
        (allowed if match else new).append(finding)
    return allowed, new


def main() -> int:
    files = ["src", "scripts/maintenance", "scripts/release", "scripts/run-phase1-tests.py",
             "scripts/run-qualified-tests.py", "tests/desktop_adapters"]
    files.extend(
        str(path.relative_to(ROOT)) for path in sorted((ROOT / "tests").glob("test_desktop*.py"))
    )
    result = subprocess.run(
        [str(ROOT / ".venv/bin/ruff"), "check", *files, "--output-format", "json"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode not in (0, 1):
        print(result.stderr, file=sys.stderr)
        return result.returncode
    allowed, new = classify(json.loads(result.stdout))
    print(json.dumps({"inherited_findings": len(allowed), "new_findings": new}, indent=2))
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
