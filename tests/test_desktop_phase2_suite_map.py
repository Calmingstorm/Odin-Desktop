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
from scripts.maintenance import restore_step5_suites as generator

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


@pytest.mark.parametrize("path", [checker.MAP_PATH, checker.PLAN_PATH, checker.QUALIFICATION_PATH])
def test_prospective_empty_document_cannot_fall_back_to_valid_disk_input(repo, path):
    snapshot = _accounting_bytes(repo)
    assert checker.validate(repo, documents={path: {}})
    assert _accounting_bytes(repo) == snapshot


@pytest.fixture
def step5_repo(repo):
    """Disposable actual decisions/loaders, with only step 5 reverted to held."""
    for path in (ROOT / "tests").rglob("*.py"):
        relative = path.relative_to(ROOT)
        target = repo / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    for path in (ROOT / "maintenance").glob("step8-part2-*.json"):
        shutil.copyfile(path, repo / "maintenance" / path.name)
    mapping = _read(ROOT, checker.MAP_PATH)
    plan = _read(ROOT, checker.PLAN_PATH)
    qualification = _read(ROOT, checker.QUALIFICATION_PATH)
    restored = set()
    for row in mapping["entries"]:
        if row["step"] != 5:
            continue
        row.pop("step8_part2", None)
        if row["status"] == "restored":
            restored.add(row["path"])
            row.update(status="deferred", blocked_on="Awaiting whole runtime suite integration")
            row.pop("restoration")
    for row in plan["entries"]:
        if row["path"] in restored:
            row["classification"] = "phase2"
    for field in ("safe_pass_now", "phase2_restored"):
        plan[field] = sorted(set(plan[field]) - restored)
        if field in plan["counts"]:
            plan["counts"][field] = len(plan[field])
    plan["phase2"] = sorted(set(plan["phase2"]) | restored)
    plan["counts"]["phase2"] = len(plan["phase2"])
    neutral = next(g for g in qualification["groups"] if g["name"] == "neutral-subsystem-guard")
    neutral["files"] = ["tests/test_subsystem_guard.py"]
    neutral["exclude_expression"] = "test_real_bot_guard"
    for filename, document in ((checker.MAP_PATH, mapping), (checker.PLAN_PATH, plan),
                               (checker.QUALIFICATION_PATH, qualification)):
        _write(repo, filename, document)
    assert checker.validate(repo) == []
    return repo


def _accounting_bytes(root):
    return {path: (root / path).read_bytes() for path in
            (checker.MAP_PATH, checker.PLAN_PATH, checker.QUALIFICATION_PATH)}


def test_generator_integrates_all_decisions_preserving_history_bytes_and_idempotency(step5_repo):
    root = step5_repo
    before = _read(root, checker.MAP_PATH)
    originals = {row["path"]: (root / row["path"]).read_bytes() for row in before["entries"]}
    result = generator.integrate(root)
    assert result["owned"] == 85
    assert result["dispositions"] == {"restored": 10, "deferred": 75}
    assert len(result["restored"]) == 10
    errors, counts = checker._evaluate(root)
    assert errors == []
    assert (counts["mapped"], counts["restored"], counts["retired"], counts["deferred"]) == (
        326, 19, 5, 302,
    )
    after = _read(root, checker.MAP_PATH)
    assert {row["path"] for row in after["entries"]} == set(originals)
    assert all((root / path).read_bytes() == data for path, data in originals.items())
    assert [row for row in before["entries"] if row["step"] != 5] == [
        row for row in after["entries"] if row["step"] != 5
    ]
    assert sum("step8_part2" in row for row in after["entries"] if row["step"] == 5) == 85
    qualification = _read(root, checker.QUALIFICATION_PATH)
    neutral = next(g for g in qualification["groups"] if g["name"] == "neutral-subsystem-guard")
    assert neutral["files"] == ["tests/test_desktop_phase2_runtime_guard.py"]
    assert "exclude_expression" not in neutral
    snapshot = _accounting_bytes(root)
    assert generator.integrate(root) == result
    assert _accounting_bytes(root) == snapshot


@pytest.mark.parametrize("mutation", [
    "missing_decision", "duplicate_decision", "unowned_decision", "unresolved_delegate",
    "partial_mode", "case_selector", "missing_blocker", "original_bytes",
    "historical_membership", "guard_subset", "guard_multiple", "duplicate_json_key",
    "guard_not_delegated",
])
def test_generator_rejects_invalid_decisions_without_writing_accounting(step5_repo, mutation):
    root = step5_repo
    filename = "maintenance/step8-part2-batch-a.json"
    document = _read(root, filename)
    restored = next(row for row in document["entries"] if row["status"] == "restored")
    deferred = next(row for row in document["entries"] if row["status"] == "deferred")
    if mutation == "missing_decision":
        document["entries"].pop()
    elif mutation == "duplicate_decision":
        document["entries"].append(copy.deepcopy(restored))
    elif mutation == "unowned_decision":
        deferred["path"] = "tests/test_unowned.py"
    elif mutation == "unresolved_delegate":
        restored["status"] = "delegated"
    elif mutation == "partial_mode":
        restored["restoration"]["mode"] = "partial-adapter"
    elif mutation == "case_selector":
        restored["restoration"]["selectors"][0] += "::test_one"
    elif mutation == "missing_blocker":
        deferred["blocked_on"] = ""
    elif mutation == "guard_not_delegated":
        for batch in "abcd":
            batch_path = f"maintenance/step8-part2-batch-{batch}.json"
            batch_document = _read(root, batch_path)
            for row in batch_document["entries"]:
                if row["path"] == "tests/test_subsystem_guard.py":
                    row["status"] = "deferred"
            if batch_path == filename:
                document = batch_document
            else:
                _write(root, batch_path, batch_document)
    elif mutation == "original_bytes":
        target = root / deferred["path"]
        target.unlink()  # Break the archive fixture hardlink before mutating bytes.
        target.write_text("def test_changed():\n    assert True\n")
    elif mutation == "historical_membership":
        mapping = _read(root, checker.MAP_PATH)
        mapping["entries"].pop()
        _write(root, checker.MAP_PATH, mapping)
    elif mutation in {"guard_subset", "guard_multiple"}:
        guard_path = "maintenance/step8-part2-guard.json"
        guard = _read(root, guard_path)
        if mutation == "guard_subset":
            guard["owned_suites"][0]["test_entry"] += "::test_one"
        else:
            guard["owned_suites"].append(copy.deepcopy(guard["owned_suites"][0]))
        _write(root, guard_path, guard)
    _write(root, filename, document)
    if mutation == "duplicate_json_key":
        (root / filename).write_text('{"entries":[],"entries":[]}')
    snapshot = _accounting_bytes(root)
    with pytest.raises(ValueError):
        generator.integrate(root)
    assert _accounting_bytes(root) == snapshot


@pytest.mark.parametrize("mutation", [
    "deferred", "wrong_step", "direct_mode", "different_association", "neutral_exclusion",
    "missing_adapter", "syntax_error", "partial_corpus", "lost_other_selector",
])
def test_guard_replacement_is_only_for_verified_complete_guard_adapter(step5_repo, mutation):
    root = step5_repo
    generator.integrate(root)
    assert checker.validate(root) == []  # Positive case uses the real static closure.
    mapping = _read(root, checker.MAP_PATH)
    qualification = _read(root, checker.QUALIFICATION_PATH)
    guard = next(row for row in mapping["entries"]
                 if row["path"] == "tests/test_subsystem_guard.py")
    neutral = next(g for g in qualification["groups"] if g["name"] == "neutral-subsystem-guard")
    if mutation == "deferred":
        guard["status"] = "deferred"
    elif mutation == "wrong_step":
        guard["step"] = 1
    elif mutation == "direct_mode":
        guard["restoration"]["mode"] = "direct-original"
    elif mutation == "different_association":
        guard["restoration"]["selectors"] = ["tests/test_subsystem_guard.py"]
    elif mutation == "neutral_exclusion":
        neutral["exclude_expression"] = "test_one"
    elif mutation == "missing_adapter":
        (root / neutral["files"][0]).unlink()
    elif mutation == "syntax_error":
        (root / neutral["files"][0]).write_text("def invalid(\n")
    elif mutation == "partial_corpus":
        path = root / "tests/desktop_adapters/step8_runtime_guard.py"
        path.write_text(path.read_text().replace(
            'CORPUS_SELECTIONS = {"test_subsystem_guard": None}',
            'CORPUS_SELECTIONS = {"test_subsystem_guard": ["test_one"]}',
        ))
    elif mutation == "lost_other_selector":
        group = next(g for g in qualification["groups"]
                     if g["name"] == "phase2-step5-profile-management")
        group["files"].remove("tests/test_desktop_management.py")
    _write(root, checker.MAP_PATH, mapping)
    _write(root, checker.QUALIFICATION_PATH, qualification)
    errors = checker.validate(root)
    if mutation in {"missing_adapter", "syntax_error"}:
        assert errors and any("file" in error or "malformed" in error for error in errors)
    else:
        group = ("phase2-step5-profile-management" if mutation == "lost_other_selector"
                 else "neutral-subsystem-guard")
        assert f"qualification: lost merged main selectors in {group}" in errors


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


def test_merged_step5_can_restore_an_entire_qualified_suite(repo):
    _restore(repo)
    mapping = _read(repo, checker.MAP_PATH)
    mapping["entries"][0]["step"] = 5
    _write(repo, checker.MAP_PATH, mapping)
    assert checker.validate(repo) == []


@pytest.mark.parametrize("step", [2, 3, 4, 6, 7, "Phase 3"])
def test_unmerged_surface_cannot_be_marked_restored(repo, step):
    _restore(repo)
    mapping = _read(repo, checker.MAP_PATH)
    mapping["entries"][0]["step"] = step
    _write(repo, checker.MAP_PATH, mapping)
    assert any("merged step 1 or 5" in error for error in checker.validate(repo))


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
