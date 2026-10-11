"""The installer acceptance's installed-core report consumer, natively (Windows PowerShell 5.1).

The exact `Check` and `Import-CoreReport` functions are taken from the script by PowerShell's own
parser and run against reports a complete, failed, interrupted, empty or malformed run could leave.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/packaging/windows-installer-acceptance.ps1"
CORE_SCRIPT = ROOT / "scripts/packaging/windows-installed-core-acceptance.py"
SPEC = importlib.util.spec_from_file_location("windows_installed_core_acceptance", CORE_SCRIPT)
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)

HARNESS = r"""
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:ODIN_SCRIPT, [ref]$tokens, [ref]$errors)
foreach ($name in 'Check', 'Import-CoreReport') {
  $definition = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
      $node.Name -eq $name }, $true)
  . ([scriptblock]::Create($definition.Extent.Text))
}
$checks = New-Object System.Collections.Generic.List[object]
$FailAt = ''
$parsed = Get-Content -LiteralPath $env:ODIN_REQUIRED -Raw | ConvertFrom-Json
$required = @($parsed)
Import-CoreReport $env:ODIN_REPORT ([int]$env:ODIN_EXIT) $required $env:ODIN_ERRORS
# As Finish writes the report: Windows PowerShell 5.1's ConvertTo-Json -InputObject fails on an
# array of ordered dictionaries ("Argument types do not match").
[ordered]@{ checks = $checks } | ConvertTo-Json -Depth 4 -Compress
"""

COMPLETION = "the installed core's run completed with every required check"


def consume(tmp_path, report: str | None, exit_code: int = 0, required=None) -> dict[str, bool]:
    path = tmp_path / "core.json"
    if report is not None:
        path.write_text(report, encoding="utf-8")
    listed = tmp_path / "required.json"
    listed.write_text(json.dumps(list(CORE.REQUIRED) if required is None else required))
    errors = tmp_path / "core.log.err"
    errors.write_text("a traceback line\n")
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    shell = root / r"System32\WindowsPowerShell\v1.0\powershell.exe"
    result = subprocess.run(
        [str(shell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", HARNESS],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "ODIN_SCRIPT": str(SCRIPT), "ODIN_REPORT": str(path),
             "ODIN_EXIT": str(exit_code), "ODIN_REQUIRED": str(listed), "ODIN_ERRORS": str(errors)})
    assert result.returncode == 0, result.stderr
    return {item["check"]: item["ok"] for item in json.loads(result.stdout)["checks"]}


def complete_report(**changes) -> str:
    report = {"completed": True, "failed": 0,
              "checks": [{"check": name, "ok": True, "detail": ""} for name in CORE.REQUIRED]}
    return json.dumps({**report, **changes})


@pytest.mark.parametrize("case, report, exit_code, required, counts", [
    ("complete", complete_report(), 0, None, True),
    ("nonzero exit", complete_report(), 1, None, False),
    ("interrupted, partial", json.dumps({"completed": False, "failed": 1, "checks": [
        {"check": CORE.REQUIRED[0], "ok": True, "detail": ""},
        {"check": CORE.ENDED, "ok": False, "detail": "KeyboardInterrupt: "}]}), 1, None, False),
    ("partial but claims success", json.dumps({"completed": True, "failed": 0, "checks": [
        {"check": CORE.REQUIRED[0], "ok": True, "detail": ""}]}), 0, None, False),
    ("empty object", "{}", 1, None, False),
    ("no checks", json.dumps({"failed": 0, "checks": []}), 1, None, False),
    ("malformed", '{"failed": ', 1, None, False),
    ("missing", None, 1, None, False),
    ("no required list", complete_report(), 0, [], False),
])
def test_the_consumer_counts_only_a_complete_report(tmp_path, case, report, exit_code, required,
                                                    counts):
    seen = consume(tmp_path, report, exit_code, required)
    assert seen[COMPLETION] is counts, (case, seen)
    if case == "interrupted, partial":  # its checks are still kept, for diagnosis
        assert seen[f"core: {CORE.REQUIRED[0]}"] is True and seen[f"core: {CORE.ENDED}"] is False
