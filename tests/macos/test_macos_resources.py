"""macOS: the first-use PDF reader's pinned wheel, as the Mac's own lock."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.desktop.platform import macos_resources
from src.runtime import pdf_resources

ROOT = Path(__file__).resolve().parents[2]
MAC_LOCK = ROOT / "app/packaging/python/pdf.lock.macos_arm64.json"


def test_the_routes_reach_the_macs_lock():
    assert pdf_resources._lock_path.darwin_target == \
        "src.desktop.platform.macos_resources:pdf_lock_path"
    assert pdf_resources._read_lock.darwin_target == \
        "src.desktop.platform.macos_resources:read_pdf_lock"


def test_a_source_run_reads_the_macs_lock_and_offers_the_tool():
    assert pdf_resources._lock_path() == MAC_LOCK
    assert pdf_resources._read_lock() == json.loads(MAC_LOCK.read_text())
    assert pdf_resources.pdf_available()


def test_the_installed_app_reads_the_lock_its_runtime_ships(tmp_path, monkeypatch):
    runtime = tmp_path / "Odin.app/Contents/Resources/runtime"
    (runtime / "python").mkdir(parents=True)
    shutil.copyfile(MAC_LOCK, runtime / "pdf.lock.json")
    monkeypatch.setattr(macos_resources.sys, "prefix", str(runtime / "python"))
    assert pdf_resources._lock_path() == runtime / "pdf.lock.json"
    assert pdf_resources._read_lock()["platform"] == "macos-arm64"


def test_another_platforms_lock_or_a_broken_one_is_refused(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    (runtime / "python").mkdir(parents=True)
    monkeypatch.setattr(macos_resources.sys, "prefix", str(runtime / "python"))
    linux = ROOT / "app/packaging/python/pdf.lock.json"
    for content in (linux.read_text(), "{not json", json.dumps({"schema": 1})):
        (runtime / "pdf.lock.json").write_text(content)
        with pytest.raises(pdf_resources.PdfUnavailable, match="missing or invalid"):
            pdf_resources._read_lock()
    (runtime / "pdf.lock.json").unlink()
    with pytest.raises(pdf_resources.PdfUnavailable, match="missing or invalid"):
        pdf_resources._read_lock()


def test_only_apple_silicon_downloads_it(monkeypatch):
    monkeypatch.setattr(macos_resources.platform, "machine", lambda: "x86_64")
    with pytest.raises(pdf_resources.PdfUnavailable, match="only available for Apple silicon"):
        pdf_resources._read_lock()
