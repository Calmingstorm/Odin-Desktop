"""Measured line counts cannot be masked by unrelated new coverage."""
from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location(
    "desktop_coverage_gate", Path(__file__).parents[1] / "scripts/ci/desktop_coverage_gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def fixture():
    current = {"python": {"src/desktop/a.py": gate.row(10, 8)},
               "app": {"app/src/a.ts": gate.row(10, 8)}}
    baseline = {runtime: {"total": gate.total(rows), "files": deepcopy(rows)}
                for runtime, rows in current.items()}
    baseline.update(target_files=["src/desktop/a.py", "app/src/a.ts"], exceptions={})
    return baseline, current


def test_pass_and_improvement():
    baseline, current = fixture()
    assert gate.evaluate(baseline, current) == []
    current["python"]["src/desktop/a.py"] = gate.row(10, 9)
    assert gate.evaluate(baseline, current) == []


def test_percentage_and_dark_line_ratchets_are_independent():
    baseline, current = fixture()
    current["python"]["src/desktop/a.py"] = gate.row(20, 17)
    assert any("coverage regressed" in finding for finding in gate.evaluate(baseline, current))
    current["python"]["src/desktop/a.py"] = gate.row(8, 6)
    assert any("total line coverage dropped" in finding
               for finding in gate.evaluate(baseline, current))


def test_unrelated_coverage_does_not_hide_file_regression():
    baseline, current = fixture()
    current["python"]["src/desktop/a.py"] = gate.row(10, 7)
    current["python"]["src/new.py"] = gate.row(100, 100)
    assert any("src/desktop/a.py: coverage regressed" == finding
               for finding in gate.evaluate(baseline, current))


def test_missing_file_target_and_new_floor_fail_closed():
    baseline, current = fixture()
    current["app"] = {"app/src/b.ts": gate.row(10, 7)}
    findings = gate.evaluate(baseline, current)
    assert any("missing from report" in finding for finding in findings)
    assert any("targeted executable file missing" in finding for finding in findings)
    assert any("new executable file below 80%" in finding for finding in findings)


def test_exception_does_not_disable_ratchet_and_requires_line_reasons():
    baseline, current = fixture()
    baseline["exceptions"]["src/desktop/a.py"] = {
        "reason": "native", "category": "native_display", "lines": [1, 2]}
    current["python"]["src/desktop/a.py"] = gate.row(10, 7)
    assert any("coverage regressed" in finding for finding in gate.evaluate(baseline, current))
    baseline["exceptions"]["src/desktop/a.py"] = {}
    assert any("exact lines" in finding for finding in gate.evaluate(baseline, current))


def test_istanbul_multiple_statements_on_one_line_count_once(tmp_path):
    report = {str(tmp_path / "app/src/a.ts"): {
        "statementMap": {"0": {"start": {"line": 1}}, "1": {"start": {"line": 1}},
                         "2": {"start": {"line": 2}}}, "s": {"0": 0, "1": 2, "2": 0}}}
    assert gate.app_rows(report, tmp_path) == {"app/src/a.ts": gate.row(2, 1)}
    foreign = {"/another/runner/app/src/a.ts": report[next(iter(report))]}
    assert gate.app_rows(foreign, tmp_path) == {"app/src/a.ts": gate.row(2, 1)}
    with pytest.raises(ValueError, match="Unexpected"):
        gate.app_rows({"outside.ts": report[next(iter(report))]}, tmp_path)


@pytest.mark.parametrize("counts", [(-1, 0), (1, 2), (True, 1), (2, -1)])
def test_malformed_counts_rejected(counts):
    with pytest.raises(ValueError):
        gate.row(*counts)


def test_zero_statement_file_is_fully_covered():
    assert gate.ratio(gate.row(0, 0)) == 1


def test_executable_inventory_does_not_omit_untested_code_or_include_data(tmp_path):
    for path in ("src/desktop/new.py", "src/__init__.py", "app/src/view.vue",
                 "app/src/main.ts", "app/src/env.d.ts", "app/src/style.css"):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("")
    assert gate.executable_inventory(tmp_path) == {
        "python": {"src/desktop/new.py", "src/__init__.py"},
        "app": {"app/src/view.vue", "app/src/main.ts"},
    }


def test_cli_missing_report_fails_closed(tmp_path):
    assert gate.main(["--python-json", str(tmp_path / "missing"),
                      "--app-json", str(tmp_path / "missing"),
                      "--output", str(tmp_path / "output")]) == 2


def test_combine_requires_each_named_shard_not_six_arbitrary_files(tmp_path):
    for index in range(6):
        directory = tmp_path / f"arbitrary-{index}"
        directory.mkdir()
        (directory / ".coverage").write_text("not a coverage database")
    with pytest.raises(ValueError, match="coverage-full-suites"):
        gate.combine(tmp_path, tmp_path / "output")


def test_ci_measurements_use_all_classified_shards_and_upload_even_on_failure():
    root = Path(__file__).parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/phase1-engine.yml").read_text())
    jobs = workflow["jobs"]
    assert jobs["qualification"]["strategy"]["matrix"]["shard"] == [1, 2, 3, 4, 5]
    for name in ("full-suites", "qualification"):
        job = jobs[name]
        assert job["env"]["ODIN_COVERAGE"] == "1"
        upload = next(step for step in job["steps"]
                      if step.get("uses") == "actions/upload-artifact@v4")
        assert upload["if"] == "always()"
        assert upload["with"]["include-hidden-files"] is True
        assert upload["with"]["if-no-files-found"] == "error"
        assert any("rm -f .test-state/.coverage" in step.get("run", "")
                   for step in job["steps"])
    assert jobs["coverage"]["needs"] == ["full-suites", "qualification"]
