"""The collection runner aggregates groups without claiming execution evidence."""
import importlib.util
import json
from pathlib import Path


def test_collection_aggregates_actual_group_identities(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "scripts/run-qualified-tests.py"
    spec = importlib.util.spec_from_file_location("qualified_collection", source)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    (tmp_path / "maintenance").mkdir()
    (tmp_path / ".test-state").mkdir()
    plan = {"groups": [{"name": name, "files": [f"tests/{name}.py"], "reason": "fixture"}
                       for name in ("one", "two")]}
    (tmp_path / "maintenance/qualification-plan.json").write_text(json.dumps(plan))
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    calls = []

    def capture(arguments, **kwargs):
        calls.append(arguments)
        path = next(arg for arg in arguments if arg.startswith("tests/"))
        payload = {"schema_version": 1, "cases": [{"original": path + "::test_case",
                   "executable": path + "::test_case"}]}
        (tmp_path / ".test-state/qualification-collected.json").write_text(json.dumps(payload))
        return 0

    monkeypatch.setattr(runner.subprocess, "call", capture)
    assert runner.main(["--collect-only"]) == 0
    result = json.loads((tmp_path / ".test-state/qualification-collected.json").read_text())
    assert [row["original"] for row in result["cases"]] == [
        "tests/one.py::test_case", "tests/two.py::test_case"]
    assert all("--collect-only" in arguments for arguments in calls)
