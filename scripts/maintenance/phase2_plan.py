#!/usr/bin/env python3
"""Check planned engine ownership against the frozen maintenance inventory.

This consumes a machine-readable work plan, not human-written document wording.
It does not import the engine, qualify a feature, or approve a protocol method.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
PACKAGING_HANDOFFS = {
    "src/packaging/__init__.py", "src/packaging/validate.py", "src/web/api/self_update.py",
}
SURFACES = {
    "conversations", "search", "attachments", "artifacts", "tool_details",
    "reports", "running_work", "usage_status", "notifications", "settings",
    "skills", "mcp", "hosts_trust", "memory_lists", "knowledge", "audit_logs",
    "turn_state", "computer_use", "codex_accounts", "integrations",
}


def _path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError(f"Noncanonical plan path: {value!r}")
    return value


def validate(plan: dict, manifest: dict) -> dict:
    if plan["schema_version"] != 1 or plan["status"] != "planned-not-implemented":
        raise ValueError("Unsupported plan schema or implementation claim")
    if plan["baseline"] != manifest["baseline"]:
        raise ValueError("Plan baseline differs from the source inventory")
    steps = plan["steps"]
    if [row["id"] for row in steps] != list(range(1, 9)):
        raise ValueError("Plan must own steps 1 through 8 exactly once, in order")
    step_modules = {}
    all_modules = set()
    for row in steps:
        modules = row["new_modules"] + row["existing_modules"]
        if len(modules) != len(set(modules)):
            raise ValueError(f"Duplicate module within step {row['id']}")
        for module in modules:
            if not _path(module).startswith("src/") or not module.endswith(".py"):
                raise ValueError(f"Not an engine Python module: {module}")
        step_modules[row["id"]] = set(modules)
        all_modules.update(modules)

    entries = [row for row in manifest["entries"]
               if row["path"].startswith(("src/", "ui/js/pages/"))]
    paths = [row["path"] for row in entries]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate source inventory path")
    expected = {row["path"] for row in entries if row["reuse_verdict"] == "replace"}
    replacements = plan["replacements"]
    replacement_paths = [_path(row["source"]) for row in replacements]
    if len(replacement_paths) != len(set(replacement_paths)):
        raise ValueError("Duplicate replacement owner")
    if set(replacement_paths) != expected:
        raise ValueError("Replacement ownership does not match the source inventory")
    for row in replacements:
        if row["step"] not in step_modules:
            raise ValueError("Replacement has an unknown step")
        boundary = ("phase3-app" if row["source"].startswith("ui/js/pages/") else
                    "phase3-packaging" if row["source"] in PACKAGING_HANDOFFS else
                    "phase2-engine")
        if row["boundary"] != boundary:
            raise ValueError("Replacement boundary does not match its source responsibility")
        if not set(row["modules"]) <= step_modules[row["step"]]:
            raise ValueError("Replacement refers to modules not owned by its step")
        if not row["modules"] and row["source"] != "ui/js/pages/tabbed-page.js":
            raise ValueError("Engine replacement lacks a module owner")

    adapted = [row for row in entries if row["reuse_verdict"] == "keep with adaptation"]
    rules = plan["adaptation_owners"]
    matches = {row["pattern"]: 0 for row in rules}
    if len(matches) != len(rules):
        raise ValueError("Duplicate adaptation pattern")
    for rule in rules:
        _path(rule["pattern"])
        if not rule["steps"] or not set(rule["steps"]) <= step_modules.keys():
            raise ValueError("Adaptation has an unknown or empty step owner")
        if rule["boundary"] not in {
            "phase2-engine", "phase2-wiring-phase3-native", "phase3-app",
        }:
            raise ValueError("Unknown adaptation phase boundary")
    for row in adapted:
        owners = [rule for rule in rules if fnmatch.fnmatchcase(row["path"], rule["pattern"])]
        if len(owners) != 1:
            raise ValueError(f"Adaptation needs one primary family owner: {row['path']}")
        matches[owners[0]["pattern"]] += 1
    if any(count == 0 for count in matches.values()):
        raise ValueError("Stale adaptation family matches no inventory rows")

    surfaces = plan["v1_surfaces"]
    if set(surfaces) != SURFACES:
        raise ValueError("Missing or unexpected v1 service surface")
    for name, row in surfaces.items():
        if row["step"] not in step_modules or not row["modules"]:
            raise ValueError(f"Missing service owner: {name}")
        if not set(row["modules"]) <= step_modules[row["step"]]:
            raise ValueError(f"Service modules not owned by step: {name}")
    return {
        "status": plan["status"], "source_rows": len(entries),
        "replacement_rows": len(replacements), "adaptation_rows": len(adapted),
        "adaptation_families": matches, "v1_surfaces": len(surfaces),
        "planned_engine_modules": len(all_modules),
        "qualification": "Ownership coverage only; no runtime or protocol qualification",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        plan = json.loads((args.root / "maintenance/phase2-file-plan.json").read_text())
        manifest = json.loads((args.root / "maintenance/manifest.json").read_text())
        print(json.dumps(validate(plan, manifest), indent=2, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Phase 2 ownership check failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
