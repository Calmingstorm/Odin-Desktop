"""Pure packaging behaviour; no graphical bus, input or service calls."""
import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "desktop_helpers", ROOT / "app/packaging/python/helpers.py"
)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def test_checked_copy_rejects_hash_drift(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"exact input")
    with pytest.raises(ValueError, match="locked input hash mismatch"):
        helpers._checked_copy(source, tmp_path / "output", "0" * 64)
    assert not (tmp_path / "output").exists()


def test_checked_copy_rejects_destination_link(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"exact input")
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"unchanged")
    output = tmp_path / "output"
    output.symlink_to(sentinel)
    with pytest.raises(ValueError, match="destination symlink"):
        helpers._checked_copy(source, output)
    assert sentinel.read_bytes() == b"unchanged"


def test_stage_requires_actual_engine_assets(tmp_path):
    with pytest.raises(ValueError, match="engine package asset missing"):
        helpers.stage_helpers(tmp_path / "runtime", tmp_path / "cache")


def test_stage_rejects_asset_drift_before_native_build(tmp_path):
    dest = tmp_path / "runtime" / helpers.ASSETS
    shutil.copytree(ROOT / "src/computer/runtime/assets", dest)
    (dest / "fonts.conf").write_bytes(b"drift")
    with pytest.raises(ValueError, match="engine package asset missing or drifted: fonts.conf"):
        helpers.stage_helpers(tmp_path / "runtime", tmp_path / "cache")


@pytest.mark.parametrize("relative", ["../outside", "/absolute"])
def test_offline_verifier_rejects_manifest_escape(tmp_path, relative):
    with pytest.raises(ValueError, match="unsafe helper manifest path"):
        helpers.prove_helpers(tmp_path, {"files": [{"path": relative}]})


def test_offline_verifier_detects_corruption(tmp_path):
    resource = tmp_path / "resource"
    resource.write_bytes(b"modified")
    with pytest.raises(ValueError, match="digest/path mismatch"):
        helpers.prove_helpers(tmp_path, {"files": [{"path": "resource", "sha256": "0" * 64}]})


def test_offline_verifier_rejects_extra_uninventoried_helper(tmp_path):
    folder = tmp_path / "helpers"
    folder.mkdir()
    (folder / "unexpected").write_bytes(b"not admitted to resource inventory")
    with pytest.raises(ValueError, match="inventory closure mismatch"):
        helpers.prove_helpers(tmp_path, {"files": []})


def test_environment_never_inherits_graphical_or_loader_state(tmp_path, monkeypatch):
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "LD_PRELOAD"):
        monkeypatch.setenv(key, "must-not-propagate")
    env = helpers._env(tmp_path)
    assert all(key not in env for key in
               ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "LD_PRELOAD"))
    assert env["PATH"] == "/usr/bin:/bin"


def test_checked_copy_preserves_bytes_and_digest(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"exact input\x00\xff")
    output = tmp_path / "subdirectory/output"
    helpers._checked_copy(source, output, helpers._sha(source))
    assert output.read_bytes() == source.read_bytes()
    assert output.stat().st_mode & 0o777 == 0o644
