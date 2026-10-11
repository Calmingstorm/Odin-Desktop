"""A skill dependency that Odin's own runtime shadows is reported, not claimed and reinstalled.

Skill packages go to the profile's folder, after the runtime's packages, so a skill never
replaces a package Odin itself uses. A requirement that conflicts with the runtime's copy used
to be reported as auto-installed, stay unsatisfied, and install again on every load.
"""
from __future__ import annotations

import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from src.tools import skill_manager as sm


def pip_writing(target: Path, name: str, release: str, calls: list):
    """pip's effect on the profile folder, without an index: one installed distribution."""
    def run(argv, **kwargs):
        calls.append(argv)
        info = target / f"{name.replace('-', '_')}-{release}.dist-info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {release}\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")
    return run


@pytest.fixture(autouse=True)
def own_import_path(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))  # the profile folder is appended


def test_a_version_odin_shadows_is_a_conflict_and_is_not_reinstalled(tmp_path, monkeypatch):
    runtime = version("packaging")  # a package Odin's runtime has
    target = tmp_path / "skill-packages"
    calls: list = []
    monkeypatch.setattr(sm.subprocess, "run", pip_writing(target, "packaging", "999.0", calls))
    for _ in range(2):  # the second load knows without running pip again
        already, new, diagnostics = sm.resolve_dependencies(["packaging==999.0"], target)
        assert (already, new) == ([], [])
        assert [d.level for d in diagnostics] == ["error"]
        assert "conflicts" in diagnostics[0].message and runtime in diagnostics[0].message
    assert len(calls) == 1
    assert version("packaging") == runtime  # Odin's own copy is still the one that imports


def test_a_package_odin_lacks_installs_once_and_then_counts_as_installed(tmp_path, monkeypatch):
    target = tmp_path / "skill-packages"
    calls: list = []
    monkeypatch.setattr(sm.subprocess, "run",
                        pip_writing(target, "odin-fixture-only", "1.0", calls))
    already, new, diagnostics = sm.resolve_dependencies(["odin-fixture-only==1.0"], target)
    assert (already, new) == ([], ["odin-fixture-only==1.0"])
    assert [d.level for d in diagnostics] == ["warn"]  # "Auto-installed dependencies: …"
    already, new, diagnostics = sm.resolve_dependencies(["odin-fixture-only==1.0"], target)
    assert (already, new, diagnostics) == (["odin-fixture-only==1.0"], [], [])
    assert len(calls) == 1


def test_pip_succeeding_without_an_importable_package_is_an_error(tmp_path, monkeypatch):
    target = tmp_path / "skill-packages"
    monkeypatch.setattr(sm.subprocess, "run",
                        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "", ""))
    already, new, diagnostics = sm.resolve_dependencies(["odin-fixture-absent==1.0"], target)
    assert (already, new) == ([], [])
    assert [d.level for d in diagnostics] == ["error"]
    assert "can't be imported" in diagnostics[0].message
