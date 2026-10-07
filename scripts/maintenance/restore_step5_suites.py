#!/usr/bin/env python3
"""Integrate audited whole-suite decisions, never turn a blocked subset green."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.maintenance import phase2_suites

ROOT = Path(__file__).resolve().parents[2]


def integrate(root: Path = ROOT) -> dict:
    mapping = phase2_suites._json((root / phase2_suites.MAP_PATH).read_bytes())
    plan = phase2_suites._json((root / phase2_suites.PLAN_PATH).read_bytes())
    qualification = phase2_suites._json((root / phase2_suites.QUALIFICATION_PATH).read_bytes())
    rows = {row["path"]: row for row in mapping["entries"]}
    expected = {path for path, row in rows.items() if row["step"] == 5}
    decisions = {}
    for batch in "abcd":
        filename = f"maintenance/step8-part2-batch-{batch}.json"
        document = phase2_suites._json((root / filename).read_bytes())
        for row in document["entries"]:
            path = row["path"]
            if path in decisions or path not in expected:
                raise ValueError(f"duplicate or unowned step-5 decision: {path}")
            decisions[path] = {**row, "decision_record": filename}
    guard_record = "maintenance/step8-part2-guard.json"
    guards = phase2_suites._json((root / guard_record).read_bytes())["owned_suites"]
    if len(guards) != 1:
        raise ValueError("guard record must own exactly one suite")
    guard = guards[0]
    guard_path = guard["path"]
    if guard_path != "tests/test_subsystem_guard.py" or guard["status"] != "restored":
        raise ValueError("guard record must restore the complete subsystem guard suite")
    if decisions.get(guard_path, {}).get("status") != "delegated":
        raise ValueError("guard must have exactly one delegated batch disposition")
    decisions[guard_path] = {
        "path": guard_path, "status": guard["status"], "decision_record": guard_record,
        "references": [guard["adapter"], guard["test_entry"], "src/desktop/management.py"],
        "evidence": "Complete constructor and guard corpus with actual shared runtime guard",
        "restoration": {"mode": guard["mode"], "selectors": [guard["test_entry"]],
                        "reason": guard["reason"],
                        "inherited_cases": guard["collected_inherited_cases"]},
    }
    if set(decisions) != expected or len(expected) != 85:
        raise ValueError("every one of the 85 step-5 suites needs exactly one disposition")
    entries = {row["path"]: row for row in plan["entries"]}
    group = next(g for g in qualification["groups"]
                 if g["name"] == "phase2-step5-profile-management")
    restored = []
    for path, decision in sorted(decisions.items()):
        row = rows[path]
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != row["inherited_sha256"]:
            raise ValueError(f"original bytes changed: {path}")
        row["step8_part2"] = {
            "decision_record": decision["decision_record"],
            "references": decision["references"], "evidence": decision["evidence"],
        }
        status = decision["status"]
        if status == "deferred":
            if not decision.get("blocked_on") or row["status"] != "deferred":
                raise ValueError(f"deferred suite lacks an honest blocker: {path}")
            row["blocked_on"] = decision["blocked_on"]
            continue
        if status != "restored" or not decision.get("restoration"):
            raise ValueError(f"unsupported step-5 disposition: {path}")
        restoration = decision["restoration"]
        if restoration["mode"] not in {"direct-original", "frozen-adapter"}:
            raise ValueError(f"not a whole-suite restoration: {path}")
        row.update(status="restored", blocked_on=None, restoration=restoration,
                   qualification_group=group["name"], historical_classification="phase2")
        entries[path].update(classification="safe_pass_now", reason=restoration["reason"])
        for selector in restoration["selectors"]:
            if selector not in group["files"]:
                group["files"].append(selector)
        restored.append(path)
    # The complete guard adapter replaces the old helper-only exclusion group.
    neutral = next(g for g in qualification["groups"] if g["name"] == "neutral-subsystem-guard")
    neutral["files"] = decisions[guard_path]["restoration"]["selectors"]
    neutral.pop("exclude_expression", None)
    neutral["reason"] = (
        "Complete inherited guard corpus and real Desktop constructor; no exclusions."
    )
    plan["safe_neutral_case_selections"] = [
        row for row in plan.get("safe_neutral_case_selections", [])
        if row["path"] not in restored
    ]
    new_boundary = sorted(str(path.relative_to(root)) for path in (root / "tests").glob(
        "test_desktop_phase2_runtime_*.py"))
    for path in new_boundary:
        if path not in group["files"]:
            group["files"].append(path)
    plan["phase2"] = sorted(set(plan["phase2"]) - set(restored))
    plan["phase2_restored"] = sorted(set(plan["phase2_restored"]) | set(restored))
    plan["safe_pass_now"] = sorted(set(plan["safe_pass_now"]) | set(restored))
    plan["counts"]["phase2"] = len(plan["phase2"])
    plan["counts"]["safe_pass_now"] = len(plan["safe_pass_now"])
    if "phase2_restored" in plan["counts"]:
        plan["counts"]["phase2_restored"] = len(plan["phase2_restored"])
    plan["execution_status"] = (
        "Historical eligibility, not whole-product acceptance. All 326 original suites remain "
        "with original hashes across deferred, restored and five reviewer-retired dispositions. "
        "Step8 part2 records all85 runtime decisions; complete suites only, "
        "no partial passing claim."
    )
    documents = {phase2_suites.MAP_PATH: mapping, phase2_suites.PLAN_PATH: plan,
                 phase2_suites.QUALIFICATION_PATH: qualification}
    # Verify prospective accounting against the real frozen bytes and history
    # before replacing any input. A rejected subset must not leave a green map.
    errors = phase2_suites.validate(root, documents=documents)
    if errors:
        raise ValueError(errors)
    for filename, document in documents.items():
        target = root / filename
        if filename == phase2_suites.MAP_PATH:
            text = json.dumps({k: v for k, v in document.items() if k != "entries"}, indent=2)
            text = text[:-2] + ',\n  "entries": [\n' + ",\n".join(
                "    " + json.dumps(row, separators=(",", ":")) for row in document["entries"]
            ) + "\n  ]\n}\n"
        else:
            text = json.dumps(document, indent=2) + "\n"
        replacement = target.with_suffix(target.suffix + ".tmp")
        replacement.write_text(text)
        replacement.replace(target)
    errors = phase2_suites.validate(root)
    if errors:
        raise ValueError(errors)
    return {"owned": len(expected), "dispositions": dict(Counter(
        d["status"] for d in decisions.values())), "restored": sorted(restored)}


if __name__ == "__main__":
    print(json.dumps(integrate(), indent=2))
