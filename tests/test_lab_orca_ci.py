"""Merge regressions for independently owned Orca and canonical fixture lanes."""

import json
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
    assert sum(step.get("run", "").strip().endswith("scripts/run-qualified-tests.py")
               for step in steps) == 1


def test_merge_preserves_orca_and_main_app_script_entrypoints():
    scripts = json.loads((ROOT / "app/package.json").read_text())["scripts"]
    assert scripts["test:orca"] == "playwright test --config test/e2e/orca.config.ts"
    assert scripts["test:a11y"] == "electron-vite build && node scripts/accessibility.mjs"
    assert scripts["test:e2e"] == "electron-vite build && node scripts/lifecycle-e2e.mjs"
    assert scripts["package:candidate"] == "node packaging/build-linux.mjs"
    assert scripts["test:packaging"] == "python3 -m unittest discover -s packaging/tests -v"


def test_canonical_kde_fixture_uses_real_namespace_helper_not_modeled_ownership():
    fixture = (ROOT / "tests/test_lab_kde.py").read_text()
    assert "from scripts.qualification.lab.fixture_userns import" in fixture
    assert 'emit_config(RECIPE, home, retry=request.param == "root-owned-retry")' in fixture
    assert "OWNERSHIP_LOG" not in fixture
    assert "modeled_owners" not in fixture
    assert '"sudo", "-n"' not in fixture
