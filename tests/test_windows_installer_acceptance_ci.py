"""The hosted Windows installer acceptance (phase 4c).

The installer is built by the selected Windows entry, then checked elevated and as a disposable
standard user, and its report is kept even when a check fails.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_the_installer_job_builds_with_the_windows_entry_then_runs_the_acceptance():
    workflow = yaml.safe_load((ROOT / ".github/workflows/windows-engine.yml").read_text())
    steps = workflow["jobs"]["windows-installer"]["steps"]
    runs = [step.get("run", "") for step in steps]
    build = next(i for i, run in enumerate(runs) if "node packaging/build-windows.mjs" in run)
    accept = next(i for i, run in enumerate(runs)
                  if "windows-installer-acceptance.ps1" in run and "-FailAt" not in run)
    failing = next(i for i, run in enumerate(runs) if "-FailAt" in run)
    assert build < failing < accept  # the report path is proved before the real run
    assert "the run reached its end" in runs[failing]
    # GitHub's PowerShell wrapper exits with the last exit code, the intentional failure's 1.
    assert runs[failing].rstrip().splitlines()[-1].strip().startswith("exit 0")
    acceptance = steps[accept]
    # Windows PowerShell: the local-accounts cmdlets, and the user's cases run under it too.
    assert acceptance["shell"] == "powershell"
    assert "-Report" in acceptance["run"]
    assert acceptance["run"].rstrip().endswith("exit $LASTEXITCODE")
    upload = next(step for step in steps
                  if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["if"] == "always()"
    paths = upload["with"]["path"].split()
    assert any(path.endswith("windows-installer-acceptance.json") for path in paths)
    assert any(path.endswith("windows-installer-acceptance-failing.json") for path in paths)
