#!/usr/bin/env python3
"""Map pending cases to actual isolated collection, never to invented pass evidence."""
from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def refresh(root=ROOT):
    result = json.loads((root / ".test-state/qualification-result.json").read_text())
    if result["failed_groups"]:
        raise ValueError("Failed collection cannot update the complete inventory")
    collected = json.loads((root / ".test-state/qualification-collected.json").read_text())["cases"]
    path = root / "maintenance/case-accounting.json"
    data = json.loads(path.read_text())
    exact = collections.defaultdict(set)
    definitions = collections.defaultdict(set)
    for item in collected:
        exact[item["original"]].add(item["executable"])
        definitions[item["original"].split("[", 1)[0]].add(item["executable"])
    rows = [*data["historical_failures"],
            *(case for suite in data["foundation_suites"] for case in suite["cases"])]
    for case in rows:
        found = (exact if "[" in case["original"] else definitions).get(case["original"])
        if found and case["disposition"] in {"executable", "unmapped-neutral-blocker"}:
            case.update({"disposition": "executable", "executable": sorted(found),
                         "replacement_cases": [], "blocks_phase1": False,
                         "collection_evidence": ".test-state/qualification-collected.json",
                         "reason": "Actual isolated collection matches original code filename, "
                                   "qualname and parameter identity. Execution and independent "
                                   "review remain separate acceptance gates."})
    data["collection_cases"] = collected
    data["historical_failure_blockers"] = [case["original"]
                                          for case in data["historical_failures"]
                                          if case["blocks_phase1"]]
    data["foundation_blockers"] = [case["original"]
                                    for suite in data["foundation_suites"]
                                    for case in suite["cases"] if case["blocks_phase1"]]
    # Preserve pending approval and every original case record. This is only
    # machine-verifiable collection accounting, not a semantic waiver.
    path.write_text(json.dumps(data, indent=2) + "\n")
    return data


if __name__ == "__main__":
    updated = refresh()
    print(json.dumps({"historical_unresolved": len(updated["historical_failure_blockers"]),
                      "foundation_unresolved": len(updated["foundation_blockers"])}))
