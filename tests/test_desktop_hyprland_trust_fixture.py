"""Portable artifact-only root modeling, not blanket process identity substitution."""
import ast
import copy
import hashlib
import os
from pathlib import Path

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.test_hyprland_manifest_campaign import _root_owned

ROOT = Path(__file__).resolve().parents[1]
_artifact_root = None


@pytest.fixture(autouse=True)
def artifact_root(tmp_path):
    global _artifact_root
    _artifact_root = tmp_path.resolve()
    try:
        yield
    finally:
        _artifact_root = None


def _trusted_filesystem(monkeypatch):
    """Model immutable fixture artifacts only; real interpreter trust stays real."""
    from src.computer.runtime import hyprland_plugin

    real_lstat = os.lstat
    real_fstat = os.fstat

    def within(path):
        candidate = Path(path).absolute()
        return candidate.is_relative_to(_artifact_root) or candidate in _artifact_root.parents

    def lstat(path, *args, **kwargs):
        measured = real_lstat(path, *args, **kwargs)
        return _root_owned(measured) if within(path) else measured

    def fstat(fd):
        measured = real_fstat(fd)
        target = os.readlink(f"/proc/self/fd/{fd}")
        return _root_owned(measured) if within(target) else measured

    monkeypatch.setattr(hyprland_plugin.os, "lstat", lstat)
    monkeypatch.setattr(hyprland_plugin.os, "fstat", fstat)


def adapted():
    original = ast.parse(frozen_source("tests/test_hyprland_autoload_trust.py"))
    changed = copy.deepcopy(original)
    for node in changed.body:
        if (isinstance(node, ast.ImportFrom)
                and node.module == "tests.test_hyprland_manifest_campaign"):
            node.names = [alias for alias in node.names if alias.name != "_trusted_filesystem"]
    assert corpus(original) == corpus(changed)
    return original, changed


def test_original_assertions_parameters_and_scoped_interpreter_measurement(monkeypatch, tmp_path):
    original, changed = adapted()
    assert corpus(original) == corpus(changed)
    executable = Path(f"/proc/{os.getpid()}/exe")
    measured = executable.stat()
    _trusted_filesystem(monkeypatch)
    fd = os.open(executable, os.O_RDONLY)
    try:
        assert os.fstat(fd).st_uid == measured.st_uid
        assert os.fstat(fd).st_mode == measured.st_mode
    finally:
        os.close(fd)
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"fixture")
    artifact.chmod(0o644)
    assert os.lstat(artifact).st_uid == 0
    assert hashlib.sha256(frozen_source("tests/test_hyprland_autoload_trust.py")).hexdigest()


_, _tree = adapted()
_namespace = {"__name__": __name__, "__file__": str(ROOT / "tests/test_hyprland_autoload_trust.py"),
              "_trusted_filesystem": _trusted_filesystem}
exec(compile(_tree, _namespace["__file__"], "exec"), _namespace)
for _node in _tree.body:
    if (isinstance(_node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _node.name.startswith("test_")):
        globals()[f"test_frozen_{_node.name[5:]}"] = _namespace[_node.name]
