#!/usr/bin/env python3
"""Record named merge provenance and reviewed lane8 paths, always pending.

This is not a generic current-byte drift recapture. The two source ledgers retain
their contracts and evidence, and new lane entries must come from the explicit
parent-owned plan. The normal inventory validator still checks every record.
"""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import inventory

MAIN = "288ce7b4"
SERVICES = "dda129d8"
MERGE_FILES = {
    "src/desktop/management.py", "scripts/maintenance/phase2_suites.py",
}


def ledger(revision):
    result = subprocess.check_output(
        ["git", "-C", str(inventory.ROOT), "show",
         f"{revision}:maintenance/desktop-deltas.json"], timeout=30,
    )
    return {row["path"]: row for row in json.loads(result)["entries"]}


def fields(row):
    return {key: row[key] for key in (
        "path", "reason", "contract", "invariant", "owner", "tests",
    )}


def merge_provenance():
    local, services = ledger(MAIN), ledger(SERVICES)
    planned = {}
    for path in sorted(local.keys() | services.keys()):
        ours, theirs = local.get(path), services.get(path)
        if ours == theirs:
            continue
        entry = fields(ours or theirs)
        if ours is not None and theirs is not None:
            for key in ("reason", "contract", "invariant"):
                if theirs[key] not in entry[key]:
                    entry[key] += " | 6A provenance: " + theirs[key]
            entry["tests"] = sorted(set(ours["tests"] + theirs["tests"]))
        entry["reason"] += (
            " | Parent revalidates the named main/6A merge and refreshed evidence bytes; "
            "all records remain pending independent review."
        )
        if path in MERGE_FILES:
            continue  # Explicit part4 plan owns these resolved/extended source paths.
        planned[path] = entry
    # Main-only records can name evidence tests that the 6A merge changed.
    # Preserve their original semantic contracts, never invent a new adaptation.
    for path, row in local.items():
        if path in planned or path in MERGE_FILES:
            continue
        if any(inventory.digest((inventory.ROOT / test).read_bytes()) != sha
               for test, sha in row.get("test_sha256", {}).items()):
            entry = fields(row)
            entry["reason"] += (
                " | Exact inherited main contract retained; named evidence test changed "
                "only by the services-part-a integration and is revalidated here."
            )
            planned[path] = entry
    return planned


def main():
    plan_path = inventory.ROOT / "maintenance/phase2-step8-part4-lane8-adaptation-plan.json"
    plan = json.loads(plan_path.read_bytes())
    if plan.get("reviewer") != "Claude, review of step 8 part 4":
        raise ValueError("Not the exact lane8 work-order plan")
    planned = merge_provenance()
    for row in plan["entries"]:
        if set(row) != {"path", "reason", "contract", "invariant", "owner", "tests"}:
            raise ValueError("Malformed explicit part4 adaptation entry")
        planned[row["path"]] = row
    for path, entry in sorted(planned.items()):
        if not (inventory.ROOT / path).is_file():
            raise ValueError(f"Named merge/part4 path missing: {path}")
        if path.startswith("maintenance/"):
            continue  # Audited generated accounting, not engine source adaptation scope.
        inventory.record(inventory.ROOT, SimpleNamespace(**entry))
    return inventory.main(["refresh"])


if __name__ == "__main__":
    raise SystemExit(main())
