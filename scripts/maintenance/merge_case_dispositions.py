#!/usr/bin/env python3
"""Merge exact triage only when original digests and actual collected targets match."""
from __future__ import annotations

import argparse
import collections
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {"executable", "removed-surface-replacement", "phase2-admission-wiring",
           "native-prohibited-scope"}


def merge(accounting, collected, triages):
    result = copy.deepcopy(accounting)
    targets = {item["executable"] for item in collected}
    rows = [*result["historical_failures"],
            *(case for suite in result["foundation_suites"] for case in suite["cases"])]
    by_original = collections.defaultdict(list)
    for case in rows:
        by_original[case["original"]].append(case)
    seen = set()
    for source, triage in triages:
        for proposal in triage["cases"]:
            original = proposal["original"]
            if original in seen:
                raise ValueError(f"Duplicate triage decision: {original}")
            seen.add(original)
            matches = by_original.get(original)
            if not matches:
                raise ValueError(f"Unknown original case: {original}")
            disposition = proposal["disposition"]
            if disposition not in ALLOWED or not proposal.get("reason"):
                raise ValueError(f"Unsupported or unexplained disposition: {original}")
            executable = proposal.get("executable", [])
            replacements = proposal.get("replacement_cases", [])
            if disposition == "executable":
                if not executable:
                    raise ValueError("Executable case must name its original alias")
            elif not replacements:
                raise ValueError("Removed/deferred cases require executable boundary evidence")
            if not set(executable + replacements) <= targets:
                raise ValueError(f"Uncollected proposed evidence: {original}")
            for case in matches:
                if case["source_sha256"] != proposal["source_sha256"]:
                    raise ValueError(f"Original digest changed: {original}")
                case.update({"disposition": disposition, "executable": executable,
                             "replacement_cases": replacements,
                             "reason": proposal["reason"], "triage_source": source,
                             "collection_evidence": ".test-state/qualification-collected.json",
                             "blocks_phase1": disposition in {
                                 "phase2-admission-wiring", "native-prohibited-scope"}})
    result["collection_cases"] = collected
    result["historical_failure_blockers"] = [case["original"]
                                              for case in result["historical_failures"]
                                              if case["blocks_phase1"]]
    result["foundation_blockers"] = [case["original"] for suite in result["foundation_suites"]
                                      for case in suite["cases"] if case["blocks_phase1"]]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("triage", nargs="+")
    args = parser.parse_args(argv)
    execution = json.loads((ROOT / ".test-state/qualification-result.json").read_text())
    if execution["failed_groups"]:
        raise SystemExit("Refusing failed collection/execution metadata")
    collected = json.loads((ROOT / ".test-state/qualification-collected.json").read_text())["cases"]
    path = ROOT / "maintenance/case-accounting.json"
    triages = []
    for source in args.triage:
        relative = Path(source)
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "maintenance":
            raise SystemExit("Triage must be inside maintenance/")
        triages.append((source, json.loads((ROOT / relative).read_text())))
    data = merge(json.loads(path.read_text()), collected, triages)
    path.write_text(json.dumps(data, indent=2) + "\n")
    unresolved = [case["original"] for case in data["historical_failures"]
                  if case["disposition"] == "unmapped-neutral-blocker"]
    unresolved += [case["original"] for suite in data["foundation_suites"]
                   for case in suite["cases"] if case["disposition"] == "unmapped-neutral-blocker"]
    print(json.dumps({"unresolved_neutral_records": len(unresolved)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
