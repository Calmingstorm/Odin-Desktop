#!/usr/bin/env python3
"""Collect both CI schedules through real isolated launchers on the same corpus.

This is opt-in proof, not another CI test execution. Raw per-group receipts and
the summary stay under .test-state; archive them outside Git for large corpora.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    state = ROOT / ".test-state"
    state.mkdir(exist_ok=True)
    receipt = state / "ci-collected-nodeids.json"
    schedules = {}
    for schedule, extras_only in (("before", False), ("after", True)):
        lanes = {}
        for lane in ("pass-now", "qualified", "checker", "fixtures", "lab"):
            groups = []

            def collect(command, **kwargs):
                receipt.unlink(missing_ok=True)
                result = subprocess.call([*command, "-p", "scripts.ci_collection_receipt"],
                                         cwd=ROOT)
                if result:
                    return result
                nodes = json.loads(receipt.read_text())
                groups.append(nodes)
                (state / f"ci-{schedule}-{lane}-{len(groups)}.json").write_text(
                    json.dumps({"command": command, "nodeids": nodes}, indent=2) + "\n")
                return 0

            if lane == "pass-now":
                selection = load("ci_default_selection", "phase1-default-selection.py")
                result = selection.run_default(ROOT, ["--collect-only"], execute=collect,
                                               extras_only=extras_only)
            elif lane == "qualified":
                qualified = load("ci_qualified_selection", "run-qualified-tests.py")
                qualified.subprocess = SimpleNamespace(call=collect)
                result = qualified.main(["--collect-only"], deduplicate=extras_only)
            elif lane == "checker":
                result = 0 if extras_only else collect([
                    sys.executable, str(ROOT / "scripts/run-phase1-tests.py"),
                    "tests/test_desktop_phase2_plan.py", "--collect-only"])
            elif lane == "fixtures":
                fixtures = load("ci_fixture_selection", "run-lab-fixture-tests.py")
                files = list(fixtures.TESTS)
                if not extras_only:
                    files.insert(0, "tests/test_desktop_qualification_lab.py")
                # The fixed fixture wrapper uses this same verified PID boundary.
                result = collect([sys.executable, str(ROOT / "scripts/run-phase1-tests.py"),
                                  *files, "--collect-only"])
            else:
                files = ["tests/test_lab_orca.py", "tests/test_lab_orca_guest.py",
                         "tests/test_lab_orca_cleanup.py", "tests/test_orca_guest_tasks.py",
                         "tests/test_native_dialog_events.py", "tests/test_lab_focused_probe.py",
                         "tests/test_orca_native_input.py", "tests/test_kde_portal_preparation.py",
                         "tests/test_lab_orca_ci.py"]
                if not extras_only:
                    files.append("tests/test_desktop_lab_fixture_runner.py")
                result = collect([sys.executable, str(ROOT / "scripts/run-phase1-tests.py"),
                                  *files, "--collect-only"])
            if result:
                raise SystemExit(f"{schedule}/{lane}: real collection failed")
            lanes[lane] = [node for group in groups for node in group]
        schedules[schedule] = lanes
    totals = {name: Counter(node for lane in lanes.values() for node in lane)
              for name, lanes in schedules.items()}
    before, after = totals["before"], totals["after"]
    requested = {name: Counter(node for lane in ("pass-now", "qualified")
                              for node in lanes[lane]) for name, lanes in schedules.items()}
    summary = {
        "scope": "full-suites Python schedule, same candidate test corpus",
        "requested_union": {
            "counts": {name: {"collected_occurrences": sum(total.values()), "unique": len(total)}
                       for name, total in requested.items()},
            "removed": sorted(requested["before"].keys() - requested["after"].keys()),
            "added": sorted(requested["after"].keys() - requested["before"].keys()),
        },
        "counts": {name: {"collected_occurrences": sum(total.values()), "unique": len(total),
                          "duplicate_occurrences": sum(total.values()) - len(total),
                          "steps": {lane: len(nodes) for lane, nodes in schedules[name].items()}}
                   for name, total in totals.items()},
        "removed": sorted(before.keys() - after.keys()),
        "added": sorted(after.keys() - before.keys()),
        "after_duplicates": {node: count for node, count in after.items() if count != 1},
    }
    (state / "ci-differential.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    return int(bool(summary["removed"] or summary["added"] or summary["after_duplicates"]
                    or summary["requested_union"]["removed"]
                    or summary["requested_union"]["added"]))


if __name__ == "__main__":
    raise SystemExit(main())
