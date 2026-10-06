#!/usr/bin/env python3
"""Offline PR34 review accounting. Preview by default; no tests are imported.

The legacy 85-suite generator is historical and must not run against this map.
Partial work is recorded, never promoted. This is eligibility accounting, not
runtime qualification. desktop-deltas byte patches remain the parent's task.
"""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path

from scripts.maintenance import phase2_suites as checker

DISPOSITIONS = "maintenance/step8-part2-review-dispositions.json"
RECORDS = tuple(f"maintenance/step8-part2-review-{lane}.json"
                for lane in ("provider", "health", "integrations", "llm"))
BLOCKER = "awaiting the step 5 completion PR"
DEFERRED = frozenset(f"tests/{stem}.py" for stem in (
    "test_action_diffs", "test_audit_tail_v412", "test_campaign_audit_observability",
    "test_campaign_openrouter_coverage", "test_openrouter_admin_boundaries",
    "test_campaign_prefix_measurement", "test_connection_pools", "test_knowledge_dedup",
    "test_knowledge_versions", "test_learning_disabled_crud", "test_recovery",
    "test_trajectories", "test_web_api_knowledge_mem", "test_web_api_new_endpoints",
    "test_web_api_observability", "test_web_api_turn_state", "test_webui_selected_trace_filters",
    "test_web_campaign_streams", "test_campaign_websocket_coverage",
    "test_codex_account_mutation_regressions",
))
REMAPS = {
    "tests/test_computer_config_admin_r19.py": 6,
    "tests/test_computer_config_toolloop_coverage_r10.py": 6,
    "tests/test_direct_chat_reasoning_records.py": 3,
    "tests/test_executor_output_retention.py": 3,
    "tests/test_pr341_b8_turn_totals.py": 3,
    "tests/test_process_retention_security.py": 6,
}
ADAPT = frozenset(f"tests/{stem}.py" for stem in (
    "test_audit_signing", "test_hosts_api", "test_image_model_config_api",
    "test_web_api_llm_admin", "test_web_api_integrations_validation_coverage",
    "test_campaign_agent_routes_coverage", "test_campaign_provider_reload_coverage",
    "test_codex_quota_check", "test_health_endpoints", "test_campaign_startup_health",
    "test_output_executor_fences", "test_webhook_campaign", "test_log_search",
))
PARTIAL_STEP5 = {"tests/test_log_search.py", "tests/test_web_api_llm_admin.py"}
BOUNDARY_TESTS = (
    "tests/test_desktop_review_audit_authority.py",
    "tests/test_desktop_review_quota_lifecycle.py",
    "tests/test_desktop_review_provider_hosts_provenance.py",
    "tests/test_desktop_review_provider_image.py",
    "tests/test_desktop_review_provider_image_provenance.py",
    "tests/test_desktop_review_provider_llm.py",
    "tests/test_desktop_review_provider_llm_provenance.py",
    "tests/test_desktop_review_provider_policy_reload.py",
    "tests/test_desktop_review_provider_quota_provenance.py",
    "tests/test_desktop_review_provider_reload_provenance.py",
)


def approved_dispositions():
    return {
        "schema_version": 1, "reviewer": checker.REVIEW34_REVIEWER,
        "reviewed_head": "8703630", "blocker": BLOCKER,
        "retirement_groups": {reason: [f"tests/{stem}.py" for stem in stems]
                              for reason, stems in checker.REVIEW34_RETIREMENT_GROUPS.items()},
        "deferred": sorted(DEFERRED), "remaps": REMAPS,
        "adapt": sorted(ADAPT), "partial_deferred": sorted(PARTIAL_STEP5),
        "approved_data_substitution": {
            "path": "tests/test_log_search.py", "inherited_line": 59,
            "reason": ("Replace the destructive command sample with a harmless string "
                       "of the same shape; preserve the search assertion."),
        },
    }


def build(root: Path = checker.ROOT, *, records=None, require_complete=True):
    """Return validated prospective documents and report, without writing.

    records=None reads four lane files. An explicit list of (filename, object)
    pairs is useful for offline tests. require_complete=False permits a preview
    with fewer decisions, never partial restoration or relaxed byte validation.
    """
    root = Path(root)
    approval = checker._json((root / DISPOSITIONS).read_bytes())
    if approval != approved_dispositions():
        raise ValueError("review #34 authority differs from exact approved paths/reasons")
    docs = {name: checker._json((root / name).read_bytes()) for name in
            (checker.MAP_PATH, checker.PLAN_PATH, checker.QUALIFICATION_PATH)}
    errors = checker.validate(root, documents=docs)
    if errors:
        raise ValueError(errors)
    mapping, plan, qualification = (
        docs[name] for name in
        (checker.MAP_PATH, checker.PLAN_PATH, checker.QUALIFICATION_PATH))
    rows = {row["path"]: row for row in mapping["entries"]}
    entries = {row["path"]: row for row in plan["entries"]}
    old_five = {p: copy.deepcopy(rows[p]) for p in checker.RETIRABLE_SUITES}
    if records is None:
        records = [(name, checker._json((root / name).read_bytes())) for name in RECORDS]
    decisions = {}
    for filename, record in records:
        if (not isinstance(record, dict)
                or type(record.get("schema_version")) is not int or record["schema_version"] != 1
                or record.get("reviewer") != checker.REVIEW34_REVIEWER
                or not isinstance(record.get("entries"), list)):
            raise ValueError(f"malformed review lane record: {filename}")
        for decision in record["entries"]:
            if not isinstance(decision, dict):
                raise ValueError(f"review lane decision must be an object: {filename}")
            path = decision.get("path")
            if path not in ADAPT or path in decisions:
                raise ValueError(f"duplicate or unreviewed adapter decision: {path}")
            if (decision.get("inherited_sha256", rows[path]["inherited_sha256"])
                    != rows[path]["inherited_sha256"]):
                raise ValueError(f"review inherited hash changed: {path}")
            if (not isinstance(decision.get("references"), list) or not decision["references"]
                    or any(not isinstance(ref, str) or not ref.strip()
                           for ref in decision["references"])
                    or not decision.get("evidence")):
                raise ValueError(f"review adapter needs references and evidence: {path}")
            decisions[path] = {**decision, "decision_record": filename}
    if require_complete and set(decisions) != ADAPT:
        missing = sorted(ADAPT - set(decisions))
        raise ValueError(f"all 13 reviewed C suites require decisions; missing={missing}")
    for path, reason in checker.REVIEW34_RETIREMENT_REASONS.items():
        row, entry = rows[path], entries[path]
        if row["step"] != 5 or row["status"] not in {"deferred", "retired"}:
            raise ValueError(f"retirement requires held reviewed step-5 suite: {path}")
        retirement = {"reviewer": checker.REVIEW34_REVIEWER, "reason": reason}
        row.update(status="retired", reason=reason, blocked_on=None,
                   qualification_group="not-applicable-retired", retirement=retirement)
        row.pop("pending_contract_disposition", None)
        entry.update(classification="retired", reason=reason, retirement=retirement)
    for path in DEFERRED:
        if rows[path]["status"] != "deferred" or rows[path]["step"] != 5:
            raise ValueError(f"group B must remain deferred in step 5: {path}")
        rows[path]["blocked_on"] = BLOCKER
    for path, step in REMAPS.items():
        row = rows[path]
        if row["status"] != "deferred" or row["step"] not in {5, step}:
            raise ValueError(f"remap must remain deferred in reviewed owner step: {path}")
        row.update(step=step,
                   blocked_on=f"Awaiting step {step} whole-suite completion and qualification")
    group = next(g for g in qualification["groups"]
                 if g["name"] == "phase2-step5-profile-management")
    restored = []
    for path, decision in sorted(decisions.items()):
        row = rows[path]
        row["step8_part2_review"] = copy.deepcopy(decision)
        if decision.get("status") == "deferred":
            if ("restoration" in decision or row["status"] != "deferred"
                    or not decision.get("blocked_on")):
                raise ValueError(f"partial/deferred suite cannot claim whole restoration: {path}")
            if path in PARTIAL_STEP5 and decision["blocked_on"] != BLOCKER:
                raise ValueError(f"mixed suite must await step 5 completion: {path}")
            row["blocked_on"] = decision["blocked_on"]
            # Selecting an independently partial adapter module is qualification
            # work, not promotion of the inherited whole-suite disposition.
            partial = decision.get("partial_adaptation", {})
            if not isinstance(partial, dict):
                raise ValueError(f"malformed partial adaptation: {path}")
            for selector in partial.get("selectors", []):
                module = selector.split("::", 1)[0] if isinstance(selector, str) else selector
                if not checker._path(module) or module == path:
                    raise ValueError(f"partial qualification needs adapter module: {path}")
                checker._regular(root, module)
                if module not in group["files"]:
                    group["files"].append(module)
            continue
        restoration = decision.get("restoration", {})
        if (not isinstance(restoration, dict)
                or decision.get("status") != "restored" or path in PARTIAL_STEP5
                or restoration.get("mode") != "frozen-adapter"
                or type(restoration.get("inherited_cases")) is not int
                or restoration["inherited_cases"] < 1
                or not isinstance(restoration.get("reason"), str)
                or not restoration["reason"].strip()
                or not isinstance(restoration.get("selectors"), list)
                or not restoration["selectors"]
                or len(restoration["selectors"]) != len(set(restoration["selectors"]))):
            raise ValueError(f"only complete reviewed frozen suites count: {path}")
        for selector in restoration["selectors"]:
            if not checker._path(selector) or not checker._full_adapter(
                    root, selector, path, row["inherited_sha256"]):
                raise ValueError(f"not an immutable whole-suite association: {path}: {selector}")
            if selector not in group["files"]:
                group["files"].append(selector)
        row.update(status="restored", blocked_on=None, restoration=restoration,
                   qualification_group=group["name"], historical_classification="phase2")
        entries[path].update(classification="safe_pass_now", reason=restoration["reason"])
        restored.append(path)
    for filename, record in records:
        for selector in record.get("qualification_tests", []):
            if not checker._path(selector):
                raise ValueError(f"qualification test must be a whole canonical module: {filename}")
            checker._regular(root, selector)
            if selector not in group["files"]:
                group["files"].append(selector)
    if require_complete:
        for selector in BOUNDARY_TESTS:
            checker._regular(root, selector)
            if selector not in group["files"]:
                group["files"].append(selector)
    for kind in checker.KINDS:
        plan[kind] = sorted(p for p, entry in entries.items() if entry["classification"] == kind)
        plan["counts"][kind] = len(plan[kind])
    for status, field in (("restored", "phase2_restored"), ("retired", "phase2_retired")):
        plan[field] = sorted(p for p, row in rows.items() if row["status"] == status)
        if field in plan["counts"]:
            plan["counts"][field] = len(plan[field])
    plan["safe_neutral_case_selections"] = [r for r in plan.get("safe_neutral_case_selections", [])
                                            if r["path"] not in restored]
    mapping.pop("counts", None)
    plan["execution_status"] = (
        "Historical eligibility, not runtime qualification or product acceptance. PR34 records "
        "36 new reviewer retirements separately from #26's immutable five; Group B and mixed "
        "log/LLM suites await the step 5 completion PR. Only complete frozen suites count.")
    if old_five != {p: rows[p] for p in old_five}:
        raise ValueError("original five #26 dispositions changed")
    errors, report = checker._evaluate(root, documents=docs)
    if errors:
        raise ValueError(errors)
    report["review34"] = {"retired": 36, "group_b_deferred": 20, "remapped": 6,
                          "adapt_decisions": dict(Counter(d["status"] for d in decisions.values())),
                          "restored_paths": restored}
    return docs, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=checker.ROOT)
    parser.add_argument("--write", action="store_true", help="Parent-authorized integration only")
    parser.add_argument("--dispositions-only", action="store_true",
                        help="Preview without lane records")
    args = parser.parse_args(argv)
    if args.write and args.dispositions_only:
        parser.error("dispositions-only previews cannot write final accounting")
    docs, report = build(args.root, records=[] if args.dispositions_only else None,
                         require_complete=not args.dispositions_only)
    if args.write:
        for name, document in docs.items():
            target = args.root / name
            temporary = target.with_suffix(target.suffix + ".tmp")
            if name == checker.MAP_PATH:
                header = json.dumps(
                    {key: value for key, value in document.items() if key != "entries"}, indent=2,
                )
                text = header[:-2] + ',\n  "entries": [\n' + ",\n".join(
                    "    " + json.dumps(row, separators=(",", ":"))
                    for row in document["entries"]
                ) + "\n  ]\n}\n"
            else:
                text = json.dumps(document, indent=2) + "\n"
            temporary.write_text(text)
            temporary.replace(target)
    print(json.dumps({"written": args.write, "counts": report}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
