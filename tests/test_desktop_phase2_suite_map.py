"""Offline accounting mutations, without engine imports or native execution."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts.maintenance import phase2_suites as checker

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def historical():
    return {path: subprocess.check_output(
        ["git", "-C", str(ROOT), "show", f"{checker.SOURCE_MAIN}:{path}"]
    ) for path in (checker.PLAN_PATH, checker.QUALIFICATION_PATH)}


@pytest.fixture(scope="session")
def merged():
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "show", f"{checker.MERGED_MAIN}:{checker.QUALIFICATION_PATH}"]
    )


def _write(root, path, data):
    target = root / path
    replacement = target.with_suffix(target.suffix + ".tmp")
    replacement.write_text(json.dumps(data))
    replacement.replace(target)


def _read(root, path):
    return json.loads((root / path).read_text())


@pytest.fixture(scope="session")
def template(tmp_path_factory, historical, merged):
    root = tmp_path_factory.mktemp("phase2-suite-map-offline")
    (root / "maintenance").mkdir()
    archive = ROOT / "maintenance/odin-v4.13.0.tar.gz"
    shutil.copyfile(archive, root / "maintenance/odin-v4.13.0.tar.gz")
    with tarfile.open(archive) as frozen:
        for member in frozen:
            if member.isfile() and member.name.startswith("tests/"):
                target = root / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(frozen.extractfile(member).read())
    plan = json.loads(historical[checker.PLAN_PATH])
    hashes = {row["path"]: row["sha256"] for row in plan["entries"]}
    mapping = {
        "schema_version": 1, "baseline": checker.BASELINE,
        "source_main": checker.SOURCE_MAIN, "work_order": checker.WORK_ORDER,
        "original_population": {"count": 326, "sha256": checker.POPULATION_SHA256},
        "entries": [{"path": path, "inherited_sha256": hashes[path], "step": 1,
                     "reason": "Offline complete historical suite fixture",
                     "surfaces": ["neutral offline fixture"],
                     "qualification_group": "phase2-core-transport",
                     "status": "deferred", "blocked_on": "Explicit adapter still required"}
                    for path in sorted(plan["phase2"])],
    }
    plan["phase2_restored"] = []
    plan["retired"] = []
    plan["counts"]["retired"] = 0
    _write(root, checker.MAP_PATH, mapping)
    _write(root, checker.PLAN_PATH, plan)
    _write(root, checker.QUALIFICATION_PATH, json.loads(merged))
    return root


@pytest.fixture
def repo(tmp_path, template, historical, merged, monkeypatch):
    root = tmp_path / "repo"
    shutil.copytree(template, root, copy_function=os.link)
    monkeypatch.setattr(checker, "_git_blob", lambda root, revision, path:
                        merged if revision == checker.MERGED_MAIN else historical[path])
    return root


def _restore(root, *, adapter=False):
    mapping = _read(root, checker.MAP_PATH)
    plan = _read(root, checker.PLAN_PATH)
    qualification = _read(root, checker.QUALIFICATION_PATH)
    row = mapping["entries"][0]
    path = row["path"]
    row.update(status="restored", blocked_on=None, historical_classification="phase2")
    plan["phase2"].remove(path)
    plan["phase2_restored"].append(path)
    plan["safe_pass_now"].append(path)
    plan["counts"]["phase2"] -= 1
    plan["counts"]["safe_pass_now"] += 1
    next(entry for entry in plan["entries"] if entry["path"] == path)["classification"] = (
        "safe_pass_now"
    )
    selector = path
    if adapter:
        selector = "tests/test_desktop_frozen_fixture.py"
        # Parsed only. A failing import makes accidental runtime loading clear.
        (root / selector).write_text(
            "raise RuntimeError('checker must never import adapters')\n"
            f"SOURCE_PATH = {path!r}\nSOURCE_SHA256 = {row['inherited_sha256']!r}\n"
            f"CORPUS_SELECTIONS = {{{Path(path).stem!r}: None}}\n"
            "CORPUS_EXCLUSIONS = {}\n"
            "def load(namespace):\n"
            "    source = frozen_source(SOURCE_PATH)\n"
            "    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:\n"
            "        raise ValueError('hash drift')\n"
            "    original = ast.parse(source)\n"
            "    adapted = copy.deepcopy(original)\n"
            "    if corpus(original) != corpus(adapted):\n"
            "        raise ValueError('assertion drift')\n"
            "    exec(compile(adapted, SOURCE_PATH, 'exec'), module.__dict__)\n"
            "    register_module(namespace, module)\n"
            "load(globals())\n"
        )
    row["restoration"] = {"mode": "frozen-adapter" if adapter else "direct-original",
                          "selectors": [selector], "reason": "Whole immutable suite"}
    next(group for group in qualification["groups"]
         if group["name"] == "phase2-core-transport")["files"].append(selector)
    for filename, value in ((checker.MAP_PATH, mapping), (checker.PLAN_PATH, plan),
                            (checker.QUALIFICATION_PATH, qualification)):
        _write(root, filename, value)
    return path, selector


def test_complete_offline_historical_mapping_is_valid(repo):
    assert checker.validate(repo) == []


@pytest.mark.parametrize("adapter", [False, True])
def test_whole_suite_restore_preserves_membership_and_counts(repo, adapter, capsys):
    _restore(repo, adapter=adapter)
    assert checker.validate(repo) == []
    assert checker.main(["report", "--root", str(repo)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["errors"] == []
    assert report["counts"]["mapped"] == report["counts"]["original_population"] == 326
    assert report["counts"]["restored"] == 1
    assert report["counts"]["deferred"] == 325
    assert report["counts"]["by_step"]["1"] == {
        "total": 326, "restored": 1, "deferred": 325, "retired": 0,
    }


@pytest.mark.parametrize("adapter", [False, True])
@pytest.mark.parametrize("step", [5, 6])
def test_later_whole_suite_restore_preserves_original_ownership(repo, adapter, step):
    path, _ = _restore(repo, adapter=adapter)
    mapping = _read(repo, checker.MAP_PATH)
    next(row for row in mapping["entries"] if row["path"] == path)["step"] = step
    _write(repo, checker.MAP_PATH, mapping)
    assert checker.validate(repo) == []
    errors, report = checker._evaluate(repo)
    assert errors == []
    assert report["by_step"][str(step)] == {
        "total": 1, "restored": 1, "deferred": 0, "retired": 0,
    }


def _restore_step6_case_adapter(repo):
    import ast
    import hashlib

    path, selector = _restore(repo, adapter=True)
    mapping = _read(repo, checker.MAP_PATH)
    row = next(row for row in mapping["entries"] if row["path"] == path)
    row["step"] = 6
    row["restoration"]["mode"] = "frozen-case-adapter"
    case, node = next(iter(checker._case_nodes((repo / path).read_bytes()).items()))
    row["case_retirements"] = [{
        "case": case,
        "source_sha256": hashlib.sha256(ast.dump(
            node, include_attributes=False).encode()).hexdigest(),
        "reviewer": checker.STEP6_RETIREMENT_REVIEWER,
        "surface": "Discord", "reason": "Removed Discord transport fixture case.",
    }]
    _write(repo, checker.MAP_PATH, mapping)
    target = repo / selector
    target.write_text(target.read_text().replace(
        "CORPUS_EXCLUSIONS = {}", f"CORPUS_EXCLUSIONS = {{{Path(path).stem!r}: [{case!r}]}}"))
    return path, selector, case


def test_step6_case_retirement_requires_complete_bound_partition(repo):
    _restore_step6_case_adapter(repo)
    assert checker.validate(repo) == []


def test_only_named_step6_groups_can_extend_historical_qualification(repo):
    qualification = _read(repo, checker.QUALIFICATION_PATH)
    qualification["groups"].append({
        "name": "phase2-step6-lane6-providers",
        "files": ["tests/test_context_budget_activation.py"],
        "reason": "Exact frozen step6 provider corpus through the canonical owner.",
    })
    _write(repo, checker.QUALIFICATION_PATH, qualification)
    assert checker.validate(repo) == []


def test_shared_adapter_retirement_does_not_cut_an_unrelated_suite(repo):
    path, selector = _restore(repo, adapter=True)
    target = repo / selector
    target.write_text(target.read_text().replace(
        "CORPUS_EXCLUSIONS = {}",
        "CORPUS_EXCLUSIONS = {'test_unrelated': ['TestOld.test_removed_transport']}"))
    assert checker.validate(repo) == []
    # A cut of the mapped suite without its bound retirement remains rejected.
    target.write_text(target.read_text().replace(
        "'test_unrelated'", repr(Path(path).stem)))
    assert checker.validate(repo)


@pytest.mark.parametrize("mutation", ["hash", "reviewer", "surface", "case", "duplicate",
                                      "missing", "undeclared", "wrong_step", "full_mode"])
def test_step6_case_retirement_mutations_fail_closed(repo, mutation):
    path, selector, case = _restore_step6_case_adapter(repo)
    mapping = _read(repo, checker.MAP_PATH)
    row = next(row for row in mapping["entries"] if row["path"] == path)
    declaration = row["case_retirements"][0]
    if mutation == "hash":
        declaration["source_sha256"] = "0" * 64
    elif mutation == "reviewer":
        declaration["reviewer"] = "pending"
    elif mutation == "surface":
        declaration["surface"] = "canonical owner not built"
    elif mutation == "case":
        declaration["case"] = "TestMissing.test_missing"
    elif mutation == "duplicate":
        row["case_retirements"].append(copy.deepcopy(declaration))
    elif mutation == "missing":
        row.pop("case_retirements")
    elif mutation == "undeclared":
        target = repo / selector
        target.write_text(target.read_text().replace(f"[{case!r}]", "[]"))
    elif mutation == "wrong_step":
        row["step"] = 5
    else:
        row["restoration"]["mode"] = "frozen-adapter"
    _write(repo, checker.MAP_PATH, mapping)
    assert checker.validate(repo)


@pytest.mark.parametrize("mutation", [
    "missing", "duplicate", "orphan", "unsorted", "wrong_hash", "wrong_baseline",
    "wrong_main", "wrong_work_order", "wrong_population", "string_step", "step8",
    "bool_step", "no_reason", "empty_surfaces", "no_group", "no_blocker", "status",
    "historical_classification", "no_phase2_member", "duplicate_top_array",
    "stale_count", "wrong_classification", "missing869", "original_changed",
    "missing_original", "symlink_original", "extra_group", "renamed_group",
    "duplicate_group", "malformed_schema", "duplicate_json_key", "map_counts",
])
def test_accounting_mutations_fail_closed(repo, mutation):
    mapping = _read(repo, checker.MAP_PATH)
    plan = _read(repo, checker.PLAN_PATH)
    qualification = _read(repo, checker.QUALIFICATION_PATH)
    row = mapping["entries"][0]
    path = row["path"]
    if mutation == "missing":
        mapping["entries"].pop()
    elif mutation == "duplicate":
        mapping["entries"].append(copy.deepcopy(row))
    elif mutation == "orphan":
        row["path"] = "tests/test_orphan.py"
    elif mutation == "unsorted":
        mapping["entries"].reverse()
    elif mutation == "wrong_hash":
        row["inherited_sha256"] = "0" * 64
    elif mutation == "wrong_baseline":
        mapping["baseline"] = "other"
    elif mutation == "wrong_main":
        mapping["source_main"] = "other"
    elif mutation == "wrong_work_order":
        mapping["work_order"] = "other"
    elif mutation == "wrong_population":
        mapping["original_population"]["sha256"] = "0" * 64
    elif mutation == "string_step":
        row["step"] = "1"
    elif mutation == "step8":
        row["step"] = 8
    elif mutation == "bool_step":
        row["step"] = True
    elif mutation == "no_reason":
        row["reason"] = " "
    elif mutation == "empty_surfaces":
        row["surfaces"] = []
    elif mutation == "no_group":
        row["qualification_group"] = ""
    elif mutation == "no_blocker":
        row["blocked_on"] = None
    elif mutation == "status":
        row["status"] = "passed"
    elif mutation == "historical_classification":
        row["historical_classification"] = "safe_pass_now"
    elif mutation == "no_phase2_member":
        plan["phase2"].remove(path)
    elif mutation == "duplicate_top_array":
        plan["phase2"].append(path)
    elif mutation == "stale_count":
        plan["counts"]["phase2"] = 325
    elif mutation == "wrong_classification":
        next(e for e in plan["entries"] if e["path"] == path)["classification"] = "safe_pass_now"
    elif mutation == "missing869":
        plan["entries"].pop()
    elif mutation == "original_changed":
        target = repo / path
        target.unlink()
        target.write_text("def test_weakened():\n    assert True\n")
    elif mutation == "missing_original":
        (repo / path).unlink()
    elif mutation == "symlink_original":
        target = repo / path
        target.unlink()
        target.symlink_to(ROOT / path)
    elif mutation == "extra_group":
        qualification["groups"].append({"name": "thirtieth", "files": [path]})
    elif mutation == "renamed_group":
        qualification["groups"][0]["name"] = "different"
    elif mutation == "duplicate_group":
        qualification["groups"][-1]["name"] = qualification["groups"][0]["name"]
    elif mutation == "malformed_schema":
        mapping["schema_version"] = True
    elif mutation == "map_counts":
        mapping["counts"] = {"total": 326, "restored": 326, "deferred": 0}
    for filename, value in ((checker.MAP_PATH, mapping), (checker.PLAN_PATH, plan),
                            (checker.QUALIFICATION_PATH, qualification)):
        _write(repo, filename, value)
    if mutation == "duplicate_json_key":
        (repo / checker.MAP_PATH).write_text('{"schema_version":1,"schema_version":1}')
    assert checker.validate(repo), mutation


@pytest.mark.parametrize("mutation", [
    "late_step", "restored_blocker", "not_safe", "lost_marker", "not_real_group",
    "not_selected", "case_selector", "exclude_k", "partial_neutral", "bad_mode",
    "adapter_is_original", "adapter_subset", "adapter_exclusion", "adapter_hash",
    "adapter_no_guard", "adapter_no_export", "adapter_no_frozen_read",
    "adapter_inverted_guard", "adapter_no_hash_guard", "adapter_not_invoked",
    "adapter_no_compile",
])
def test_restore_cannot_claim_a_subset_or_unqualified_whole_suite(repo, mutation):
    adapter = mutation.startswith("adapter_") and mutation != "adapter_is_original"
    path, selector = _restore(repo, adapter=adapter)
    mapping = _read(repo, checker.MAP_PATH)
    plan = _read(repo, checker.PLAN_PATH)
    qualification = _read(repo, checker.QUALIFICATION_PATH)
    row = mapping["entries"][0]
    group = next(g for g in qualification["groups"] if g["name"] == "phase2-core-transport")
    if mutation == "late_step":
        row["step"] = 2
    elif mutation == "restored_blocker":
        row["blocked_on"] = "not yet"
    elif mutation == "not_safe":
        next(e for e in plan["entries"] if e["path"] == path)["classification"] = "phase2"
    elif mutation == "lost_marker":
        plan["phase2_restored"] = []
    elif mutation == "not_real_group":
        row["qualification_group"] = "imaginary"
    elif mutation == "not_selected":
        group["files"].remove(selector)
    elif mutation == "case_selector":
        row["restoration"]["selectors"] = [path + "::test_only_one"]
    elif mutation == "exclude_k":
        group["exclude_expression"] = "one_original_assertion"
    elif mutation == "partial_neutral":
        plan.setdefault("safe_neutral_case_selections", []).append(
            {"path": path, "exclude_expression": "one_case"}
        )
    elif mutation == "bad_mode":
        row["restoration"]["mode"] = "new_smoke_test"
    elif mutation == "adapter_is_original":
        row["restoration"]["mode"] = "frozen-adapter"
    else:
        target = repo / selector
        source = target.read_text()
        if mutation == "adapter_subset":
            source = source.replace(": None}", ": ['test_one']}")
        elif mutation == "adapter_exclusion":
            source = source.replace(
                "CORPUS_EXCLUSIONS = {}",
                f"CORPUS_EXCLUSIONS = {{{Path(path).stem!r}: ['test_one']}}",
            )
        elif mutation == "adapter_hash":
            source = source.replace(row["inherited_sha256"], "0" * 64)
        elif mutation == "adapter_no_guard":
            source = source.replace("if corpus(original) != corpus(adapted):", "if False:")
        elif mutation == "adapter_no_export":
            source = source.replace("register_module(namespace, module)", "pass")
        elif mutation == "adapter_no_frozen_read":
            source = source.replace("frozen_source(SOURCE_PATH)", "b''")
        elif mutation == "adapter_inverted_guard":
            source = source.replace(
                "corpus(original) != corpus(adapted)", "corpus(original) == corpus(adapted)"
            )
        elif mutation == "adapter_no_hash_guard":
            source = source.replace("hashlib.sha256(source).hexdigest() != SOURCE_SHA256", "False")
        elif mutation == "adapter_not_invoked":
            source = source.replace("load(globals())", "pass")
        elif mutation == "adapter_no_compile":
            source = source.replace(
                "exec(compile(adapted, SOURCE_PATH, 'exec'), module.__dict__)", "pass"
            )
        target.write_text(source)
    for filename, value in ((checker.MAP_PATH, mapping), (checker.PLAN_PATH, plan),
                            (checker.QUALIFICATION_PATH, qualification)):
        _write(repo, filename, value)
    assert checker.validate(repo), mutation


def test_check_cli_returns_json_errors_and_nonzero_on_missing_input(tmp_path, capsys):
    assert checker.main(["check", "--root", str(tmp_path)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["errors"] and result["valid"] is False


def test_pinned_history_is_required_not_a_rewritten_current_plan(repo, monkeypatch):
    def unavailable(*args):
        raise ValueError("missing pinned history")
    monkeypatch.setattr(checker, "_git_blob", unavailable)
    assert any("missing pinned history" in error for error in checker.validate(repo))


def test_live_accounting_artifact_is_complete_and_coherent():
    assert checker.validate(ROOT) == []


def test_phase3_is_a_handoff_not_a_restore(repo):
    mapping = _read(repo, checker.MAP_PATH)
    mapping["entries"][0]["step"] = "Phase 3"
    _write(repo, checker.MAP_PATH, mapping)
    assert checker.validate(repo) == []


def test_equal_population_size_cannot_substitute_historical_member(repo):
    mapping = _read(repo, checker.MAP_PATH)
    plan = _read(repo, checker.PLAN_PATH)
    orphan = next(path for path in plan["safe_pass_now"] if path not in plan["phase2"])
    mapping["entries"][0]["path"] = orphan
    _write(repo, checker.MAP_PATH, mapping)
    assert any("membership mismatch" in error for error in checker.validate(repo))


def test_historical_plan_is_hashed_independently(repo, historical, merged, monkeypatch):
    rewritten = json.loads(historical[checker.PLAN_PATH])
    rewritten["phase2"][0] = "tests/test_reclassified.py"
    monkeypatch.setattr(
        checker, "_git_blob",
        lambda root, revision, path:
        merged if revision == checker.MERGED_MAIN else
        json.dumps(rewritten).encode() if path == checker.PLAN_PATH else historical[path],
    )
    assert any("historical accounting object hash changed" in error
               for error in checker.validate(repo))


def test_review_retirements_preserve_bytes_membership_and_are_idempotent(repo):
    originals = {path: (repo / path).read_bytes() for path in checker.RETIRABLE_SUITES}
    checker.record_review_retirements(repo)
    assert checker.validate(repo) == []
    snapshot = [(repo / path).read_bytes() for path in (checker.MAP_PATH, checker.PLAN_PATH)]
    checker.record_review_retirements(repo)
    assert snapshot == [(repo / path).read_bytes()
                        for path in (checker.MAP_PATH, checker.PLAN_PATH)]
    for path, original in originals.items():
        assert (repo / path).read_bytes() == original
    errors, report = checker._evaluate(repo)
    assert errors == []
    assert (report["restored"], report["deferred"], report["retired"]) == (0, 321, 5)
    plan = _read(repo, checker.PLAN_PATH)
    assert set(plan["retired"]) == checker.RETIRABLE_SUITES
    assert set(plan["retired"]).isdisjoint(plan["safe_pass_now"])


@pytest.mark.parametrize("mutation", [
    "reviewer", "reason", "restoration", "group", "selected", "selected_case",
    "safe", "marker", "hash", "step", "count", "classification", "unreviewed_path",
])
def test_retirement_cannot_be_unreviewed_or_claim_passing(repo, mutation):
    checker.record_review_retirements(repo)
    mapping, plan, qualification = (_read(repo, path) for path in
                                  (checker.MAP_PATH, checker.PLAN_PATH,
                                   checker.QUALIFICATION_PATH))
    row = next(row for row in mapping["entries"] if row["status"] == "retired")
    path = row["path"]
    if mutation == "reviewer":
        row["retirement"]["reviewer"] = "Claude"
    elif mutation == "reason":
        row["retirement"]["reason"] = " "
    elif mutation == "restoration":
        row["restoration"] = {"mode": "direct-original", "selectors": [path]}
    elif mutation == "group":
        row["qualification_group"] = "phase2-core-transport"
    elif mutation in {"selected", "selected_case"}:
        qualification["groups"][0]["files"].append(
            path if mutation == "selected" else path + "::test_one")
    elif mutation == "safe":
        plan["safe_pass_now"].append(path)
    elif mutation == "marker":
        plan["phase2_retired"].remove(path)
    elif mutation == "hash":
        row["inherited_sha256"] = "0" * 64
    elif mutation == "step":
        row["step"] = 5
    elif mutation == "count":
        plan["counts"]["retired"] = 0
    elif mutation == "classification":
        next(entry for entry in plan["entries"] if entry["path"] == path)["classification"] = (
            "retained_support")
    elif mutation == "unreviewed_path":
        row["path"] = "tests/test_unreviewed_retirement.py"
    for filename, value in ((checker.MAP_PATH, mapping), (checker.PLAN_PATH, plan),
                            (checker.QUALIFICATION_PATH, qualification)):
        _write(repo, filename, value)
    assert checker.validate(repo), mutation


@pytest.mark.parametrize("mutation", ["missing_step5", "lost_selector", "rewritten_pin"])
def test_merged_main_group_and_selectors_are_preserved(
    repo, historical, merged, monkeypatch, mutation,
):
    qualification = _read(repo, checker.QUALIFICATION_PATH)
    group = next(g for g in qualification["groups"]
                 if g["name"] == "phase2-step5-profile-management")
    if mutation == "missing_step5":
        qualification["groups"].remove(group)
    elif mutation == "lost_selector":
        group["files"].pop()
    else:
        monkeypatch.setattr(checker, "_git_blob", lambda root, revision, path:
                            merged + b" " if revision == checker.MERGED_MAIN else historical[path])
    _write(repo, checker.QUALIFICATION_PATH, qualification)
    assert checker.validate(repo)


def _step6a_group(root):
    qualification = _read(root, checker.QUALIFICATION_PATH)
    group = {
        "name": "phase2-step6a-qualified-local-services",
        "files": [
            "tests/test_desktop_skills.py", "tests/test_desktop_mcp.py",
            "tests/test_desktop_browser_runtime.py", "tests/test_desktop_computer_binding.py",
            "tests/test_desktop_dependency_resolver.py", "tests/test_desktop_service_catalog.py",
            "tests/test_desktop_services_core.py", "tests/test_desktop_workspace_diagnostics.py",
        ],
        "reason": (
            "Step 6A real skill lifecycle/schema/dependency installation, supervised configured "
            "MCP, bundled Chromium startup, bounded local workspace diagnostics and authentic "
            "computer management/recovery. Pip, keyring, network, browser and native backends "
            "stubbed; benign disposable git only. No foreground/delivery/work/schedule "
            "implementation or native qualification claim. Immutable GI original cases run "
            "in the direct group through the worker-only resolver adapter without assertion "
            "edits. All engine suites remain isolated PID namespace with throwaway HOME."
        ),
    }
    for path in group["files"]:
        shutil.copyfile(ROOT / path, root / path)
    qualification["groups"].append(group)
    _write(root, checker.QUALIFICATION_PATH, qualification)
    return group


ADAPTER_ASSOCIATIONS = (
    ("direct-shared-stores-providers-tools", "tests/test_gi_support_loading.py",
     "tests/test_desktop_gi_loading_adaptation.py"),
    ("direct-shared-computer", "tests/test_computer_runtime_coverage_r10.py",
     "tests/test_desktop_accessibility_gi_adaptation.py"),
)


def _replace_gi_selector(root, association):
    name, original, adapter = association
    qualification = _read(root, checker.QUALIFICATION_PATH)
    group = next(group for group in qualification["groups"] if group["name"] == name)
    group["files"][group["files"].index(original)] = adapter
    shutil.copyfile(ROOT / adapter, root / adapter)
    _write(root, checker.QUALIFICATION_PATH, qualification)


def test_exact_reviewed_step6a_group_and_both_adapters_are_permitted(repo):
    _step6a_group(repo)
    assert checker.validate(repo) == []
    for association in ADAPTER_ASSOCIATIONS:
        _replace_gi_selector(repo, association)
        assert checker.validate(repo) == []


@pytest.mark.parametrize("mutation", [
    "unknown_group", "renamed_group", "missing_file", "extra_file", "case_selector",
    "reason", "duplicate_file", "exclude_expression", "args", "missing_regular",
    "symlink_file",
])
def test_reviewed_step6a_group_is_not_a_generic_addition_waiver(repo, mutation):
    reviewed = _step6a_group(repo)
    qualification = _read(repo, checker.QUALIFICATION_PATH)
    group = qualification["groups"][-1]
    path = group["files"][0]
    if mutation == "unknown_group":
        qualification["groups"].append({"name": "unreviewed", "files": [path]})
    elif mutation == "renamed_group":
        group["name"] += "-renamed"
    elif mutation == "missing_file":
        group["files"].pop()
    elif mutation == "extra_file":
        group["files"].append("tests/test_desktop_unreviewed.py")
    elif mutation == "case_selector":
        group["files"][0] += "::test_one"
    elif mutation == "reason":
        group["reason"] = "Generic Phase 2 waiver"
    elif mutation == "duplicate_file":
        group["files"].append(path)
    elif mutation in {"exclude_expression", "args"}:
        group[mutation] = "test_one"
    elif mutation == "missing_regular":
        (repo / path).unlink()
    elif mutation == "symlink_file":
        (repo / path).unlink()
        (repo / path).symlink_to(ROOT / path)
    _write(repo, checker.QUALIFICATION_PATH, qualification)
    assert checker.validate(repo), (mutation, reviewed)


@pytest.mark.parametrize("association", ADAPTER_ASSOCIATIONS)
def test_reviewed_adapters_are_independently_permitted_without_new_group(repo, association):
    _replace_gi_selector(repo, association)
    assert checker.validate(repo) == []


@pytest.mark.parametrize("association", ADAPTER_ASSOCIATIONS)
@pytest.mark.parametrize("mutation", [
    "corrupt_adapter", "missing_adapter", "symlink_adapter", "corrupt_original",
    "missing_original", "wrong_adapter", "drop_adapter", "drop_other_selector",
    "wrong_group", "duplicate_association", "both_selectors", "exclude_expression",
    "include_expression", "args", "pytest_args", "exclusions",
])
def test_reviewed_gi_replacements_cannot_weaken_merged_suites(repo, association, mutation):
    name, original, adapter = association
    _replace_gi_selector(repo, association)
    qualification = _read(repo, checker.QUALIFICATION_PATH)
    group = next(group for group in qualification["groups"] if group["name"] == name)
    if mutation == "corrupt_adapter":
        with (repo / adapter).open("a") as stream:
            stream.write("\n# unreviewed adapter drift\n")
    elif mutation == "missing_adapter":
        (repo / adapter).unlink()
    elif mutation == "symlink_adapter":
        (repo / adapter).unlink()
        (repo / adapter).symlink_to(ROOT / adapter)
    elif mutation == "corrupt_original":
        (repo / original).unlink()  # Do not mutate the hard-linked immutable template.
        (repo / original).write_text("def test_weakened():\n    assert True\n")
    elif mutation == "missing_original":
        (repo / original).unlink()
    elif mutation == "wrong_adapter":
        unknown = "tests/test_unreviewed_adapter.py"
        shutil.copyfile(repo / adapter, repo / unknown)
        group["files"][group["files"].index(adapter)] = unknown
    elif mutation == "drop_adapter":
        group["files"].remove(adapter)
    elif mutation == "drop_other_selector":
        group["files"].remove(next(path for path in group["files"] if path != adapter))
    elif mutation in {"wrong_group", "duplicate_association"}:
        other = next(group for group in qualification["groups"]
                     if group["name"] == "phase2-core-transport")
        other["files"].append(adapter)
        if mutation == "wrong_group":
            group["files"].remove(adapter)
    elif mutation == "both_selectors":
        group["files"].append(original)
    else:
        group[mutation] = "test_one"
    _write(repo, checker.QUALIFICATION_PATH, qualification)
    assert checker.validate(repo), (association, mutation)
