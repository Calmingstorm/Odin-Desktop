"""Preserve reviewed per-group selections and current Desktop boundaries."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path, PurePosixPath


def _safe_selection(root: Path, selection: object) -> str:
    if not isinstance(selection, str) or not selection.strip():
        raise ValueError("Empty or non-string test selection")
    # Parameterized node IDs may contain path-like text. Check only the file
    # portion, preserving every reviewed selector verbatim.
    filename = selection.split("::", 1)[0]
    path = PurePosixPath(filename)
    if (path.is_absolute() or len(path.parts) < 2
            or path.parts[0] != "tests" or ".." in path.parts
            or "\\" in filename or "\x00" in selection
            or str(path) != filename or path.suffix != ".py"):
        raise ValueError(f"Unsafe test selection path: {filename!r}")
    resolved = (root / filename).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError(f"Missing or unsafe test selection file: {filename!r}")
    return selection


def _groups(root: Path) -> list[dict]:
    plan = json.loads((root / "maintenance/qualification-plan.json").read_text())
    groups = plan.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("No reviewed groups: unclassified default selection")
    validated = []
    whole_files = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Invalid qualification group")
        name, reason, files = group.get("name"), group.get("reason"), group.get("files")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Group lacks a name")
        if name == "additional-desktop-boundaries":
            raise ValueError("Additional Desktop group name is reserved")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"Group {name!r} lacks reviewed selection rationale")
        if not isinstance(files, list) or not files:
            raise ValueError(f"Group {name!r} lacks files")
        selections = [_safe_selection(root, item) for item in files]
        excluded = group.get("exclude_expression")
        if excluded is not None and not isinstance(excluded, str):
            raise ValueError(f"Group {name!r} has an invalid exclusion")
        whole_files.update(item for item in selections if "::" not in item)
        validated.append({**group, "files": selections})
    extras = [
        _safe_selection(root, path.relative_to(root).as_posix())
        for path in sorted((root / "tests").glob("test_desktop_*.py"))
        if path.relative_to(root).as_posix() not in whole_files
    ]
    if extras:
        validated.append({
            "name": "additional-desktop-boundaries",
            "reason": "Desktop boundary suites not named as whole files in the reviewed plan",
            "files": extras,
        })
    return validated


def run_default(root: Path, arguments: list[str], *, execute=None,
                extras_only: bool = False) -> int:
    """Validate the entire plan first, then optionally run only Desktop extras."""
    try:
        groups = _groups(root)
    except (OSError, ValueError, TypeError, AttributeError) as error:
        raise SystemExit(f"Default selection refused: {error}") from error
    if extras_only:
        groups = [group for group in groups if group["name"] == "additional-desktop-boundaries"]
    failures = []
    for index, group in enumerate(groups, 1):
        command = [sys.executable, str(root / "scripts/run-phase1-tests.py"),
                   *group["files"], *arguments]
        if group.get("exclude_expression"):
            command.extend(["-k", f"not ({group['exclude_expression']})"])
        if extras_only:
            command.append("--junitxml=.test-state/additional-desktop-boundaries.xml")
        print(f"Default qualification group {index}/{len(groups)}: {group['name']}", flush=True)
        try:
            result = execute(command) if execute is not None else subprocess.call(command, cwd=root)
        except OSError as error:
            print(f"Group {group['name']!r} could not launch: {error}", file=sys.stderr, flush=True)
            result = 1
        if result:
            failures.append({"name": group["name"], "exit_code": result})
    print(json.dumps({"groups": len(groups), "failed_groups": failures}), flush=True)
    return 1 if failures else 0
