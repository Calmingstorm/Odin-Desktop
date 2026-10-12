"""PDF support on Windows: the pinned win_amd64 wheel, first use (phase 3 plan C12)."""
from __future__ import annotations

import json
import sys

import pytest

from src.desktop.platform.windows_files import dacl_is_private
from src.runtime import pdf_resources as pdf
from tests.test_pdf_resources import PDF_BYTES, installed_entries
from tests.test_pdf_resources import wheel_fixture as wheel_fixture  # the shared fixture wheel
from tests.windows.test_windows_adversarial import security_of


def windows_lock(state) -> None:
    state.lock.write_text(json.dumps({**state.metadata, "platform": "windows-amd64"}))


async def test_first_use_installs_the_pinned_wheel_privately(wheel_fixture):
    windows_lock(wheel_fixture)
    module = await pdf.ensure_pdf()
    document = module.open(stream=PDF_BYTES, filetype="pdf")
    assert document[0].get_text() == "Pinned first-use PDF text"
    assert [entry.name for entry in installed_entries(wheel_fixture)] == [wheel_fixture.digest]
    assert dacl_is_private(security_of(wheel_fixture.root, directory=True))
    assert wheel_fixture.requests == 1


def test_a_linux_lock_is_refused_on_windows(wheel_fixture):
    with pytest.raises(pdf.PdfUnavailable, match="missing or invalid"):
        pdf._read_lock()


def test_only_x64_windows_downloads(wheel_fixture, monkeypatch):
    windows_lock(wheel_fixture)
    monkeypatch.setattr("platform.machine", lambda: "ARM64")
    with pytest.raises(pdf.PdfUnavailable, match="only available for x64 Windows"):
        pdf._read_lock()


def test_the_source_tree_lock_is_the_windows_wheel():
    assert pdf._lock_path().name == "pdf.lock.win_amd64.json"
    lock = pdf._read_lock()
    assert (lock["platform"], lock["wheel"]) == (
        "windows-amd64", "pymupdf-1.28.2-cp310-abi3-win_amd64.whl")


def test_a_packaged_runtime_reads_its_own_lock(tmp_path, monkeypatch):
    (tmp_path / "runtime" / "python").mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "runtime" / "python"))
    assert pdf._lock_path() == (tmp_path / "runtime").resolve() / "pdf.lock.json"
