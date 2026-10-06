#!/usr/bin/env python3
"""Conservative D19 operational inventory gate, not behavioural qualification."""
from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE_SHA = "16e35e8f370661a2baf8e7030a27919b3e658b3b"
SOURCE_TABLE = "maintenance/pr2-model-facing-string-approvals.md"
STATUSES = {
    "removed_by_restored_behaviour", "pending_restoration",
    "proposed_mechanical", "proposed_behavioural", "approved_behavioural",
    "internal_unreachable_guard",
}
PENDING_REFERENCES = {
    "PR #37 (6B)", "PR #42 (step 7)", "PR #48 (media publication)",
    "PR #62 (skill delivery, lane 3)", "PR #61 (step 8 closure, lane 2)",
    "P3.3", "P3.5", "unassigned", "D17 restoration (next bridge task)",
}
HEALTH_RESTORATION_TEST = (
    "tests/test_desktop_health_delivery.py::"
    "test_health_delivery_ready_after_startup_and_real_guarded_turn"
)


def parse_rows(text, *, source_paths):
    """Preserve exact cells, counting rows not fragments, and resolve aliases."""
    rows = []
    in_section = internal = False
    internal_none = False
    section = None
    previous = None
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            match = re.match(r"## (4)\.", line)
            section = int(match[1]) if match else None
            in_section = section == 4
            internal = False
            internal_none = False
            continue
        if not in_section:
            continue
        if line.startswith("### "):
            internal = line.startswith("### Internal control/storage")
            internal_none = False
        if internal and "**NONE**" in line and not line.startswith("|"):
            internal_none = True
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(cells) < 3 or cells[0].startswith(("---", "Source", "Current source")):
            continue
        location = cells[0]
        paths = re.findall(r"`([^`]+\.(?:py|md))`", location)
        if paths:
            if paths[0].startswith(("src/", "docs/")):
                previous = paths[0]
            else:
                matches = [p for p in source_paths if p.endswith("/" + paths[0])]
                if len(matches) != 1:
                    raise ValueError(f"Ambiguous source alias {paths[0]!r} at {number}")
                previous = matches[0]
        elif not location.startswith("Same "):
            raise ValueError(f"Unresolved source selector at {number}")
        if not internal and (len(cells) != 4 or not re.search(r"\bNONE\b", cells[3])):
            continue
        if internal and not internal_none:
            raise ValueError("Internal NONE table lacks explicit NONE context")
        fragments = re.findall(r"`([^`]+)`", cells[2])
        if not previous or not fragments:
            raise ValueError(f"Unresolved operational row at {number}")
        rows.append({"id": f"D19-{len(rows)+1:03d}", "source_location": location,
                     "exact_string": cells[2], "strings": fragments,
                     "source_path": previous, "source_line": number,
                     "scope": "section4"})
    if not rows:
        raise ValueError("No section-4 NONE records")
    keys = [(row["source_location"], row["exact_string"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate exact source-location/string key in source inventory")
    return rows


def folded_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = folded_string(node.left), folded_string(node.right)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        parts = []
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                conversion = "!" + chr(part.conversion) if part.conversion != -1 else ""
                spec = ":" + (folded_string(part.format_spec) or "") if part.format_spec else ""
                parts.append("{" + ast.unparse(part.value) + conversion + spec + "}")
            else:
                value = folded_string(part)
                if value is None:
                    return None
                parts.append(value)
        return "".join(parts)
    return None


def scan_source(source, path):
    """Only post-terminator code is inactive; raising diagnostics stay active."""
    findings = []

    def visit(node, selector="", inactive=False, parent=None):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            selector = f"{selector}.{node.name}" if selector else node.name
        folded = folded_string(node)
        value = folded if folded is not None and folded_string(parent) is None else None
        if isinstance(node, ast.Attribute):
            value = ast.unparse(node)
        if value is not None:
            findings.append({"path": path, "selector": selector or "<module>", "line": node.lineno,
                             "value": value, "reachability": "inactive" if inactive else "active",
                             "reason": ("after unconditional function terminator" if inactive
                                        else "not structurally proven unreachable")})
        for field, child in ast.iter_fields(node):
            if isinstance(child, list):
                dead = inactive
                for item in child:
                    if isinstance(item, ast.AST):
                        visit(item, selector, dead, node)
                        if (field == "body"
                                and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                                and isinstance(item, (ast.Raise, ast.Return))):
                            dead = True
            elif isinstance(child, ast.AST):
                visit(child, selector, inactive, node)

    visit(ast.parse(source, filename=path))
    return findings


def _matches(fragment, value):
    # The audit uses descriptive placeholders, not the actual AST expression:
    # {name} can be {tool_input['name']}, and {staging_error} can be the retained
    # delivery constant. Preserve surrounding bytes while matching that slot.
    slots = re.split(r"(\{[^{}]+\})", fragment)
    pattern = "".join(r"\{[^{}]+\}" if part.startswith("{") and part.endswith("}")
                      else re.escape(part) for part in slots)
    return re.search(pattern, value) is not None


def observe(row, findings):
    observations = []
    for finding in findings:
        matched = [s for s in row["strings"] if _matches(s, finding["value"])]
        if matched:
            observations.append({**finding, "matched_strings": matched})
    return observations or [{"path": row["source_path"], "selector": "<absent>",
                            "reachability": "absent",
                            "reason": "no folded AST match anywhere in src"}]


def test_reference_exists(root, nodeid):
    if not isinstance(nodeid, str):
        return False
    parts = nodeid.split("::")
    path = Path(parts[0])
    if (path.is_absolute() or ".." in path.parts or not parts[0].startswith("tests/")
            or path.suffix != ".py" or len(parts) < 2):
        return False
    candidate = root / path
    # A syntactically local nodeid must not resolve through a foreign symlink.
    if not candidate.resolve().is_relative_to(root.resolve() / "tests"):
        return False
    try:
        scope = ast.parse(candidate.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    for name in parts[1:]:
        name = name.split("[", 1)[0]
        matches = [n for n in getattr(scope, "body", [])
                   if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == name]
        if len(matches) != 1:
            return False
        scope = matches[0]
    return (isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
            and scope.name.startswith("test_"))


def load_source(root):
    paths = sorted(p.relative_to(root).as_posix() for p in (root / "src").rglob("*.py"))
    rows = parse_rows((root / SOURCE_TABLE).read_text(encoding="utf-8"), source_paths=paths)
    findings = []
    for path in paths:
        findings.extend(scan_source((root / path).read_text(encoding="utf-8"), path))
    return rows, findings


def validate(inventory, rows, findings, root):
    errors = []
    if not isinstance(inventory, dict):
        return {"errors": ["Inventory must be an object"], "counts": {}}
    if inventory.get("version") != 1 or inventory.get("baseline_sha") != BASELINE_SHA:
        errors.append("Unsupported schema or baseline SHA")
    if inventory.get("source_table") != {"path": SOURCE_TABLE, "section": 4}:
        errors.append("Source table must name section 4 exactly")
    records = inventory.get("rows", [])
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        return {"errors": errors + ["rows must be a list of objects"], "counts": {}}
    expected = {r["id"]: r for r in rows}
    identifiers = [r.get("id") for r in records]
    if any(not isinstance(ident, str) for ident in identifiers):
        return {"errors": errors + ["Row identifiers must be strings"], "counts": {}}
    if len(identifiers) != len(set(identifiers)):
        errors.append("Duplicate row records")
    if set(identifiers) != set(expected):
        errors.append("Missing/extraneous row records")
    for record in records:
        ident = record.get("id")
        if ident not in expected:
            continue
        row = expected[ident]
        for field in ("source_location", "exact_string", "strings",
                      "source_path", "source_line", "scope"):
            if record.get(field) != row[field]:
                errors.append(f"{ident}: exact {field} differs from source")
        status = record.get("status")
        if not isinstance(status, str) or status not in STATUSES:
            errors.append(f"{ident}: invalid disposition")
        observations = observe(row, findings)
        def projection(items):
            return sorted((str(i.get("path")), str(i.get("selector")),
                           str(i.get("reachability"))) for i in items)
        declared = record.get("observations")
        if declared is not None and (not isinstance(declared, list)
                or any(not isinstance(i, dict) for i in declared)
                or projection(declared) != projection(observations)):
            errors.append(f"{ident}: observations differ from conservative source scan")
        evidence = record.get("evidence_tests", [])
        if (not isinstance(evidence, list)
                or any(not test_reference_exists(root, test) for test in evidence)):
            errors.append(f"{ident}: invalid test reference")
        # #69 restores the live projection, not the legitimate not-ready and
        # uncomposed-owner diagnostics. Their retained literals are not a fence.
        health_restored = ident == "D19-049"
        if health_restored and (
                status != "removed_by_restored_behaviour"
                or record.get("restoration_kind") != "composed_delivery_health"
                or evidence != [HEALTH_RESTORATION_TEST]):
            errors.append(f"{ident}: require #69 composed delivery health restoration "
                          "and its exact guarded-turn evidence")
        if status == "removed_by_restored_behaviour":
            if not evidence:
                errors.append(f"{ident}: restoration requires real test nodeids")
            if health_restored:
                if {(i["path"], i["selector"]) for i in observations} != {
                        ("src/health/checker.py", "check_delivery")}:
                    errors.append(f"{ident}: health diagnostics moved or gained unproved callers")
            elif any(i["reachability"] == "active" for i in observations):
                errors.append(f"{ident}: removed claim has present active AST matches")
        elif status == "pending_restoration":
            if not record.get("owner") or not record.get("pending_reference"):
                errors.append(f"{ident}: pending needs owner and pending_reference")
            reference = record.get("pending_reference")
            if not isinstance(reference, str) or reference not in PENDING_REFERENCES:
                errors.append(f"{ident}: pending reference must name "
                              "an existing PR/phase or unassigned")
            if reference == "unassigned" and record.get("owner") != "unassigned":
                errors.append(f"{ident}: unassigned pending row must not invent an owner")
            # Recompute from current source, not the recorded observation. A
            # merged restoration must force a disposition/evidence update even
            # if the diagnostic survives only after an unconditional terminator.
            fragment_paths = record.get("pending_fragment_paths", {})
            if (not isinstance(fragment_paths, dict)
                    or any(fragment not in row["strings"] for fragment in fragment_paths)
                    or any(not isinstance(paths, list) or not paths
                           or any(not isinstance(path, str) or not path.startswith("src/")
                                  or ".." in Path(path).parts or not path.endswith(".py")
                                  for path in paths) for paths in fragment_paths.values())):
                errors.append(f"{ident}: invalid pending fragment source paths")
                fragment_paths = {}
            for fragment in row["strings"]:
                for path in fragment_paths.get(fragment, [row["source_path"]]):
                    if not any(i["path"] == path and i["reachability"] == "active"
                               and fragment in i.get("matched_strings", []) for i in observations):
                        errors.append(f"{ident}: pending string no longer has an active AST match; "
                                      "update the disposition and evidence")
        elif status == "internal_unreachable_guard":
            if record.get("reviewer") != "Claude" or not record.get("guard_proof") or not evidence:
                errors.append(f"{ident}: internal guard requires "
                              "Claude reviewer, spy proof and tests")
            targets = record.get("guard_targets")
            if (not isinstance(targets, list) or not targets
                    or any(not isinstance(t, dict)
                           or not isinstance(t.get("path"), str)
                           or not isinstance(t.get("selector"), str) for t in targets)):
                errors.append(f"{ident}: internal guard requires source path/selector targets")
            else:
                declared_targets = {(t["path"], t["selector"]) for t in targets}
                current_targets = {(i["path"], i["selector"]) for i in observations
                                   if i["reachability"] != "absent"}
                if not current_targets or declared_targets != current_targets:
                    errors.append(f"{ident}: internal guard moved/disappeared "
                                  "or has unproved source targets")
        elif status == "proposed_mechanical":
            if (not record.get("odin_string") or not record.get("desktop_string")
                    or record.get("reviewer") != "Claude"):
                errors.append(f"{ident}: mechanical needs exact strings and Claude reviewer")
        elif status in ("proposed_behavioural", "approved_behavioural"):
            if not record.get("behaviour_change") or record.get("reviewer") != "Aaron":
                errors.append(f"{ident}: behavioural needs behaviour_change and Aaron reviewer")
            for field in ("when_odin_sees_it", "odin_v4130_equivalent"):
                if not isinstance(record.get(field), str) or not record[field].strip():
                    errors.append(f"{ident}: behavioural needs {field} for a decidable review")
            if status == "approved_behavioural":
                approved_on = record.get("approval_date")
                try:
                    if not isinstance(approved_on, str) or date.fromisoformat(
                            approved_on).isoformat() != approved_on:
                        raise ValueError("Approval must have a canonical date")
                except ValueError:
                    errors.append(f"{ident}: Aaron approval requires an ISO approval_date")
    return {"errors": errors, "counts": dict(Counter(str(r.get("status")) for r in records)),
            "source_row_count": len(rows),
            "proof_limit": "Static gate does not prove composed restoration or approve wording."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=["report", "rows"], default="report")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--template", action="store_true")
    parser.add_argument("--inventory", default="maintenance/phase2-d19-closure.json")
    args = parser.parse_args(argv)
    try:
        rows, findings = load_source(args.root)
        if args.template or args.command == "rows":
            result = {"version": 1, "baseline_sha": BASELINE_SHA,
                      "source_table": {"path": SOURCE_TABLE, "section": 4},
                      "rows": [{**r, "status": "pending_restoration",
                                "observations": observe(r, findings), "evidence_tests": []}
                               for r in rows]}
        else:
            inventory = json.loads((args.root / args.inventory).read_text(encoding="utf-8"))
            result = validate(inventory, rows, findings, args.root)
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        result = {"errors": [str(exc)]}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return int(bool(result.get("errors")))


if __name__ == "__main__":
    raise SystemExit(main())
