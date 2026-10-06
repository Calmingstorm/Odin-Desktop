#!/usr/bin/env python3
"""Record/check exact frozen part6 case dispositions, not passing or approval."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.maintenance.fixture_corpus import dump, frozen_source

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = "maintenance/phase2-step8-part6-cases.json"
COLLECTION = "maintenance/phase2-step8-part6-collection.json"
SUITES = (
    "test_generated_api_reference", "test_github_webhook", "test_gitlab_webhook",
    "test_native_monitoring_removal", "test_self_audit_fixes",
)
CITATION = "Claude, desktop-lane5-step7-suites.md Task1 (step8 part6)"


def definitions(source):
    result = {}
    for node in ast.parse(source).body:
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")):
            result[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if getattr(child, "name", "").startswith("test_"):
                    result[f"{node.name}.{child.name}"] = child
    return result


def expansion(node):
    count = 1
    for decorator in node.decorator_list:
        if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "parametrize"):
            values = decorator.args[1]
            if not isinstance(values, (ast.List, ast.Tuple)):
                raise ValueError("Unaccounted parameter expression")
            count *= len(values.elts)
    return count


def parameter_rows(node, disposition):
    rows = []
    for decorator in node.decorator_list:
        if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "parametrize"):
            for index, value in enumerate(decorator.args[1].elts):
                text = ast.unparse(value)
                rows.append({"index": index, "frozen_parameter_ast": dump(value),
                             "frozen_expression": text,
                             "parameter_sha256": hashlib.sha256(dump(value).encode()).hexdigest(),
                             "disposition": disposition["disposition"],
                             "reason": (f"Removed REST/RBAC row: {text}" if
                                        disposition["disposition"] == "retired" else
                                        f"Retained mixed inventory row: {text}; "
                                        "blocked by the function's named projection.")})
    return rows or [{"index": 0, "frozen_parameter_ast": None,
                     "disposition": disposition["disposition"],
                     "reason": "Exact non-parameterized case; see case reason."}]


def decision(stem, name):
    from tests.desktop_adapters.step8_part6 import CASE_MAP, export
    from tests.desktop_adapters.webhook_cases import SELECTIONS

    # Register unchanged retained bodies solely to obtain their exact aliases.
    if not CASE_MAP:
        export({"__name__": "part6_accounting_projection"})
    original = f"tests/{stem}.py::{name.replace('.', '::')}"
    if original in CASE_MAP:
        return {"disposition": "restored", "mode": "exact-frozen",
                "selectors": [CASE_MAP[original]],
                "reason": ("Unchanged frozen body/decorators/data on retained real scheduler, "
                           "knowledge or config implementation.")}
    if stem == "test_github_webhook":
        if name.replace('.', '::') in SELECTIONS[stem]:
            cls, method = name.split('.')
            return {"disposition": "restored", "mode": "exact-frozen",
                    "selectors": [f"tests/test_desktop_webhook_adapters.py::"
                                  f"TestWebhook_{stem}_{cls}::{method}"],
                    "reason": ("Retain step7 exact selected frozen assertion corpus with sealed "
                               "real ingress constructor; no new substitutions.")}
        if name.startswith("TestGitHubTriggerMatching."):
            blocker = ("GitHub schedule-specific callback observation adapter missing; mutable "
                       "global callback cannot fabricate durable dispatch equivalence.")
        else:
            return retirement("discord", "Exact Discord default/source channel routing or "
                              "channel_id schema assertion; schedule conversation delivery is "
                              "not that removed surface.")
    elif stem == "test_gitlab_webhook":
        if name.startswith(("TestGitLabChannelRouting.", "TestWebhookConfigGitLab.")):
            return retirement("discord", "Exact Discord channel override/default/schema assertion; "
                              "not retirement of GitLab authentication, normalization or "
                              "ingress configuration.")
        blocker = ("GitLab ingress not implemented: retain shared-token fail-close, original "
                   "event normalization/truncation/invalid JSON and dispatch/configuration "
                   "obligations; missing endpoint is not removal authority.")
    elif stem == "test_native_monitoring_removal":
        if name == "test_startup_wires_component_health_without_a_metrics_collector":
            return retirement("discord", "This case asserts only the removed Discord startup "
                              "component and gateway latency/is_ready wiring, not general "
                              "component health.")
        blockers = {
            "test_removed_settings_are_inert_and_neighbors_survive": (
                "Mixed migration: removed Grafana settings inertness and retained webhook "
                "enabled neighbor require exact projection; channel_id is removed but whole "
                "migration case cannot retire."),
            "test_scheduling_catalog_no_longer_advertises_removed_trigger": (
                "Retained schedule catalogue/skill exclusions mixed with removed HTTP "
                "AUTH_PUBLIC_PREFIXES; exact unchanged catalogue projection missing."),
            "test_removed_routes_absent_but_component_health_remains": (
                "Mixed removed metrics/Grafana HTTP routes and retained healthy readiness "
                "component require exact runtime-health/ingress exclusion projection; HTTP "
                "response spelling alone cannot retire component health."),
        }
        blocker = blockers[name]
    elif stem == "test_self_audit_fixes":
        if name.startswith("TestSetupCompleteGate."):
            return retirement("http-listener-route", "Exact POST /api/setup/complete 409/error "
                              "wording and Discord setup payload of removed web wizard; durable "
                              "installation gate remains covered separately and is not retired "
                              "here.")
        if name.endswith("test_verify_shared_secret_accepts_matching_token"):
            blocker = ("Frozen literal secret '[REDACTED]' differs from asserted 'correct-secret'; "
                       "no substitution permitted. Also legacy HealthServer verifier has no "
                       "exact per-trigger projection.")
        elif name.startswith("TestSharedSecretWebhookFailClose."):
            blocker = ("Retained generic shared-token fail-close/empty-header semantics need "
                       "exact per-trigger verifier projection; do not retire authentication "
                       "with legacy HealthServer.")
        else:
            blocker = ("Frozen relative ToolsConfig default differs from Desktop profile-owned "
                       "absolute path default; retained config obligation needs reviewed "
                       "profile projection, no expected-value rewrite.")
    else:
        retained = {
            "test_every_purpose_and_owner_come_from_the_registered_handler": (
                "Mixed removed REST handler ownership inventory with retained purpose/source-link "
                "introspection provenance; Desktop protocol/service generator projection missing, "
                "not a blanket documentation retirement."),
            "test_decorated_gate_and_missing_docstring_without_execution": (
                "Mixed removed local-admin route gate introspection with retained missing/first-"
                "doc-line and no-handler-execution behavior; exact split/projection missing."),
            "test_committed_api_reference_is_byte_identical": (
                "Retained committed generator drift invariant; legacy generator imports removed "
                "REST implementation, Desktop reference inventory projection missing."),
            "test_generation_does_not_load_config_start_services_or_read_ui": (
                "Retained offline/no-I/O generator invariant mixed with removed 231 REST count; "
                "no silent 231-to-Desktop data substitution."),
            "test_cli_is_offline_and_works_outside_repo_without_git": (
                "Retained offline CLI check outside repo/no Git; legacy generator imports removed "
                "web API, Desktop reference generator missing."),
            "test_check_fails_for_missing_and_stale_files_without_writes": (
                "Retained missing/stale drift check and write semantics; generator module cannot "
                "import removed web API, standalone generator projection missing."),
            "test_non_rest_registration_conditions_and_order": (
                "Mixed retained webhook ingress inventory with removed health HTTP/UI/WebSocket "
                "registration/order; all seven frozen parameter rows retained pending exact "
                "split/projection."),
        }
        if name not in retained:
            return retirement("rest-rbac", "Exact removed 231 REST registration/handler ownership "
                              "or multi-user/admin/local-admin middleware policy characterization; "
                              "not retirement of offline generation/drift semantics.")
        blocker = retained[name]
    owners = {
        "test_generated_api_reference": "Maintenance offline API-reference generator owner",
        "test_github_webhook": "Phase2 GitHub schedule dispatch/callback owner",
        "test_gitlab_webhook": "Phase2 GitLab authentication/event/ingress configuration owner",
        "test_native_monitoring_removal": "Phase2 profile migration/catalogue/runtime health owner",
        "test_self_audit_fixes": ("Phase2 profile-owned configuration owner"
                                  if name.startswith("TestConfigSchemaFields.") else
                                  "Phase2 generic webhook authentication owner; "
                                  "frozen corpus owner"),
    }
    return {"disposition": "deferred", "owner": owners[stem],
            "blocker": blocker, "reason": blocker}


def retirement(category, reason):
    return {"disposition": "retired", "category": category, "reason": reason,
            "citation": CITATION, "independent_review": "pending"}


def build(root=ROOT):
    suites = []
    for stem in SUITES:
        path = f"tests/{stem}.py"
        source = frozen_source(path, root=root)
        cases = []
        for name, node in definitions(source).items():
            disposition = decision(stem, name)
            cases.append({"case": name, "original": f"{path}::{name.replace('.', '::')}",
                          "definition_sha256": hashlib.sha256(dump(node).encode()).hexdigest(),
                          "expanded_cases": expansion(node),
                          "expanded_rows": parameter_rows(node, disposition),
                          **disposition})
        suites.append({"path": path, "inherited_sha256": hashlib.sha256(source).hexdigest(),
                       "status": "deferred", "whole_restore": False, "cases": cases})
    return {"schema_version": 1, "suites": suites, "independent_review": "pending",
            "runtime_pass_claim": False, "source_data_substitutions": [],
            "disposition_authority": CITATION}


def validate(root=ROOT, data=None):
    expected = build(root)
    actual = json.loads((root / OUTPUT).read_text()) if data is None else data
    errors = ([] if actual == expected else [
        "Exact frozen case disposition/identity differs from authorized record"])
    rows = [case for suite in expected["suites"] for case in suite["cases"]]
    counts = Counter(row["disposition"] for row in rows)
    expanded = Counter()
    for row in rows:
        expanded[row["disposition"]] += row["expanded_cases"]
    if len(rows) != 83 or sum(expanded.values()) != 108:
        errors.append("Original five-suite population must be 83 functions /108 expanded cases")
    mapping = json.loads((root / "maintenance/phase2-suite-map.json").read_text())
    if any(row["status"] != "deferred" for row in mapping["entries"]
           if row["path"] in {suite["path"] for suite in expected["suites"]}):
        errors.append("Mixed suites cannot claim whole-suite restoration or retirement")
    groups = json.loads((root / "maintenance/qualification-plan.json").read_text())["groups"]
    selected = {selector.split('::')[0] for group in groups for selector in group["files"]}
    for row in rows:
        if row["disposition"] == "restored" and any(s.split('::')[0] not in selected
                                                     for s in row["selectors"]):
            errors.append(f"Unqualified retained alias: {row['original']}")
    collection_path = root / COLLECTION
    if collection_path.exists():
        collection = json.loads(collection_path.read_text())["cases"]
        for row in rows:
            if row["disposition"] == "restored" and not any(
                    item["original"] == row["original"]
                    and item["executable"] in row["selectors"] for item in collection):
                errors.append(f"Missing actual frozen collection alias: {row['original']}")
        case_accounting = json.loads((root / "maintenance/case-accounting.json").read_text())
        if case_accounting.get("phase2_step8_part6") != {
                "dispositions": OUTPUT, "collection": COLLECTION,
                "collection_sha256": hashlib.sha256(collection_path.read_bytes()).hexdigest(),
                "functions": 83, "expanded_cases": 108, "independent_review": "pending"}:
            errors.append("Existing case accounting does not bind the exact part6 collection")
    return errors, {"suites": 5, "functions": len(rows), "expanded_cases": sum(expanded.values()),
                    "function_dispositions": dict(counts), "expanded_dispositions": dict(expanded),
                    "runtime_pass_claim": False, "independent_review": "pending"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--record-collection", action="store_true")
    args = parser.parse_args(argv)
    if args.record:
        data = build()
        (ROOT / OUTPUT).write_text(json.dumps(data, indent=2) + "\n")
        path = ROOT / "maintenance/phase2-suite-map.json"
        mapping = json.loads(path.read_text())
        for suite in data["suites"]:
            row = next(row for row in mapping["entries"] if row["path"] == suite["path"])
            row["blocked_on"] = (
                "Exact final part6 per-case dispositions and named blockers: " + OUTPUT +
                "; mixed suite remains deferred, no whole-suite restoration, "
                "independent review pending. " + " ".join(
                    sorted({case["blocker"] for case in suite["cases"]
                            if case["disposition"] == "deferred"})))
        # Preserve the existing compact one-row-per-line map, not a 5000-line
        # formatting-only rewrite. This official writer changes only five rows.
        entries = mapping.pop("entries")
        prefix = json.dumps(mapping, indent=2)[:-2]
        text = prefix + ',\n  "entries": [\n'
        text += ",\n".join("    " + json.dumps(row, separators=(",", ":")) for row in entries)
        path.write_text(text + "\n  ]\n}\n")
    if args.record_collection:
        collection = json.loads((ROOT / ".test-state/qualification-collected.json").read_text())
        restored = {case["original"] for suite in build()["suites"] for case in suite["cases"]
                    if case["disposition"] == "restored"}
        collection["cases"] = [case for case in collection["cases"]
                               if case["original"] in restored]
        if {case["original"] for case in collection["cases"]} != restored:
            raise ValueError("Actual isolated collection missing retained part6 aliases")
        path = ROOT / COLLECTION
        path.write_text(json.dumps(collection, indent=2) + "\n")
        case_path = ROOT / "maintenance/case-accounting.json"
        cases = json.loads(case_path.read_text())
        cases["phase2_step8_part6"] = {
            "dispositions": OUTPUT, "collection": COLLECTION,
            "collection_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "functions": 83, "expanded_cases": 108, "independent_review": "pending"}
        case_path.write_text(json.dumps(cases, indent=2) + "\n")
    errors, counts = validate()
    print(json.dumps({"errors": errors, "counts": counts}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
