#!/usr/bin/env python3
"""Run isolated source-build lifecycle E2E and retain reproducible evidence.

This driver never imports an engine. app/scripts/lifecycle-e2e.mjs owns the
fail-closed namespace/bus/graphics launcher; native D11/package rows stay open.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("cases", nargs="*", help="Playwright file/test filters")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output == repository or repository in output.parents:
        parser.error("Evidence output must be outside the source checkout")
    command = ["/usr/bin/node", str(repository / "app/scripts/lifecycle-e2e.mjs"), *args.cases]
    # The inner launcher independently discards all ambient state. Do the same
    # here so the driver cannot accidentally run tooling against a live profile.
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
        "HOME": str(Path.home()), "ODIN_APP_E2E_OUT": str(output),
    }
    python = os.environ.get("ODIN_DESKTOP_ENGINE_PYTHON")
    if python:
        environment["ODIN_DESKTOP_ENGINE_PYTHON"] = python
    started = time.time()
    with (output / "qualification.log").open("w") as log:
        child = subprocess.Popen(command, cwd=repository, env=environment,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, bufsize=1)
        assert child.stdout is not None
        for line in child.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        code = child.wait()
    artifacts = {}
    for relative in (
        "app/out/main/index.js", "app/out/preload/index.js", "app/package-lock.json", "uv.lock",
    ):
        path = repository / relative
        artifacts[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted((repository / "app/out/renderer").rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            artifacts[str(path.relative_to(repository))] = digest
    evidence = {
        "scope": "P3.3 part 1, source build, isolated Xvfb/private notification test bus",
        "source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True,
        ).strip(),
        "source_dirty": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=repository, text=True,
        ),
        "artifacts_sha256": artifacts, "command": command,
        "started_at_unix": started, "finished_at_unix": time.time(), "exit_code": code,
        "native_d11": "open: no native tray/login/compositor input/human visibility qualification",
        "package_paths": "open: no installed package exercised",
        "process_cleanup": (
            "Kernel PID-namespace teardown; see per-case exact process identities/receipts. "
            "Not native input release proof."
        ),
    }
    (output / "qualification.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
