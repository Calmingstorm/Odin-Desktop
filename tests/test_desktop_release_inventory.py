"""Real temporary JSON inventories drive the offline report, never an engine."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "release_inventory", Path(__file__).resolve().parents[1] / "scripts/qualification/release.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


@pytest.fixture
def inventory(tmp_path):
    source = tmp_path / release.SOURCE
    source.parent.mkdir(parents=True)
    paragraph = "D10 `CC-19` covers source auth and packaged lifecycle.\nUse isolated peers only."
    source.write_text(
        "## 5. R4 acceptance inventory and contract additions\n\n"
        + "\n".join(f"| {identity} | Scenario {identity} | Gate {identity} |"
                    for identity in release.IDS if identity != "CC-19")
        + f"\n\n{paragraph}\n\n## 6. Decisions\n", encoding="utf-8",
    )
    rows = [{"id": identity, "scenario": scenario, "dependency": dependency,
             "environments": ["isolated Linux final .deb and AppImage"],
             "evidence": {lane: [] for lane in release.LANES},
             "status": "no_evidence", "unresolved": ["Needs final candidates."]}
            for identity, (scenario, dependency) in release.source_cases(tmp_path).items()]
    return tmp_path, {"schema_version": 1, "source": release.SOURCE, "cases": rows}


def run(inventory, capsys):
    root, data = inventory
    target = root / release.INVENTORY
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(data), encoding="utf-8")
    code = release.main(["--root", str(root), "report"])
    return code, capsys.readouterr()


def point(inventory, pointer, lane="headless"):
    row = inventory[1]["cases"][0]
    row["status"] = "partial"
    row["evidence"][lane] = [pointer]
    return row


def proof_manifest(root):
    (root / "proof.json").write_text(json.dumps({"artifacts": [
        {"id": "proof", "path": "/external/proof.log", "sha256": "a" * 64},
    ]}), encoding="utf-8")


def test_valid_inventory_reports_all_gaps_without_claiming_acceptance(inventory, capsys):
    code, output = run(inventory, capsys)
    assert code == 0
    assert "no_evidence: 29" in output.out
    assert "No case is passed" in output.out
    assert all(f"- {identity} [no_evidence]" in output.out for identity in release.IDS)
    assert "Needs final candidates." in output.out
    assert not output.err


@pytest.mark.parametrize("mutation,diagnostic", [
    ("missing", "missing=['CC-19']"), ("duplicate", "duplicate=['R4-01']"),
    ("extra", "extra=['R4-11']"),
])
def test_id_coverage_fails_closed(inventory, capsys, mutation, diagnostic):
    rows = inventory[1]["cases"]
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(rows[0].copy())
    else:
        rows[-1]["id"] = "R4-11"
    code, output = run(inventory, capsys)
    assert code == 1
    assert diagnostic in output.err
    assert not output.out


def test_dangling_pointer_refuses_report(inventory, capsys):
    point(inventory, "tests/test_missing.py::test_missing")
    code, output = run(inventory, capsys)
    assert code == 1
    assert "dangling" in output.err
    assert not output.out


@pytest.mark.parametrize("hash_bound", [False, True])
def test_premature_pass_refused_even_with_hash_and_environment(inventory, capsys, hash_bound):
    row = inventory[1]["cases"][0]
    row["status"] = "passed"
    if hash_bound:
        row["package_sha256"] = "a" * 64
    code, output = run(inventory, capsys)
    assert code == 1
    assert "passed is forbidden" in output.err
    assert "package hashes and an environment" in output.err
    assert not output.out


@pytest.mark.parametrize("field,value", [
    ("scenario", "Paraphrased"), ("dependency", "New gate"),
    ("environments", []), ("unresolved", [""]), ("status", "unknown"),
    ("evidence", {"headless": []}),
])
def test_schema_and_work_order_are_validated(inventory, capsys, field, value):
    inventory[1]["cases"][0][field] = value
    code, output = run(inventory, capsys)
    assert code == 1
    assert output.err.startswith("Invalid R4/CC inventory:")


@pytest.mark.parametrize("pointer", ["pending: #0", "pending: #31/path", "../foreign.json"])
def test_malformed_pending_and_escaping_pointer_refused(inventory, capsys, pointer):
    point(inventory, pointer)
    assert run(inventory, capsys)[0] == 1


def test_pending_prs_are_visible_but_never_ready(inventory, capsys):
    row = point(inventory, "pending: #50", "native")
    row["status"] = "no_evidence"
    code, output = run(inventory, capsys)
    assert code == 0
    assert "native pending, not accepted: pending: #50" in output.out
    row["status"] = "ready_for_final_run"
    row["unresolved"] = []
    assert run(inventory, capsys)[0] == 1


@pytest.mark.parametrize("suffix,content,selector", [
    (".py", "class TestBoundary:\n    async def test_one(self):\n        pass\n",
     "TestBoundary::test_one"),
    (".ts", "test('retains identity', async () => {});\n", "retains identity"),
    (".ts", "test.only('named case', async () => {});\n", "named case"),
])
def test_test_case_resolves_without_import_or_execution(
    inventory, capsys, suffix, content, selector,
):
    root, _ = inventory
    path = root / f"proof{suffix}"
    path.write_text(content + "raise_if_executed()\n", encoding="utf-8")
    point(inventory, f"{path.name}::{selector}")
    assert run(inventory, capsys)[0] == 0
    point(inventory, f"{path.name}::nonexistent")
    code, output = run(inventory, capsys)
    assert code == 1
    assert "dangling test case" in output.err


def test_hashed_manifest_pointer_resolves_without_opening_external_artifact(inventory, capsys):
    root, _ = inventory
    path = root / "manifest.json"
    path.write_text(json.dumps({"artifacts": [{"id": "proof", "path": "/external/proof.log",
                                              "sha256": "a" * 64}]}), encoding="utf-8")
    point(inventory, "manifest.json::proof", "package")
    assert run(inventory, capsys)[0] == 0
    point(inventory, "manifest.json::missing", "package")
    code, output = run(inventory, capsys)
    assert code == 1
    assert "manifest artifact" in output.err
    path.write_text(json.dumps({"artifacts": [{"id": "missing", "path": "/external/proof.log",
                                              "sha256": "not-a-hash"}]}), encoding="utf-8")
    assert run(inventory, capsys)[0] == 1


def test_external_symlink_pointer_refused(inventory, capsys, tmp_path_factory):
    external = tmp_path_factory.mktemp("outside") / "proof.txt"
    external.write_text("not tree evidence", encoding="utf-8")
    (inventory[0] / "proof.txt").symlink_to(external)
    point(inventory, "proof.txt")
    code, output = run(inventory, capsys)
    assert code == 1
    assert "external pointer" in output.err


def test_status_cannot_hide_missing_or_pending_evidence(inventory, capsys):
    row = inventory[1]["cases"][0]
    row["status"] = "partial"
    assert run(inventory, capsys)[0] == 1
    row = point(inventory, "pending: #50")
    assert run(inventory, capsys)[0] == 1
    proof_manifest(inventory[0])
    row = point(inventory, "proof.json")
    row["status"] = "no_evidence"
    assert run(inventory, capsys)[0] == 1


def test_ready_is_readiness_only_not_a_pass(inventory, capsys):
    proof_manifest(inventory[0])
    row = point(inventory, "proof.json")
    row["status"] = "ready_for_final_run"
    row["unresolved"] = []
    code, output = run(inventory, capsys)
    assert code == 0
    assert "R4-01 [ready_for_final_run]" in output.out
    assert "Final hash-bound applicable Linux run remains outstanding." in output.out


def test_malformed_json_refused_without_partial_gap_output(inventory, capsys):
    root, _ = inventory
    target = root / release.INVENTORY
    target.parent.mkdir()
    target.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
    assert release.main(["--root", str(root), "report"]) == 1
    output = capsys.readouterr()
    assert "duplicate JSON key" in output.err
    assert not output.out


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2), ("source", "different.md"), ("cases", [{}]),
    ("cases", "not records"),
])
def test_top_level_contract_refused(inventory, capsys, field, value):
    inventory[1][field] = value
    assert run(inventory, capsys)[0] == 1


def test_duplicate_and_blank_evidence_is_refused(inventory, capsys):
    row = point(inventory, "pending: #50")
    row["evidence"]["headless"].append("pending: #50")
    assert run(inventory, capsys)[0] == 1
    row["evidence"]["headless"] = [""]
    assert run(inventory, capsys)[0] == 1


def test_empty_selector_or_bad_manifest_cannot_resolve(inventory, capsys):
    path = inventory[0] / "manifest.json"
    path.write_text("{}", encoding="utf-8")
    point(inventory, "manifest.json::")
    assert run(inventory, capsys)[0] == 1
    point(inventory, "manifest.json::proof")
    assert run(inventory, capsys)[0] == 1


def test_unsupported_selector_is_not_evidence(inventory, capsys):
    (inventory[0] / "proof.txt").write_text("test_one", encoding="utf-8")
    point(inventory, "proof.txt::test_one")
    assert run(inventory, capsys)[0] == 1


def test_missing_work_order_case_is_an_error(inventory, capsys):
    path = inventory[0] / release.SOURCE
    path.write_text("## 5. R4 acceptance inventory and contract additions\n\n## 6. End\n",
                    encoding="utf-8")
    assert run(inventory, capsys)[0] == 1


def test_checked_in_inventory_is_resolvable_machine_data():
    rows = release.validate(release.ROOT, release.load_json(release.ROOT / release.INVENTORY))
    assert len(rows) == 29
    assert {row["status"] for row in rows} <= release.STATUSES


def test_ready_cannot_hide_unresolved_notes(inventory, capsys):
    proof_manifest(inventory[0])
    row = point(inventory, "proof.json")
    row["status"] = "ready_for_final_run"
    code, output = run(inventory, capsys)
    assert code == 1
    assert "unresolved or pending evidence" in output.err


@pytest.mark.parametrize("change", ["duplicate", "missing"])
def test_work_order_id_set_cannot_drift(inventory, capsys, change):
    path = inventory[0] / release.SOURCE
    text = path.read_text(encoding="utf-8")
    line = "| R4-01 | Scenario R4-01 | Gate R4-01 |\n"
    replacement = line + line if change == "duplicate" else ""
    path.write_text(text.replace(line, replacement), encoding="utf-8")
    assert run(inventory, capsys)[0] == 1


def test_cli_entrypoint_reports_temporary_json_without_running_acceptance(inventory, capsys):
    run(inventory, capsys)
    result = subprocess.run(
        [sys.executable, release.__file__, "--root", str(inventory[0]), "report"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "no_evidence: 29" in result.stdout
    assert not result.stderr


@pytest.mark.parametrize("content", ["{}", '{"artifacts": []}', "[]"])
def test_bare_json_must_be_a_real_evidence_manifest(inventory, capsys, content):
    (inventory[0] / "proof.json").write_text(content, encoding="utf-8")
    row = point(inventory, "proof.json")
    row["status"] = "ready_for_final_run"
    row["unresolved"] = []
    code, output = run(inventory, capsys)
    assert code == 1
    assert "evidence manifest" in output.err


@pytest.mark.parametrize("content", [
    "// test('not real', async () => {});\n",
    "/* test('not real', async () => {}); */\n",
    'const text = "test(\'not real\', async () => {});";\n',
])
def test_commented_or_string_test_declaration_is_not_a_case(inventory, capsys, content):
    (inventory[0] / "proof.ts").write_text(content, encoding="utf-8")
    point(inventory, "proof.ts::not real")
    code, output = run(inventory, capsys)
    assert code == 1
    assert "dangling test case" in output.err


def test_bare_test_file_is_not_a_manifest(inventory, capsys):
    (inventory[0] / "proof.py").write_text("def test_one(): pass", encoding="utf-8")
    point(inventory, "proof.py")
    assert run(inventory, capsys)[0] == 1
