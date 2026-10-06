"""Merge regressions for independently owned Orca and canonical fixture lanes."""

import shlex
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_ci_preserves_canonical_fixture_runner_without_duplicate_fixture_selection():
    workflow = yaml.safe_load((ROOT / ".github/workflows/phase1-engine.yml").read_text())
    steps = workflow["jobs"]["full-suites"]["steps"]
    lane = next(step for step in steps
                if step.get("name", "").startswith("Qualification lab"))
    commands = [shlex.split(line) for line in lane["run"].splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    fixtures = [command for command in commands
                if "scripts/run-lab-fixture-tests.py" in command
                and command[0].endswith("python")]
    assert fixtures == [[".venv/bin/python", "scripts/run-lab-fixture-tests.py"]]
    orca = next(command for command in commands
                if "scripts/run-phase1-tests.py" in command)
    assert {"tests/test_lab_orca.py", "tests/test_native_dialog_events.py",
            "tests/test_lab_orca_ci.py"}.issubset(orca)
    assert not {"tests/test_lab_kde.py", "tests/test_lab_cinnamon.py",
                "tests/test_lab_gnome.py"}.intersection(orca)
    assert not any("run-qualified-tests.py" in step.get("run", "") for step in steps)
    shards = workflow["jobs"]["qualification"]["steps"]
    assert sum(step.get("run", "").strip().endswith(
        'scripts/run-qualified-tests.py --shard "$QUALIFICATION_SHARD/5"') for step in shards) == 1
