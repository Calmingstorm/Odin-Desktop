"""Pure refusal tests; optional actual pinned inputs are exercised by native CI."""
import json
import sys
from pathlib import Path

import pytest

PYTHON = Path(__file__).resolve().parents[1] / "python"
sys.path.insert(0, str(PYTHON))

import chromium  # noqa: E402

import tools  # noqa: E402


def test_tools_lock_is_client_only_and_qualified():
    lock = json.loads(tools.LOCK_PATH.read_text())
    tools._validate_lock(lock)
    assert "non-production ready" in lock["openssh"]["upstream_support_status"]
    assert "phase-5" in lock["openssh"]["support_decision"]
    assert set(lock["openssh"]["executables"]) == {"ssh.exe", "ssh-keygen.exe"}
    assert "--cacert" in lock["curl"]["trust_policy"]
    assert "LibreSSL" in lock["curl"]["tls_backend"]


@pytest.mark.parametrize("name,field", [(name, field) for name in ("openssh", "curl")
                                      for field in ("size", "sha256", "license", "provenance",
                                                    "closure_sha256")])
def test_missing_tools_pin_refused(name, field):
    lock = json.loads(tools.LOCK_PATH.read_text())
    del lock[name][field]
    with pytest.raises(ValueError, match="Missing"):
        tools._validate_lock(lock)


@pytest.mark.parametrize("path", ["sshd.exe", "ssh-agent.exe", "install-sshd.ps1", "../../ssh.exe"])
def test_server_or_unsafe_tool_closure_refused(path):
    lock = json.loads(tools.LOCK_PATH.read_text())
    lock["openssh"]["files"].append(path)
    with pytest.raises(ValueError, match="Unexpected"):
        tools._validate_lock(lock)


def test_wrong_host_refused_before_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.sys, "platform", "linux")
    with pytest.raises(ValueError, match="Windows AMD64"):
        tools.stage_tools(tmp_path / "resources", tmp_path / "cache")
    assert not (tmp_path / "resources").exists()


def test_cached_size_mismatch_refused(tmp_path):
    path = tmp_path / "input.zip"
    path.write_bytes(b"fixture")
    with pytest.raises(ValueError, match="hash mismatch"):
        chromium._cached({"sha256": chromium._sha256(path), "size": 99}, tmp_path, "input.zip")


def test_windows_browser_lock_has_locked_driver_and_data_closure():
    lock = json.loads((PYTHON / "chromium.lock.win_amd64.json").read_text())
    assert lock["playwright"]["driver"]["path"].endswith("node.exe")
    assert lock["chromium"]["closure"]["files"] == 290
    assert lock["chromium"]["executable"].endswith("chrome-headless-shell.exe")
    assert len(lock["chromium"]["closure"]["inventory_sha256"]) == 64


def test_pdf_windows_stage_selects_existing_windows_lock(tmp_path, monkeypatch):
    import pdf

    monkeypatch.setattr(pdf.sys, "platform", "win32")
    result = pdf.stage_pdf(tmp_path / "runtime", tmp_path / "cache")
    assert (tmp_path / "runtime/pdf.lock.json").read_bytes() == (
        PYTHON / "pdf.lock.win_amd64.json").read_bytes()
    assert result["provenance"]["input_lock"].endswith("pdf.lock.win_amd64.json")
    assert result["installed_payload"] == []


def test_search_model_pins_are_one_cross_platform_set():
    import models

    assert models.ASSETS["model_optimized.onnx"][:2] == (
        "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431", 66465124)
    assert models.ASSETS["tokenizer.json"][:2] == (
        "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66", 711396)


def test_stage_tool_failure_never_publishes(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.sys, "platform", "win32")
    monkeypatch.setattr(tools.platform, "machine", lambda: "AMD64")

    def fail(*args, **kwargs):
        raise ValueError("fixture hash mismatch")

    monkeypatch.setattr(tools, "_cached", fail)
    root = tmp_path / "resources"
    with pytest.raises(ValueError, match="hash mismatch"):
        tools.stage_tools(root, tmp_path / "cache")
    assert not (root / "tools").exists()
    assert not list(root.glob(".tools-*"))


def test_stage_tools_refuses_prior_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.sys, "platform", "win32")
    monkeypatch.setattr(tools.platform, "machine", lambda: "AMD64")
    root = tmp_path / "resources"
    (root / "tools").mkdir(parents=True)
    sentinel = root / "tools/prior"
    sentinel.write_bytes(b"preserved")
    with pytest.raises(ValueError, match="must be absent"):
        tools.stage_tools(root, tmp_path / "cache")
    assert sentinel.read_bytes() == b"preserved"
