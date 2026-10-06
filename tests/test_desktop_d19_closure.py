"""Exercise the D19 validator with synthetic operational inventory and code."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("d19_gate", ROOT / "scripts/maintenance/d19.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def table(*rows):
    return ("## 4. Inventory\n| Source / selector | Previous | Changed | Approval |\n"
            "|---|---|---|---|\n" + "\n".join(rows) + "\n## 5. Outside\n")


def parsed():
    return gate.parse_rows(
        table("| `src/example.py`, fail | old | `fence complete` | **NONE** |"),
        source_paths=["src/example.py"],
    )


def inventory(rows, findings):
    return {"version": 1, "baseline_sha": gate.BASELINE_SHA,
            "source_table": {"path": gate.SOURCE_TABLE, "section": 4},
            "rows": [{**row, "status": "proposed_behavioural", "reviewer": "Aaron",
                      "behaviour_change": "Refuse an unavailable execution path.",
                      "when_odin_sees_it": "A handler is unavailable during a stale call.",
                      "odin_v4130_equivalent": "No equivalent state in Odin.",
                      "observations": gate.observe(row, findings), "evidence_tests": []}
                     for row in rows]}


def test_parser_preserves_exact_row_keys_aliases_and_internal_context():
    text = table(
        "| `src/a/example.py`, first | old | `one`; `two` | **NONE** |",
        "| Same file, second | old | `three` plus prose | **NONE** |",
        "| `example.py`, approved | old | `approved` | D19 |",
        "### Adjacent changed config/status strings\n"
        "| Same module, config | old | `config` | **NONE** |",
        "### Internal control/storage and lifecycle diagnostics\nEach has **NONE**.\n"
        "| Current source / selector | Previous | Current |\n|---|---|---|\n"
        "| Same module, internals | old | `four`; `five` |")
    rows = gate.parse_rows(text, source_paths=["src/a/example.py"])
    assert len(rows) == 4
    assert rows[0]["strings"] == ["one", "two"]
    assert rows[1]["exact_string"] == "`three` plus prose"
    assert rows[3]["source_path"] == "src/a/example.py"
    assert rows[3]["source_location"] == "Same module, internals"


def test_parser_does_not_include_other_sections():
    rows = gate.parse_rows(
        table("| `src/example.py`, f | old | `one` | **NONE** |")
        + "| `src/example.py`, g | old | `outside` | **NONE** |",
        source_paths=["src/example.py"],
    )
    assert len(rows) == 1


def test_parser_rejects_ambiguous_canonical_alias():
    with pytest.raises(ValueError, match="Ambiguous"):
        gate.parse_rows(table("| `example.py`, f | old | `one` | NONE |"),
                        source_paths=["src/a/example.py", "src/b/example.py"])


def test_scan_folds_literals_and_full_fstring_diagnostics():
    findings = gate.scan_source(
        'def f(name):\n return "fence " "complete" + f" for {name}: " + "do not replay"\n',
        "src/example.py",
    )
    assert any(i["value"] == "fence complete for {name}: do not replay" for i in findings)
    assert gate._matches("for {...}", findings[0]["value"])


def test_scan_shape_attributes_and_only_post_terminator_dead_code():
    findings = gate.scan_source(
        'def f():\n raise RuntimeError("fence complete")\n task.progress_text = "inert"\n'
        'def g(enabled):\n if enabled:\n  raise RuntimeError("conditional")\n return "live"\n',
        "src/example.py",
    )
    assert next(i for i in findings if i["value"] == "fence complete")["reachability"] == "active"
    shape = next(i for i in findings if i["value"] == "task.progress_text")
    assert shape["reachability"] == "inactive"
    assert next(i for i in findings if i["value"] == "live")["reachability"] == "active"


def test_removed_cannot_use_json_to_waive_present_active_string(tmp_path):
    rows = parsed()
    findings = gate.scan_source(
        'def f():\n raise RuntimeError("fence complete")\n', "src/example.py",
    )
    data = inventory(rows, findings)
    data["rows"][0]["status"] = "removed_by_restored_behaviour"
    data["rows"][0]["observations"][0]["reachability"] = "inactive"
    result = gate.validate(data, rows, findings, tmp_path)
    assert any("observations differ" in e for e in result["errors"])
    assert any("present active" in e for e in result["errors"])


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "extra", "location", "string", "fragment",
                 "path", "line", "scope"],
)
def test_exact_record_coverage_and_identity_are_mandatory(tmp_path, mutation):
    rows = parsed()
    data = inventory(rows, [])
    if mutation == "missing":
        data["rows"] = []
    elif mutation == "duplicate":
        data["rows"].append(dict(data["rows"][0]))
    elif mutation == "extra":
        data["rows"].append({"id": "D19-999"})
    else:
        field = {"location": "source_location", "string": "exact_string",
                 "fragment": "strings", "path": "source_path", "line": "source_line",
                 "scope": "scope"}[mutation]
        data["rows"][0][field] = "altered"
    assert gate.validate(data, rows, [], tmp_path)["errors"]


def test_multifragment_row_rejects_removal_if_any_fragment_survives(tmp_path):
    rows = parsed()
    rows[0]["strings"] = ["removed", "still live"]
    findings = gate.scan_source('value = "still live"', "src/other.py")
    data = inventory(rows, findings)
    data["rows"][0]["status"] = "removed_by_restored_behaviour"
    errors = gate.validate(data, rows, findings, tmp_path)["errors"]
    assert any("present active" in e for e in errors)


def test_absent_restoration_requires_existing_test_nodeid(tmp_path):
    rows = parsed()
    data = inventory(rows, [])
    row = data["rows"][0]
    row["status"] = "removed_by_restored_behaviour"
    assert gate.validate(data, rows, [], tmp_path)["errors"]
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_proof.py").write_text(
        "class TestProof:\n def test_real(self):\n  assert True\n", encoding="utf-8",
    )
    row["evidence_tests"] = ["tests/test_proof.py::TestProof::test_real[case]"]
    assert not gate.validate(data, rows, [], tmp_path)["errors"]
    row["evidence_tests"] = ["tests/test_proof.py::TestProof::test_missing"]
    errors = gate.validate(data, rows, [], tmp_path)["errors"]
    assert any("invalid test reference" in e for e in errors)


def test_structurally_dead_string_requires_test_even_when_retained(tmp_path):
    rows = parsed()
    findings = gate.scan_source(
        'def f():\n raise RuntimeError("different")\n return "fence complete"\n', "src/example.py",
    )
    data = inventory(rows, findings)
    data["rows"][0]["status"] = "removed_by_restored_behaviour"
    errors = gate.validate(data, rows, findings, tmp_path)["errors"]
    assert any("requires real test" in e for e in errors)
    assert not any("present active" in e for e in errors)


@pytest.mark.parametrize(
    "status", ["pending_restoration", "proposed_mechanical", "proposed_behavioural"],
)
def test_proposal_and_pending_owner_fields(tmp_path, status):
    rows = parsed()
    findings = gate.scan_source('value = "fence complete"', "src/example.py")
    data = inventory(rows, findings)
    record = data["rows"][0]
    record["status"] = status
    record.pop("behaviour_change")
    record.pop("reviewer")
    assert gate.validate(data, rows, findings, tmp_path)["errors"]
    record.update(owner="Odin", pending_reference="PR #42 (step 7)", odin_string="old",
                  desktop_string="new",
                  reviewer="Claude" if status == "proposed_mechanical" else "Aaron",
                  behaviour_change="Change the admission contract.")
    assert not gate.validate(data, rows, findings, tmp_path)["errors"]


def test_committed_inventory_gate():
    """Run the operational validator, not document wording assertions."""
    assert gate.main(["--root", str(ROOT)]) == 0


def test_all_internal_rows_are_counted_as_rows_not_literal_fragments():
    internal = ("### Internal control/storage and lifecycle diagnostics\nEach has **NONE**.\n"
                "| Current source / selector | Previous | Current |\n|---|---|---|\n")
    text = table("| `src/example.py`, first | old | `one` | **NONE** |",
                 internal + "\n".join(
                     f"| Same module, record{i} | old | `a{i}`; `b{i}` |" for i in range(7)))
    rows = gate.parse_rows(text, source_paths=["src/example.py"])
    assert len(rows) == 8
    assert rows[-1]["strings"] == ["a6", "b6"]


def test_omitted_observations_do_not_waive_active_restoration(tmp_path):
    rows = parsed()
    findings = gate.scan_source('value = "fence complete"', "src/example.py")
    data = inventory(rows, findings)
    data["rows"][0].pop("observations")
    data["rows"][0]["status"] = "removed_by_restored_behaviour"
    errors = gate.validate(data, rows, findings, tmp_path)["errors"]
    assert any("present active" in e for e in errors)


def test_schema_and_baseline_must_match(tmp_path):
    data = inventory(parsed(), [])
    data.update(version=2, baseline_sha="invalid", source_table={"path": "other", "section": 5})
    assert len(gate.validate(data, parsed(), [], tmp_path)["errors"]) == 2


def test_identifier_must_be_a_string(tmp_path):
    data = inventory(parsed(), [])
    data["rows"][0]["id"] = []
    assert gate.validate(data, parsed(), [], tmp_path)["errors"]


def test_missing_inventory_is_a_gate_failure(tmp_path, capsys):
    assert gate.main(["--root", str(tmp_path)]) == 1
    assert '"errors"' in capsys.readouterr().out


def test_folded_fstring_conversion_and_format_spec():
    findings = gate.scan_source('text = f"failure {value!r:>10}"', "src/example.py")
    assert findings[0]["value"] == "failure {value!r:>10}"


def test_internal_table_without_none_context_is_not_silently_dispositioned():
    text = table("| `src/example.py`, first | old | `one` | **NONE** |",
                 "### Internal control/storage and lifecycle diagnostics\n"
                 "| Same module, fail | old | `two` |")
    with pytest.raises(ValueError, match="lacks explicit NONE"):
        gate.parse_rows(text, source_paths=["src/example.py"])


def test_duplicate_exact_source_key_rejected():
    row = "| `src/example.py`, fail | old | `one` | **NONE** |"
    with pytest.raises(ValueError, match="Duplicate exact"):
        gate.parse_rows(table(row, row), source_paths=["src/example.py"])


@pytest.mark.parametrize("invalid", [[], None, {"version": 1, "rows": "invalid"}, {"rows": [None]}])
def test_malformed_inventory_fails_cleanly(tmp_path, invalid):
    assert gate.validate(invalid, parsed(), [], tmp_path)["errors"]


@pytest.mark.parametrize(
    "nodeid", ["../escape.py::test_x", "/tmp/test_x.py::test_x",
               "tests/test_x.py", "tests/test_x.py::test_x"],
)
def test_test_reference_rejects_foreign_or_missing_paths(tmp_path, nodeid):
    assert not gate.test_reference_exists(tmp_path, nodeid)


def test_conditional_fence_and_other_function_do_not_retire_diagnostic():
    findings = gate.scan_source(
        'def old():\n raise RuntimeError("obsolete")\n'
        'def current(flag):\n if flag:\n  return "fence complete"\n'
        ' return "other"\n', "src/example.py",
    )
    assert next(i for i in findings if i["value"] == "fence complete")["reachability"] == "active"


def test_invalid_syntax_source_is_not_silently_ignored():
    with pytest.raises(SyntaxError):
        gate.scan_source("def malformed(", "src/example.py")


def test_source_requires_operational_fragments():
    with pytest.raises(ValueError, match="Unresolved operational"):
        gate.parse_rows(table("| `src/example.py`, f | old | no fragment | **NONE** |"),
                        source_paths=["src/example.py"])


def test_joined_expression_can_contain_unknown_non_string():
    findings = gate.scan_source('value = "fence complete" + unknown', "src/example.py")
    assert any(i["value"] == "fence complete" for i in findings)


def test_real_reference_syntax_error_is_rejected(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_invalid.py").write_text("def malformed(", encoding="utf-8")
    assert not gate.test_reference_exists(tmp_path, "tests/test_invalid.py::test_missing")


def test_foreign_test_symlink_rejected(tmp_path):
    root = tmp_path / "repository"
    (root / "tests").mkdir(parents=True)
    foreign = tmp_path / "foreign.py"
    foreign.write_text("def test_foreign():\n assert True\n", encoding="utf-8")
    (root / "tests/test_foreign.py").symlink_to(foreign)
    assert not gate.test_reference_exists(root, "tests/test_foreign.py::test_foreign")


def test_invalid_status_container_fails_cleanly(tmp_path):
    data = inventory(parsed(), [])
    data["rows"][0]["status"] = []
    assert gate.validate(data, parsed(), [], tmp_path)["errors"]


def test_audit_placeholder_matches_real_fstring_expression_not_false_absence():
    findings = gate.scan_source(
        'def export(inp, filename, error):\n'
        ' return f"Skill \'{inp[\"name\"]}\' prepared as {filename}. {error}"\n',
        "src/example.py",
    )
    rows = parsed()
    rows[0]["strings"] = ["Skill '{name}' prepared as {filename}. {staging_error}"]
    observed = gate.observe(rows[0], findings)
    assert observed[0]["reachability"] == "active"
    assert gate._matches("Skill '{name}'", "Skill '{inp['name']}'")
    assert not gate._matches("Skill '{name}' completed", "Skill '{name}' failed")
