#!/usr/bin/env python3
"""Line coverage for both runtimes: complete inventory, floors and no-drop ratchets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "maintenance/desktop-coverage-baseline.json"
WINDOWS_INVENTORY = "maintenance/windows-only-files.json"
# Windows-only engine files are named so; the explicit inventory must match exactly.
WINDOWS_NAME = re.compile(r"src/desktop/platform/(win32|windows(_[a-z]+)*)\.py")


def row(total, covered):
    if (type(total) is not int or type(covered) is not int
            or not 0 <= covered <= total):
        raise ValueError("Invalid line counts")
    return {"total": total, "covered": covered, "missing": total - covered}


def ratio(value):
    return Fraction(value["covered"], value["total"]) if value["total"] else Fraction(1)


def python_rows(report):
    return {path: row(data["summary"]["num_statements"], data["summary"]["covered_lines"])
            for path, data in report["files"].items() if path.startswith("src/")}


def app_rows(report, root=ROOT):
    result = {}
    for path, data in report.items():
        absolute = Path(path)
        if absolute.is_absolute():
            # Artifacts can come from a different runner checkout prefix.
            if absolute.is_relative_to(root):
                relative = absolute.relative_to(root).as_posix()
            elif "/app/src/" in path:
                relative = "app/src/" + path.rsplit("/app/src/", 1)[1]
            else:
                raise ValueError(f"Unexpected app coverage path: {path}")
        else:
            relative = path
        if (not relative.startswith("app/src/") or ".." in Path(relative).parts
                or "\\" in relative):
            raise ValueError(f"Unexpected app coverage path: {path}")
        # Istanbul statements may share a source line. A line is covered if any
        # statement on it executes, matching Istanbul's getLineCoverage().
        lines = {}
        for identifier, statement in data["statementMap"].items():
            line = statement["start"]["line"]
            lines[line] = max(lines.get(line, 0), data["s"][identifier])
        result[relative] = row(len(lines), sum(count > 0 for count in lines.values()))
    return result


def total(rows):
    return row(sum(value["total"] for value in rows.values()),
               sum(value["covered"] for value in rows.values()))


def executable_inventory(root=ROOT):
    """No executable source may disappear behind a report include pattern."""
    return {
        "python": {path.relative_to(root).as_posix() for path in (root / "src").rglob("*.py")},
        "app": {path.relative_to(root).as_posix() for path in (root / "app/src").rglob("*")
                if path.suffix in {".ts", ".vue"} and not path.name.endswith(".d.ts")},
    }


def windows_inventory(root=ROOT) -> set[str]:
    """The explicit Windows-only files; the naming invariant keeps the list complete."""
    listed = json.loads((root / WINDOWS_INVENTORY).read_text())
    if (not isinstance(listed, list) or any(type(path) is not str for path in listed)
            or len(set(listed)) != len(listed)):
        raise ValueError("Windows-only inventory must be a list of unique paths")
    named = {path.relative_to(root).as_posix()
             for path in (root / "src/desktop/platform").glob("*.py")
             if WINDOWS_NAME.fullmatch(path.relative_to(root).as_posix())}
    if set(listed) != named:
        difference = sorted(set(listed) ^ named)
        raise ValueError(f"Windows-only inventory differs from its files: {difference}")
    return set(listed)


def source_digest(path: Path) -> str:
    """Line-ending neutral: the Windows checkout may write CRLF."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def windows_path(key: str) -> str:
    """A Windows report key as a repository-relative POSIX path."""
    text = key.replace("\\", "/")
    if re.match(r"[A-Za-z]:/", text) or text.startswith("/"):
        index = text.find("/src/")
        if index < 0:
            raise ValueError(f"Unexpected Windows coverage path: {key}")
        text = text[index + 1:]
    if not text.startswith("src/") or ".." in text.split("/"):
        raise ValueError(f"Unexpected Windows coverage path: {key}")
    return text


def windows_rows(report, provenance, inventory, *, sha, root=ROOT):
    """Native rows for the Windows-only files, from this exact revision's sources."""
    if provenance.get("sha") != sha:
        raise ValueError("Windows coverage was measured at another revision")
    sources = provenance.get("sources")
    if not isinstance(sources, dict) or set(sources) != inventory:
        raise ValueError("Windows coverage provenance does not name the inventory exactly")
    for path in sorted(inventory):
        if sources[path] != source_digest(root / path):
            raise ValueError(f"{path}: Windows coverage measured other source bytes")
    rows = {}
    for key, data in report["files"].items():
        path = windows_path(key)
        if path in inventory:
            rows[path] = row(data["summary"]["num_statements"], data["summary"]["covered_lines"])
    if set(rows) != inventory:
        raise ValueError(f"Windows coverage lacks rows: {sorted(inventory - set(rows))}")
    return rows


def evaluate(baseline, current):
    findings = []
    windows = set(baseline.get("windows", {}).get("files", {})) | set(current.get("windows", {}))
    for runtime in ("python", "app", "windows"):
        if runtime not in baseline and runtime not in current:
            continue
        actual = current[runtime]
        expected = baseline[runtime]
        aggregate = total(actual)
        if ratio(aggregate) < ratio(expected["total"]):
            findings.append(f"{runtime}: total line coverage dropped")
        if aggregate["missing"] > expected["total"]["missing"]:
            findings.append(f"{runtime}: total missed lines grew")
        for path, previous in expected["files"].items():
            value = actual.get(path)
            if value is None:
                findings.append(f"{path}: missing from report")
                continue
            if ratio(value) < ratio(previous) or value["missing"] > previous["missing"]:
                findings.append(f"{path}: coverage regressed")
        for path in baseline["target_files"]:
            owner = ("windows" if path in windows else "python" if path.startswith("src/")
                     else "app")
            if owner != runtime:
                continue
            value = actual.get(path)
            if value is None:
                findings.append(f"{path}: targeted executable file missing")
            elif ratio(value) < Fraction(4, 5) and path not in baseline["exceptions"]:
                findings.append(f"{path}: below 80% without explained exception")
        for path in set(actual) - set(expected["files"]):
            if ratio(actual[path]) < Fraction(4, 5):
                findings.append(f"{path}: new executable file below 80%")
    for path, exception in baseline["exceptions"].items():
        lines = exception.get("lines", [])
        if (path not in baseline["target_files"] or not exception.get("reason")
                or exception.get("category") not in {"native_display", "real_hardware"}
                or not isinstance(lines, list) or not lines
                or any(type(line) is not int or line <= 0 for line in lines)
                or len(lines) != len(set(lines))):
            findings.append(f"{path}: exception needs exact lines and reason")
    return findings


def combine(directory, output):
    from coverage import Coverage

    names = {"coverage-full-suites", *(f"coverage-qualification-{index}" for index in range(1, 6))}
    inputs = []
    for name in sorted(names):
        files = list((directory / name).rglob(".coverage"))
        if len(files) != 1:
            raise ValueError(f"Expected one engine coverage file in {name}, got {len(files)}")
        inputs.extend(files)
    cov = Coverage(data_file=str(output / ".coverage"), config_file=str(ROOT / ".coveragerc"))
    cov.combine(data_paths=[str(path) for path in inputs], strict=True, keep=True)
    cov.save()
    cov.json_report(outfile=str(output / "python.json"))
    cov.html_report(directory=str(output / "python-html"))
    cov.xml_report(outfile=str(output / "python.xml"))
    return output / "python.json"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-json", type=Path)
    parser.add_argument("--app-json", type=Path, required=True)
    parser.add_argument("--combine", type=Path)
    parser.add_argument("--output", type=Path, default=Path("coverage"))
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--update-baseline", action="store_true",
                        help="Explicit reviewed baseline creation/update, never used by CI")
    parser.add_argument("--windows-json", type=Path,
                        help="The Windows job's coverage report for the Windows-only files")
    parser.add_argument("--windows-provenance", type=Path,
                        help="The Windows job's revision and source digests")
    parser.add_argument("--revision", default=os.environ.get("GITHUB_SHA"),
                        help="The commit both measurements must come from")
    args = parser.parse_args(argv)
    try:
        args.output.mkdir(parents=True, exist_ok=True)
        python_report = combine(args.combine, args.output) if args.combine else args.python_json
        inventory = windows_inventory()
        linux = python_rows(json.loads(python_report.read_text()))
        current = {
            # Linux rows come from Linux data only; Windows hits can't hide a Linux miss.
            "python": {path: value for path, value in linux.items() if path not in inventory},
            "app": app_rows(json.loads(args.app_json.read_text())),
        }
        if inventory:
            if not args.windows_json or not args.windows_provenance or not args.revision:
                raise ValueError("Windows coverage evidence or its revision is missing")
            current["windows"] = windows_rows(
                json.loads(args.windows_json.read_text()),
                json.loads(args.windows_provenance.read_text()), inventory, sha=args.revision)
        if args.update_baseline:
            changed = subprocess.check_output([
                "git", "log", "--since=2026-10-04T00:00:00-04:00", "--format=", "--name-only",
                "--", "src/desktop", "app/src"], cwd=ROOT, text=True).splitlines()
            inventory = executable_inventory()
            baseline = {runtime: {"total": total(rows), "files": dict(rows)}
                        for runtime, rows in current.items()}
            baseline.update(schema_version=1, target_files=sorted(
                set(changed) & (inventory["python"] | inventory["app"])), exceptions={})
            previous = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
            # Updating is explicit, not permission to erase stronger evidence.
            # Preserve each existing ceiling; regressions remain findings until
            # the code/tests improve or a separate reviewed policy change occurs.
            if previous:
                for runtime in current:
                    if runtime not in previous:
                        continue
                    for path, old in previous[runtime]["files"].items():
                        value = baseline[runtime]["files"].get(path)
                        if (value is None or ratio(value) < ratio(old)
                                or value["missing"] > old["missing"]):
                            baseline[runtime]["files"][path] = old
                    value = baseline[runtime]["total"]
                    old = previous[runtime]["total"]
                    if ratio(value) < ratio(old) or value["missing"] > old["missing"]:
                        baseline[runtime]["total"] = old
            print("Explicit baseline update; prior totals:",
                  {key: previous[key]["total"] for key in current if key in previous}
                  if previous else "none")
            args.baseline.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
        else:
            baseline = json.loads(args.baseline.read_text())
        findings = evaluate(baseline, current)
        measured = {**current, "python": {**current["python"], **current.get("windows", {})}}
        for runtime, paths in executable_inventory().items():
            findings.extend(f"{path}: executable source absent from measurement"
                            for path in sorted(paths - set(measured[runtime])))
        # A checked-in list cannot omit an executable file changed since the
        # release-scope date. Git history is the authority, not that JSON list.
        changed = subprocess.check_output([
            "git", "log", "--since=2026-10-04T00:00:00-04:00", "--format=", "--name-only",
            "--", "src/desktop", "app/src"], cwd=ROOT, text=True).splitlines()
        inventory = executable_inventory()
        targets = set(baseline["target_files"])
        for path in sorted(set(changed) & (inventory["python"] | inventory["app"])):
            if path not in targets:
                findings.append(f"{path}: changed executable source absent from target inventory")
        summary = {runtime: {"total": total(rows), "files": rows}
                   for runtime, rows in current.items()}
        summary["findings"] = findings
        (args.output / "line-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
        return bool(findings)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"Coverage fails closed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
