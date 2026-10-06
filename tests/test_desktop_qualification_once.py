"""Exercise exact-node ownership with real pytest, only in the isolated runner."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def invoke(tmp_path, state, *arguments):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--noconftest", "-q",
         "-p", "scripts.qualification_once", f"--qualification-once-state={state}",
         *arguments], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True, text=True, timeout=20,
    )


def test_exact_node_ownership_after_exclusions_preserves_parameters_and_failure(tmp_path):
    source = tmp_path / "test_cases.py"
    source.write_text(
        "import pytest\n"
        "@pytest.mark.parametrize('value', ['one', 'two'])\n"
        "def test_case(value): assert value == 'two'\n"
        "def test_skip(): pass\n"
    )
    state = tmp_path / "seen.json"
    state.write_text(json.dumps({"seen": [], "groups": []}))
    first = invoke(tmp_path, state, "test_cases.py", "-k", "not (two or skip)")
    assert first.returncode == 1, first.stdout + first.stderr
    first_state = json.loads(state.read_text())
    assert first_state["seen"] == ["test_cases.py::test_case[one]"]
    second = invoke(tmp_path, state, "test_cases.py", "--junitxml=second.xml")
    assert second.returncode == 0, second.stdout + second.stderr
    assert "2 passed, 1 deselected" in second.stdout
    final = json.loads(state.read_text())
    assert final["groups"] == [
        {"selected": ["test_cases.py::test_case[one]"], "duplicates": []},
        {"selected": ["test_cases.py::test_case[two]", "test_cases.py::test_skip"],
         "duplicates": ["test_cases.py::test_case[one]"]},
    ]
    assert "test_case[one]" not in (tmp_path / "second.xml").read_text()
    duplicate_only = invoke(tmp_path, state, "test_cases.py", "--junitxml=duplicate.xml")
    assert duplicate_only.returncode == 0, duplicate_only.stdout + duplicate_only.stderr
    assert "tests=\"0\"" in (tmp_path / "duplicate.xml").read_text()
    excluded_all = invoke(tmp_path, state, "test_cases.py", "-k", "not test")
    assert excluded_all.returncode == 5, excluded_all.stdout + excluded_all.stderr
    # Missing/corrupt state refuses collection, never silently allows a replay.
    state.write_text("invalid json")
    failed = invoke(tmp_path, state, "test_cases.py")
    assert failed.returncode != 0


def test_real_response_file_selection_loads_explicit_collection_plugin(tmp_path):
    receipt = tmp_path / "nodeids.json"
    (tmp_path / "test_long.py").write_text("def test_one(): pass\n")
    selector = "test_long.py::test_one"
    response = tmp_path / "arguments.txt"
    response.write_text("\n".join([selector] * 500) + "\n--collect-only\n")
    # Already behind the parent PID boundary. No nested sudo/escalation attempt.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--noconftest", "-q",
         "-p", "scripts.ci_collection_receipt", f"--ci-collection-receipt={receipt}",
         f"@{response}"],
        cwd=tmp_path, capture_output=True, text=True, timeout=20,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(receipt.read_text()) == [selector]
