#!/usr/bin/env python3
"""Explicit whole-suite enrollment for the requested step-five completion.

This records qualification selection and exact lineage, not passing evidence or
independent approval. Every original byte and the historical population stays
bound by phase2_suites and inventory. No unrelated deferred suite is promoted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.maintenance import inventory  # noqa: E402

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
    "tests/test_desktop_step5_accounting.py",
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


def record_lineage(root=ROOT):
    """Exact enumerated source contracts, never unreviewed whole-tree recapture."""
    from types import SimpleNamespace

    domains = [
        ("Records diffs, rotated failure snapshots and bounded newline/UTF-8 tails",
         ["src/desktop/records.py", "tests/desktop_adapters/step5_records.py",
          "tests/desktop_adapters/step5_records_legacy.py",
          "tests/test_desktop_records.py", "tests/test_desktop_step5_records_corpus.py",
          "tests/test_desktop_step5_records_methods.py"],
         ["tests/test_desktop_step5_records_corpus.py",
          "tests/test_desktop_step5_records_methods.py", "tests/test_desktop_records.py"],
         "Actual retained read algorithms, complete diffs, filters and fallback limits; "
         "profile/source-bound follow cursors instead of renderer sockets. Historical tier "
         "assertions use sealed original policy only, not production Desktop tiers.",
         "No writer construction by fallback readers, no dropped incomplete UTF-8 records, "
         "no alteration to any original assertion/parameter/decorator or audit repair."),
        ("Knowledge chunk/dedup/version and learned-context CRUD completion",
         ["src/desktop/knowledge.py", "src/desktop/learned_context.py", "src/desktop/state.py",
          "tests/desktop_adapters/step5_knowledge_corpus.py",
          "tests/desktop_adapters/step5_knowledge_services.py", "tests/test_desktop_state.py",
          "tests/test_desktop_step5_knowledge_corpus.py",
          "tests/test_desktop_step5_knowledge_methods.py"],
         ["tests/test_desktop_step5_knowledge_corpus.py",
          "tests/test_desktop_step5_knowledge_methods.py", "tests/test_desktop_state.py"],
         "Pinned store semantics including delete-only merge and generation-disabled CRUD. "
         "Authenticated single profile owner has Odin admin access to retained memory scopes; "
         "absent personal scopes remain not-found instead of invented records.",
         "Original corpus bytes and native owner admission unchanged; mutations settle actual "
         "store commits, corruption refuses writes, no model-facing instruction changes."),
        ("Passive real-owner observability, recovery, capacity and pool methods",
         ["src/desktop/observability.py", "tests/desktop_adapters/step5_observability_http.py",
          "tests/desktop_adapters/step5_observability_neutral.py",
          "tests/desktop_adapters/step5_observability_turn_state.py",
          "tests/test_desktop_step5_observability_http.py",
          "tests/test_desktop_step5_observability_neutral.py",
          "tests/test_desktop_step5_observability_turn_state.py",
          "tests/test_desktop_step5_observability_methods.py"],
         ["tests/test_desktop_step5_observability_http.py",
          "tests/test_desktop_step5_observability_neutral.py",
          "tests/test_desktop_step5_observability_turn_state.py",
          "tests/test_desktop_step5_observability_methods.py"],
         "Lazy references observe the actual composed counters/breaker/pools, without creating "
         "requests, probe admission or connections. Pool close is a journaled mutation; all "
         "other methods are reads. Sealed legacy auth proves historical policy separately.",
         "No fabricated unavailable-owner measurements, no provider-cache claims from local "
         "prefix equality, no guard relaxations or original test edits."),
        ("OpenRouter catalog preview, selection/pin, measured cache and diagnostics",
         ["src/desktop/openrouter_admin.py", "src/desktop/model_settings.py",
          "tests/desktop_adapters/step5_llm_bridge.py", "tests/desktop_adapters/step5_llm_cases.py",
          "tests/test_desktop_step5_llm_corpus.py", "tests/test_desktop_step5_llm_methods.py"],
         ["tests/test_desktop_step5_llm_corpus.py", "tests/test_desktop_step5_llm_methods.py"],
         "Retained public/auth-scoped caches, route profile validation, current-policy "
         "revalidation after awaits and persistence before runtime publication. tools.list "
         "reports actual affordance cost/risk. Diagnostics are scrubbed copies.",
         "No credential readback or mutation of model-facing inputs, no main-model switch "
         "invented by pin selection, no changed original corpus assertions."),
        ("Trajectory guarded filtered readers and retained Codex account refresh",
         ["src/desktop/trajectories.py", "src/desktop/codex_accounts.py",
          "tests/desktop_adapters/step5_traces.py", "tests/test_desktop_step5_traces_frozen.py",
          "tests/test_desktop_step5_traces_methods.py"],
         ["tests/test_desktop_step5_traces_frozen.py",
          "tests/test_desktop_step5_traces_methods.py"],
         "Retained filter-before-limit trajectory algorithms, live configured path and actual "
         "runtime saver count; refresh shares serving auth pool/per-account settlement lock.",
         "Path traversal/resolved containment guards, keyring-only persistence, unknown/no-replay "
         "semantics and frozen original assertions remain intact."),
        ("Completion composition binds actual request and management owners",
         ["src/desktop/management.py", "src/desktop/services.py",
          "tests/test_desktop_step5_completion_core.py"],
         ["tests/test_desktop_step5_completion_core.py", "tests/test_desktop_engine_services.py",
          "app/test/real-core-completion.test.ts"],
         "One knowledge store for native tools and management, shared reflector/audit locks, "
         "actual trajectory saver and compression tracker passed to the original runner. "
         "Measured cache uses real usage summary or a read-only profile query.",
         "No replacement runner or transport, no fabricated measurement, read methods reserve "
         "no commands, journaled effects replay without execution."),
        ("Public numeric model-profile window metadata is not a credential",
         ["src/config/sensitivity.py", "tests/test_desktop_step5_sensitivity.py"],
         ["tests/test_desktop_step5_sensitivity.py", "tests/test_desktop_step5_llm_methods.py"],
         "Exact schema key total_window_tokens joins existing public token-count keys so "
         "validated OpenRouter derived profiles can persist through the real settings owner.",
         "Credential substring rules, storage-sensitive keys and opaque containers unchanged; "
         "no broad token suffix exemption."),
        ("Exact step-five whole-suite qualification enrollment",
         ["scripts/maintenance/record_step5_completion.py", "scripts/maintenance/phase2_suites.py",
          "tests/test_desktop_phase2_suite_map.py", "tests/test_desktop_step5_accounting.py"],
         ["tests/test_desktop_phase2_suite_map.py", "tests/test_desktop_step5_accounting.py"],
         "Enumerated 21 whole source/corpus-bound adapters and named tests added to existing "
         "management group. Permit restored step5 like Admin lane; preserve all original326 "
         "members, original869 hashes, previous selectors and exclusions.",
         "No generic source blessing, no smoke-only restoration, no automatic review approval "
         "or passing evidence from static enrollment."),
    ]
    planned = []
    for reason, paths, tests, contract, invariant in domains:
        for path in paths:
            entry = {"path": path, "reason": reason, "contract": contract,
                     "invariant": invariant, "owner": "Odin", "tests": tests}
            planned.append(entry)
            inventory.record(root, SimpleNamespace(**entry))
    # Source bytes for these six existing records are unchanged. Refresh only
    # their named evidence hashes while preserving their original accountability.
    dependent = {
        "src/desktop/settings.py", "tests/test_desktop_model_settings.py",
        "scripts/run-phase1-tests.py", "tests/desktop_adapters/process_cases.py",
        "tests/test_desktop_round2_acceptance.py", "tests/test_desktop_test_plan.py",
    }
    ledger = inventory.ledger(root)
    for row in ledger["entries"]:
        if row["path"] in dependent:
            actual = (root / row["path"]).read_bytes()
            if inventory.digest(actual) != row["after_sha256"]:
                raise ValueError(f"Dependent source unexpectedly changed: {row['path']}")
            row["test_sha256"] = {path: inventory.digest((root / path).read_bytes())
                                  for path in row["tests"]}
            row["evidence"] += " Step-five completion updates named evidence hashes only."
    inventory.write_json(root / "maintenance/desktop-deltas.json", ledger)
    inventory.write_json(root / "maintenance/phase2-step5-completion-adaptation-plan.json",
                         {"schema_version": 1, "artifact": "Explicit pending completion lineage",
                          "entries": planned,
                          "unchanged_source_evidence_refresh": sorted(dependent)})
    inventory.main(["--root", str(root), "refresh"])


if __name__ == "__main__":
    if sys.argv[1:] == ["--record-lineage"]:
        record_lineage()
    elif not sys.argv[1:]:
        print(f"Enrolled {enroll()} whole suites; this is not execution evidence")
    else:
        raise SystemExit("Only --record-lineage or no arguments are supported")
