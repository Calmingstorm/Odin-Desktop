"""Ownership tooling consumes JSON data; no document-wording assertions."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.maintenance.phase2_plan import main, validate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    return (
        json.loads((ROOT / "maintenance/phase2-file-plan.json").read_text()),
        json.loads((ROOT / "maintenance/manifest.json").read_text()),
    )


def test_actual_plan_covers_each_source_replacement_and_adaptation(inputs):
    result = validate(*inputs)
    assert result["source_rows"] == 409
    assert result["replacement_rows"] == 30
    assert result["adaptation_rows"] == 233
    assert sum(result["adaptation_families"].values()) == 233
    assert result["v1_surfaces"] == 20
    assert result["status"] == "planned-not-implemented"


@pytest.mark.parametrize("mutation", [
    "missing_replacement", "duplicate_replacement", "wrong_baseline", "claimed_implemented",
    "unknown_step", "unsafe_module", "unowned_module", "missing_surface", "empty_surface",
    "unowned_surface", "missing_family", "overlapping_family", "stale_family",
    "duplicate_inventory", "engine_without_modules", "unknown_boundary", "duplicate_module",
    "unsafe_source", "missing_step", "unsafe_pattern", "unknown_family_step",
    "duplicate_family", "unknown_family_boundary", "wrong_module_extension",
    "core_as_app_exemption", "core_as_packaging", "app_missing_core_counterpart",
])
def test_incomplete_or_ambiguous_plans_fail_closed(inputs, mutation):
    plan, manifest = copy.deepcopy(inputs)
    if mutation == "missing_replacement":
        plan["replacements"].pop()
    elif mutation == "duplicate_replacement":
        plan["replacements"].append(plan["replacements"][0])
    elif mutation == "wrong_baseline":
        plan["baseline"] = "other"
    elif mutation == "claimed_implemented":
        plan["status"] = "passed"
    elif mutation == "unknown_step":
        plan["replacements"][0]["step"] = 9
    elif mutation == "unsafe_module":
        plan["steps"][0]["new_modules"][0] = "../outside.py"
    elif mutation == "unowned_module":
        plan["replacements"][0]["modules"] = ["src/not_owned.py"]
    elif mutation == "missing_surface":
        del plan["v1_surfaces"]["search"]
    elif mutation == "empty_surface":
        plan["v1_surfaces"]["search"]["modules"] = []
    elif mutation == "unowned_surface":
        plan["v1_surfaces"]["search"]["modules"] = ["src/not_owned.py"]
    elif mutation == "missing_family":
        plan["adaptation_owners"].pop()
    elif mutation == "overlapping_family":
        plan["adaptation_owners"].append(
            {"pattern": "src/*", "steps": [1], "boundary": "phase2-engine"})
    elif mutation == "stale_family":
        plan["adaptation_owners"].append(
            {"pattern": "src/absent/*", "steps": [1], "boundary": "phase2-engine"})
    elif mutation == "duplicate_inventory":
        manifest["entries"].append(next(row for row in manifest["entries"]
                                        if row["path"].startswith("src/")))
    elif mutation == "engine_without_modules":
        plan["replacements"][0]["modules"] = []
    elif mutation == "unknown_boundary":
        plan["replacements"][0]["boundary"] = "qualified"
    elif mutation == "duplicate_module":
        plan["steps"][0]["new_modules"].append(plan["steps"][0]["new_modules"][0])
    elif mutation == "unsafe_source":
        plan["replacements"][0]["source"] = "/outside.py"
    elif mutation == "missing_step":
        plan["steps"].pop()
    elif mutation == "unsafe_pattern":
        plan["adaptation_owners"][0]["pattern"] = "../*"
    elif mutation == "unknown_family_step":
        plan["adaptation_owners"][0]["steps"] = [9]
    elif mutation == "duplicate_family":
        plan["adaptation_owners"].append(plan["adaptation_owners"][0])
    elif mutation == "unknown_family_boundary":
        plan["adaptation_owners"][0]["boundary"] = "qualified"
    elif mutation == "wrong_module_extension":
        plan["steps"][0]["new_modules"][0] = "src/desktop/not_a_module.txt"
    elif mutation == "core_as_app_exemption":
        plan["replacements"][0].update({"modules": [], "boundary": "phase3-app"})
    elif mutation == "core_as_packaging":
        plan["replacements"][0]["boundary"] = "phase3-packaging"
    elif mutation == "app_missing_core_counterpart":
        next(row for row in plan["replacements"]
             if row["source"] == "ui/js/pages/setup.js")["modules"] = []
    with pytest.raises(ValueError):
        validate(plan, manifest)


def test_check_command_reports_counts_without_engine_imports(inputs, tmp_path, capsys):
    plan, manifest = inputs
    directory = tmp_path / "maintenance"
    directory.mkdir()
    (directory / "phase2-file-plan.json").write_text(json.dumps(plan))
    (directory / "manifest.json").write_text(json.dumps(manifest))
    assert main(["--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["replacement_rows"] == 30


def test_missing_or_malformed_input_is_not_a_passing_gate(tmp_path, capsys):
    assert main(["--root", str(tmp_path)]) == 1
    assert "failed" in capsys.readouterr().out
    directory = tmp_path / "maintenance"
    directory.mkdir()
    (directory / "phase2-file-plan.json").write_text("{")
    assert main(["--root", str(tmp_path)]) == 1
    assert "failed" in capsys.readouterr().out
