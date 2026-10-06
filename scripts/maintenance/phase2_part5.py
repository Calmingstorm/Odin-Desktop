#!/usr/bin/env python3
"""Check exact case dispositions, not runtime passes or review approval.

The whole-suite map remains conservative: a mixed suite is still deferred.
This additional gate consumes the case-level restoration/retirement/handoff
record rather than silently declaring a mixed inherited suite safe-pass-now.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import tarfile
from collections import Counter
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = "maintenance/phase2-step8-part5-cases.json"
ARCHIVE_SHA256 = "845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0"
CITATION = "Claude, review of step 8 part 5"
SUITES = (
    "tests/test_campaign_health_coverage.py",
    "tests/test_campaign_reasoning_contracts.py",
    "tests/test_docs_campaign_contracts.py",
    "tests/test_fd_health.py",
    "tests/test_hosts_web_edges.py",
    "tests/test_image_default_update_paths.py",
    "tests/test_internals_bindings_contract.py",
    "tests/test_local_workspace.py",
    "tests/test_main_exit_codes.py",
    "tests/test_onboarding_durable_binding_restart.py",
    "tests/test_restart.py",
    "tests/test_schedule_report_format_parity.py",
    "tests/test_self_update_campaign_rollback.py",
    "tests/test_ui_effort_mirror.py",
    "tests/test_web_api_self_update.py",
    "tests/test_webauth_campaign_regressions.py",
)
RETIREMENT_CATEGORIES = {
    "web-ui-only", "self-update-apply-rollback", "systemd-docker-postinstall",
    "raw-source-web-build",
}
STATES = {"restored", "retired", "deferred", "proposed"}


def _json(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def definitions(source: bytes) -> dict[str, ast.AST]:
    """Original definition identity; parameter expansions remain inherited."""
    result = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                result[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child.name.startswith("test_"):
                        result[f"{node.name}.{child.name}"] = child
    return result


def _text(row, key):
    return isinstance(row.get(key), str) and bool(row[key].strip())


def _canonical(path):
    return (isinstance(path, str) and not PurePosixPath(path).is_absolute()
            and ".." not in PurePosixPath(path).parts
            and str(PurePosixPath(path)) == path)


def _file(root: Path, path: str) -> Path:
    if not _canonical(path):
        raise ValueError(f"unsafe path: {path}")
    current = root
    for part in PurePosixPath(path).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"symlink path: {path}")
    if not current.is_file():
        raise ValueError(f"missing regular file: {path}")
    return current


def validate(root=ROOT, data=None) -> tuple[list[str], dict]:
    errors = []
    counts = Counter()
    try:
        root = Path(root)
        data = _json(_file(root, MANIFEST)) if data is None else data
        if data.get("schema_version") != 1 or type(data.get("schema_version")) is not int:
            errors.append("unsupported case-disposition schema")
        archive_bytes = _file(root, "maintenance/odin-v4.13.0.tar.gz").read_bytes()
        if hashlib.sha256(archive_bytes).hexdigest() != ARCHIVE_SHA256:
            raise ValueError("immutable archive hash changed")
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            originals = {path: archive.extractfile(path).read() for path in SUITES}
        rows = data.get("suites", [])
        if not isinstance(rows, list):
            raise ValueError("suites must be a list")
        paths = [row.get("path") for row in rows]
        if paths != list(SUITES):
            errors.append("exact sorted 16-suite membership required")
        qualification = _json(_file(root, "maintenance/qualification-plan.json"))
        selected = {selector.split("::")[0] for group in qualification["groups"]
                    for selector in group["files"]}
        mapped = {row["path"]: row for row in
                  _json(_file(root, "maintenance/phase2-suite-map.json"))["entries"]}
        for suite in rows:
            path = suite.get("path")
            if path not in originals:
                continue
            source = originals[path]
            digest = hashlib.sha256(source).hexdigest()
            if suite.get("inherited_sha256") != digest:
                errors.append(f"inherited hash mismatch: {path}")
            if _file(root, path).read_bytes() != source:
                errors.append(f"original bytes changed: {path}")
            case_rows = suite.get("cases", [])
            if not isinstance(case_rows, list):
                raise ValueError(f"cases must be a list: {path}")
            names = [row.get("case") for row in case_rows]
            expected = definitions(source)
            if len(names) != len(set(names)) or set(names) != set(expected):
                errors.append(f"exact original case definitions required: {path}")
            if mapped.get(path, {}).get("case_dispositions") != MANIFEST:
                errors.append(f"suite map must link consumed case dispositions: {path}")
            # Cases may be accounted without constituting a complete inherited
            # suite restore. Neither retirement nor counterpart evidence is a
            # license to change the immutable whole-suite historical markers.
            if mapped.get(path, {}).get("status") != "deferred":
                errors.append(f"mixed case record must not claim whole-suite pass: {path}")
            for case in case_rows:
                label = f"{path}::{case.get('case')}"
                state = case.get("disposition")
                if state not in STATES:
                    errors.append(f"unknown disposition: {label}")
                    continue
                counts[state] += 1
                if not _text(case, "reason"):
                    errors.append(f"missing concrete reason: {label}")
                if state == "retired":
                    if (case.get("category") not in RETIREMENT_CATEGORIES
                            or case.get("citation") != CITATION):
                        errors.append(f"retirement needs named removed surface and citation: {label}")
                    if case.get("selectors"):
                        errors.append(f"retirement cannot claim passing selectors: {label}")
                elif state in {"deferred", "proposed"}:
                    if not _text(case, "owner") or not _text(case, "blocker"):
                        errors.append(f"handoff/proposal needs named owner and blocker: {label}")
                else:
                    if case.get("mode") not in {"exact-frozen", "desktop-counterpart"}:
                        errors.append(f"restoration needs explicit proof mode: {label}")
                    if not _text(case, "counterpart"):
                        errors.append(f"restoration needs named counterpart: {label}")
                    selectors = case.get("selectors")
                    if (not isinstance(selectors, list) or not selectors
                            or any(not isinstance(s, str) for s in selectors)):
                        errors.append(f"restoration needs executable selectors: {label}")
                        continue
                    for selector in selectors:
                        target = selector.split("::")[0]
                        _file(root, target)
                        if target.startswith("tests/"):
                            if target not in selected:
                                errors.append(f"counterpart absent from qualification: {label}: {target}")
                        elif not (target.startswith("app/test/")
                                  and target.endswith((".test.ts", ".test.mts"))):
                            errors.append(f"unsupported counterpart selector: {label}: {target}")
        report = {"suites": len(rows), "definitions": sum(counts.values()),
                  "dispositions": dict(sorted(counts.items())),
                  "runtime_pass_claim": False, "independent_review": "pending"}
        return errors, report
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            tarfile.TarError, SyntaxError) as exc:
        return [*errors, f"malformed case-accounting input: {exc}"], {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    errors, report = validate(args.root)
    print(json.dumps({"errors": errors, "counts": report}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
