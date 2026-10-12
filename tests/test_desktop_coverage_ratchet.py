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


def test_explicit_update_cannot_lower_existing_ceiling(tmp_path, monkeypatch):
    baseline, current = fixture()
    baseline_path = tmp_path / "baseline.json"
    import json
    baseline_path.write_text(json.dumps(baseline))
    python = tmp_path / "python.json"
    python.write_text(json.dumps({"files": {"src/desktop/a.py": {
        "summary": {"num_statements": 10, "covered_lines": 7}}}}))
    app = tmp_path / "app.json"
    app.write_text(json.dumps({"app/src/a.ts": {
        "statementMap": {str(index): {"start": {"line": index + 1}} for index in range(10)},
        "s": {str(index): int(index < 8) for index in range(10)}}}))
    monkeypatch.setattr(gate, "executable_inventory", lambda: {
        runtime: set(rows) for runtime, rows in current.items()})
    monkeypatch.setattr(gate, "windows_inventory", lambda: set())
    monkeypatch.setattr(gate.subprocess, "check_output", lambda *args, **kwargs:
                        "src/desktop/a.py\napp/src/a.ts\n")
    assert gate.main(["--python-json", str(python), "--app-json", str(app),
                      "--baseline", str(baseline_path), "--output", str(tmp_path / "out"),
                      "--update-baseline"]) == 1
    updated = json.loads(baseline_path.read_text())
    assert updated["python"]["files"] == baseline["python"]["files"]
    assert updated["python"]["total"] == baseline["python"]["total"]


def test_ci_measurements_use_all_classified_shards_and_upload_even_on_failure():
    root = Path(__file__).parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/phase1-engine.yml").read_text())
    jobs = workflow["jobs"]
    assert jobs["qualification"]["strategy"]["matrix"]["shard"] == [1, 2, 3, 4, 5]
    for name in ("full-suites", "qualification"):
        job = jobs[name]
        assert job["env"]["ODIN_COVERAGE"] == "1"
        upload = next(step for step in job["steps"]
                      if step.get("uses", "").startswith("actions/upload-artifact@"))
        assert len(upload["uses"].split("@", 1)[1]) == 40
        assert upload["if"] == "always()"
        assert upload["with"]["include-hidden-files"] is True
        assert upload["with"]["if-no-files-found"] == "error"
        assert any("rm -f .test-state/.coverage" in step.get("run", "")
                   for step in job["steps"])
    assert jobs["coverage"]["needs"] == ["full-suites", "qualification", "windows-engine"]
    windows = jobs["windows-engine"]
    assert windows["uses"] == "./.github/workflows/windows-engine.yml"
    assert windows["if"] == jobs["coverage"]["if"]
    gate_step = next(step for step in jobs["coverage"]["steps"]
                     if "desktop_coverage_gate.py" in step.get("run", ""))
    assert "--windows-json" in gate_step["run"] and "--windows-provenance" in gate_step["run"]


# --- Windows-only files: native rows, exact provenance, Linux evaluated on its own ---------


WIN = "src/desktop/platform/win32.py"


def windows_fixture():
    baseline, current = fixture()
    current["windows"] = {WIN: gate.row(10, 9)}
    baseline["windows"] = {"total": gate.total(current["windows"]),
                           "files": deepcopy(current["windows"])}
    baseline["target_files"].append(WIN)
    return baseline, current


def test_windows_rows_never_hide_a_linux_regression():
    baseline, current = windows_fixture()
    assert gate.evaluate(baseline, current) == []
    current["python"]["src/desktop/a.py"] = gate.row(10, 7)
    current["windows"][WIN] = gate.row(10, 10)
    findings = gate.evaluate(baseline, current)
    assert "src/desktop/a.py: coverage regressed" in findings
    assert "python: total missed lines grew" in findings


def test_windows_files_keep_their_own_ratchet_and_floor():
    baseline, current = windows_fixture()
    current["windows"][WIN] = gate.row(10, 8)
    assert f"{WIN}: coverage regressed" in gate.evaluate(baseline, current)
    current["windows"][WIN] = gate.row(10, 9)
    current["windows"]["src/desktop/platform/windows_new.py"] = gate.row(10, 7)
    assert ("src/desktop/platform/windows_new.py: new executable file below 80%"
            in gate.evaluate(baseline, current))


@pytest.mark.parametrize("key", [
    "src\\desktop\\platform\\win32.py",
    "D:\\a\\Odin-Desktop\\Odin-Desktop\\src\\desktop\\platform\\win32.py",
    "D:/a/Odin-Desktop/src/desktop/platform/win32.py",
    "src/desktop/platform/win32.py",
])
def test_windows_report_paths_normalize(key):
    assert gate.windows_path(key) == WIN


@pytest.mark.parametrize("key", ["C:\\other\\file.py", "src/../etc/x.py", "app/src/a.ts"])
def test_unexpected_windows_paths_fail_closed(key):
    with pytest.raises(ValueError, match="Unexpected Windows coverage path"):
        gate.windows_path(key)


def _windows_evidence(tmp_path, *, crlf=True):
    source = tmp_path / WIN
    source.parent.mkdir(parents=True)
    source.write_bytes(b"line\r\nline\r\n" if crlf else b"line\nline\n")
    report = {"files": {WIN.replace("/", "\\"): {
        "summary": {"num_statements": 10, "covered_lines": 9}}}}
    provenance = {"sha": "abc", "sources": {
        WIN: gate.hashlib.sha256(b"line\nline\n").hexdigest()}}
    return report, provenance


def test_windows_rows_need_this_revision_and_these_sources(tmp_path):
    report, provenance = _windows_evidence(tmp_path)
    rows = gate.windows_rows(report, provenance, {WIN}, sha="abc", root=tmp_path)
    assert rows == {WIN: gate.row(10, 9)}
    with pytest.raises(ValueError, match="another revision"):
        gate.windows_rows(report, provenance, {WIN}, sha="def", root=tmp_path)
    with pytest.raises(ValueError, match="name the inventory exactly"):
        gate.windows_rows(report, {**provenance, "sources": {}}, {WIN}, sha="abc", root=tmp_path)
    (tmp_path / WIN).write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="other source bytes"):
        gate.windows_rows(report, provenance, {WIN}, sha="abc", root=tmp_path)


def test_a_missing_windows_row_fails_closed(tmp_path):
    report, provenance = _windows_evidence(tmp_path, crlf=False)
    with pytest.raises(ValueError, match="lacks rows"):
        gate.windows_rows({"files": {}}, provenance, {WIN}, sha="abc", root=tmp_path)


def test_the_windows_inventory_matches_its_naming_invariant(tmp_path):
    platform = tmp_path / "src/desktop/platform"
    platform.mkdir(parents=True)
    for name in ("win32.py", "windows_files.py", "linux.py"):
        (platform / name).write_text("")
    (tmp_path / "maintenance").mkdir()
    inventory = tmp_path / gate.WINDOWS_INVENTORY
    inventory.write_text('["src/desktop/platform/win32.py"]')
    with pytest.raises(ValueError, match="differs from its files"):
        gate.windows_inventory(tmp_path)
    inventory.write_text(gate.json.dumps(
        ["src/desktop/platform/win32.py", "src/desktop/platform/windows_files.py"]))
    assert gate.windows_inventory(tmp_path) == {
        "src/desktop/platform/win32.py", "src/desktop/platform/windows_files.py"}
    assert gate.windows_inventory() == set(gate.json.loads(
        (gate.ROOT / gate.WINDOWS_INVENTORY).read_text()))


def test_cli_without_windows_evidence_fails_closed(tmp_path):
    python = tmp_path / "python.json"
    python.write_text(gate.json.dumps({"files": {}}))
    app = tmp_path / "app.json"
    app.write_text("{}")
    assert gate.main(["--python-json", str(python), "--app-json", str(app),
                      "--output", str(tmp_path / "out"), "--revision", "abc"]) == 2


def test_an_explicit_update_initializes_the_windows_section(tmp_path, monkeypatch):
    """A baseline from before the Windows job gains its section instead of failing."""
    baseline, current = fixture()
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(gate.json.dumps(baseline))
    python = tmp_path / "python.json"
    python.write_text(gate.json.dumps({"files": {"src/desktop/a.py": {
        "summary": {"num_statements": 10, "covered_lines": 9}}}}))
    app = tmp_path / "app.json"
    app.write_text(gate.json.dumps({"app/src/a.ts": {
        "statementMap": {str(index): {"start": {"line": index + 1}} for index in range(10)},
        "s": {str(index): int(index < 9) for index in range(10)}}}))
    report, provenance = _windows_evidence(tmp_path)
    (tmp_path / "windows.json").write_text(gate.json.dumps(report))
    (tmp_path / "provenance.json").write_text(gate.json.dumps(provenance))
    rows = gate.windows_rows
    monkeypatch.setattr(gate, "windows_rows", lambda *args, **kwargs: rows(
        *args, **{**kwargs, "root": tmp_path}))
    monkeypatch.setattr(gate, "windows_inventory", lambda: {WIN})
    monkeypatch.setattr(gate, "executable_inventory", lambda: {
        "python": {"src/desktop/a.py"}, "app": {"app/src/a.ts"}, "windows": {WIN}})
    monkeypatch.setattr(gate.subprocess, "check_output", lambda *args, **kwargs: "")
    assert gate.main(["--python-json", str(python), "--app-json", str(app),
                      "--baseline", str(baseline_path), "--output", str(tmp_path / "out"),
                      "--windows-json", str(tmp_path / "windows.json"),
                      "--windows-provenance", str(tmp_path / "provenance.json"),
                      "--revision", "abc", "--update-baseline"]) == 0
    updated = gate.json.loads(baseline_path.read_text())
    assert updated["windows"]["files"] == {WIN: gate.row(10, 9)}
    assert updated["python"]["files"]["src/desktop/a.py"] == gate.row(10, 9)  # an improvement
