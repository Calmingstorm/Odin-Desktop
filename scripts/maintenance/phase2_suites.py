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
KINDS = ("excluded", "phase2", "retained_adaptation_gated", "retained_support",
         "safe_pass_now", "safety_manual_gated", "retired")
MAP_PATH = "maintenance/phase2-suite-map.json"
PLAN_PATH = "maintenance/test-plan.json"
QUALIFICATION_PATH = "maintenance/qualification-plan.json"

# Reviewed PR28 additions only. These are byte-pinned full original imports,
# not the generic frozen-adapter protocol used by Phase 2 restorations.
STEP6A_GROUP = "phase2-step6a-qualified-local-services"
STEP6A_FILES = frozenset({
    "tests/test_desktop_skills.py", "tests/test_desktop_mcp.py",
    "tests/test_desktop_browser_runtime.py", "tests/test_desktop_computer_binding.py",
    "tests/test_desktop_dependency_resolver.py", "tests/test_desktop_service_catalog.py",
    "tests/test_desktop_services_core.py", "tests/test_desktop_workspace_diagnostics.py",
})
STEP6A_REASON = (
    "Step 6A real skill lifecycle/schema/dependency installation, supervised configured MCP, "
    "bundled Chromium startup, bounded local workspace diagnostics and authentic computer "
    "management/recovery. Pip, keyring, network, browser and native backends stubbed; benign "
    "disposable git only. No foreground/delivery/work/schedule implementation or native "
    "qualification claim. Immutable GI original cases run in the direct group through the "
    "worker-only resolver adapter without assertion edits. All engine suites remain isolated "
    "PID namespace with throwaway HOME."
)
MERGED_SELECTOR_ADAPTERS = {
    "direct-shared-stores-providers-tools": (
        "tests/test_gi_support_loading.py", "tests/test_desktop_gi_loading_adaptation.py",
        "18488dd73087297c17291811744e770730d866d338f563cd3490a411f1e24b8b",
    ),
    "direct-shared-computer": (
        "tests/test_computer_runtime_coverage_r10.py",
        "tests/test_desktop_accessibility_gi_adaptation.py",
        "01f8d63a5d5c6f6fa596209fc29623a7a9f344e9475e134a86974bb4d3192955",
    ),
}


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
        if not isinstance(exclusions, dict) or any(exclusions.values()):
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


def _check(root: Path) -> tuple[list[str], dict]:
    errors: list[str] = []
    report = {"original_population": 0, "mapped": 0, "restored": 0,
              "deferred": 0, "retired": 0, "by_step": {}, "classifications": {}}
    try:
        mapping = _json((root / MAP_PATH).read_bytes())
        plan = _json((root / PLAN_PATH).read_bytes())
        qualification = _json((root / QUALIFICATION_PATH).read_bytes())
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
    additions = set(named) - merged_names
    if (not old_names <= merged_names or not merged_names <= set(named)
            or additions - {STEP6A_GROUP}):
        errors.append("qualification: preserve all historical and merged main named groups")
    if STEP6A_GROUP in named:
        group = named[STEP6A_GROUP]
        if (set(group) != {"name", "files", "reason"}
                or set(group.get("files", [])) != STEP6A_FILES
                or group.get("reason") != STEP6A_REASON):
            errors.append(f"qualification: exact reviewed files/reason required for {STEP6A_GROUP}")
        for selector in STEP6A_FILES:
            try:
                _regular(root, selector)
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
    replacements = {}
    for name, (original, adapter, sha) in MERGED_SELECTOR_ADAPTERS.items():
        selected_by = {group_name for group_name, group in named.items()
                       if adapter in group.get("files", [])}
        if not selected_by:
            continue
        group = named.get(name, {})
        if (selected_by != {name} or original in group.get("files", [])
                or any(group.get(key) for key in (
                    "exclude_expression", "include_expression", "args", "pytest_args",
                    "exclusions"))):
            errors.append(
                f"qualification: exact full-suite adapter association required for {adapter}")
            continue
        try:
            if _digest(_regular(root, adapter).read_bytes()) != sha:
                raise ValueError(f"reviewed adapter bytes changed: {adapter}")
            if _regular(root, original).read_bytes() != originals[original]:
                raise ValueError(f"adapter original bytes changed: {original}")
        except (OSError, ValueError, KeyError) as exc:
            errors.append(str(exc))
            continue
        replacements[name] = (original, adapter)
    for group in merged_groups:
        required = set(group["files"])
        if group["name"] in replacements:
            original, adapter = replacements[group["name"]]
            required.remove(original)
            required.add(adapter)
        if not required <= set(named.get(group["name"], {}).get("files", [])):
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
            if (path not in RETIRABLE_SUITES or type(step) is not int or step != 1
                    or not isinstance(retirement, dict)
                    or retirement.get("reviewer") != RETIREMENT_REVIEWER
                    or retirement.get("reason") != RETIREMENT_REASONS.get(path)):
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
    case_manifest = root / "maintenance/phase2-step8-part5-cases.json"
    if case_manifest.exists() or mapping.get("case_dispositions"):
        try:
            from scripts.maintenance import phase2_part5
        except ModuleNotFoundError:
            import phase2_part5
        case_errors, case_report = phase2_part5.validate(root)
        errors.extend(f"part5 cases: {error}" for error in case_errors)
        report["part5_case_dispositions"] = case_report
    return errors, report


def _evaluate(root: Path) -> tuple[list[str], dict]:
    try:
        return _check(root)
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            subprocess.SubprocessError) as exc:
        return [f"malformed accounting input: {exc}"], {}


def validate(root: Path | str = ROOT) -> list[str]:
    """Return all detected mapping/accounting errors; an empty list is valid."""
    return _evaluate(Path(root))[0]


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
