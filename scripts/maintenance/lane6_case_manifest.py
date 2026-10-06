#!/usr/bin/env python3
"""Read-only lane6 candidate report. No enrollment, source recapture or imports
of adapters/production owners. Parent supplies exact reviewed decision overrides.
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))
from scripts.maintenance import fixture_corpus, phase2_suites  # noqa: E402

STATUSES = ("restored", "retired", "deferred", "proposed")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def literal_metadata(path):
    result = {}
    for node in ast.parse(path.read_bytes()).body:
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = value
    return result


def identity(value, path=None):
    if not isinstance(value, str):
        return None
    if "::" in value and value.split("::", 1)[0] in ASSIGNED:
        path, value = value.split("::", 1)
        return identity(value, path)
    if path in ASSIGNED:
        symbol = value.replace("::", ".")
        if re.fullmatch(r"(?:[A-Za-z_]\w*\.)*test_\w+", symbol):
            return path + "::" + symbol
        return None
    for suite in ASSIGNED:
        stem = Path(suite).stem
        if value.startswith(stem + "."):
            return suite + "::" + value[len(stem) + 1:]
    return None


ASSIGNED = tuple(sorted("""
tests/characterization/test_autonomous_loop.py
tests/characterization/test_chat_tool_loop.py
tests/characterization/test_scheduled_events.py
tests/test_agent_audit_parity.py
tests/test_agent_auto_dynamic.py
tests/test_agent_completion_classifier.py
tests/test_agent_model_admission.py
tests/test_agent_parent_activity.py
tests/test_agent_repetition.py
tests/test_agent_result_pages.py
tests/test_agent_stream_progress.py
tests/test_agent_trajectory.py
tests/test_agent_transcript_contract.py
tests/test_agent_wait_budget.py
tests/test_agents_tasks_provider_paths.py
tests/test_background_task_cancel.py
tests/test_background_task_failure_visibility.py
tests/test_campaign_loops.py
tests/test_campaign_scheduler_workflows.py
tests/test_chat_loop_recovery.py
tests/test_config_liveness_wiring.py
tests/test_context_budget_activation.py
tests/test_context_density_calibration.py
tests/test_generation_duration_contract.py
tests/test_graceful_shutdown.py
tests/test_health_checker.py
tests/test_health_checker_paths.py
tests/test_learning_runtime_switch.py
tests/test_learning_transport_switch.py
tests/test_max_reasoning_effort.py
tests/test_mixed_agent_reasoning_contract.py
tests/test_native_agents_tasks.py
tests/test_native_scheduling.py
tests/test_nested_agents.py
tests/test_output_streamer.py
tests/test_predictive_presend.py
tests/test_preserved_reasoning_accounting.py
tests/test_process_api_provenance.py
tests/test_process_command_visibility.py
tests/test_provider_argument_acceptance.py
tests/test_provider_campaign_regressions.py
tests/test_provider_stream_acceptance.py
tests/test_reasoning_generation_records.py
tests/test_resource_usage.py
tests/test_runtime_output_delivery.py
tests/test_scheduled_digest_identity.py
tests/test_scheduled_events.py
tests/test_scheduled_events_digest_failure_summary.py
tests/test_scheduled_report.py
tests/test_scheduled_report_pagination_listener.py
tests/test_scheduled_report_wiring.py
tests/test_scheduled_workflow.py
tests/test_search_output_capture.py
tests/test_tool_lifecycle_correlation.py
tests/test_tool_loop_provenance.py
tests/test_trajectory_completeness.py
tests/test_turn_recorder_loop_reflection.py
tests/test_wait_stuck_integration.py
tests/test_web_api_agents_loops.py
tests/test_web_api_schedules.py
tests/test_window_observer.py
tests/test_write_invariant_integration.py
""".split()))

# Exact mixed useful-behavior cases raised in the parent review corrections.
MIXED = {
    "tests/test_agent_completion_classifier.py::test_iteration_cap_failure_visible_to_wait_results_and_agents_api",
    "tests/test_agent_result_pages.py::test_byte_complete_dispatch_pages_after_eviction_and_restart",
    "tests/test_mixed_agent_reasoning_contract.py::test_codex_default_spawn_requires_model_selection",
    "tests/test_scheduled_events.py::TestFormatDigestRaw.test_failed_probe_is_a_collection_failure",
    "tests/test_scheduled_events.py::TestWorkflow.test_strict_workflow_stops_on_step_permission_denial",
    "tests/test_scheduled_events.py::TestWorkflow.test_strict_workflow_rejects_missing_skill_name",
    "tests/test_scheduled_events.py::TestWorkflow.test_strict_workflow_checks_skill_target_permission",
}


def normalize_report(data):
    """Explicit lists/maps only. Counts and prose contracts are not case IDs."""
    claims, suites = [], []
    fields = {"restored": "restored", "restored_cases": "restored",
              "retired": "retired", "retired_cases": "retired", "retirements": "retired",
              "additional_retired_cases": "retired", "case_retirements": "retired",
              "deferred": "deferred", "deferred_cases": "deferred", "case_deferrals": "deferred",
              "proposed": "proposed", "proposals": "proposed", "proposed_cases": "proposed",
              "case_proposals": "proposed"}

    def cases(value, status, path, context):
        if isinstance(value, list):
            for item in value:
                cases(item, status, path, context)
        elif isinstance(value, str):
            key = identity(value, path)
            if key:
                claims.append((key, {**context, "status": status}))
        elif isinstance(value, dict):
            key = identity(value.get("original", value.get("case", value.get("symbol"))), path)
            if key:
                claims.append((key, {**context, **value, "status": status}))
            else:
                for name, item in value.items():
                    suite = name if name in ASSIGNED else "tests/" + name + ".py"
                    if suite in ASSIGNED:
                        cases(item, status, suite, context)
                    elif isinstance(item, str) and identity(name, path):
                        claims.append((identity(name, path), {**context, "status": status, "reason": item}))
                    elif isinstance(item, dict) and identity(name, path):
                        claims.append((identity(name, path), {**context, **item, "status": status}))

    def walk(node, path=None, context=None):
        context = dict(context or {})
        if isinstance(node, list):
            for item in node:
                walk(item, path, context)
        elif isinstance(node, dict):
            path = node.get("path", node.get("suite", node.get("source_path", path)))
            if path not in ASSIGNED:
                path = None
            for key in ("reason", "reviewer", "authority", "surface", "selector", "adapter"):
                if isinstance(node.get(key), str):
                    context[key] = node[key]
            if path and any(key in node for key in ("status", "whole_suite", "restored_cases", "case_dispositions")):
                suites.append((path, {**context, **node}))
            if path and isinstance(node.get("cases"), list) and node.get("status") in STATUSES:
                cases(node["cases"], node["status"], path, context)
            if "original" in node and node.get("disposition", node.get("status")) in STATUSES:
                cases(node, node.get("disposition", node.get("status")), path, context)
            for key, value in node.items():
                if key in fields:
                    cases(value, fields[key], path, context)
                elif key in ASSIGNED:
                    walk({"path": key, **value} if isinstance(value, dict) else value, key, context)
                elif isinstance(value, (list, dict)):
                    walk(value, path, context)
    walk(data)
    return claims, suites


def snapshot_loaders(module_names):
    """Resolve CASE_MAP/DISPOSITIONS by named pure namespace loaders only.

    Call from an isolated test via scripts/run-phase1-tests.py. No production
    fixtures/test functions are invoked. Caller must review import/load purity.
    Namespace evidence prevents accidental direct invocation on the workstation.
    """
    import importlib

    if (os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1"
            or not os.environ.get("PYTEST_CURRENT_TEST")
            or b"subprocess.call(sys.argv[1:])" not in Path("/proc/1/cmdline").read_bytes()):
        raise RuntimeError("Named loaders require the PID-isolated test runner")
    result = {"modules": [], "claims": [], "exports": []}
    for name in module_names:
        if not name.startswith("tests.desktop_adapters.lane6_"):
            raise ValueError("Not an explicitly named lane6 loader")
        module = importlib.import_module(name)
        namespace = {"__name__": "lane6_case_accounting"}
        module.load(namespace)
        result["modules"].append({"module": name, "sha256": digest(Path(module.__file__).read_bytes())})
        current, _ = normalize_report({key.lower(): getattr(module, key, {}) for key in (
            "RETIRED_CASES", "DEFERRED_CASES", "PROPOSED_CASES")})
        nonrestored = {key: row for key, row in current}
        for key, row in current:
            result["claims"].append({"original": key, **row})
        for original, row in getattr(module, "DISPOSITIONS", {}).items():
            result["claims"].append({"original": original, **row})
        for original, target in getattr(module, "CASE_MAP", {}).items():
            parts = target.split("::")
            value = namespace.get(parts[0])
            for part in parts[1:]:
                value = getattr(value, part, None)
            if value is not None:
                result["exports"].append({"original": original, "module": name, "selector": target})
                if identity(original) not in nonrestored:
                    disposition = getattr(module, "DISPOSITIONS", {}).get(original)
                    if not disposition or disposition["status"] == "restored":
                        result["claims"].append({"original": original, "status": "restored",
                                                 "selector": target,
                                                 "metadata_source": "actual named-loader export"})
    return result


def pure_disposition(source, values, path, symbols):
    """Evaluate only reviewed classification functions with literal constants.

    Never execute imports, decorators, owners or arbitrary adapter setup. Unknown
    function syntax fails closed. Current health-core/resources are the named
    simple policy variants; other variants need explicit reports/snapshots.
    """
    if source.name not in {"lane6_health_core.py", "lane6_health_resources.py"}:
        return {}
    tree = ast.parse(source.read_bytes())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == "disposition"]
    if len(functions) != 1 or functions[0].decorator_list:
        return {}
    for node in ast.walk(functions[0]):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.Await, ast.With,
                             ast.For, ast.While, ast.Lambda, ast.Global, ast.Nonlocal)):
            raise ValueError("Unexpected classification syntax")
        if isinstance(node, ast.Call) and not (
            isinstance(node.func, ast.Attribute) and node.func.attr == "startswith"
            and isinstance(node.func.value, ast.Name)):
            raise ValueError("Unexpected classification call")
    namespace = {"__builtins__": {}, **values}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
    stem = Path(path).stem
    return {identity(symbol, path): {"status": status, "reason": reason}
            for symbol in symbols for status, reason in [namespace["disposition"](stem, symbol)]}


def build_report(root=ROOT, *, extra_roots=(), overrides=None, snapshot=None, collected_nodeids=None):
    """Parent decisions map original IDs to status/reason/selector metadata.

    Retirement MUST include exact case source_sha256, reviewer, allowed surface.
    Snapshots contain explicit claims, not bare CASE_MAP membership: blocked
    xfail exports and sparse/nonrestored CASE_MAP entries cannot establish status.
    """
    root = Path(root)
    nodes, sources, claims, suites, inputs, errors, warnings = {}, {}, {}, {}, [], [], []
    for path in ASSIGNED:
        sources[path] = fixture_corpus.frozen_source(path, root=root)
        for symbol, node in phase2_suites._case_nodes(sources[path]).items():
            nodes[identity(symbol, path)] = node
    roots = [Path(p) for p in extra_roots] + [root]
    for checkout in roots:
        for source in sorted((checkout / "maintenance").glob("*lane6*report.json")):
            rows, suite_rows = normalize_report(json.loads(source.read_text()))
            inputs.append({"path": str(source), "sha256": digest(source.read_bytes())})
            for key, row in rows:
                if key not in nodes:
                    errors.append("Unknown report case: " + key)
                    continue
                if key in claims and claims[key]["status"] != row["status"]:
                    warnings.append("Conflicting reports require current metadata/override: " + key)
                claims[key] = {**claims.get(key, {}), **row, "metadata_source": str(source)}
            for path, row in suite_rows:
                suites[path] = {**suites.get(path, {}), **row}
        for source in sorted((checkout / "tests/desktop_adapters").glob("lane6*.py")):
            values = literal_metadata(source)
            inputs.append({"path": str(source), "sha256": digest(source.read_bytes())})
            rows, _ = normalize_report({key.lower(): values.get(key, {}) for key in (
                "RETIRED_CASES", "DEFERRED_CASES", "PROPOSED_CASES")})
            for key, row in rows:
                if key in nodes:
                    claims[key] = {**claims.get(key, {}), **row, "metadata_source": str(source)}
            for path in ASSIGNED:
                if Path(path).stem not in values.get("SUITES", {}):
                    continue
                symbols = [key.split("::", 1)[1] for key in nodes if key.startswith(path + "::")]
                for key, row in pure_disposition(source, values, path, symbols).items():
                    claims[key] = {**claims.get(key, {}), **row, "metadata_source": str(source)}
    # Explicit current whole-suite finish reports replace historical metadata,
    # not lexicographically whichever filename happens to be last. These are
    # named assignment corrections, not a generic report approval heuristic.
    for filename in ("lane6-schedules-finish-report.json", "lane6-work-projection-report.json"):
        source = root / "maintenance" / filename
        if not source.is_file():
            continue
        data = json.loads(source.read_text())
        if filename == "lane6-work-projection-report.json":
            authority = data.get("authoritative_for", "")
            path = "tests/test_web_api_agents_loops.py"
            if not authority.startswith(path):
                errors.append("Unknown work-projection report authority")
                continue
            data = {**data, "path": path,
                    "selector": "tests/test_desktop_lane6_work_projection_finish.py"}
        rows, current_suites = normalize_report(data)
        for path, row in current_suites:
            for key in list(claims):
                if key.startswith(path + "::"):
                    del claims[key]
            suites[path] = {**suites.get(path, {}), **row}
        for key, row in rows:
            if key in nodes:
                claims[key] = {**row, "metadata_source": str(source)}
    # The new trajectory whole adapter supersedes invalid old HTTP retirements,
    # but source finder/search failures still block runtime qualification.
    source = root / "maintenance/lane6-trajectory-endpoint-report.json"
    if source.is_file():
        data = json.loads(source.read_text())
        path = data.get("source_path")
        if path == "tests/test_agent_trajectory.py" and data.get("whole_suite_exported"):
            suites[path] = {**suites.get(path, {}), "selector": data["selector"],
                            "selectors": [data["selector"]]}
            for key in nodes:
                if key.startswith(path + "::"):
                    endpoint = key.split("::", 1)[1].startswith("TestAgentTrajectoryAPI.")
                    blocked = endpoint and data.get("qualification_claim", "").startswith("Not qualified")
                    claims[key] = {"status": "deferred" if blocked else "restored",
                        "reason": ("TrajectoriesService lacks trajectories.agent finder and forwards "
                                   "incompatible search kwargs to AgentTrajectorySaver; whole exact "
                                   "wrapper exists but runtime source-owner fixes remain unproven.")
                                  if blocked else "Current whole frozen trajectory export",
                        "metadata_source": str(source)}
    if snapshot:
        stale = False
        for module in snapshot.get("modules", []):
            target = root / (module["module"].replace(".", "/") + ".py")
            if not target.is_file() or digest(target.read_bytes()) != module["sha256"]:
                errors.append("Stale loader snapshot: " + module["module"])
                stale = True
        for row in [] if stale else snapshot.get("claims", []):
            key = identity(row["original"])
            if key not in nodes:
                raise ValueError("Unknown snapshot case: " + row["original"])
            claims[key] = {**claims.get(key, {}), **row}
    decisions = {}
    for key, row in (overrides or {}).items():
        canonical = identity(key)
        if canonical not in nodes:
            raise ValueError("Unknown override case: " + key)
        decisions[canonical] = row
    entries = []
    for path in ASSIGNED:
        suite = suites.get(path, {})
        partition = {status: [] for status in STATUSES}
        for original, node in nodes.items():
            if not original.startswith(path + "::"):
                continue
            symbol = original.split("::", 1)[1]
            row = dict(claims.get(original, {}))
            if not row:
                if suite.get("status") == "restored" or suite.get("whole_suite") is True:
                    row = {"status": "restored", "metadata_source": "reported whole-suite complement"}
                else:
                    row = {"status": "deferred", "reason": "Explicit case metadata/current loader snapshot missing."}
                    errors.append("Unresolved source case: " + original)
            if row.get("status") == "retired" and (
                (path == "tests/test_agent_trajectory.py" and symbol.startswith("TestAgentTrajectoryAPI."))
                or original in MIXED):
                row.update(status="proposed", reason="Mixed retained behavior requires exact owner/service/assertion adaptation; removed identity/listener alone does not retire useful behavior.")
            row.update(decisions.get(original, {}))
            status = row.get("status")
            if status not in STATUSES:
                raise ValueError("Invalid disposition: " + original)
            case_hash = digest(ast.dump(node, include_attributes=False).encode())
            row.update(case=symbol, original=original, case_ast_sha256=case_hash)
            if status == "retired" and (
                row.get("source_sha256") != case_hash
                or row.get("reviewer", row.get("authority")) != phase2_suites.STEP6_RETIREMENT_REVIEWER
                or row.get("surface") not in phase2_suites.REMOVED_STEP6_SURFACES
                or not row.get("reason")):
                errors.append("Unbound retirement AST/reviewer/surface: " + original)
            if status == "retired":
                row["reviewer"] = row.get("reviewer", row.get("authority"))
            if status in {"deferred", "proposed"} and not row.get("reason"):
                row["reason"] = suite.get("blocked_on") or "Concrete missing method/feature or semantic proposal metadata required."
                errors.append("Missing concrete reason: " + original)
            partition[status].append(row)
        status = "deferred" if partition["deferred"] or partition["proposed"] else (
            "restored" if partition["restored"] else "retired")
        selector = suite.get("selector", suite.get("test_file"))
        entries.append({"path": path, "status": status, "selector": selector,
            "selectors": suite.get("selectors", [selector] if selector else []),
            "mode": "frozen-case-adapter" if partition["retired"] else "frozen-adapter",
            "source_sha256": digest(sources[path]),
            "restored_cases": [r["case"] for r in partition["restored"]],
            "case_retirements": [{key: r.get(key) for key in (
                "case", "source_sha256", "reviewer", "surface", "reason")} for r in partition["retired"]],
            "case_deferrals": partition["deferred"], "case_proposals": partition["proposed"],
            "cases": [r for status in STATUSES for r in partition[status]],
            "counts": {status: len(rows) for status, rows in partition.items()},
            "substitutions": suite.get("substitutions", [])})
    return {"schema_version": 1, "candidate_only": True,
        "assignment": {"count": len(ASSIGNED), "paths": list(ASSIGNED),
                       "sha256": digest(("\n".join(ASSIGNED) + "\n").encode())},
        "suite_dispositions": dict(Counter(row["status"] for row in entries)),
        "source_case_definitions": {"total": len(nodes), **{
            status: sum(row["counts"][status] for row in entries) for status in STATUSES}},
        "parameter_expanded_collected": None if collected_nodeids is None else {
            "count": len(collected_nodeids), "nodeids": collected_nodeids,
            "evidence": "Supplied actual collection, not passing tests; may include supplements/blocked cases."},
        "entries": entries, "inputs": inputs, "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)), "limitations": [
            "No runtime passing claim or guessed param expansion.",
            "Retirement bindings require explicit parent review, never generated approval.",
            "Rerun after incoming finish reports; unresolved metadata blocks enrollment."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--extra-root", type=Path, action="append", default=[])
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--collected-nodeids", type=Path)
    args = parser.parse_args()

    def read(path):
        return json.loads(path.read_text()) if path else None

    report = build_report(args.root, extra_roots=args.extra_root,
                          overrides=read(args.overrides), snapshot=read(args.snapshot),
                          collected_nodeids=read(args.collected_nodeids))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
