"""The installer acceptance's installed-core report consumer, natively (Windows PowerShell 5.1).

The exact `Check` and `Import-CoreReport` functions are taken from the script by PowerShell's own
parser and run against reports a complete, failed, interrupted, empty or malformed run could leave.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
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


def complete_report(first=None, **changes) -> str:
    """A complete report; first replaces fields of the first row, changes the top-level ones."""
    checks = [{"check": name, "ok": True, "detail": ""} for name in CORE.REQUIRED]
    checks[0] = {**checks[0], **(first or {})}
    return json.dumps({"completed": True, "failed": 0, "checks": checks, **changes})


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
    # Syntactically valid, wrongly typed or inconsistent: never coerced green (round 6, R6-2).
    ("ok as a string", complete_report(first={"ok": "false"}), 0, None, False),
    ("ok as an object", complete_report(first={"ok": {}}), 0, None, False),
    ("a name that isn't a string", complete_report(first={"check": 5}), 0, None, False),
    ("completed as a string", complete_report(completed="true"), 0, None, False),
    ("a failure count with no false row", complete_report(failed=1), 0, None, False),
    ("a negative failure count", complete_report(failed=-1), 0, None, False),
    ("a genuine, counted failure", complete_report(first={"ok": False}, failed=1), 0, None, True),
])
def test_the_consumer_counts_only_a_complete_report(tmp_path, case, report, exit_code, required,
                                                    counts):
    seen = consume(tmp_path, report, exit_code, required)
    assert seen[COMPLETION] is counts, (case, seen)
    if case == "interrupted, partial":  # its checks are still kept, for diagnosis
        assert seen[f"core: {CORE.REQUIRED[0]}"] is True and seen[f"core: {CORE.ENDED}"] is False
    if case in ("ok as a string", "ok as an object", "a genuine, counted failure"):
        # The row itself is a failed check: the run fails even when execution was complete.
        assert seen[f"core: {CORE.REQUIRED[0]}"] is False


# The bounded waits, natively (round 9): Run keeps a direct child's exit code (Windows PowerShell
# 5.1 loses it unless the handle was taken), and a command that overruns its bound ends the run as
# a named failure. It is killed, the checks made so far stay in the progress file in order, and the
# final report still says what happened.
RUN_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:ODIN_SCRIPT, [ref]$tokens, [ref]$errors)
foreach ($name in 'Check', 'Run', 'Outcome', 'Finish') {
  $definition = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
      $node.Name -eq $name }, $true)
  . ([scriptblock]::Create($definition.Extent.Text))
}
$checks = New-Object System.Collections.Generic.List[object]
$FailAt = ''
$Mode = 'user'
$Report = $env:ODIN_REPORT
$Progress = "$Report.progress"
$shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$outcome = ''
try {
  Check 'an exit code survives' ((Run $shell @('-NoProfile', '-Command', 'exit 7') 2) -eq 7) ''
  Check 'a failed check is kept' $false 'kept'
  Run $shell @('-NoProfile', '-Command', $env:ODIN_SLEEPER) 0 | Out-Null
  Check 'never reached' $true ''
} catch {
  $outcome = Outcome $_
}
exit (Finish $outcome)
"""


def test_a_wait_that_overruns_ends_the_run_named_and_reported(tmp_path):
    report = tmp_path / "report.json"
    marker = f"odin-timeout-probe-{os.getpid()}"
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    shell = root / r"System32\WindowsPowerShell\v1.0\powershell.exe"
    result = subprocess.run(
        [str(shell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", RUN_HARNESS],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "ODIN_SCRIPT": str(SCRIPT), "ODIN_REPORT": str(report),
             "ODIN_SLEEPER": f"Start-Sleep -Seconds 90 # {marker}"})
    assert result.returncode == 1, result.stderr  # a failed check, not a crash
    checks = json.loads(report.read_text(encoding="utf-8-sig"))["checks"]
    assert [(c["check"], c["ok"]) for c in checks] == [
        ("an exit code survives", True), ("a failed check is kept", False),
        ("the run reached its end", False)]
    assert "didn't exit within 0 minutes" in checks[-1]["detail"], checks[-1]
    assert marker in checks[-1]["detail"]  # the command is named
    progress = (tmp_path / "report.json.progress").read_text(encoding="utf-8-sig").splitlines()
    assert progress == ["True an exit code survives", "False a failed check is kept"]
    # The overrunning command was ended, not left behind.
    query = ("@(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'powershell.exe' "
             f"-and $_.CommandLine -like '*{marker}*' "
             "-and $_.CommandLine -notlike '*Get-CimInstance*' }).Count")
    listing = subprocess.run(
        [str(shell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", query],
        capture_output=True, text=True, timeout=120)
    assert listing.stdout.strip() == "0", listing.stdout + listing.stderr


FACTS_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:ODIN_SCRIPT, [ref]$tokens, [ref]$errors)
foreach ($name in 'Run', 'InstallFacts') {
  $definition = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
      $node.Name -eq $name }, $true)
  . ([scriptblock]::Create($definition.Extent.Text))
}
$inst = $env:ODIN_INSTALL; $python = $env:ODIN_PYTHON
$ownership = $env:ODIN_OWNERSHIP; $marker = Join-Path $ownership 'transaction.json'
InstallFacts -Verdict
"""

# The installed guardian, stood in: its refusal goes to stderr with exit 3, as the real one's does,
# and its lease is held by another owner, so the lease probe ends in a traceback.
FAKE_GUARDIAN = '''import sys


def ownership_paths(kind):
    return kind


def _open(paths):
    return 3


def _lock(fd, *, exclusive):
    raise BlockingIOError(11, "the lock is held by another owner")


def _close(fd):
    pass


if __name__ == "__main__":
    print("Odin install ownership refusal: one-app.json: Core resource cleanup is unresolved",
          file=sys.stderr)
    sys.exit(3)
'''


def test_refused_install_facts_keep_stderr_as_text_under_stop(tmp_path):
    """A refused install's facts, from the exact InstallFacts under the script's 'Stop', in Windows
    PowerShell 5.1: the guardian's refusal (stderr, exit 3) and a held lease (a traceback) are
    recorded as text, never raised, so the check they describe is still written."""
    install = tmp_path / "Odin"
    (install / "resources").mkdir(parents=True)
    (install / "resources" / "ownership.py").write_text(FAKE_GUARDIAN, encoding="utf-8")
    ownership = tmp_path / "nsis"
    (ownership / "receipts").mkdir(parents=True)
    (ownership / "receipts" / "one-app.json").write_text(
        json.dumps({"role": "app", "state": "running", "boot_id": "b1"}), encoding="utf-8")
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    shell = root / r"System32\WindowsPowerShell\v1.0\powershell.exe"
    result = subprocess.run(
        [str(shell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", FACTS_HARNESS],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "ODIN_SCRIPT": str(SCRIPT), "ODIN_INSTALL": str(install),
             "ODIN_PYTHON": sys.executable, "ODIN_OWNERSHIP": str(ownership)})
    assert result.returncode == 0, result.stderr
    facts = result.stdout.strip().split("; ")
    assert facts[:3] == ["running: none", "marker: False",
                         "receipt one-app.json: app running boot b1"], facts
    assert facts[3] == ("receipts verdict: exit 3 Odin install ownership refusal: one-app.json: "
                        "Core resource cleanup is unresolved"), facts
    assert facts[4] == ("lease: exit 1 BlockingIOError: [Errno 11] "
                        "the lock is held by another owner"), facts
