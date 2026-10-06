#!/usr/bin/env python3
"""Explicit whole-suite enrollment for the requested step-five completion.

This records qualification selection and exact lineage, not passing evidence or
independent approval. Every original byte and the historical population stays
bound by phase2_suites and inventory. No unrelated deferred suite is promoted.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.maintenance import inventory

ROOT = Path(__file__).resolve().parents[2]
GROUP = "phase2-step5-profile-management"
RESTORATIONS = {
    "tests/test_desktop_step5_records_corpus.py": [
        "action_diffs", "campaign_audit_observability", "audit_tail_v412", "log_search",
        "web_campaign_streams", "campaign_websocket_coverage",
    ],
    "tests/test_desktop_step5_knowledge_corpus.py": [
        "knowledge_dedup", "knowledge_versions", "learning_disabled_crud", "web_api_knowledge_mem",
    ],
    "tests/test_desktop_step5_observability_http.py": [
        "web_api_observability", "campaign_prefix_measurement",
    ],
    "tests/test_desktop_step5_observability_neutral.py": ["recovery", "connection_pools"],
    "tests/test_desktop_step5_observability_turn_state.py": ["web_api_turn_state"],
    "tests/test_desktop_step5_llm_corpus.py": [
        "campaign_openrouter_coverage", "openrouter_admin_boundaries", "web_api_new_endpoints",
    ],
    "tests/test_desktop_step5_traces_frozen.py": [
        "trajectories", "webui_selected_trace_filters", "codex_account_mutation_regressions",
    ],
}
METHOD_TESTS = [
    "tests/test_desktop_step5_completion_core.py",
    "tests/test_desktop_step5_knowledge_methods.py",
    "tests/test_desktop_step5_llm_methods.py",
    "tests/test_desktop_step5_observability_methods.py",
    "tests/test_desktop_step5_records_methods.py",
    "tests/test_desktop_step5_sensitivity.py",
    "tests/test_desktop_step5_traces_methods.py",
]


def enroll(root=ROOT):
    from scripts.maintenance.phase2_suites import _full_adapter

    mapping = json.loads((root / "maintenance/phase2-suite-map.json").read_text())
    plan = json.loads((root / "maintenance/test-plan.json").read_text())
    qualification = json.loads((root / "maintenance/qualification-plan.json").read_text())
    rows = {row["path"]: row for row in mapping["entries"]}
    entries = {row["path"]: row for row in plan["entries"]}
    for selector, names in RESTORATIONS.items():
        for name in names:
            path = f"tests/test_{name}.py"
            row = rows[path]
            if row["step"] != 5 or not _full_adapter(
                root, selector, path, row["inherited_sha256"],
            ):
                raise ValueError(f"Whole pinned step-five adapter required: {path}")
            row.update(status="restored", blocked_on=None, qualification_group=GROUP,
                       restoration={
                           "mode": "frozen-adapter", "selectors": [selector],
                           "reason": "Entire source-hash-bound frozen suite, with identical "
                           "assertions, test signatures, decorators and parameter data. "
                           "Explicit setup projections call actual named management owners; "
                           "retired tier assertions remain sealed historical policy proofs, "
                           "not Desktop tiers or production transport.",
                       })
            entries[path]["classification"] = "safe_pass_now"
            entries[path]["reason"] = (
                "Step-five completion whole frozen-source adapter enrollment; named service "
                "method tests and authenticated core/Broker tests are separate runtime proofs. "
                "Independent review and full qualification remain required."
            )
            for key in ("phase2", "safe_pass_now", "phase2_restored"):
                plan.setdefault(key, [])
            if path in plan["phase2"]:
                plan["phase2"].remove(path)
            for key in ("safe_pass_now", "phase2_restored"):
                plan[key] = sorted(set(plan[key]) | {path})
    for key in plan["counts"]:
        if key in plan and isinstance(plan[key], list):
            plan["counts"][key] = len(plan[key])
    group = next(group for group in qualification["groups"] if group["name"] == GROUP)
    group["files"] = sorted(set(group["files"]) | set(RESTORATIONS) | set(METHOD_TESTS))
    group["reason"] += (
        " Step-five completion additionally executes all 21 requested original filenames "
        "through whole hash/corpus-bound adapters, plus named-method and authenticated "
        "transport proofs. No original selection is removed, no new skip/exclusion is added."
        if "all 21 requested original filenames" not in group["reason"] else ""
    )
    for path, value in (("maintenance/phase2-suite-map.json", mapping),
                        ("maintenance/test-plan.json", plan),
                        ("maintenance/qualification-plan.json", qualification)):
        inventory.write_json(root / path, value)
    return sum(map(len, RESTORATIONS.values()))


if __name__ == "__main__":
    print(f"Enrolled {enroll()} whole suites; this is not execution evidence")
