#!/usr/bin/env python3
"""Report Phase 2 exit obligations, not passing-suite or release approval.

Offline checkers supply byte/membership validation. A passing qualification run
does not close pending D19 approval or missing parity evidence. A deferred suite
closes only as a named deferral: Aaron's decision 3 (2026-10-06).
CI deliberately uses report mode: this change provides no enforcing mode.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITES = "maintenance/phase2-suite-map.json"
D19 = "maintenance/phase2-d19-closure.json"
PARITY = "maintenance/fresh-profile-parity.json"
FINAL_SUITE_STATUSES = frozenset({"restored", "retired"})
# Aaron, decision 3 (2026-10-06): the remaining inherited-suite restorations end
# Phase 2 as deferrals. A deferral is final only when it names its blocker.
NAMED_DEFERRAL_AUTHORITY = ("Aaron decision 3, 2026-10-06: remaining inherited-suite "
                            "restorations are named deferrals at Phase 2 exit")
# A proven internal guard is final: d19.py requires its Claude review, spy proof,
# tests and exact current targets, and any drift fails that validator, which
# blocks the exit report as an integrity error.
FINAL_D19_STATUSES = frozenset({"removed_by_restored_behaviour", "approved_mechanical",
                                "approved_behavioural", "internal_unreachable_guard"})


def _json(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def _tool(name: str):
    """Only repository checker code, never a path supplied by input metadata."""
    path = ROOT / "scripts/maintenance" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"desktop_closure_{name}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Unavailable checker: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _named_deferral(row) -> bool:
    blocker = row.get("blocked_on")
    return row.get("status") == "deferred" and isinstance(blocker, str) and bool(blocker.strip())


def _final_suite(row) -> bool:
    status = row.get("status")
    return (isinstance(status, str) and status in FINAL_SUITE_STATUSES) or _named_deferral(row)


def summarize(mapping, suite_check, wording, wording_check, parity_check):
    """Pure aggregation for temporary-data tests; validation is not approval."""
    errors, blockers = [], []
    rows = mapping.get("entries", []) if isinstance(mapping, dict) else []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        rows = []
        errors.append("Suite map entries must be a list of objects")
    for label, check in (("suites", suite_check), ("D19", wording_check),
                         ("parity", parity_check)):
        if not isinstance(check, dict) or not isinstance(check.get("errors"), list):
            errors.append(f"{label}: unavailable checker result")
        else:
            errors.extend(f"{label}: {error}" for error in check["errors"])
    open_suites = [row for row in rows if not _final_suite(row)]
    deferrals = [{"kind": "suite", "id": row.get("path", "<invalid>"),
                  "reason": row["blocked_on"].strip()} for row in rows if _named_deferral(row)]
    for row in open_suites:
        blockers.append({"kind": "suite", "id": row.get("path", "<invalid>"),
                         "status": row.get("status", "missing"),
                         "reason": row.get("blocked_on") or "No final suite disposition"})
    wording_rows = wording.get("rows", []) if isinstance(wording, dict) else []
    if not isinstance(wording_rows, list) or any(not isinstance(row, dict)
                                               for row in wording_rows):
        wording_rows = []
        errors.append("D19 rows must be a list of objects")
    if wording is None:
        blockers.append({"kind": "D19_inventory", "id": D19, "status": "missing",
                         "reason": "Bridge lane closure inventory has not landed"})
    open_wording = [row for row in wording_rows if not isinstance(row.get("status"), str)
                    or row["status"] not in FINAL_D19_STATUSES]
    for row in open_wording:
        blockers.append({"kind": "D19", "id": row.get("id", "<invalid>"),
                         "status": row.get("status", "missing"),
                         "reason": row.get("pending_reference") or
                         row.get("behaviour_change") or "No final D19 approval/restoration"})
    if not isinstance(parity_check, dict) or parity_check.get("valid") is not True:
        blockers.append({"kind": "parity", "id": PARITY, "status": "unproved",
                         "reason": "Fresh-profile parity proof absent, stale or invalid"})
    if errors:
        blockers.append({"kind": "integrity", "id": "offline-checkers",
                         "status": "invalid", "reason": "Closure data failed validation"})
    return {"schema_version": 1, "mode": "report", "ready": not blockers,
            "proof_limit": ("Exit-obligation inventory only; not qualification, review "
                            "or release approval"),
            "suites": {"total": len(rows),
                       "statuses": dict(sorted(Counter(str(row.get("status", "missing"))
                                                        for row in rows).items())),
                       "without_final_disposition": len(open_suites),
                       "named_deferrals": len(deferrals)},
            "deferral_authority": NAMED_DEFERRAL_AUTHORITY,
            "D19": {"inventory": "missing" if wording is None else "present",
                    "rows": len(wording_rows), "open": len(open_wording)},
            "parity": {"valid": isinstance(parity_check, dict)
                       and parity_check.get("valid") is True},
            "errors": errors, "blockers": blockers, "deferrals": deferrals}


def report(root: Path):
    try:
        mapping = _json(root / SUITES)
        errors, counts = _tool("phase2_suites")._evaluate(root)
        suite_check = {"errors": errors, "counts": counts}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        mapping, suite_check = {}, {"errors": [str(exc)]}
    if not (root / D19).exists():
        wording, wording_check = None, {"errors": []}
    else:
        try:
            wording = _json(root / D19)
            checker = _tool("d19")
            rows, findings = checker.load_source(root)
            wording_check = checker.validate(wording, rows, findings, root)
        except (OSError, ValueError, SyntaxError, TypeError, KeyError) as exc:
            wording, wording_check = {}, {"errors": [str(exc)]}
    try:
        parity_check = _tool("fresh_profile_parity").check(root)
    except (OSError, ValueError, SyntaxError, TypeError, KeyError) as exc:
        parity_check = {"valid": False, "errors": [str(exc)]}
    return summarize(mapping, suite_check, wording, wording_check, parity_check)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["report"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--details", action="store_true",
                        help="Include every blocking row and every named deferral")
    args = parser.parse_args(argv)
    result = report(args.root)
    if not args.details:
        result["blocker_counts"] = dict(sorted(Counter(row["kind"] for row in
                                                       result.pop("blockers")).items()))
        result.pop("deferrals", None)  # Counted in suites.named_deferrals.
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0  # CI inventory only. Enforcing Phase 2 exit is a separate change.


if __name__ == "__main__":
    raise SystemExit(main())
