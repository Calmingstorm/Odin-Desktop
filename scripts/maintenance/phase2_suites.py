#!/usr/bin/env python3
"""Offline Phase 2 suite accounting. No engine or inherited test is imported.

This checks immutable membership, bytes, classifications and executable whole-
suite associations. It is not runtime passing evidence or feature qualification.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import subprocess
import tarfile
from collections import Counter
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "cd7530906e9cfa10a0fa900247d7ce2a8bb33e25"
SOURCE_MAIN = "7d919f0c32402e28179e019dee948be8ed3f5407"
ARCHIVE_SHA256 = "845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0"
POPULATION_SHA256 = "a4bcf41b3ee1660c991df903cccbda1583497c2ec01cea6bb2be6425ba43888f"
HISTORICAL_PLAN_SHA256 = "75a862f004d6780baa11fd85c509b0ef5ddfa7a5c9ad3d9f734df4c1abe2ff9f"
HISTORICAL_QUALIFICATION_SHA256 = "0e45810c0574b26a79d23842a65fe02f0d1ec0ca6d8c9691ece0680536baff02"
MERGED_MAIN = "566b7954911154ed36d9e5e751c2db9029e262e2"
MERGED_QUALIFICATION_SHA256 = "89094765dc426da5fa6844efb8d54273d94d1b79dd54e62e0207d315bfc79956"
RETIREMENT_REVIEWER = "Claude, review of #26"
RETIRABLE_SUITES = {
    "tests/test_client.py", "tests/test_command_reconciliation.py",
    "tests/test_gateway_transition_regressions.py", "tests/test_rate_limiter.py",
    "tests/test_websocket_production_stack.py",
}
RETIREMENT_REASONS = {
    "tests/test_client.py": (
        "Retired: Odin's Discord client (class name, intents, prefix, reaction extension). "
        "Report paging is step 6's reports.py, with its own tests."),
    "tests/test_command_reconciliation.py": "Retired: Discord slash-command publication.",
    "tests/test_gateway_transition_regressions.py": (
        "Retired: Discord gateway ready/resume/disconnect races."),
    "tests/test_rate_limiter.py": (
        "Retired: it covers only Odin's /api/ routes (src/health/server.py:721-753), "
        "and the desktop has no management listener. Odin's incoming webhooks (/webhook/*) "
        "aren't rate-limited, so step 7's listener inherits nothing here."),
    "tests/test_websocket_production_stack.py": (
        "Retired: the WebSocket stack. The IPC transport has no URL to carry a credential, "
        "and step 1's tests prove its handshake authenticates before any method runs."),
}
WORK_ORDER = "docs/work/phase-2-desktop-engine.md"
REVIEW34_REVIEWER = "Claude, review of #34"
# This is a separate authority, not an extension of #26's five dispositions.
# Exact path/reason pairs are the admission policy; no caller-supplied reason
# or reviewer string can retire another inherited surface.
REVIEW34_RETIREMENT_GROUPS = {
    ("Retired: multi-user API tokens, tiers and ACLs, and bearer and web sessions; "
     "these surfaces were removed by design from Desktop."): (
        "test_auth_config_integration_review", "test_auth_entry_preservation",
        "test_auth_snapshot_compatibility", "test_auth_snapshot_routes",
        "test_campaign_a_coverage_boundaries", "test_campaign_authorization_persistence",
        "test_campaign_private_persistence", "test_campaign_startup_auth",
        "test_pr356_static_recovery_identity", "test_pr356_storage_compatibility",
        "test_pr356_tokenless_upgrade", "test_startup_auth_middleware_review",
        "test_web_api_security_helpers_coverage", "test_web_api_security_routes",
        "test_web_campaign_policy_races", "test_web_campaign_truth",
        "test_web_persisted_sessions", "test_web_api_codex_admin",
    ),
    ("Retired: the HTTP management listener and its bind or consent policy; "
     "Desktop has no management listener."): (
        "test_bootstrap_bind_policy", "test_bootstrap_runtime_bind",
        "test_health_shutdown", "test_listener_consent",
    ),
    ("Retired: Discord configuration, setup and diagnostics; "
     "these surfaces were removed by design from Desktop."): (
        "test_config", "test_config_campaign_v410", "test_onboarding_campaign",
        "test_onboarding_partial_publication", "test_setup_helpers",
        "test_startup_diagnostics", "test_startup_onboarding_context",
    ),
    "Retired: credential files with .bak copies; Desktop replaces these files with the keyring.": (
        "test_listener_credential_provenance", "test_independent_credential_review",
    ),
    "Retired: the WebSocket; Desktop uses its authenticated IPC transport instead.": (
        "test_web_websocket", "test_websocket_bootstrap_auth", "test_websocket_handler",
    ),
    "Retired: per-user host preferences, removed by D17.": (
        "test_host_access_removal_audit_v412",
    ),
    ("Retired: Desktop never imports an old Odin config, "
     "so there is no legacy timeout to migrate."): (
        "test_compatible_timeout_migration",
    ),
}
REVIEW34_RETIREMENT_REASONS = {
    f"tests/{stem}.py": reason
    for reason, stems in REVIEW34_RETIREMENT_GROUPS.items() for stem in stems
}
REVIEW34_RETIRABLE_SUITES = frozenset(REVIEW34_RETIREMENT_REASONS)
if len(REVIEW34_RETIRABLE_SUITES) != 36 or REVIEW34_RETIRABLE_SUITES & RETIRABLE_SUITES:
    raise RuntimeError("review #34 must admit exactly 36 new, disjoint retirements")
KINDS = ("excluded", "phase2", "retained_adaptation_gated", "retained_support",
         "safe_pass_now", "safety_manual_gated", "retired")
MAP_PATH = "maintenance/phase2-suite-map.json"
PLAN_PATH = "maintenance/test-plan.json"
QUALIFICATION_PATH = "maintenance/qualification-plan.json"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: str | bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def _git_blob(root: Path, revision: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{revision}:{path}"],
        check=False, capture_output=True, timeout=30,
    )
    if result.returncode:
        raise ValueError(f"cannot read pinned historical object {revision}:{path}")
    return result.stdout


def _path(value, *, python=True) -> bool:
    return (isinstance(value, str) and value.startswith("tests/")
            and (not python or value.endswith(".py")) and "::" not in value
            and not PurePosixPath(value).is_absolute()
            and ".." not in PurePosixPath(value).parts
            and str(PurePosixPath(value)) == value)


def _regular(root: Path, path: str) -> Path:
    target = root / path
    current = root
    for part in PurePosixPath(path).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlink test path: {path}")
    if not target.is_file():
        raise ValueError(f"missing regular file: {path}")
    return target


def _strings(value, label: str, errors: list[str], *, empty=False) -> list[str]:
    if (not isinstance(value, list) or (not value and not empty)
            or any(not isinstance(item, str) or not item.strip() for item in value)):
        errors.append(f"{label}: expected {'possibly empty ' if empty else ''}string list")
        return []
    if len(value) != len(set(value)):
        errors.append(f"{label}: duplicate values")
    return value


def _indexed(rows, label: str, errors: list[str]) -> dict:
    if not isinstance(rows, list):
        errors.append(f"{label}: expected row list")
        return {}
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not _path(row.get("path"), python=False):
            errors.append(f"{label}: malformed/noncanonical path row")
            continue
        path = row["path"]
        if path in result:
            errors.append(f"{label}: duplicate path {path}")
        result[path] = row
    return result


def _adapter_modules(root: Path, selector: str) -> list[ast.Module]:
    """Read only test-local static import closure; never import these modules."""
    todo, seen, trees = [selector], set(), []
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(_regular(root, path).read_bytes(), filename=path)
        trees.append(tree)
        for node in ast.walk(tree):
            names = ([node.module] if isinstance(node, ast.ImportFrom)
                     and node.level == 0 and node.module else
                     [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            for name in names:
                candidate = name.replace(".", "/") + ".py"
                if candidate.startswith("tests/") and (root / candidate).is_file():
                    todo.append(candidate)
            # Follow a named import of a test-local submodule, too.
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                for alias in node.names:
                    candidate = (node.module + "." + alias.name).replace(".", "/") + ".py"
                    if candidate.startswith("tests/") and (root / candidate).is_file():
                        todo.append(candidate)
    return trees


def _full_adapter(root: Path, selector: str, path: str, inherited_hash: str) -> bool:
    """Fail-closed static full-export association for frozen corpus loaders.

    A literal admission alone is insufficient: the reachable loader must read
    frozen bytes, pin their digest, guard corpus AST identity and export the
    complete module. Runtime qualification remains the named group's job.
    """
    trees = _adapter_modules(root, selector)
    admitted = False
    pinned = False
    frozen = False
    export = False
    corpus_guard = False
    hash_guard = False
    compile_frozen = False
    invokes_loader = False
    stem = PurePosixPath(path).stem
    for tree in trees:
        constants = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = value
        selections = constants.get("CORPUS_SELECTIONS", {})
        if isinstance(selections, dict) and stem in selections:
            if selections[stem] is not None:
                return False
            admitted = True
        exclusions = constants.get("CORPUS_EXCLUSIONS", {})
        # An unrelated partial corpus in a shared loader cannot cut this suite.
        # Its own literal full admission and empty exclusions remain mandatory.
        if (not isinstance(exclusions, dict) or exclusions.get(stem)
                or any(exclusions.values()) and not isinstance(selections, dict)
                or any(value and (key not in selections or selections[key] is None)
                       for key, value in exclusions.items())):
            return False
        if (constants.get("SOURCE_PATH") == path
                and constants.get("SOURCE_SHA256") == inherited_hash):
            pinned = True
        suites = constants.get("SUITES", {})
        if isinstance(suites, dict) and suites.get(stem) == inherited_hash:
            pinned = True
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (node.func.id if isinstance(node.func, ast.Name)
                        else node.func.attr if isinstance(node.func, ast.Attribute) else "")
                frozen |= name == "frozen_source"
                export |= name == "register_module"
                compile_frozen |= name == "compile" and len(node.args) >= 3 and any(
                    isinstance(arg, ast.Constant) and arg.value == "exec" for arg in node.args)
                invokes_loader |= name == "load" and any(
                    isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                    and arg.func.id == "globals" for arg in node.args)
                if name == "register_module" and any(
                    kw.arg in {"selected", "excluded"} for kw in node.keywords
                ):
                    return False
            if isinstance(node, (ast.If, ast.Assert)):
                condition = node.test
                calls = [n for n in ast.walk(condition) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Name) and n.func.id == "corpus"]
                guards = (isinstance(node, ast.Assert) or any(
                    isinstance(n, ast.Raise) for child in node.body for n in ast.walk(child)))
                comparisons = [n for n in ast.walk(condition) if isinstance(n, ast.Compare)]
                equality = ast.Eq if isinstance(node, ast.Assert) else ast.NotEq
                correct_operator = any(any(isinstance(op, equality) for op in n.ops)
                                       for n in comparisons)
                if len(calls) >= 2 and guards and correct_operator:
                    corpus_guard = True
                hash_calls = [n for n in ast.walk(condition) if isinstance(n, ast.Call)
                              and isinstance(n.func, ast.Attribute)
                              and n.func.attr in {"sha256", "hexdigest"}]
                hash_guard |= bool(hash_calls and guards and correct_operator)
    return (admitted and pinned and frozen and export and corpus_guard and hash_guard
            and compile_frozen and invokes_loader)


def _check(root: Path, documents: dict | None = None) -> tuple[list[str], dict]:
    errors: list[str] = []
    report = {"original_population": 0, "mapped": 0, "restored": 0,
              "deferred": 0, "retired": 0, "by_step": {}, "classifications": {}}
    try:
        documents = documents or {}
        mapping, plan, qualification = (
            documents[path] if path in documents else _json((root / path).read_bytes())
            for path in (MAP_PATH, PLAN_PATH, QUALIFICATION_PATH)
        )
        historical_bytes = _git_blob(root, SOURCE_MAIN, PLAN_PATH)
        qualification_bytes = _git_blob(root, SOURCE_MAIN, QUALIFICATION_PATH)
        merged_bytes = _git_blob(root, MERGED_MAIN, QUALIFICATION_PATH)
        if (_digest(historical_bytes) != HISTORICAL_PLAN_SHA256
                or _digest(qualification_bytes) != HISTORICAL_QUALIFICATION_SHA256):
            raise ValueError("pinned historical accounting object hash changed")
        if _digest(merged_bytes) != MERGED_QUALIFICATION_SHA256:
            raise ValueError("pinned merged qualification object hash changed")
        merged_qualification = _json(merged_bytes)
        historical = _json(historical_bytes)
        historical_qualification = _json(qualification_bytes)
        if not all(isinstance(item, dict) for item in
                   (mapping, plan, qualification, historical, historical_qualification,
                    merged_qualification)):
            raise ValueError("mapping/plan/qualification must be JSON objects")
        archive_bytes = (root / "maintenance/odin-v4.13.0.tar.gz").read_bytes()
        if _digest(archive_bytes) != ARCHIVE_SHA256:
            raise ValueError("immutable original archive hash changed")
        originals = {}
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            for member in archive:
                if not member.name.startswith("tests/") or not member.isfile():
                    continue
                if not _path(member.name, python=False) or member.name in originals:
                    raise ValueError("duplicate/noncanonical original archive test path")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("unreadable original archive member")
                originals[member.name] = stream.read()
    except (OSError, ValueError, TypeError, KeyError, tarfile.TarError,
            subprocess.SubprocessError) as exc:
        return [f"input: {exc}"], report

    if type(mapping.get("schema_version")) is not int or mapping["schema_version"] != 1:
        errors.append("mapping: unsupported schema_version")
    for key, value in (("baseline", BASELINE), ("source_main", SOURCE_MAIN),
                       ("work_order", WORK_ORDER)):
        if mapping.get(key) != value:
            errors.append(f"mapping: {key} differs from pinned authority")
    population = _strings(historical.get("phase2"), "historical phase2", errors)
    expected = set(population)
    digest = _digest(("\n".join(sorted(expected)) + "\n").encode())
    if len(population) != 326 or len(expected) != 326 or digest != POPULATION_SHA256:
        errors.append("historical Phase 2 membership/hash is not the original 326")
    report["original_population"] = len(expected)
    if mapping.get("original_population") != {"count": 326, "sha256": POPULATION_SHA256}:
        errors.append("mapping: original_population count/hash mismatch")
    original_entries = _indexed(historical.get("entries"), "historical plan", errors)
    entries = _indexed(plan.get("entries"), "current test-plan", errors)
    if (
        len(originals) != 869
        or set(entries) != set(originals)
        or set(original_entries) != set(originals)
    ):
        errors.append("test-plan: exact original 869-path membership required")
    if plan.get("schema_version") != 1 or plan.get("baseline") != historical.get("baseline"):
        errors.append("test-plan: schema/baseline mismatch")
    classified = {kind: set() for kind in KINDS}
    for path, entry in entries.items():
        kind = entry.get("classification")
        if kind not in classified:
            errors.append(f"test-plan: unknown classification for {path}")
            continue
        classified[kind].add(path)
        if path not in originals:
            continue
        sha = _digest(originals[path])
        if entry.get("sha256") != sha or original_entries.get(path, {}).get("sha256") != sha:
            errors.append(f"test-plan: immutable inherited_sha256 mismatch {path}")
        if kind != "excluded" or (root / path).exists() or (root / path).is_symlink():
            try:
                if _digest(_regular(root, path).read_bytes()) != sha:
                    errors.append(f"original bytes changed: {path}")
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
    counts = plan.get("counts", {})
    if not isinstance(counts, dict):
        errors.append("test-plan: counts must be an object")
        counts = {}
    for kind, paths in classified.items():
        array = _strings(plan.get(kind), f"test-plan {kind}", errors, empty=True)
        if set(array) != paths:
            errors.append(f"test-plan: {kind} array differs from entry classifications")
        if type(counts.get(kind)) is not int or counts[kind] != len(paths):
            errors.append(f"test-plan: stale {kind} count")
    report["classifications"] = {kind: len(paths) for kind, paths in classified.items()}
    restored_array = _strings(plan.get("phase2_restored", []), "test-plan phase2_restored",
                              errors, empty=True)
    restored_paths = set(restored_array)
    retired_paths = set(_strings(plan.get("phase2_retired", []),
                                 "test-plan phase2_retired", errors, empty=True))
    if (classified["phase2"] & restored_paths or classified["phase2"] & retired_paths
            or restored_paths & retired_paths
            or classified["phase2"] | restored_paths | retired_paths != expected):
        errors.append("test-plan: phase2/restored/retired must preserve exact historical 326")
    if retired_paths != classified["retired"]:
        errors.append("test-plan: phase2_retired must match retired classification")
    if not restored_paths <= classified["safe_pass_now"]:
        errors.append("test-plan: every phase2_restored suite must be safe_pass_now")
    if "phase2_restored" in counts and (
        type(counts["phase2_restored"]) is not int
        or counts["phase2_restored"] != len(restored_paths)
    ):
        errors.append("test-plan: stale phase2_restored count")
    if "phase2_retired" in counts and (
        type(counts["phase2_retired"]) is not int
        or counts["phase2_retired"] != len(retired_paths)
    ):
        errors.append("test-plan: stale phase2_retired count")
    if set(counts) - set(KINDS) - {"phase2_restored", "phase2_retired"}:
        errors.append("test-plan: unknown classification count")

    groups = qualification.get("groups")
    old_groups = historical_qualification.get("groups", [])
    if not isinstance(groups, list):
        errors.append("qualification: groups must be a list")
        groups = []
    named = {}
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("name"), str):
            errors.append("qualification: malformed group")
            continue
        name = group["name"]
        if name in named:
            errors.append(f"qualification: duplicate group {name}")
        named[name] = group
        _strings(group.get("files"), f"qualification {name} files", errors)
    old_names = {group["name"] for group in old_groups}
    merged_groups = merged_qualification["groups"]
    merged_names = {group["name"] for group in merged_groups}
    if not old_names <= merged_names or set(named) != merged_names:
        errors.append("qualification: preserve all historical and merged main named groups")
    for group in merged_groups:
        current_files = set(named.get(group["name"], {}).get("files", []))
        missing = set(group["files"]) - current_files
        # One explicit transition replaces the old guard subset with the entire
        # frozen corpus. No other inherited selector can disappear on rebase.
        if (group["name"] == "neutral-subsystem-guard"
                and missing == {"tests/test_subsystem_guard.py"}
                and "tests/test_desktop_phase2_runtime_guard.py" in current_files):
            guard = next((row for row in mapping.get("entries", [])
                          if row.get("path") == "tests/test_subsystem_guard.py"), {})
            neutral = named[group["name"]]
            if (guard.get("status") == "restored" and guard.get("step") == 5
                    and guard.get("restoration", {}).get("mode") == "frozen-adapter"
                    and guard.get("restoration", {}).get("selectors")
                    == ["tests/test_desktop_phase2_runtime_guard.py"]
                    and not any(neutral.get(key) for key in (
                        "exclude_expression", "include_expression", "args",
                        "pytest_args", "exclusions"))
                    and _full_adapter(root, "tests/test_desktop_phase2_runtime_guard.py",
                                      "tests/test_subsystem_guard.py",
                                      original_entries["tests/test_subsystem_guard.py"]["sha256"])):
                missing.clear()
        if missing:
            errors.append(f"qualification: lost merged main selectors in {group['name']}")
    if "phase2-core-transport" not in named:
        errors.append("qualification: phase2-core-transport group missing")

    rows = mapping.get("entries")
    mapped = _indexed(rows, "mapping", errors)
    if set(mapped) != expected:
        missing, orphan = sorted(expected - set(mapped)), sorted(set(mapped) - expected)
        errors.append(f"mapping: historical membership mismatch missing={missing} orphan={orphan}")
    if isinstance(rows, list) and all(
        isinstance(row, dict) and _path(row.get("path")) for row in rows
    ):
        if [row["path"] for row in rows] != sorted(row["path"] for row in rows):
            errors.append("mapping: entries must be sorted by path")
    report["mapped"] = len(mapped)
    by_step = {str(step): {"total": 0, "restored": 0, "deferred": 0, "retired": 0}
               for step in (*range(1, 8), "Phase 3")}
    status_counts = Counter()
    mapped_restored = set()
    mapped_retired = set()
    for path, row in mapped.items():
        step, status = row.get("step"), row.get("status")
        if not (type(step) is int and 1 <= step <= 7 or step == "Phase 3"):
            errors.append(f"mapping: invalid step for {path}")
        else:
            by_step[str(step)]["total"] += 1
            if status in {"restored", "deferred", "retired"}:
                by_step[str(step)][status] += 1
        if status not in {"restored", "deferred", "retired"}:
            errors.append(f"mapping: invalid status for {path}")
            continue
        status_counts[status] += 1
        if row.get("inherited_sha256") != original_entries.get(path, {}).get("sha256"):
            errors.append(f"mapping: inherited_sha256 mismatch for {path}")
        for field in ("reason", "qualification_group"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(f"mapping: missing {field} for {path}")
        _strings(row.get("surfaces"), f"mapping {path} surfaces", errors)
        if row.get("historical_classification", "phase2") != "phase2":
            errors.append(f"mapping: historical classification changed for {path}")
        if status == "retired":
            mapped_retired.add(path)
            retirement = row.get("retirement", {})
            legacy = path in RETIRABLE_SUITES
            approved_reason = (RETIREMENT_REASONS if legacy else
                               REVIEW34_RETIREMENT_REASONS).get(path)
            approved_reviewer = RETIREMENT_REVIEWER if legacy else REVIEW34_REVIEWER
            approved_step = 1 if legacy else 5
            if (approved_reason is None or type(step) is not int or step != approved_step
                    or not isinstance(retirement, dict)
                    or retirement != {"reviewer": approved_reviewer,
                                      "reason": approved_reason}
                    or row.get("reason") != approved_reason
                    or entries.get(path, {}).get("reason") != approved_reason):
                errors.append(f"mapping: retired suite needs exact reviewed disposition: {path}")
            if path not in retired_paths or path not in classified["retired"]:
                errors.append(f"mapping: retired suite must be retired in test-plan: {path}")
            if entries.get(path, {}).get("retirement") != retirement:
                errors.append(f"mapping: retired review differs from test-plan: {path}")
            if (row.get("blocked_on", "missing") is not None or "restoration" in row
                    or row.get("qualification_group") != "not-applicable-retired"):
                errors.append(
                    f"mapping: retired suite cannot claim restoration/qualification: {path}")
            if any(any(selector == path or selector.startswith(path + "::")
                       for selector in group.get("files", [])) for group in groups):
                errors.append(f"mapping: retired suite cannot be selected as passing: {path}")
            continue
        if status == "deferred":
            if path not in classified["phase2"] or path in restored_paths:
                errors.append(f"mapping: deferred suite no longer classified phase2: {path}")
            if not isinstance(row.get("blocked_on"), str) or not row["blocked_on"].strip():
                errors.append(f"mapping: deferred suite needs clear blocker: {path}")
            if "restoration" in row:
                errors.append(f"mapping: deferred suite carries restoration: {path}")
            continue
        mapped_restored.add(path)
        if type(step) is not int or step not in {1, 5}:
            errors.append(f"mapping: restored suite must belong to merged step 1 or 5: {path}")
        if row.get("blocked_on", "missing") is not None:
            errors.append(f"mapping: restored suite must have blocked_on null: {path}")
        if path not in classified["safe_pass_now"] or path not in restored_paths:
            errors.append(
                f"mapping: restored suite must be safe_pass_now and phase2_restored: {path}"
            )
        group = named.get(row.get("qualification_group"))
        if group is None:
            errors.append(f"mapping: restored suite names nonexistent qualification group: {path}")
            continue
        if any(group.get(key) for key in ("exclude_expression", "include_expression", "args",
                                           "pytest_args", "exclusions")):
            errors.append(
                f"mapping: restored suite group cuts assertions with selection/exclusions: {path}"
            )
        restoration = row.get("restoration", {"mode": "direct-original", "selectors": [path],
                                               "reason": row.get("reason")})
        if not isinstance(restoration, dict):
            errors.append(f"mapping: malformed restoration: {path}")
            continue
        mode = restoration.get("mode")
        selectors = _strings(restoration.get("selectors"), f"restoration {path} selectors", errors)
        if not isinstance(restoration.get("reason"), str) or not restoration["reason"].strip():
            errors.append(f"mapping: restoration needs reason: {path}")
        if mode not in {"direct-original", "frozen-adapter"}:
            errors.append(f"mapping: unknown restoration mode: {path}")
        for selector in selectors:
            if not _path(selector) or selector not in group.get("files", []):
                errors.append(
                    f"mapping: whole suite selector not selected in named group: {path}: {selector}"
                )
                continue
            try:
                _regular(root, selector)
                if mode == "direct-original" and selectors != [path]:
                    errors.append(
                        f"mapping: direct-original must select entire original suite: {path}"
                    )
                if mode == "frozen-adapter" and not _full_adapter(
                    root, selector, path, row.get("inherited_sha256", "")
                ):
                    errors.append(
                        f"mapping: adapter lacks immutable full-suite corpus association: {path}"
                    )
            except (OSError, ValueError, SyntaxError, TypeError) as exc:
                errors.append(f"mapping: invalid executable association {path}: {exc}")
        for neutral in plan.get("safe_neutral_case_selections", []):
            if (
                isinstance(neutral, dict)
                and neutral.get("path") == path
                and neutral.get("exclude_expression")
            ):
                errors.append(
                    f"mapping: restored suite still has partial neutral exclusion: {path}"
                )
    if mapped_restored != restored_paths:
        errors.append("mapping: restored rows differ from phase2_restored historical marker")
    if mapped_retired != retired_paths:
        errors.append("mapping: retired rows differ from phase2_retired historical marker")
    report.update({"restored": status_counts["restored"], "deferred": status_counts["deferred"],
                   "retired": status_counts["retired"], "by_step": by_step})
    if "counts" in mapping:
        expected_counts = {"total": len(mapped), "restored": report["restored"],
                           "deferred": report["deferred"], "retired": report["retired"],
                           "by_step": by_step}
        if mapping["counts"] != expected_counts:
            errors.append("mapping: stale recomputed counts")
    return errors, report


def _evaluate(root: Path, documents: dict | None = None) -> tuple[list[str], dict]:
    try:
        return _check(root, documents)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, SyntaxError,
            subprocess.SubprocessError) as exc:
        return [f"malformed accounting input: {exc}"], {}


def validate(root: Path | str = ROOT, *, documents: dict | None = None) -> list[str]:
    """Check on-disk inputs or prospective documents against the same pinned files."""
    return _evaluate(Path(root), documents)[0]


def record_review_retirements(root: Path) -> None:
    """Record only the five explicit #26 dispositions; never run or rewrite suites."""
    mapping = _json((root / MAP_PATH).read_bytes())
    plan = _json((root / PLAN_PATH).read_bytes())
    rows = {row["path"]: row for row in mapping["entries"]}
    entries = {row["path"]: row for row in plan["entries"]}
    for path, reason in RETIREMENT_REASONS.items():
        row, entry = rows[path], entries[path]
        if (row["status"] not in {"deferred", "retired"} or row["step"] != 1
                or entry["classification"] not in {"phase2", "retired"}
                or _digest(_regular(root, path).read_bytes()) != row["inherited_sha256"]
                or entry["sha256"] != row["inherited_sha256"]):
            raise ValueError(f"retirement requires original held step-1 bytes: {path}")
    for path, reason in RETIREMENT_REASONS.items():
        row, entry = rows[path], entries[path]
        row.update(status="retired", reason=reason, blocked_on=None,
                   qualification_group="not-applicable-retired",
                   retirement={"reviewer": RETIREMENT_REVIEWER, "reason": reason})
        row.pop("pending_contract_disposition", None)
        entry.update(classification="retired", reason=reason,
                     retirement={"reviewer": RETIREMENT_REVIEWER, "reason": reason})
    plan["phase2"] = sorted(path for path in plan["phase2"] if path not in RETIRABLE_SUITES)
    plan["retired"] = plan["phase2_retired"] = sorted(RETIRABLE_SUITES)
    plan["counts"]["phase2"] = len(plan["phase2"])
    plan["counts"]["retired"] = len(plan["retired"])
    plan["execution_status"] = (
        "Historical eligibility inventory, not whole-product parity or acceptance. "
        "Nine whole inherited suites restored; five retired by Claude, review of #26, "
        "never passing. All 326 original paths remain in phase2 plus phase2_restored "
        "plus phase2_retired with original hashes. Merged main retains 30 qualification "
        "groups including phase2-step5-profile-management. Historical116/259 evidence unchanged."
    )
    # Preserve the compact one-row-per-suite map, rather than rewriting unrelated rows.
    text = (root / MAP_PATH).read_text()
    original = _json(text)
    for before, after in zip(original["entries"], mapping["entries"], strict=True):
        if before != after:
            compact = json.dumps(before, separators=(",", ":"))
            if compact in text:
                text = text.replace(compact, json.dumps(after, separators=(",", ":")), 1)
            else:
                text = text.replace(json.dumps(before), json.dumps(after), 1)
    if _json(text) != mapping:
        raise ValueError("suite map compact serialization changed; no data written")
    for path, content in ((MAP_PATH, text), (PLAN_PATH, json.dumps(plan, indent=2) + "\n")):
        target = root / path
        replacement = target.with_suffix(target.suffix + ".tmp")
        replacement.write_text(content)
        replacement.replace(target)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "report", "record-review-retirements"),
                        nargs="?", default="check")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if args.command == "record-review-retirements":
        record_review_retirements(args.root)
    errors, counters = _evaluate(args.root)
    print(json.dumps({"command": args.command, "valid": not errors,
                      "errors": errors, "counts": counters}, indent=2, sort_keys=True))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
