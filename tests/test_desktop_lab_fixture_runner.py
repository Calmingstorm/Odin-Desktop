"""Behavioural wrapper coverage with fake exec, never real sudo or namespaces."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lab_fixture_runner", ROOT / "scripts/run-lab-fixture-tests.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

EXPECTED_TESTS = [
    "tests/test_lab_common.py",
    "tests/test_lab_cinnamon.py",
    "tests/test_lab_gnome.py",
    "tests/test_lab_guest_smoke.py",
    "tests/test_lab_hyprland.py",
    "tests/test_lab_kde.py",
    "tests/test_lab_fixture_userns.py",
]


class ReplacedProcessError(Exception):
    pass


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.os, "getuid", lambda: 1000)
    monkeypatch.setattr(runner.os, "geteuid", lambda: 1000)
    calls = []

    def replace(executable, command):
        calls.append((executable, command))
        raise ReplacedProcessError

    monkeypatch.setattr(runner.os, "execv", replace)
    return calls, tmp_path


@pytest.mark.parametrize("identity", ["getuid", "geteuid"])
def test_root_refused_before_exec(fake, monkeypatch, identity):
    monkeypatch.setattr(runner.os, identity, lambda: 0)
    with pytest.raises(SystemExit, match="root host"):
        runner.main([])
    assert not fake[0]


@pytest.mark.parametrize("arguments", [
    ["tests/test_other.py"], ["--privileged"], ["-k", "x"],
    ["--collect-only", "--collect-only"], ["--collect-only", "-q"],
])
def test_arbitrary_selection_and_options_refused(fake, arguments):
    with pytest.raises(SystemExit, match="selection is fixed"):
        runner.main(arguments)
    assert not fake[0]


@pytest.mark.parametrize("arguments", [[], ["--collect-only"]])
def test_fixed_selection_replaces_wrapper_with_repository_pid_launcher(fake, arguments):
    calls, root = fake
    with pytest.raises(ReplacedProcessError):
        runner.main(arguments)
    assert calls == [(str(root / ".venv/bin/python"),
                      [str(root / ".venv/bin/python"),
                       str(root / "scripts/run-phase1-tests.py"),
                       *EXPECTED_TESTS, "-rs", *arguments])]


def test_exec_failure_propagates_without_fallback(fake, monkeypatch):
    calls = []

    def fail(*arguments):
        calls.append(arguments)
        raise FileNotFoundError("repository python missing")

    monkeypatch.setattr(runner.os, "execv", fail)
    with pytest.raises(FileNotFoundError, match="repository python missing"):
        runner.main([])
    assert len(calls) == 1


def test_collect_only_from_command_line(fake, monkeypatch):
    monkeypatch.setattr(runner.sys, "argv", ["run-lab-fixture-tests.py", "--collect-only"])
    with pytest.raises(ReplacedProcessError):
        runner.main()
    assert fake[0][0][1][-2:] == ["-rs", "--collect-only"]


def test_fixed_fixtures_are_disjoint_from_desktop_extras():
    assert len(runner.TESTS) == len(set(runner.TESTS))
    assert not any(Path(path).name.startswith("test_desktop_") for path in runner.TESTS)
