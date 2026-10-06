"""Core attachment uses shipped ownership, never an env-based opt-out."""
import sys

import pytest

from src.desktop.package_ownership import acquire_core_lease
from src.desktop.package_state import PackageStateError
from src.desktop.paths import ProfilePaths


def test_source_core_has_no_installed_lease_or_writes(tmp_path):
    paths = ProfilePaths.from_xdg("test", environ={}, home=tmp_path)
    assert acquire_core_lease(paths) is None
    assert not paths.config_dir.exists()


def test_bundled_core_missing_module_cannot_run_as_development(tmp_path, monkeypatch):
    monkeypatch.delenv("ODIN_DESKTOP_PACKAGE_KIND", raising=False)
    paths = ProfilePaths.from_xdg("test", environ={}, home=tmp_path)
    source = tmp_path / "resources/runtime/engine/src/desktop/package_ownership.py"
    source.parent.mkdir(parents=True)
    with pytest.raises(PackageStateError, match="startup refused"):
        acquire_core_lease(paths, source_file=source)
    assert not paths.config_dir.exists()


def test_bundled_core_uses_resource_module_and_exact_cleanup_paths(tmp_path):
    resources = tmp_path / "resources"
    source = resources / "runtime/python/lib/python3.12/site-packages/src/desktop/module.py"
    source.parent.mkdir(parents=True)
    (resources / "ownership.py").write_text('''
def ownership_paths(kind):
    return kind
def acquire_lifetime(paths, role, app_cleanup, core_cleanup):
    return paths,role,app_cleanup,core_cleanup
''')
    paths = ProfilePaths.from_xdg("test", environ={}, home=tmp_path)
    assert acquire_core_lease(paths, source_file=source) == (
        "appimage", "core", paths.config_dir.parent / "test-cleanup-state.json",
        paths.data_dir / "resource-cleanup.json")
    assert not paths.config_dir.exists()
    sys.modules.pop("odin_package_ownership", None)


def test_module_symlink_cannot_select_other_installation(tmp_path):
    resources = tmp_path / "resources"
    source = resources / "runtime/engine/src/module.py"
    source.parent.mkdir(parents=True)
    marker = tmp_path / "foreign-module"
    marker.write_text("appimage")
    (resources / "ownership.py").symlink_to(marker)
    paths = ProfilePaths.from_xdg("test", environ={}, home=tmp_path)
    with pytest.raises(PackageStateError):
        acquire_core_lease(paths, source_file=source)
