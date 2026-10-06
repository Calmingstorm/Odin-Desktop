#!/usr/bin/env python3
"""Generate exact lane6 accounting/lineage candidates, never mutate the workspace.

Generated candidates must be integrated with context-checked apply_patch. Passing
tests, corpus enrollment and independent approval remain separate evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from scripts.maintenance import inventory

ROOT = Path(__file__).resolve().parents[2]


def lineage_candidate(root, decisions):
    """Explicit per-path contracts only; preserve existing review/provenance."""
    baseline = inventory.baseline_blobs(root)
    data = inventory.ledger(root)
    rows = {entry["path"]: entry for entry in data["entries"]}
    seen = set()
    for decision in decisions:
        path = inventory.safe_path(decision["path"])
        if path in seen:
            raise ValueError(f"Duplicate explicit lineage decision: {path}")
        seen.add(path)
        before = baseline.get(path, b"")
        if path.startswith("tests/") and path in baseline:
            raise ValueError(f"Frozen behavior source cannot be recaptured: {path}")
        if not inventory.regular_file(root, path):
            raise ValueError(f"Missing regular candidate: {path}")
        after = (root / path).read_bytes()
        row = copy.deepcopy(rows.get(path, {}))
        if not row:
            row = {
                "path": path, "origin": "Odin to Desktop" if path in baseline
                else "Desktop foundation", "source_commit": inventory.BASELINE,
                "owner": "Odin", "reviewer": "pending Claude", "state": "pending",
                "approval": "pending independent review",
                "evidence": "Exact bytes only; not execution, qualification or approval",
                "destination_commit": "pending parent commit/PR",
                "backport": "Desktop boundary; applicability review pending",
                "date": "2026-10-06", "severity": "safety review required",
                "review_deadline": "before lane6 PR merge",
                "next_revisit": "next upstream release or weekly review",
                "release_status": "unreleased Phase 2", "dependency_assets": "see manifest",
            }
        for key in ("reason", "contract", "invariant"):
            value = decision.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Missing concrete {key}: {path}")
            old = row.get(key)
            row[key] = f"{old} | Lane6: {value}" if old and value not in old else value
        tests = sorted(set(row.get("tests", [])) | set(decision["tests"]))
        if not tests or any(not inventory.regular_file(root, test) for test in tests):
            raise ValueError(f"Missing named evidence: {path}")
        row.update(before_sha256=hashlib.sha256(before).hexdigest(),
                   after_sha256=hashlib.sha256(after).hexdigest(),
                   patch=inventory.byte_patch(before, after), tests=tests,
                   state="pending", reviewer="pending Claude",
                   approval="pending independent review")
        row["test_sha256"] = {
            test: hashlib.sha256((root / test).read_bytes()).hexdigest() for test in tests
        }
        rows[path] = row
    # Existing explicitly named evidence references follow only the named changed
    # tests. This does not recapture unrelated source or expand qualification.
    changed_tests = {path for path in seen if path.startswith("tests/")}
    for row in rows.values():
        for test in changed_tests & set(row["tests"]):
            row["test_sha256"][test] = hashlib.sha256((root / test).read_bytes()).hexdigest()
    data["entries"] = [rows[path] for path in sorted(rows)]
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    decisions = json.loads(args.plan.read_text())["entries"]
    candidate = lineage_candidate(ROOT, decisions)
    args.output.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
    print(f"Generated pending lineage for {len(decisions)} explicit paths: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
