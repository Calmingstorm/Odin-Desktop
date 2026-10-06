"""Default selection tests use only fake subprocess calls."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_selection():
    spec = importlib.util.spec_from_file_location(
        "desktop_default_selection", ROOT / "scripts/phase1-default-selection.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def group(name, files, **extra):
    return {"name": name, "files": files, "reason": "Reviewed cases", **extra}


def make_plan(root, groups):
    (root / "maintenance").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests/test_good.py").touch()
    (root / "maintenance/qualification-plan.json").write_text(json.dumps({"groups": groups}))


def fake_calls(module, monkeypatch, outcomes=None):
    calls = []
    results = iter(outcomes) if outcomes is not None else None

    def call(command, *, cwd):
        calls.append((command, cwd))
        result = next(results) if results is not None else 0
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(module.subprocess, "call", call)
    return calls


def test_exact_group_selectors_exclusions_and_cli(tmp_path, monkeypatch):
    module = load_selection()
    groups = [group("one", ["tests/test_good.py::TestCase::test_one[param/../x]"],
                    exclude_expression="skip_one or skip_two"),
              group("two", ["tests/test_good.py"])]
    make_plan(tmp_path, groups)
    calls = fake_calls(module, monkeypatch)
    flags = ["--tb=short", "--maxfail=3"]
    assert module.run_default(tmp_path, flags) == 0
    prefix = [sys.executable, str(tmp_path / "scripts/run-phase1-tests.py")]
    assert calls == [
        (prefix + groups[0]["files"] + flags + ["-k", "not (skip_one or skip_two)"], tmp_path),
        (prefix + groups[1]["files"] + flags, tmp_path),
    ]
    assert flags == ["--tb=short", "--maxfail=3"]


def test_desktop_extras_deduplicate_only_whole_files(tmp_path, monkeypatch):
    module = load_selection()
    make_plan(tmp_path, [group("whole", ["tests/test_desktop_whole.py"]),
                         group("partial", ["tests/test_desktop_partial.py::test_one"])])
    for name in ["whole", "partial", "new"]:
        (tmp_path / f"tests/test_desktop_{name}.py").touch()
    calls = fake_calls(module, monkeypatch)
    assert module.run_default(tmp_path, []) == 0
    assert len(calls) == 3
    assert calls[-1][0][2:] == ["tests/test_desktop_new.py", "tests/test_desktop_partial.py"]
    assert sum("tests/test_desktop_whole.py" in cmd for cmd, _ in calls) == 1


def test_failures_visible_all_groups_executed_without_retries(tmp_path, monkeypatch, capsys):
    module = load_selection()
    make_plan(tmp_path, [group(str(i), ["tests/test_good.py"]) for i in range(4)])
    calls = fake_calls(module, monkeypatch, [3, 0, OSError("fake launch failure"), -9])
    assert module.run_default(tmp_path, []) == 1
    assert len(calls) == 4
    output = capsys.readouterr()
    assert json.loads(output.out.splitlines()[-1]) == {"groups": 4, "failed_groups": [
        {"name": "0", "exit_code": 3}, {"name": "2", "exit_code": 1},
        {"name": "3", "exit_code": -9}]}
    assert "fake launch failure" in output.err


@pytest.mark.parametrize("bad", [
    {"files": []}, {"files": "tests/test_good.py"}, {"files": [""]},
    {"files": ["/tests/test_good.py"]}, {"files": ["tests/../test_good.py"]},
    {"files": ["src/test_good.py"]}, {"files": ["tests"]},
    {"files": ["tests//test_good.py"]}, {"files": ["tests/test_good.txt"]},
    {"files": [None]}, {"reason": None}, {"reason": " "},
    {"exclude_expression": []},
])
@pytest.mark.parametrize("extras_only", [False, True])
def test_invalid_later_group_refuses_all_execution(tmp_path, monkeypatch, bad, extras_only):
    module = load_selection()
    make_plan(tmp_path, [group("valid", ["tests/test_good.py"]),
                         {**group("invalid", ["tests/test_good.py"]), **bad}])
    calls = fake_calls(module, monkeypatch)
    with pytest.raises(SystemExit, match="Default selection refused"):
        module.run_default(tmp_path, [], extras_only=extras_only)
    assert calls == []


def test_missing_reason_refuses_execution(tmp_path, monkeypatch):
    module = load_selection()
    make_plan(tmp_path, [{"name": "bad", "files": ["tests/test_good.py"]}])
    calls = fake_calls(module, monkeypatch)
    with pytest.raises(SystemExit, match="rationale"):
        module.run_default(tmp_path, [])
    assert calls == []


@pytest.mark.parametrize("kind", ["empty", "missing-plan", "missing-file", "symlink", "malformed"])
@pytest.mark.parametrize("extras_only", [False, True])
def test_missing_or_unsafe_plan_and_files_fail_closed(tmp_path, monkeypatch, kind, extras_only):
    module = load_selection()
    make_plan(tmp_path, [] if kind == "empty" else [group("one", ["tests/test_good.py"])])
    if kind == "missing-plan":
        (tmp_path / "maintenance/qualification-plan.json").unlink()
    elif kind == "missing-file":
        (tmp_path / "tests/test_good.py").unlink()
    elif kind == "symlink":
        (tmp_path / "tests/test_good.py").unlink()
        (tmp_path / "tests/test_good.py").symlink_to(
            ROOT / "tests/test_desktop_default_selection.py"
        )
    elif kind == "malformed":
        (tmp_path / "maintenance/qualification-plan.json").write_text("{")
    calls = fake_calls(module, monkeypatch)
    with pytest.raises(SystemExit):
        module.run_default(tmp_path, [], extras_only=extras_only)
    assert calls == []


def test_actual_reviewed_plan_preserved_exactly(monkeypatch):
    module = load_selection()
    plan = json.loads((ROOT / "maintenance/qualification-plan.json").read_text())
    calls = fake_calls(module, monkeypatch)
    assert module.run_default(ROOT, ["--collect-only"]) == 0
    for (command, cwd), reviewed in zip(calls, plan["groups"]):
        expected = [sys.executable, str(ROOT / "scripts/run-phase1-tests.py"),
                    *reviewed["files"], "--collect-only"]
        if reviewed.get("exclude_expression"):
            expected += ["-k", f"not ({reviewed['exclude_expression']})"]
        assert command == expected
        assert cwd == ROOT
    whole = {item for g in plan["groups"] for item in g["files"] if "::" not in item}
    extras = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").glob("test_desktop_*.py")
        if path.relative_to(ROOT).as_posix() not in whole
    )
    assert len(calls) == len(plan["groups"]) + bool(extras)
    if extras:
        assert calls[-1][0][2:] == [*extras, "--collect-only"]


def test_additional_only_validates_plan_and_keeps_exact_extra_files_and_receipt(
    tmp_path, monkeypatch,
):
    module = load_selection()
    make_plan(tmp_path, [group("plan", ["tests/test_good.py"], exclude_expression="old_surface")])
    (tmp_path / "tests/test_desktop_extra.py").touch()
    calls = fake_calls(module, monkeypatch)
    assert module.run_default(tmp_path, ["--collect-only"], extras_only=True) == 0
    assert calls == [([sys.executable, str(tmp_path / "scripts/run-phase1-tests.py"),
                      "tests/test_desktop_extra.py", "--collect-only",
                      "--junitxml=.test-state/additional-desktop-boundaries.xml"], tmp_path)]


def test_additional_only_empty_extras_do_not_fall_back_to_plan(tmp_path, monkeypatch):
    module = load_selection()
    make_plan(tmp_path, [group("plan", ["tests/test_good.py"])])
    calls = fake_calls(module, monkeypatch)
    assert module.run_default(tmp_path, [], extras_only=True) == 0
    assert calls == []


@pytest.mark.parametrize("outcome", [7, OSError("launch failed")])
def test_additional_failure_fails_without_retries(tmp_path, monkeypatch, outcome):
    module = load_selection()
    make_plan(tmp_path, [group("plan", ["tests/test_good.py"])])
    (tmp_path / "tests/test_desktop_extra.py").touch()
    calls = fake_calls(module, monkeypatch, [outcome])
    assert module.run_default(tmp_path, [], extras_only=True) == 1
    assert len(calls) == 1


def test_plan_cannot_impersonate_generated_additional_group(tmp_path, monkeypatch):
    module = load_selection()
    make_plan(tmp_path, [group("additional-desktop-boundaries", ["tests/test_good.py"])])
    calls = fake_calls(module, monkeypatch)
    with pytest.raises(SystemExit, match="reserved"):
        module.run_default(tmp_path, [], extras_only=True)
    assert calls == []
