#!/usr/bin/env python3
"""Validate and report the R4/CC groundwork inventory, never run acceptance.

Only final-candidate qualification can record passes. Existing tests, source
proofs and pending PRs are pointers, not Linux release acceptance outcomes.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "docs/work/phase-3-app-v1.md"
INVENTORY = "maintenance/r4-acceptance.json"
IDS = tuple([f"R4-{n:02d}" for n in range(1, 11)] + [f"CC-{n:02d}" for n in range(1, 20)])
LANES = ("headless", "real_core", "native", "package")
STATUSES = {"no_evidence", "partial", "ready_for_final_run"}
PENDING = re.compile(r"pending: #[1-9][0-9]*\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class InventoryError(ValueError):
    """Invalid inventory or unresolvable evidence, not an acceptance failure."""


def tree_file(root: Path, relative: str) -> Path:
    """A canonical regular file inside this checkout; no external file reads."""
    path = PurePosixPath(relative)
    if (not relative or path.is_absolute() or ".." in path.parts
            or str(path) != relative or "\\" in relative):
        raise InventoryError(f"non-canonical tree path: {relative!r}")
    target = root / relative
    if not target.is_file() or not target.resolve().is_relative_to(root.resolve()):
        raise InventoryError(f"dangling or external pointer: {relative}")
    return target


def load_json(path: Path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InventoryError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)


def source_cases(root: Path) -> dict[str, tuple[str, str]]:
    """Read the authoritative section 5, preserving its scenario Markdown bytes."""
    text = tree_file(root, SOURCE).read_text(encoding="utf-8")
    section = text.split("## 5. R4 acceptance inventory and contract additions\n", 1)[1]
    section = section.split("\n## 6.", 1)[0]
    cases = {}
    for line in section.splitlines():
        match = re.fullmatch(r"\| ((?:R4|CC)-\d{2}) \| (.+) \| (.+) \|", line)
        if match:
            identity, scenario, dependency = match.groups()
            if identity in cases:
                raise InventoryError(f"duplicate work-order ID: {identity}")
            cases[identity] = (scenario, dependency)
    # CC-19 is a prose contract addition, not a table row. Preserve its entire
    # original paragraph rather than inventing or silently shortening a scenario.
    paragraph = next((p for p in section.split("\n\n") if "`CC-19`" in p), None)
    if paragraph is None:
        raise InventoryError("work order is missing CC-19")
    cases["CC-19"] = (paragraph, "Phase 2 step 7; P4.5")
    if set(cases) != set(IDS):
        raise InventoryError("work-order ID set changed; review the acceptance inventory")
    return cases


def test_selector(path: Path, selector: str) -> bool:
    """Resolve static Python node IDs or JS/TS test titles without executing code."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        nodes = ast.parse(text).body
        for name in selector.split("::"):
            node = next((n for n in nodes if isinstance(
                n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ) and n.name == name), None)
            if node is None:
                return False
            nodes = node.body
        return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    if path.suffix in {".ts", ".js", ".mjs"}:
        # Comments and strings can contain convincing non-executable test
        # declarations. Templates stay source titles, not collected expansions.
        tokens = [match.group() for match in re.finditer(
            r"//[^\n]*|/\*[\s\S]*?\*/|"
            r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`|"
            r"[A-Za-z_$][\w$]*|[^\s]", text,
        ) if not match.group().startswith(("//", "/*"))]
        for index, token in enumerate(tokens):
            if token not in {"test", "it"}:
                continue
            tail = tokens[index + 1:]
            if tail[:2] in [[".", "only"], [".", "skip"], [".", "fixme"]]:
                tail = tail[2:]
            if len(tail) >= 3 and tail[0] == "(" and tail[2] == ",":
                title = tail[1]
                if title[:1] in {"'", '"', "`"} and title[1:-1] == selector:
                    return True
    return False


def manifest_entries(path: Path) -> list[dict]:
    manifest = load_json(path)
    artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else None
    if not isinstance(artifacts, list) or not artifacts:
        raise InventoryError(f"invalid or empty evidence manifest: {path.name}")
    identities = set()
    for artifact in artifacts:
        if (not isinstance(artifact, dict)
                or not isinstance(artifact.get("id"), str) or not artifact["id"].strip()
                or artifact["id"] in identities
                or not isinstance(artifact.get("path"), str) or not artifact["path"].strip()
                or not SHA256.fullmatch(str(artifact.get("sha256", "")))):
            raise InventoryError(f"invalid evidence manifest artifact: {path.name}")
        identities.add(artifact["id"])
    return artifacts


def evidence_pointer(root: Path, pointer: str) -> bool:
    """Return whether a pointer is pending. Manifest artifacts need a hash/path.

    manifest.json::artifact-id references an entry in an `artifacts` array of
    {id, path, sha256}. External raw artifact paths are not opened or claimed
    verified by this offline report. The committed manifest is the pointer.
    """
    if PENDING.fullmatch(pointer):
        return True
    relative, separator, selector = pointer.partition("::")
    path = tree_file(root, relative)
    if not separator:
        if path.suffix != ".json":
            raise InventoryError(f"bare pointer must identify an evidence manifest: {pointer}")
        manifest_entries(path)
        return False
    if not selector:
        raise InventoryError(f"empty evidence selector: {pointer}")
    if path.suffix == ".json":
        matches = [a for a in manifest_entries(path) if a["id"] == selector]
        if len(matches) != 1:
            raise InventoryError(f"dangling or invalid manifest artifact: {pointer}")
    elif not test_selector(path, selector):
        raise InventoryError(f"dangling test case: {pointer}")
    return False


def strings(value, label: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise InventoryError(f"{label} must be a list of nonblank strings")
    if nonempty and not value:
        raise InventoryError(f"{label} must not be empty")
    if len(value) != len(set(value)):
        raise InventoryError(f"{label} has duplicates")
    return value


def validate(root: Path, inventory: dict) -> list[dict]:
    if not isinstance(inventory, dict) or inventory.get("schema_version") != 1:
        raise InventoryError("inventory must have schema_version 1")
    if inventory.get("source") != SOURCE:
        raise InventoryError(f"source must be {SOURCE}")
    rows = inventory.get("cases")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise InventoryError("cases must be a list of records")
    identities = [row.get("id") for row in rows]
    if any(not isinstance(identity, str) for identity in identities):
        raise InventoryError("each case needs a string ID")
    counts = Counter(identities)
    missing = sorted(set(IDS) - counts.keys())
    extra = sorted(counts.keys() - set(IDS))
    duplicates = sorted(identity for identity, count in counts.items() if count != 1)
    if missing or extra or duplicates:
        raise InventoryError(
            f"ID coverage: missing={missing}, extra={extra}, duplicate={duplicates}"
        )
    expected = source_cases(root)
    for row in rows:
        identity = row["id"]
        if (row.get("scenario"), row.get("dependency")) != expected[identity]:
            raise InventoryError(
                f"{identity}: scenario/dependency must match the work order verbatim"
            )
        strings(row.get("environments"), f"{identity} environments", nonempty=True)
        unresolved = strings(row.get("unresolved"), f"{identity} unresolved")
        status = row.get("status")
        if status == "passed":
            raise InventoryError(
                f"{identity}: passed is forbidden in groundwork; final acceptance requires "
                "package hashes and an environment at the final candidate run"
            )
        if not isinstance(status, str) or status not in STATUSES:
            raise InventoryError(f"{identity}: invalid groundwork status {status!r}")
        evidence = row.get("evidence")
        if not isinstance(evidence, dict) or set(evidence) != set(LANES):
            raise InventoryError(f"{identity}: evidence needs exactly {LANES}")
        current = False
        pending = False
        for lane in LANES:
            for pointer in strings(evidence[lane], f"{identity} {lane}"):
                is_pending = evidence_pointer(root, pointer)
                pending |= is_pending
                current |= not is_pending
        if status == "no_evidence" and current:
            raise InventoryError(f"{identity}: no_evidence cannot contain current tree evidence")
        if status != "no_evidence" and not current:
            raise InventoryError(
                f"{identity}: {status} requires current, not merely pending evidence"
            )
        if status == "ready_for_final_run" and (unresolved or pending):
            raise InventoryError(
                f"{identity}: ready_for_final_run has unresolved or pending evidence"
            )
    return sorted(rows, key=lambda row: IDS.index(row["id"]))


def report(rows: list[dict]) -> str:
    counts = Counter(row["status"] for row in rows)
    lines = ["# R4/CC acceptance groundwork", "",
             "Inventory only. No case is passed; no final candidate was run.", "",
             ", ".join(f"{status}: {counts[status]}" for status in sorted(STATUSES)), "",
             "## Gap list", ""]
    for row in rows:
        identity = row["id"]
        lines.append(f"- {identity} [{row['status']}] ({row['dependency']})")
        if row["status"] == "no_evidence":
            lines.append(
                "  - No current tree/manifest evidence; pending PRs do not close this gap."
            )
        for lane in LANES:
            pending = [p for p in row["evidence"][lane] if PENDING.fullmatch(p)]
            if not row["evidence"][lane]:
                lines.append(
                    f"  - {lane}: no current evidence pointer (not an automatic requirement)."
                )
            elif pending:
                lines.append(f"  - {lane} pending, not accepted: {', '.join(pending)}.")
        for note in row["unresolved"]:
            lines.append(f"  - {note}")
        lines.append("  - Final hash-bound applicable Linux run remains outstanding.")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("command", choices=["report"])
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        rows = validate(root, load_json(tree_file(root, INVENTORY)))
    except (InventoryError, OSError, ValueError, IndexError, SyntaxError) as exc:
        print(f"Invalid R4/CC inventory: {exc}", file=sys.stderr)
        return 1
    print(report(rows), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
