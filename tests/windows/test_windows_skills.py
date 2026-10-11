"""Skill packages on Windows: the profile's own folder, not the runtime (phase 3 plan C10)."""
from __future__ import annotations

import base64
import hashlib
import sys
import zipfile

import pytest

from src.desktop.platform.windows_files import dacl_is_private
from src.tools.skill_manager import resolve_dependencies
from tests.windows.test_windows_adversarial import security_of


def demo_wheel(folder) -> None:
    """A one-module wheel, installed from this folder without an index."""
    dist = "odin_demo_win-1.0.dist-info"
    files = {"odin_demo_win/__init__.py": "VALUE = 'windows'\n",
             f"{dist}/METADATA": "Metadata-Version: 2.1\nName: odin-demo-win\nVersion: 1.0\n",
             f"{dist}/WHEEL": ("Wheel-Version: 1.0\nGenerator: odin-test\n"
                               "Root-Is-Purelib: true\nTag: py3-none-any\n")}

    def digest(text: str) -> str:
        raw = hashlib.sha256(text.encode()).digest()
        return "sha256=" + base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    record = "".join(f"{path},{digest(text)},{len(text.encode())}\n"
                     for path, text in files.items())
    with zipfile.ZipFile(folder / "odin_demo_win-1.0-py3-none-any.whl", "w") as wheel:
        for path, text in files.items():
            wheel.writestr(path, text)
        wheel.writestr(f"{dist}/RECORD", record + f"{dist}/RECORD,,\n")


def test_a_dependency_installs_into_a_private_profile_folder(tmp_path, monkeypatch):
    pytest.importorskip("pip")  # the packaged runtime gets pip with phase 4
    monkeypatch.setattr(sys, "path", [*sys.path])
    (tmp_path / "wheels").mkdir()
    demo_wheel(tmp_path / "wheels")
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(tmp_path / "wheels"))
    target = tmp_path / "skill-packages"
    already, added, diagnostics = resolve_dependencies(["odin-demo-win==1.0"], target)
    assert (already, added) == ([], ["odin-demo-win==1.0"]), diagnostics
    assert dacl_is_private(security_of(target, directory=True))
    try:
        import odin_demo_win

        assert odin_demo_win.VALUE == "windows"
        assert odin_demo_win.__file__.lower().startswith(str(target).lower())
        assert sys.path[-1] == str(target)  # after the runtime's own packages
    finally:
        sys.modules.pop("odin_demo_win", None)
