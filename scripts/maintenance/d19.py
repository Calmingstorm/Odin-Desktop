#!/usr/bin/env python3
"""Conservative D19 operational inventory gate, not behavioural qualification."""
from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE_SHA = "16e35e8f370661a2baf8e7030a27919b3e658b3b"
SOURCE_TABLE = "maintenance/pr2-model-facing-string-approvals.md"
STATUSES = {
    "removed_by_restored_behaviour", "pending_restoration",
    "proposed_mechanical", "proposed_behavioural",
}


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
        if status == "removed_by_restored_behaviour":
            if not evidence:
                errors.append(f"{ident}: restoration requires real test nodeids")
            if any(i["reachability"] == "active" for i in observations):
                errors.append(f"{ident}: removed claim has present active AST matches")
        elif status == "pending_restoration":
            if not record.get("owner") or not record.get("pending_reference"):
                errors.append(f"{ident}: pending needs owner and pending_reference")
        elif status == "proposed_mechanical":
            if (not record.get("odin_string") or not record.get("desktop_string")
                    or record.get("reviewer") != "Claude"):
                errors.append(f"{ident}: mechanical needs exact strings and Claude reviewer")
        elif status == "proposed_behavioural":
            if not record.get("behaviour_change") or record.get("reviewer") != "Aaron":
                errors.append(f"{ident}: behavioural needs behaviour_change and Aaron reviewer")
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
