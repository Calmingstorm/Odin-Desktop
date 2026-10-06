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


def _restore(root, *, adapter=False, source_path=None):
    mapping = _read(root, checker.MAP_PATH)
    plan = _read(root, checker.PLAN_PATH)
    qualification = _read(root, checker.QUALIFICATION_PATH)
    row = (mapping["entries"][0] if source_path is None else
           next(row for row in mapping["entries"] if row["path"] == source_path))
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
        row["step"] = 6
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
                "CORPUS_EXCLUSIONS = {}", "CORPUS_EXCLUSIONS = {'suite': ['test_one']}"
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


@pytest.mark.parametrize("step", [2, 3, 4])
@pytest.mark.parametrize("adapter", [False, True])
def test_restored_steps_two_to_four_require_complete_owning_group(repo, step, adapter):
    path, selector = _restore(repo, adapter=adapter)
    mapping = _read(repo, checker.MAP_PATH)
    qualification = _read(repo, checker.QUALIFICATION_PATH)
    row = mapping["entries"][0]
    row["step"] = step
    _write(repo, checker.MAP_PATH, mapping)
    assert checker.validate(repo)
    row["qualification_group"] = checker.RESTORATION_GROUPS[step]
    next(group for group in qualification["groups"]
         if group["name"] == "phase2-core-transport")["files"].remove(selector)
    qualification["groups"].append({
        "name": row["qualification_group"], "files": [selector],
    })
    _write(repo, checker.MAP_PATH, mapping)
    _write(repo, checker.QUALIFICATION_PATH, qualification)
    assert checker.validate(repo) == []
    assert path in _read(repo, checker.PLAN_PATH)["phase2_restored"]
    qualification["groups"][-1]["files"] = [selector + "::one_case"]
    _write(repo, checker.QUALIFICATION_PATH, qualification)
    assert checker.validate(repo)


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


def _reviewed_cases(path):
    return [{"case": case, "reviewer": checker.PR35_REVIEWER, "reason": reason,
             "source_path": path, "source_sha256": checker.PR35_CASE_SOURCE_SHA256[path]}
            for case, reason in sorted(checker.PR35_CASE_REASONS[path].items())]


def _reviewed_adapter(root, source_path="tests/test_tool_loop_helpers.py"):
    path, selector = _restore(root, adapter=True, source_path=source_path)
    dispositions = _reviewed_cases(path)
    mapping = _read(root, checker.MAP_PATH)
    row = next(row for row in mapping["entries"] if row["path"] == path)
    row["restoration"]["case_retirements"] = dispositions
    _write(root, checker.MAP_PATH, mapping)
    target = root / selector
    source = target.read_text().replace(
        "CORPUS_EXCLUSIONS = {}",
        f"CORPUS_EXCLUSIONS = {{{Path(path).stem!r}: {dispositions!r}}}")
    source = source.replace("    register_module(namespace, module)",
                            f"    stem = {Path(path).stem!r}\n"
                            "    register_module(namespace, module, excluded="
                            "[item['case'] for item in CORPUS_EXCLUSIONS.get(stem, ())])")
    target.write_text(source)
    return path, selector, dispositions


def test_reviewed_case_exclusions_keep_full_original_and_restoration_agreement(repo):
    original = (repo / "tests/test_tool_loop_helpers.py").read_bytes()
    path, selector, dispositions = _reviewed_adapter(repo)
    assert checker.validate(repo) == []
    assert checker._full_adapter(repo, selector, path, checker.PR35_CASE_SOURCE_SHA256[path],
                                 dispositions)
    assert (repo / path).read_bytes() == original
    assert not checker._full_adapter(repo, selector, path, checker.PR35_CASE_SOURCE_SHA256[path])


@pytest.mark.parametrize("source_path", [
    "tests/test_tool_loop_helpers.py", "tests/test_resume_admission.py",
])
@pytest.mark.parametrize("mutation", [
    "case", "parameter", "reviewer", "reason", "source_path", "source_sha256",
    "duplicate", "unsorted", "extra_field", "loader_disagreement", "unreviewed_suite",
    "blanket", "dynamic", "wrong_projection", "selected", "no_exclusion_export",
    "direct_original", "no_metadata", "no_plan_cases", "empty_row",
    "mutated_constant", "mutated_item", "annotation", "hidden_kwargs",
])
def test_case_retirement_mutations_fail_closed(repo, mutation, source_path):
    path, selector, dispositions = _reviewed_adapter(repo, source_path)
    mapping = _read(repo, checker.MAP_PATH)
    row = next(row for row in mapping["entries"] if row["path"] == path)
    cases = row["restoration"]["case_retirements"]
    if mutation in {"case", "reviewer", "reason", "source_path", "source_sha256"}:
        cases[0][mutation] = "unreviewed"
    elif mutation == "parameter":
        cases[0]["case"] += "[True]"
    elif mutation == "duplicate":
        cases.append(copy.deepcopy(cases[0]))
    elif mutation == "unsorted":
        cases.reverse()
    elif mutation == "extra_field":
        cases[0]["approved"] = True
    elif mutation == "direct_original":
        row["restoration"]["mode"] = "direct-original"
    elif mutation == "no_plan_cases":
        row["restoration"].pop("case_retirements")
    elif mutation == "empty_row":
        cases[0] = {}
    else:
        target = repo / selector
        source = target.read_text()
        declaration = f"CORPUS_EXCLUSIONS = {{{Path(path).stem!r}: {dispositions!r}}}"
        if mutation == "loader_disagreement":
            source = source.replace(
                declaration, f"CORPUS_EXCLUSIONS = {{{Path(path).stem!r}: {dispositions[1:]!r}}}")
        elif mutation == "unreviewed_suite":
            source = source.replace(declaration, "CORPUS_EXCLUSIONS = {'arbitrary': ['test_one']}")
        elif mutation == "blanket":
            source = source.replace(
                declaration, f"CORPUS_EXCLUSIONS = {{{Path(path).stem!r}: ['*']}}")
        elif mutation == "dynamic":
            source = source.replace(declaration, "CORPUS_EXCLUSIONS = arbitrary_exclusions()")
        elif mutation == "wrong_projection":
            source = source.replace("item['case']", "item['reason']")
        elif mutation == "selected":
            source = source.replace("excluded=", "selected=")
        elif mutation == "no_exclusion_export":
            source = source.replace(
                ", excluded=[item['case'] for item in CORPUS_EXCLUSIONS.get(stem, ())]", "")
        elif mutation == "no_metadata":
            source = source.replace(declaration, "CORPUS_EXCLUSIONS = {}")
        elif mutation == "mutated_constant":
            source = source.replace(declaration, declaration + "\nCORPUS_EXCLUSIONS.clear()")
        elif mutation == "mutated_item":
            source = source.replace(
                declaration, declaration + "\nCORPUS_EXCLUSIONS['extra'] = ['*']")
        elif mutation == "annotation":
            source = source.replace(
                declaration, declaration + "\nCORPUS_EXCLUSIONS: dict = {'extra': ['*']}")
        elif mutation == "hidden_kwargs":
            source = source.replace("register_module(namespace, module, excluded=",
                                    "register_module(namespace, module, **extra, excluded=")
        target.write_text(source)
    _write(repo, checker.MAP_PATH, mapping)
    assert checker.validate(repo), mutation


def test_resume_eight_removed_surface_dispositions_use_genuine_validator(repo):
    path, selector, dispositions = _reviewed_adapter(repo, "tests/test_resume_admission.py")
    assert len(dispositions) == 8
    assert checker.validate(repo) == []
    assert checker._full_adapter(repo, selector, path, checker.PR35_CASE_SOURCE_SHA256[path],
                                 dispositions)
    for supported in (
        "TestCalibrationReleaseTotality.test_rebuild_author_mismatch_is_terminal_and_releases",
        "TestExplicitResume.test_deleted_original_is_terminal_rejected",
        "TestExplicitResume.test_confirmed_not_found_is_terminal_but_fetch_outage_preserves_lease",
    ):
        changed = copy.deepcopy(dispositions)
        changed[0]["case"] = supported
        changed.sort(key=lambda row: row["case"])
        assert not checker._case_retirements(
            repo, path, checker.PR35_CASE_SOURCE_SHA256[path], changed)


@pytest.mark.parametrize("case_index", range(8))
@pytest.mark.parametrize("field", ["case", "reviewer", "reason", "source_path", "source_sha256"])
def test_every_resume_disposition_is_individually_pinned(repo, case_index, field):
    path = "tests/test_resume_admission.py"
    dispositions = _reviewed_cases(path)
    assert checker._case_retirements(repo, path, checker.PR35_CASE_SOURCE_SHA256[path],
                                    dispositions)
    dispositions[case_index][field] = "unreviewed"
    assert not checker._case_retirements(repo, path, checker.PR35_CASE_SOURCE_SHA256[path],
                                        dispositions)


def test_resume_dispositions_reject_changed_actual_source_bytes(repo):
    path = "tests/test_resume_admission.py"
    target = repo / path
    replacement = target.with_suffix(".changed")
    replacement.write_bytes(target.read_bytes() + b"\n# source drift\n")
    replacement.replace(target)
    assert not checker._case_retirements(
        repo, path, checker.PR35_CASE_SOURCE_SHA256[path], _reviewed_cases(path))


def test_actual_exact_resume_wrapper_has_complete_static_association():
    import ast

    path = "tests/test_resume_admission.py"
    adapter = ROOT / "tests/desktop_adapters/step8_review_resume_exact.py"
    tree = ast.parse(adapter.read_bytes())
    exclusions = next(
        ast.literal_eval(node.value)["test_resume_admission"]
        for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "CORPUS_EXCLUSIONS"
                for target in node.targets))
    assert checker._full_adapter(
        ROOT, "tests/test_desktop_step8_review_resume_exact.py", path,
        checker.PR35_CASE_SOURCE_SHA256[path], exclusions)


@pytest.mark.parametrize("mutation", [None, "wrong_path", "wrong_hash"])
def test_sources_dictionary_exact_path_and_hash_pin(repo, mutation):
    path, selector = _restore(repo, adapter=True)
    mapping = _read(repo, checker.MAP_PATH)
    digest = next(row["inherited_sha256"] for row in mapping["entries"] if row["path"] == path)
    source_path = path if mutation != "wrong_path" else "tests/test_other.py"
    source_hash = digest if mutation != "wrong_hash" else "0" * 64
    target = repo / selector
    target.write_text(target.read_text().replace(
        f"SOURCE_PATH = {path!r}\nSOURCE_SHA256 = {digest!r}",
        f"SOURCES = {{'runtime': ({source_path!r}, {source_hash!r})}}"))
    assert (checker.validate(repo) == []) is (mutation is None)


def test_package_import_closure_follows_exact_test_local_adapter_without_importing(repo):
    path, selector, dispositions = _reviewed_adapter(repo)
    package = repo / "tests/desktop_adapters"
    package.mkdir(exist_ok=True)
    (package / "review_fixture.py").write_text((repo / selector).read_text())
    (repo / selector).write_text(
        "from tests.desktop_adapters import review_fixture as adapter\nadapter.load(globals())\n")
    assert checker._full_adapter(repo, selector, path, checker.PR35_CASE_SOURCE_SHA256[path],
                                 dispositions)


def _branch_case(root):
    path, selector, _ = _reviewed_adapter(root)
    branch = {
        "case": "TestBehaviorPreservedByRefactor.test_all_combinations_match_reference",
        "reviewer": checker.PR35_REVIEWER,
        "reason": checker.PR35_CASE_REASONS[path][
            "TestBuildRequestPreamble.test_bot_message_block"],
        "source_path": path, "source_sha256": checker.PR35_CASE_SOURCE_SHA256[path],
        "line": 170, "column": 36,
        "node_sha256": "dca8f82ad2c13093e18831c63d876733f70de16f7f9f34083e01bc131bb8218e",
        "before_source": "(True, False)", "after_source": "(False,)",
    }
    mapping = _read(root, checker.MAP_PATH)
    row = next(row for row in mapping["entries"] if row["path"] == path)
    row["restoration"]["branch_retirements"] = [branch]
    _write(root, checker.MAP_PATH, mapping)
    target = root / selector
    target.write_text(
        target.read_text()
        + f"\nCORPUS_BRANCH_RETIREMENTS = {{{Path(path).stem!r}: {[branch]!r}}}\n")
    return path, selector, branch


def test_exact_reviewed_bot_branch_metadata_preserves_supported_case(repo):
    path, selector, branch = _branch_case(repo)
    assert checker.validate(repo) == []
    assert checker._branch_retirements(repo, path, checker.PR35_CASE_SOURCE_SHA256[path], [branch])
    assert not checker._full_adapter(repo, selector, path, checker.PR35_CASE_SOURCE_SHA256[path],
                                     _reviewed_cases(path))


@pytest.mark.parametrize("field", ["case", "reviewer", "reason", "source_path", "source_sha256",
                                   "line", "column", "node_sha256", "before_source",
                                   "after_source"])
def test_branch_retirement_rejects_changed_source_identity_or_disposition(repo, field):
    path, _, branch = _branch_case(repo)
    branch[field] = "unreviewed"
    assert not checker._branch_retirements(
        repo, path, checker.PR35_CASE_SOURCE_SHA256[path], [branch])


def test_branch_retirement_cannot_be_undeclared_or_blanket(repo):
    _, selector, _ = _branch_case(repo)
    mapping = _read(repo, checker.MAP_PATH)
    row = next(
        row for row in mapping["entries"] if row["path"] == "tests/test_tool_loop_helpers.py")
    row["restoration"].pop("branch_retirements")
    _write(repo, checker.MAP_PATH, mapping)
    assert checker.validate(repo)
    target = repo / selector
    target.write_text(target.read_text() + "\nCORPUS_BRANCH_RETIREMENTS.clear()\n")
    assert checker.validate(repo)


def test_cli_removed_http_proposal_is_not_review_c_retirement_authority(repo):
    assert "tests/test_campaign_cli_coverage.py" not in checker.PR35_CASE_REASONS
    assert not checker._case_retirements(repo, "tests/test_campaign_cli_coverage.py",
                                        "fe47a4c99af2c48f8bf397a0634830b82c5afa50e74ab53eb0fb26864a434d0b",
                                        [{"case":
                                          "test_transport_failure_is_nonzero_even_in_json_mode"}])


def _pr35_steps(root):
    mapping = _read(root, checker.MAP_PATH)
    for row in mapping["entries"]:
        if row["path"] in checker.PR35_RETIREMENTS:
            row["step"] = checker.PR35_RETIREMENTS[row["path"]][0]
    _write(root, checker.MAP_PATH, mapping)


def test_pr35_exact_retirements_preserve_all_869_bytes_history_and_old_review(repo):
    _pr35_steps(repo)
    plan_before = _read(repo, checker.PLAN_PATH)
    originals = {entry["path"]: (repo / entry["path"]).read_bytes()
                 for entry in plan_before["entries"] if (repo / entry["path"]).exists()}
    assert len(originals) == 869
    checker.record_review_retirements(repo)
    old_review = {row["path"]: copy.deepcopy(row) for row in
                  _read(repo, checker.MAP_PATH)["entries"] if row["status"] == "retired"}
    checker.record_pr35_review_retirements(repo)
    assert checker.validate(repo) == []
    snapshot = [(repo / path).read_bytes() for path in (checker.MAP_PATH, checker.PLAN_PATH)]
    checker.record_pr35_review_retirements(repo)
    assert snapshot == [(repo / path).read_bytes()
                        for path in (checker.MAP_PATH, checker.PLAN_PATH)]
    assert len(checker.PR35_RETIREMENTS) == 21
    for row in _read(repo, checker.MAP_PATH)["entries"]:
        if row["path"] in old_review:
            assert row == old_review[row["path"]]
    assert all((repo / path).read_bytes() == data for path, data in originals.items())
    plan = _read(repo, checker.PLAN_PATH)
    assert {e["path"]: e["sha256"] for e in plan["entries"]} == {
        e["path"]: e["sha256"] for e in plan_before["entries"]}
    assert set(plan["phase2"]) | set(plan["phase2_retired"]) == set(plan_before["phase2"])
    assert len(plan["phase2"]) == 300
    assert len(plan["phase2_retired"]) == 26
    assert len(_read(repo, checker.MAP_PATH)["entries"]) == 326


@pytest.mark.parametrize("mutation", [
    "reviewer", "reason", "step", "source_hash", "restoration", "selected",
    "extra_metadata", "plan_disagreement", "wrong_path", "count",
])
def test_pr35_retirement_is_exact_and_never_blanket_permission(repo, mutation):
    _pr35_steps(repo)
    checker.record_pr35_review_retirements(repo)
    mapping, plan, qualification = (_read(repo, path) for path in
                                   (checker.MAP_PATH, checker.PLAN_PATH,
                                    checker.QUALIFICATION_PATH))
    row = next(row for row in mapping["entries"] if row["path"] in checker.PR35_RETIREMENTS)
    path = row["path"]
    if mutation in {"reviewer", "reason"}:
        row["retirement"][mutation] = "unreviewed"
    elif mutation == "step":
        row["step"] = 1
    elif mutation == "source_hash":
        row["inherited_sha256"] = "0" * 64
    elif mutation == "restoration":
        row["restoration"] = {"mode": "direct-original", "selectors": [path]}
    elif mutation == "selected":
        qualification["groups"][0]["files"].append(path)
    elif mutation == "extra_metadata":
        row["retirement"]["blanket_permission"] = True
    elif mutation == "plan_disagreement":
        next(entry for entry in plan["entries"] if entry["path"] == path)["retirement"] = {}
    elif mutation == "wrong_path":
        row["path"] = "tests/test_delivery_review_regressions.py"
    elif mutation == "count":
        plan["counts"]["retired"] += 1
    for filename, value in ((checker.MAP_PATH, mapping), (checker.PLAN_PATH, plan),
                            (checker.QUALIFICATION_PATH, qualification)):
        _write(repo, filename, value)
    assert checker.validate(repo), mutation


def test_pr35_recording_rejects_wrong_owning_step_without_writing(repo):
    before = [(repo / path).read_bytes() for path in (checker.MAP_PATH, checker.PLAN_PATH)]
    with pytest.raises(ValueError, match="reviewed step"):
        checker.record_pr35_review_retirements(repo)
    assert before == [(repo / path).read_bytes() for path in (checker.MAP_PATH, checker.PLAN_PATH)]


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
