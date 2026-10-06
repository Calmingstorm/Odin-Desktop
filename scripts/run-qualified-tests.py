#!/usr/bin/env python3
"""Execute each reviewed Phase 1 group through the isolated namespace launcher."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None, *, deduplicate=True) -> int:
    plan = json.loads((ROOT / "maintenance/qualification-plan.json").read_text())
    groups = plan["groups"]
    if not groups:
        raise SystemExit("No classified qualification groups")
    failures = []
    collection = []
    arguments_input = [] if argv is None else argv
    collect_only = arguments_input == ["--collect-only"]
    if arguments_input and not collect_only:
        raise SystemExit("Only --collect-only is supported")
    (ROOT / ".test-state").mkdir(mode=0o700, exist_ok=True)
    state_directory = tempfile.TemporaryDirectory(
        prefix="qualification-once-", dir=ROOT / ".test-state")
    once_state = Path(state_directory.name) / "seen.json"
    once_state.write_text(json.dumps({"seen": [], "groups": []}) + "\n")
    for index, group in enumerate(groups):
        files = group["files"]
        if not files or not group.get("reason"):
            raise SystemExit("Group lacks files or reviewed selection rationale")
        for path in files:
            relative = Path(path)
            if (relative.is_absolute() or ".." in relative.parts
                    or not str(path).startswith("tests/")):
                raise SystemExit("Unsafe test selection path")
        arguments = [*files, "--tb=short"]
        excluded = group.get("exclude_expression")
        if excluded:
            arguments.extend(["-k", f"not ({excluded})"])
        xml = f".test-state/qualification-{index}.xml"
        arguments.append(f"--junitxml={xml}")
        if collect_only:
            arguments.extend(["--collect-only", "-p", "tests.test_desktop_qualification"])
        if deduplicate:
            arguments.extend(["-p", "scripts.qualification_once",
                              f"--qualification-once-state={once_state}"])
        print(f"Qualification group {index + 1}/{len(groups)}: {group['name']}", flush=True)
        result = subprocess.call(
            [sys.executable, str(ROOT / "scripts/run-phase1-tests.py"), *arguments],
            cwd=ROOT,
        )
        if result:
            failures.append({"name": group["name"], "exit_code": result})
        elif collect_only:
            captured = ROOT / ".test-state/qualification-collected.json"
            collection.extend(json.loads(captured.read_text())["cases"])
    if collect_only:
        # Replace once after all groups. A failed group must not forge a complete
        # corpus; callers inspect failed_groups before updating accounting.
        target = ROOT / ".test-state/qualification-collected.json"
        unique = {row["executable"]: row for row in collection}
        with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as file:
            json.dump({"schema_version": 1, "cases": list(unique.values())}, file, indent=2)
            file.write("\n")
        Path(file.name).replace(target)
    output = {"groups": len(groups), "failed_groups": failures}
    if deduplicate:
        (ROOT / ".test-state/qualification-once-result.json").write_text(once_state.read_text())
    state_directory.cleanup()
    (ROOT / ".test-state/qualification-result.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )
    print(json.dumps(output), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
