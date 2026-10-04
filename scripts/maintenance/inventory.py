#!/usr/bin/env python3
"""Offline byte-exact Desktop lineage inventory; never imports engine code."""
from __future__ import annotations

import argparse
import base64
import difflib
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

BASELINE = "cd7530906e9cfa10a0fa900247d7ce2a8bb33e25"
ARCHIVE_SHA256 = "845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0"
REF = "refs/baselines/odin-v4.13.0"
REPLACEABLE_SURFACES = {"src/__main__.py", "src/discord/client.py", "src/discord/cogs/scheduled_report_pagination.py", "src/discord/views/confirm.py", "src/packaging/validate.py", "src/permissions/token_manager.py"}
ROOT = Path(__file__).resolve().parents[2]
PINNED_DOCS = {
    "docs/design/reuse-map.md": "817813ff28d4667a42de4f7f56b8ecf0d1e39a2406b5fec8f4b2c7ce0dd40d7f",
    "docs/design/prompt-changes.md": "a904b5f49112b933fa277c1ddd6497e30203fb5ffd144dbf6635d79e3da15722",
    "docs/discussion/06-odin-round3.md": "20899b40218b801d5ff3373bde716bee4a1a9738452c90a9f3728d4721a939c0",
}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def safe_path(path):
    p = PurePosixPath(path)
    if not path or p.is_absolute() or ".." in p.parts or str(p) != path:
        raise ValueError(f"Non-canonical relative path: {path!r}")
    return path

def regular_file(root, path):
    """Never follow a substituted ancestor out of the offline target tree."""
    target = root / safe_path(path)
    return target.is_file() and not any(p.is_symlink() for p in [target, *target.parents])

def baseline_blobs(root):
    archive = root / "maintenance/odin-v4.13.0.tar.gz"
    if digest(archive.read_bytes()) != ARCHIVE_SHA256:
        raise ValueError("Frozen archive digest mismatch")
    proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", REF], capture_output=True, text=True)
    if proc.returncode == 0 and proc.stdout.strip() != BASELINE:
        raise ValueError("Pinned Git ref changed")
    blobs = {}
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf:
            if member.isdir():
                continue
            path = safe_path(member.name)
            if path in blobs or not member.isfile():
                raise ValueError(f"Duplicate or non-regular archive member: {path}")
            stream = tf.extractfile(member)
            if stream is None:
                raise ValueError(f"Unreadable archive member: {path}")
            blobs[path] = stream.read()
    return blobs

def reuse_rows(root, blobs):
    for path, expected in PINNED_DOCS.items():
        if digest((root / path).read_bytes()) != expected:
            raise ValueError(f"Selection/approval document changed; independent review required: {path}")
    rows = {}
    text = (root / "docs/design/reuse-map.md").read_text(encoding="utf-8")
    for match in re.finditer(r"^\| `([^`]+)` \| (?:\*\*)?(keep as is|keep with adaptation|strip|replace)(?:\*\*)? \| (.+) \|$", text, re.MULTILINE):
        path, verdict, reason = match.groups()
        if path not in blobs:
            continue
        if path in rows:
            raise ValueError(f"Duplicate reuse row: {path}")
        rows[path] = (verdict, reason)
    needed = {p for p in blobs if p.startswith("src/") or p.startswith("ui/js/pages/")}
    if set(rows) != needed:
        raise ValueError(f"Reuse map closure mismatch: missing={sorted(needed - rows.keys())}")
    return rows

def test_plan(root, blobs):
    plan = load_json(root / "maintenance/test-plan.json")
    entries = {e["path"]: e for e in plan["entries"]}
    needed = {p for p in blobs if p.startswith("tests/")}
    if len(entries) != len(plan["entries"]) or set(entries) != needed:
        raise ValueError("Test plan must account for every upstream tests/ path exactly once")
    allowed = {"safe_pass_now", "phase2", "excluded", "safety_manual_gated", "retained_support", "retained_adaptation_gated"}
    for entry in entries.values():
        if not entry.get("reason") or entry.get("classification") not in allowed:
            raise ValueError(f"Invalid test classification: {entry['path']}")
    return plan, entries

def manifests(root, blobs):
    rows = reuse_rows(root, blobs)
    plan, test_entries = test_plan(root, blobs)
    override_path = root / "maintenance/selection-overrides.json"
    overrides = load_json(override_path) if override_path.exists() else {"version": 1, "baseline": BASELINE, "entries": []}
    if overrides.get("baseline") != BASELINE or overrides.get("version") != 1:
        raise ValueError("Selection override identity changed")
    override_map = {}
    for override in overrides["entries"]:
        path = safe_path(override["path"])
        if path in override_map or path not in REPLACEABLE_SURFACES or path not in rows or rows[path][0] not in {"replace", "keep with adaptation"}:
            raise ValueError(f"Invalid/duplicate selection override: {path}")
        required = ("reason", "contract", "invariant", "replacement", "tests", "owner", "reviewer", "state")
        if any(not override.get(k) for k in required) or override.get("upstream_sha256") != digest(blobs[path]):
            raise ValueError(f"Incomplete exact-path selection decision: {path}")
        override_map[path] = override
    associated = {}
    for path, entry in test_entries.items():
        closure = plan.get("import_closures", {}).get(entry.get("import_closure_id"), {})
        sources = closure.get("source_import_closure", []) if isinstance(closure, dict) else closure
        for source in entry.get("source_import_closure", []) + entry.get("direct_source_imports", []) + sources:
            if source.startswith("src."):
                source = source.replace(".", "/") + ".py"
            associated.setdefault(source, set()).add(path)
    entries, test_closures = [], {}
    for path, content in sorted(blobs.items()):
        classification = None
        if path in rows:
            verdict, reason = rows[path]
            selected = verdict != "strip" and not path.startswith("ui/")
        elif path in test_entries:
            classification = test_entries[path]["classification"]
            selected = classification != "excluded"
            verdict = "keep as is" if selected else "strip"
            reason = test_entries[path]["reason"]
        elif path.startswith("assets/"):
            selected, verdict, reason = True, "keep as is", "Frozen native helper/protocol/proof closure retained; execution isolated and qualification-gated."
        elif path.startswith(("scripts/computer-feasibility/", "scripts/ci/")) or path in {"scripts/build-hyprland-capture.sh", "scripts/build-hyprland-input.sh", "scripts/codex_login.py", "scripts/generate_model_hints_seed.py", "scripts/docs/_reference.py", "scripts/docs/generate_tool_reference.py", "docs/skills.md"}:
            selected, verdict = True, "keep with adaptation" if path in {"docs/skills.md", "docs/generate_tool_reference.py"} else "keep as is"
            reason = "Parent-selected retained capability/native test/helper/reference closure. Historical/native runners are non-runtime assets, not shipping server installers; qualification requires isolated proof."
        elif path == "pyproject.toml":
            selected, verdict, reason = True, "replace", "Phase 1 Desktop Python 3.12/D14 locked capability dependencies replace server packaging."
        else:
            selected, verdict = False, "strip"
            if path.startswith("ui/"):
                reason = "Entire legacy UI excluded; replaced by Electron, not hidden server surface."
            elif path.startswith(("packaging/", "scripts/")) or path in {"Dockerfile", "docker-compose.yml", "Makefile", ".dockerignore"}:
                reason = "Entire old server deployment/build/install/scripts excluded; no service/daemon/ambient native runner."
            elif path.startswith(".github/"):
                reason = "Upstream server/UI/release CI excluded; independent Desktop isolated qualification required."
            elif path == "LICENSE":
                reason = "Notice preserved in maintenance/UPSTREAM-LICENSE and frozen archive; private product license decision pending."
            else:
                reason = "Upstream docs/config/project metadata excluded from runtime; immutable archive preserves provenance without adopting server defaults or existing-user state."
        tests = [path] if path in test_entries else sorted(associated.get(path, []))
        closure_id = digest(json.dumps(tests, separators=(",", ":")).encode())[:16]
        test_closures[closure_id] = tests
        if path in override_map:
            decision = override_map[path]
            selected, verdict, reason = False, "replace", decision["reason"]
        entries.append({"path": path, "upstream_sha256": digest(content), "selected": selected,
                        "reuse_verdict": verdict, "destination": path if selected else None,
                        "reason": reason, "owner": "Odin", "test_closure_id": closure_id,
                        "fixtures_closure": "retained-test-support" if tests else None,
                        "assets_closure": "retained-native-assets" if path.startswith("src/computer/") else None,
                        "dependency_origin": "upstream native source/protocol/evidence; compositor ABI qualification required" if path.startswith("assets/") else "upstream tracked source; runtime dependency resolution belongs to Desktop lockfile",
                        "test_classification": classification,
                        "selection_override": override_map.get(path)})
    manifest = {"version": 1, "baseline": BASELINE, "archive_sha256": ARCHIVE_SHA256, "selection_documents": PINNED_DOCS, "review": "pending independent Claude review", "entries": entries,
                "test_closures": test_closures,
                "support_closures": {"retained-test-support": sorted(p for p, e in test_entries.items() if e["classification"] != "excluded" and p.startswith(("tests/fixtures/", "tests/helpers/"))),
                                     "retained-native-assets": sorted(p for p in blobs if p.startswith("assets/"))}}
    safety = {"version": 1, "baseline": BASELINE, "review": "pending independent Claude review",
              "contracts": ["guards/anti-hedging", "foreground/agent completion", "command/effect classifier", "governor floor/shape", "containment/descendant settlement", "patch/workspace identity", "output authorization/provenance", "durability/resume/spent budgets", "computer release/quarantine/native helpers"],
              "selection_policy": "Protect entire retained source/native/test closure; no file-wide exceptions.",
              "test_closures": test_closures,
              "entries": [{"path": e["path"], "sha256": e["upstream_sha256"], "test_closure_id": e["test_closure_id"], "symbols": "all bytes including strings, budgets, helper payloads and case corpus"} for e in entries if e["selected"] and e["path"].startswith(("src/", "assets/", "tests/", "scripts/"))]}
    return manifest, safety

def approved_wording(path, original, root=ROOT):
    changes = {}
    if path == "src/discord/response_guards.py":
        changes = {b"before Discord delivery.": b"before conversation delivery.", b"before sending to Discord.": b"before sending to the conversation."}
    elif path == "src/llm/system_prompt.py":
        text = (root / "docs/design/prompt-changes.md").read_text(encoding="utf-8")
        if digest(text.encode()) != PINNED_DOCS["docs/design/prompt-changes.md"]:
            raise ValueError("Prompt approval document changed")
        for line in text.splitlines():
            if not re.match(r"^\| (33|47|61|66|95|97|105|116|131) ", line):
                continue
            cells = line.removeprefix("| ").removesuffix(" |").split(" | ")
            def quoted(cell):
                cell = cell.split(" (D7:", 1)[0].split(" The desktop history tool", 1)[0]
                marker = "``" if cell.startswith("``") else "`"
                end = cell.rfind(marker)
                if end < 0:
                    raise ValueError("Malformed prompt approval row")
                return cell[len(marker):end].replace("\\`", "`").encode()
            changes[quoted(cells[1])] = quoted(cells[2])
        if len(changes) != 9:
            raise ValueError("Expected exactly nine D7 substitutions")
    if not changes:
        return None
    result = original
    for old, new in changes.items():
        if result.count(old) != 1:
            raise ValueError(f"Approved wording anchor must occur once: {path}: {old!r}")
        result = result.replace(old, new, 1)
    return result

def byte_patch(before, after):
    a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
    offsets = [0]
    for line in a:
        offsets.append(offsets[-1] + len(line))
    return [
        {
            "start": offsets[start],
            "end": offsets[end],
            "old_base64": base64.b64encode(b"".join(a[start:end])).decode(),
            "new_base64": base64.b64encode(b"".join(b[new_start:new_end])).decode(),
        }
        for tag, start, end, new_start, new_end in difflib.SequenceMatcher(
            None, a, b, autojunk=False
        ).get_opcodes()
        if tag != "equal"
    ]

def apply_byte_patch(before, patch):
    cursor, parts = 0, []
    for hunk in patch:
        start, end = hunk["start"], hunk["end"]
        if not isinstance(start, int) or not isinstance(end, int) or not cursor <= start <= end <= len(before):
            raise ValueError("Non-monotonic or out-of-bounds patch")
        old, new = base64.b64decode(hunk["old_base64"], validate=True), base64.b64decode(hunk["new_base64"], validate=True)
        if before[start:end] != old:
            raise ValueError("Patch original bytes do not match baseline")
        parts.extend((before[cursor:start], new))
        cursor = end
    parts.append(before[cursor:])
    return b"".join(parts)

def ledger(root):
    data = load_json(root / "maintenance/desktop-deltas.json")
    if data.get("baseline") != BASELINE or data.get("version") != 1:
        raise ValueError("Desktop ledger baseline/version mismatch")
    paths = [safe_path(e["path"]) for e in data["entries"]]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate Desktop delta path")
    return data

def record(root, args):
    blobs = baseline_blobs(root)
    path = safe_path(args.path)
    if not path.startswith(("src/", "tests/", "assets/", "scripts/")) and path not in {"pyproject.toml", "uv.lock", "requirements.lock", "docs/skills.md", "docs/_reference.py", "docs/generate_tool_reference.py"}:
        raise ValueError("Delta outside engine/test/asset/dependency scope")
    before, target = blobs.get(path, b""), root / path
    if not regular_file(root, path):
        raise ValueError("Record requires existing regular destination; removals need selection review")
    after = target.read_bytes()
    if after == before:
        raise ValueError("No byte adaptation to record")
    reuse_rows(root, blobs)
    wording = approved_wording(path, before, root)
    if wording is not None and after != wording:
        raise ValueError("Prompt/guard change is not exact D7 substitutions")
    if path in blobs and path.startswith("tests/"):
        raise ValueError("Cannot recapture upstream behavior corpus; add Desktop tests or reviewed identical-case proof")
    if not args.reason or not args.contract or not args.invariant or not args.tests:
        raise ValueError("Concrete reason, contract, invariant and named tests required")
    data = ledger(root)
    entry = {"path": path, "origin": "Odin to Desktop" if path in blobs else "Desktop foundation", "source_commit": BASELINE,
             "before_sha256": digest(before), "after_sha256": digest(after), "patch": byte_patch(before, after),
             "reason": args.reason, "contract": args.contract, "invariant": args.invariant, "tests": sorted(set(safe_path(p) for p in args.tests)),
             "owner": args.owner, "reviewer": "pending Claude", "state": "pending", "approval": "D7 wording; implementation review pending" if wording is not None else "pending independent review",
             "evidence": "Exact bytes only; not test execution, qualification or approval", "destination_commit": "pending parent commit/PR", "backport": "Desktop boundary; applicability review pending",
             "date": "2026-10-04", "severity": "safety review required", "review_deadline": "before Phase 1 merge", "next_revisit": "next upstream release or weekly review", "release_status": "unreleased Phase 1", "dependency_assets": "see manifest closure"}
    entry["test_sha256"] = {p: digest((root / p).read_bytes()) for p in entry["tests"]}
    data["entries"] = sorted([e for e in data["entries"] if e["path"] != path] + [entry], key=lambda e: e["path"])
    write_json(root / "maintenance/desktop-deltas.json", data)
    print(f"Recorded pending exact delta: {path}; independent review still required")

def validate_delta(root, entry, before, actual, errors, pending, statuses):
    path = entry["path"]
    try:
        fields = ("reason", "contract", "invariant", "owner", "reviewer", "state", "tests", "approval", "evidence")
        if any(not entry.get(field) for field in fields):
            raise ValueError("Missing accountability/contract/review fields")
        reconstructed = apply_byte_patch(before, entry["patch"])
        if entry["before_sha256"] != digest(before) or entry["after_sha256"] != digest(reconstructed):
            raise ValueError("Delta digest/patch inconsistency")
        if reconstructed != actual:
            raise ValueError("Current bytes differ from exact ledger patch")
        wording = approved_wording(path, before, root)
        if wording is not None and reconstructed != wording:
            raise ValueError("Unapproved surrounding prompt/guard drift")
        if before and path.startswith("tests/"):
            raise ValueError("Changed upstream test corpus; automatic exemption forbidden")
        for test in entry["tests"]:
            safe_path(test)
            if not regular_file(root, test):
                raise ValueError(f"Missing named evidence test: {test}")
            if "test_sha256" in entry and entry["test_sha256"].get(test) != digest((root / test).read_bytes()):
                raise ValueError(f"Named evidence test digest changed: {test}")
        if entry["state"] != "reviewed":
            pending.append(path)
        elif entry["reviewer"] == entry["owner"] or "pending" in entry["reviewer"].lower() or "pending" in entry["approval"].lower():
            raise ValueError("Invalid independent approval")
        statuses.append((path, "ledgered-exact-delta"))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        errors.append(f"Invalid delta {path}: {exc}")

def report(root, require_review=False):
    blobs = baseline_blobs(root)
    expected_manifest, expected_safety = manifests(root, blobs)
    errors, pending, statuses = [], [], []
    for name, expected in [("manifest.json", expected_manifest), ("safety-manifest.json", expected_safety)]:
        if load_json(root / "maintenance" / name) != expected:
            errors.append(f"Index tampering/staleness: {name}; refresh then review")
    upstream = load_json(root / "maintenance/ledger.json")
    if upstream != {"version": 1, "baseline": BASELINE, "review_watermark": BASELINE, "entries": []}:
        errors.append("Unexpected upstream ledger/watermark; no post-baseline port authorized")
    deltas = {e["path"]: e for e in ledger(root)["entries"]}
    checked = set()
    for entry in expected_manifest["entries"]:
        path = entry["path"]
        decision = entry.get("selection_override")
        if decision:
            if decision["state"] != "reviewed":
                pending.append(path + " (selection/replacement)")
            elif decision["reviewer"] == decision["owner"] or "pending" in decision["reviewer"].lower():
                errors.append(f"Invalid selection approval: {path}")
            for evidence in decision["tests"]:
                if not regular_file(root, evidence):
                    errors.append(f"Missing selection evidence {path}: {evidence}")
        if not entry["selected"]:
            if path.startswith(("src/", "tests/", "ui/", "packaging/", "scripts/")) and (root / path).exists():
                errors.append(f"Excluded upstream path still present: {path}")
            continue
        checked.add(path)
        target = root / path
        if not regular_file(root, path):
            errors.append(f"Missing/unsafe selected path: {path}")
            continue
        actual, before = target.read_bytes(), blobs[path]
        if path in deltas:
            validate_delta(root, deltas[path], before, actual, errors, pending, statuses)
        elif actual == before:
            statuses.append((path, "shared-byte-identical"))
        else:
            errors.append(f"Unexplained divergence: {path}")
    for scope in ("src", "tests", "assets", "scripts"):
        for file in sorted((root / scope).rglob("*")):
            if "__pycache__" in file.parts or file.suffix == ".pyc":
                continue
            path = file.relative_to(root).as_posix()
            if file.is_symlink():
                errors.append(f"Unsafe symlink in checked tree: {path}")
                continue
            if not file.is_file():
                continue
            if path.startswith("scripts/maintenance/"):
                continue  # checker implementation independently reviewed, not self-approved
            if path in blobs:
                continue
            checked.add(path)
            if path in deltas and regular_file(root, path):
                validate_delta(root, deltas[path], b"", file.read_bytes(), errors, pending, statuses)
            else:
                errors.append(f"Unledgered Desktop addition: {path}")
    for path in ("uv.lock", "requirements.lock"):
        target = root / path
        if target.exists():
            checked.add(path)
            if path in deltas and regular_file(root, path):
                validate_delta(root, deltas[path], blobs.get(path, b""), target.read_bytes(), errors, pending, statuses)
            else:
                errors.append(f"Unledgered dependency lock: {path}")
    for path in deltas.keys() - checked:
        errors.append(f"Orphan/unmapped delta: {path}")
    if require_review:
        errors.extend(f"Independent review pending: {p}" for p in pending)
        errors.append("Manifest/safety/test-plan independent review pending; not release-qualified")
    return {"baseline": BASELINE, "archive_verified": True,
            "shared": [p for p, s in statuses if s == "shared-byte-identical"], "ledgered": [p for p, s in statuses if s == "ledgered-exact-delta"],
            "pending_review": pending, "errors": errors, "gate": "fail" if errors else "byte-drift-clean-review-pending",
            "qualification": "Static byte check only; no dependency/runtime/native/semantic parity claim"}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("refresh", help="Deterministic inventory only; never captures source drift")
    rep = sub.add_parser("report")
    rep.add_argument("--require-review", action="store_true")
    rec = sub.add_parser("record", help="Explicit pending per-path patch, not approval")
    rec.add_argument("path")
    for flag in ("reason", "contract", "invariant", "owner"):
        rec.add_argument(f"--{flag}", required=True)
    rec.add_argument("--tests", nargs="+", required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "refresh":
            manifest, safety = manifests(root, baseline_blobs(root))
            write_json(root / "maintenance/manifest.json", manifest)
            write_json(root / "maintenance/safety-manifest.json", safety)
            print(f"Refreshed {len(manifest['entries'])} upstream paths and {len(safety['entries'])} safety paths; ledger unchanged")
            return 0
        if args.command == "record":
            record(root, args)
            return 0
        result = report(root, args.require_review)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result["errors"] else 0
    except (ValueError, KeyError, TypeError, OSError, tarfile.TarError, json.JSONDecodeError) as exc:
        print(f"Maintenance check failed closed: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
