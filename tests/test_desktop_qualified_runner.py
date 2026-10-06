"""Qualification plans cannot fall back to an unisolated or empty suite."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def runner():
    spec = importlib.util.spec_from_file_location(
        "qualified_runner", ROOT / "scripts/run-qualified-tests.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_qualified_groups_use_namespace_launcher_and_preserve_failure(tmp_path, monkeypatch):
    module = runner()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "maintenance").mkdir()
    (tmp_path / ".test-state").mkdir()
    plan = {"groups": [{"name": "neutral", "files": ["tests/test_neutral.py"],
                        "reason": "reviewed neutral cases", "exclude_expression": "old_surface"}]}
    (tmp_path / "maintenance/qualification-plan.json").write_text(json.dumps(plan))
    captured = []
    monkeypatch.setattr(module.subprocess, "call", lambda args, **kw: captured.append(args) or 1)
    assert module.main() == 1
    assert captured[0][1] == str(tmp_path / "scripts/run-phase1-tests.py")
    assert captured[0][2:6] == ["tests/test_neutral.py", "--tb=short", "-k", "not (old_surface)"]
    result = json.loads((tmp_path / ".test-state/qualification-result.json").read_text())
    assert result["failed_groups"] == [{"name": "neutral", "exit_code": 1}]
    assert "scripts.qualification_once" in captured[0]
    state_flag = next(arg for arg in captured[0] if arg.startswith("--qualification-once-state="))
    assert not Path(state_flag.split("=", 1)[1]).exists()


def test_group_failure_is_not_hidden_when_later_group_succeeds(tmp_path, monkeypatch):
    module = runner()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "maintenance").mkdir()
    (tmp_path / ".test-state").mkdir()
    (tmp_path / "maintenance/qualification-plan.json").write_text(json.dumps({
        "groups": [{"name": name, "reason": "reviewed", "files": ["tests/test_overlap.py"]}
                   for name in ("first", "second")],
    }))
    results = iter([1, 0])
    calls = []
    monkeypatch.setattr(module.subprocess, "call",
                        lambda args, **kw: calls.append(args) or next(results))
    assert module.main() == 1
    assert len(calls) == 2
    assert "--junitxml=.test-state/qualification-0.xml" in calls[0]
    assert "--junitxml=.test-state/qualification-1.xml" in calls[1]
    assert [arg for arg in calls[0] if arg.startswith("--qualification-once-state=")] == [
        arg for arg in calls[1] if arg.startswith("--qualification-once-state=")]


def test_empty_qualification_is_not_success(tmp_path, monkeypatch):
    module = runner()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "maintenance").mkdir()
    (tmp_path / "maintenance/qualification-plan.json").write_text('{"groups": []}')
    with pytest.raises(SystemExit, match="No classified"):
        module.main()


def _plan(tmp_path, names, minutes=None):
    (tmp_path / "maintenance").mkdir(exist_ok=True)
    (tmp_path / ".test-state").mkdir(exist_ok=True)
    groups = [{"name": name, "files": [f"tests/test_{name}.py"], "reason": "reviewed"}
              for name in names]
    (tmp_path / "maintenance/qualification-plan.json").write_text(json.dumps({"groups": groups}))
    if minutes is not None:
        (tmp_path / "maintenance/qualification-group-weights.json").write_text(
            json.dumps({"source": "fixture", "minutes": minutes}))
    return groups


@pytest.mark.parametrize("count", [1, 2, 3, 5, 6])
def test_shards_partition_every_group_exactly_once(count):
    module = runner()
    groups = [{"name": f"g{index}"} for index in range(11)]
    minutes = {f"g{index}": float(index % 4 + 1) for index in range(9)}  # two unmeasured
    shards = module.assign_shards(groups, minutes, count)
    assert len(shards) == count
    assert sorted(index for shard in shards for index in shard) == list(range(11))
    assert shards == module.assign_shards(groups, minutes, count)


def test_shards_balance_longest_first_and_unmeasured_take_the_median():
    module = runner()
    groups = [{"name": name} for name in ("a", "b", "c", "d", "e")]
    assert module.assign_shards(groups, {"a": 5, "b": 3, "c": 3, "d": 2, "e": 1}, 2) == [
        [0, 3], [1, 2, 4]]
    # "e" is unmeasured: the median measurement (3) sorts it ahead of 1-minute "d".
    assert module.assign_shards(groups, {"a": 5, "b": 3, "c": 3, "d": 1}, 2) == [
        [0, 4], [1, 2, 3]]


def test_shard_runs_only_its_groups_but_validates_all(tmp_path, monkeypatch):
    module = runner()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    groups = _plan(tmp_path, ["big", "mid", "small"], {"big": 4, "mid": 3, "small": 2})
    captured = []
    monkeypatch.setattr(module.subprocess, "call", lambda args, **kw: captured.append(args) or 0)
    assert module.main(["--shard", "2/2"]) == 0
    assert [args[2] for args in captured] == ["tests/test_mid.py", "tests/test_small.py"]
    result = json.loads((tmp_path / ".test-state/qualification-result.json").read_text())
    assert result == {"groups": 3, "failed_groups": [], "shard": "2/2",
                      "selected_groups": ["mid", "small"]}
    groups[0]["files"] = ["../escape.py"]
    (tmp_path / "maintenance/qualification-plan.json").write_text(json.dumps({"groups": groups}))
    with pytest.raises(SystemExit, match="Unsafe test selection path"):
        module.main(["--shard", "2/2"])


@pytest.mark.parametrize("arguments", [["--shard", "0/2"], ["--shard", "3/2"], ["--shard", "x"],
                                       ["--shard"], ["--shard", "1/2", "extra"],
                                       ["--collect-only", "--shard", "1/2"]])
def test_bad_shard_arguments_are_refused(tmp_path, monkeypatch, arguments):
    module = runner()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    _plan(tmp_path, ["only"])
    monkeypatch.setattr(module.subprocess, "call", lambda args, **kw: 0)
    with pytest.raises(SystemExit):
        module.main(arguments)
