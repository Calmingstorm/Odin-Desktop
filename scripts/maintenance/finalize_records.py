#!/usr/bin/env python3
"""Apply explicit audited path plans as pending records, never generic recapture."""
from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plans", nargs="+", type=Path)
    args = parser.parse_args()
    root = inventory.ROOT
    seen = set()
    blobs = inventory.baseline_blobs(root)
    rows = inventory.reuse_rows(root, blobs)
    for path in args.plans:
        plan = inventory.load_json(path)
        for entry in plan["entries"]:
            if entry["path"] in seen:
                raise ValueError(f"Duplicate planned path: {entry['path']}")
            seen.add(entry["path"])
            if not (root / entry["path"]).exists():
                if entry["path"] in rows and rows[entry["path"]][0] == "strip":
                    continue  # named baseline strip decision, not a local delta
                overrides = inventory.load_json(root / "maintenance/selection-overrides.json")
                if any(e["path"] == entry["path"] for e in overrides["entries"]):
                    continue  # explicit separately validated replacement decision
                raise ValueError(f"Unmapped removal in plan: {entry['path']}")
            inventory.record(root, SimpleNamespace(**entry))
        if plan.get("selection_overrides"):
            overrides = inventory.load_json(root / "maintenance/selection-overrides.json")
            for entry in plan["selection_overrides"]:
                if "replacement_disposition" in entry:
                    entry["replacement"] = entry.pop("replacement_disposition")
            overrides["entries"] = sorted(
                plan["selection_overrides"], key=lambda entry: entry["path"]
            )
            inventory.write_json(root / "maintenance/selection-overrides.json", overrides)
    return inventory.main(["refresh"])


if __name__ == "__main__":
    raise SystemExit(main())
