#!/usr/bin/env python3
"""Integrate only explicitly audited lane8 candidates into derived accounting.

The source assignment is immutable, other lane rows are untouched, inherited
bytes are independently hash-checked, and no runtime test/source is rewritten.
Qualification and independent review remain separate from this generator.
"""
from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEWER = "Claude, review of step 8 part 4"
ASSIGNMENT_SHA256 = "20f094868694949d7e3fc89d74f9277e4d1a293e0c7578311f7b1c6bb0b5d12c"
INPUTS = {
    "tools": "maintenance/step8-part4-tools-candidates.json",
    "computer": "maintenance/step8-part4-computer-candidates.json",
    "hyprland": "maintenance/step8-part4-hyprland-candidates.json",
    "campaigns": "maintenance/step8-part4-campaigns-candidates.json",
}


def read(path):
    return json.loads((ROOT / path).read_bytes())


def write(path, data):
    target = ROOT / path
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def case_names(path):
    result = set()
    for node in ast.parse((ROOT / path).read_bytes()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                result.add(node.name)
        elif isinstance(node, ast.ClassDef):
            result.update(f"{node.name}.{child.name}" for child in node.body
                          if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and child.name.startswith("test_"))
    return result


def main():
    assignment = Path("/home/odin/reviews/step6-assignment.json").read_bytes()
    if hashlib.sha256(assignment).hexdigest() != ASSIGNMENT_SHA256:
        raise ValueError("Immutable task assignment changed")
    assigned = set(json.loads(assignment)["lane8_6A"])
    if len(assigned) != 97:
        raise ValueError("Task scope is not the exact 97 suites")
    candidates, adaptations, proposals, substitutions = {}, {}, [], []
    for batch, filename in INPUTS.items():
        data = read(filename)
        for row in data["dispositions"]:
            path = row["path"]
            if path not in assigned or path in candidates:
                raise ValueError(f"Unassigned or duplicate lane row: {path}")
            source_hash = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            if source_hash != row["inherited_sha256"]:
                raise ValueError(f"Candidate source hash differs: {path}")
            if row["status"] not in {"restored", "retired", "deferred"}:
                raise ValueError(f"Invalid candidate status: {path}")
            normalized = dict(row)
            normalized["batch"] = batch
            retired = []
            for case in row.get("retired_cases", []):
                exact = {key: case[key] for key in ("case", "reason", "reviewer")}
                exact.update(source_path=path, source_sha256=source_hash)
                if exact["reviewer"] != REVIEWER or exact["case"] not in case_names(path):
                    raise ValueError(f"Retirement is not an exact task-authorized case: {path}")
                retired.append(exact)
            normalized["retired_cases"] = sorted(retired, key=lambda case: case["case"])
            if len({case["case"] for case in retired}) != len(retired):
                raise ValueError(f"Duplicate case retirement: {path}")
            if row["status"] == "retired":
                if {case["case"] for case in retired} != case_names(path):
                    raise ValueError(f"Suite retirement does not dispose every case: {path}")
                normalized["retirement"] = {
                    "reviewer": REVIEWER,
                    "reason": "All inherited cases individually retired for removed surfaces; "
                    "exact case-level reasons in the immutable lane8 disposition artifact.",
                }
            candidates[path] = normalized
        for entry in data.get("entries", []):
            if set(entry) != {"path", "reason", "contract", "invariant", "owner", "tests"}:
                if "baseline_sha256" in entry and "transformations" in entry:
                    continue  # Separate immutable fixture proof, not source adaptation authority.
                raise ValueError("New adaptation must use exact record-plan schema")
            adaptations[entry["path"]] = entry
        proposals.extend(data.get("proposed", []))
        substitutions.extend(data.get("data_substitutions", []))
        substitutions.extend(data.get("safe_substitutions", []))
    if set(candidates) != assigned:
        raise ValueError(f"Missing assigned suite dispositions: {sorted(assigned-set(candidates))}")
    artifact = {
        "schema_version": 1, "reviewer": REVIEWER,
        "assignment_sha256": ASSIGNMENT_SHA256,
        "status": "pending-independent-review-not-accepted",
        "counts": dict(Counter(row["status"] for row in candidates.values())),
        "dispositions": [candidates[path] for path in sorted(candidates)],
        "proposed": proposals, "data_substitutions": substitutions,
    }
    write("maintenance/phase2-step8-part4-lane8-dispositions.json", artifact)
    mapping, plan = read("maintenance/phase2-suite-map.json"), read("maintenance/test-plan.json")
    entries = {entry["path"]: entry for entry in plan["entries"]}
    for row in mapping["entries"]:
        path = row["path"]
        if path not in candidates:
            continue
        candidate = candidates[path]
        row.pop("restoration", None)
        row.pop("retirement", None)
        row["status"] = candidate["status"]
        if candidate["status"] == "restored":
            selector = candidate["selector"]
            row["blocked_on"] = None
            row["qualification_group"] = f"phase2-step6a-{candidate['batch']}-restored-corpus"
            row["restoration"] = {
                "mode": "frozen-adapter", "selectors": [selector],
                "reason": str(candidate.get("restoration") or "Exact complete retained corpus"),
                "retired_cases": candidate["retired_cases"],
            }
            entries[path]["classification"] = "safe_pass_now"
        elif candidate["status"] == "retired":
            row["blocked_on"] = None
            row["qualification_group"] = "not-applicable-retired"
            row["retirement"] = candidate["retirement"]
            entries[path].update(classification="retired", retirement=candidate["retirement"])
        else:
            blocker = candidate.get("blocker") or candidate.get("blocked_on")
            if not isinstance(blocker, str) or not blocker.strip():
                raise ValueError(f"Deferred suite lacks concrete blocker: {path}")
            row["blocked_on"] = blocker
            entries[path]["classification"] = "phase2"
        if candidate["retired_cases"]:
            row["retired_cases"] = candidate["retired_cases"]
    kinds = {entry["classification"] for entry in plan["entries"]}
    for kind in kinds:
        plan[kind] = sorted(path for path, entry in entries.items()
                            if entry["classification"] == kind)
        plan["counts"][kind] = len(plan[kind])
    plan["phase2_restored"] = sorted(row["path"] for row in mapping["entries"]
                                     if row["status"] == "restored")
    plan["phase2_retired"] = sorted(row["path"] for row in mapping["entries"]
                                    if row["status"] == "retired")
    plan["counts"]["phase2_restored"] = len(plan["phase2_restored"])
    plan["counts"]["phase2_retired"] = len(plan["phase2_retired"])
    plan["execution_status"] = (
        "Exact whole-suite restoration accounting, not passing or acceptance evidence. "
        "Lane8 step6A dispositions are hash/corpus bound; partial support does not restore "
        "a suite. Retirements are case-level removed surfaces under the current work order."
    )
    mapping.pop("counts", None)
    write("maintenance/phase2-suite-map.json", mapping)
    write("maintenance/test-plan.json", plan)
    parent = read("maintenance/phase2-step8-part4-lane8-adaptation-plan.json")
    for row in parent["entries"]:
        adaptations[row["path"]] = row
    parent["entries"] = [adaptations[path] for path in sorted(adaptations)]
    write("maintenance/phase2-step8-part4-lane8-adaptation-plan.json", parent)
    print(json.dumps(artifact["counts"], sort_keys=True))
    print("Disposition SHA256:", hashlib.sha256(
        (ROOT / "maintenance/phase2-step8-part4-lane8-dispositions.json").read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
