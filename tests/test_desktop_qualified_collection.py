"""The collection runner aggregates groups without claiming execution evidence."""
import importlib.util
import json
from functools import wraps
from pathlib import Path
from types import SimpleNamespace


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


def test_actual_wrapped_frozen_function_preserves_original_collection_identity(
        tmp_path, monkeypatch):
    from tests import test_desktop_qualification as plugin

    source = tmp_path / "tests/test_frozen_fixture.py"
    namespace = {}
    exec(compile("def test_retained_case():\n    return True\n", str(source), "exec"), namespace)
    original = namespace["test_retained_case"]

    @wraps(original)
    def admission_wrapper():
        return original()

    monkeypatch.setattr(plugin, "ROOT", tmp_path)
    (tmp_path / ".test-state").mkdir()
    plugin.pytest_collection_modifyitems(
        SimpleNamespace(getoption=lambda _: True),
        [SimpleNamespace(obj=admission_wrapper,
                         nodeid="tests/test_wrapper.py::test_alias[case1]")],
    )
    result = json.loads((tmp_path / ".test-state/qualification-collected.json").read_text())
    assert result["cases"] == [{
        "original": "tests/test_frozen_fixture.py::test_retained_case[case1]",
        "executable": "tests/test_wrapper.py::test_alias[case1]",
    }]
