"""Portable harness contract checks; native results come only from Windows CI."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "windows_runtime_acceptance", ROOT / "scripts/packaging/windows-runtime-acceptance.py")
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


def test_cold_environment_does_not_inherit_python_trust_proxy_or_user_settings(tmp_path):
    ambient = {"SystemRoot": "C:/Windows", "PATH": "malicious", "PYTHONPATH": "host",
               "CURL_CA_BUNDLE": "host.pem", "HTTPS_PROXY": "host", "SECRET": "hidden",
               "LOCALAPPDATA": "real-user", "GITHUB_TOKEN": "hidden"}
    env = HARNESS.cold_environment(tmp_path / "work", tmp_path / "resources", ambient)
    assert env["PATH"] == "C:/Windows/System32"
    unwanted = {"PYTHONPATH", "CURL_CA_BUNDLE", "HTTPS_PROXY", "SECRET", "GITHUB_TOKEN"}
    assert not unwanted & env.keys()
    assert env["LOCALAPPDATA"] == str(tmp_path / "work/local")
    assert env["ODIN_DESKTOP_BUNDLE_ROOT"] == str(tmp_path / "resources/runtime")
    assert env["HF_HUB_OFFLINE"] == "1"


def test_resource_snapshot_detects_extra_missing_and_changed_files(tmp_path):
    (tmp_path / "one").write_bytes(b"one")
    before = HARNESS.digest_tree(tmp_path)
    (tmp_path / "two").write_bytes(b"two")
    assert HARNESS.digest_tree(tmp_path) != before
    (tmp_path / "two").unlink()
    assert HARNESS.digest_tree(tmp_path) == before
    (tmp_path / "one").write_bytes(b"changed")
    assert HARNESS.digest_tree(tmp_path) != before
    (tmp_path / "one").unlink()
    assert HARNESS.digest_tree(tmp_path) != before


def test_workflow_has_actual_stage_and_native_acceptance_not_just_source_tests():
    text = (ROOT / ".github/workflows/windows-engine.yml").read_text()
    assert "build-runtime.py" in text
    assert "windows-runtime-acceptance.py" in text
    assert "windows-runtime-acceptance.json" in text
