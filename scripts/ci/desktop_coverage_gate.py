#!/usr/bin/env python3
"""Line coverage for both runtimes: complete inventory, floors and no-drop ratchets."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "maintenance/desktop-coverage-baseline.json"


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


def evaluate(baseline, current):
    findings = []
    for runtime in ("python", "app"):
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
            if not path.startswith("src/" if runtime == "python" else "app/"):
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
    args = parser.parse_args(argv)
    try:
        args.output.mkdir(parents=True, exist_ok=True)
        python_report = combine(args.combine, args.output) if args.combine else args.python_json
        current = {
            "python": python_rows(json.loads(python_report.read_text())),
            "app": app_rows(json.loads(args.app_json.read_text())),
        }
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
                  {key: previous[key]["total"] for key in current} if previous else "none")
            args.baseline.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
        else:
            baseline = json.loads(args.baseline.read_text())
        findings = evaluate(baseline, current)
        for runtime, paths in executable_inventory().items():
            findings.extend(f"{path}: executable source absent from measurement"
                            for path in sorted(paths - set(current[runtime])))
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
