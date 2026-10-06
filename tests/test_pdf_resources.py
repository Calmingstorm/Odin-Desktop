"""First-use PDF behavior with a locally served fixture wheel, never the internet.

The tiny fixture exports the PyMuPDF interface used by all three call sites and
reads the text stream in our uncompressed one-page PDF. Native PyMuPDF itself is
exercised separately by the packaging candidate's read-only wheel fixture lane.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import subprocess
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.runtime import pdf_resources as pdf

PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj\n<< /Length 43 >>\nstream\nBT (Pinned first-use PDF text) Tj ET\n"
    b"endstream\nendobj\n%%EOF"
)
FIXTURE_FITZ = '''import re
class Document:
    page_count = 1
    def __init__(self, stream):
        if not stream.startswith(b"%PDF-"): raise ValueError("not a PDF")
        self.text = re.search(rb"\\((.*?)\\) Tj", stream).group(1).decode()
    def __getitem__(self, index):
        if index != 0: raise IndexError(index)
        return self
    def __iter__(self): return iter([self])
    def get_text(self): return self.text
    def close(self): pass
def open(*, stream, filetype):
    assert filetype == "pdf"
    return Document(stream)
'''


@pytest.fixture
def wheel_fixture(tmp_path, monkeypatch):
    wheel = tmp_path / "fixture.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("fitz/__init__.py", FIXTURE_FITZ)
        archive.writestr("pymupdf-1.28.2.dist-info/METADATA", "Name: PyMuPDF\nVersion: 1.28.2\n")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    lock = tmp_path / "pdf.lock.json"
    metadata = dict(schema=1, package="PyMuPDF", platform="linux-x86_64",
                    version="1.28.2", wheel="fixture.whl",
                    url="https://files.pythonhosted.org/fixture.whl", sha256=digest)
    lock.write_text(json.dumps(metadata))
    data = tmp_path / "data"
    monkeypatch.setattr(pdf, "_lock_path", lambda: lock)
    monkeypatch.setattr(pdf, "runtime_profile_paths", lambda: SimpleNamespace(data_dir=data))
    real_import = importlib.import_module

    def import_fitz(name, *args, **kwargs):
        if name == "fitz" and not any(str(data) in str(path) for path in sys.path):
            raise ModuleNotFoundError("No module named 'fitz'")
        return real_import(name, *args, **kwargs)

    # Simulate an absent extra regardless of the runner's installed dependencies.
    saved = {key: value for key, value in sys.modules.items()
             if key == "fitz" or key.startswith(("fitz.", "pymupdf"))}
    for key in saved:
        del sys.modules[key]
    old_path = sys.path[:]
    monkeypatch.setattr(pdf.importlib, "import_module", import_fitz)
    state = SimpleNamespace(wheel=wheel, metadata=metadata, lock=lock, data=data,
                            root=data / "resources/pdf", digest=digest, requests=0,
                            failure=False, corrupt=False, entered=threading.Event(),
                            release=threading.Event())
    state.release.set()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state.requests += 1
            state.entered.set()
            state.release.wait(5)
            if state.failure:
                self.send_error(503)
                return
            content = b"bad wheel" if state.corrupt else wheel.read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.address = f"http://127.0.0.1:{server.server_port}/fixture.whl"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_urlopen = pdf.urllib.request.urlopen

    def local_urlopen(url, **kwargs):
        assert url == metadata["url"], "no external network permitted"
        return original_urlopen(f"http://127.0.0.1:{server.server_port}/fixture.whl", **kwargs)

    monkeypatch.setattr(pdf.urllib.request, "urlopen", local_urlopen)
    try:
        yield state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join()
        sys.path[:] = old_path
        for key in list(sys.modules):
            if key == "fitz" or key.startswith(("fitz.", "pymupdf")):
                del sys.modules[key]
        sys.modules.update(saved)


def installed_entries(fixture):
    return [entry for entry in fixture.root.iterdir() if entry.name != ".install.lock"]


def test_download_verify_atomic_install_and_cache(wheel_fixture):
    state = wheel_fixture
    module = pdf._ensure_pdf()
    text = module.open(stream=PDF_BYTES, filetype="pdf")[0].get_text()
    assert text == "Pinned first-use PDF text"
    assert Path(module.__file__).is_relative_to(state.root / state.digest)
    assert pdf._ensure_pdf() is module
    assert state.requests == 1
    assert installed_entries(state) == [state.root / state.digest]


def test_hash_mismatch_installs_nothing_and_next_use_retries(wheel_fixture):
    state = wheel_fixture
    state.corrupt = True
    with pytest.raises(pdf.PdfUnavailable, match="SHA-256 mismatch"):
        pdf._ensure_pdf()
    assert installed_entries(state) == []
    state.corrupt = False
    assert callable(pdf._ensure_pdf().open)
    assert state.requests == 2


def test_offline_plain_reason_and_retry(wheel_fixture):
    state = wheel_fixture
    state.failure = True
    with pytest.raises(pdf.PdfUnavailable, match="Check your internet connection and try again"):
        pdf._ensure_pdf()
    assert installed_entries(state) == []
    state.failure = False
    assert callable(pdf._ensure_pdf().open)
    assert state.requests == 2


def test_two_concurrent_first_uses_share_one_download(wheel_fixture):
    state = wheel_fixture
    state.release.clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(pdf._ensure_pdf)
        assert state.entered.wait(3)
        second = pool.submit(pdf._ensure_pdf)
        time.sleep(0.05)
        assert not second.done()
        state.release.set()
        assert first.result(timeout=5) is second.result(timeout=5)
    assert state.requests == 1


def test_two_processes_share_one_download(wheel_fixture):
    state = wheel_fixture
    state.release.clear()
    # Separate cores do not share Python locks or sys.modules. Each process
    # uses only the fixture lock/wheel and the same isolated profile folder.
    script = '''import importlib, pathlib, sys, urllib.request
from types import SimpleNamespace
from src.runtime import pdf_resources as pdf
lock, data, address = map(str, sys.argv[1:])
pdf._lock_path = lambda: pathlib.Path(lock)
pdf.runtime_profile_paths = lambda: SimpleNamespace(data_dir=pathlib.Path(data))
real_import = importlib.import_module
def import_module(name, *args, **kwargs):
    if name == "fitz" and not any(data in p for p in sys.path):
        raise ModuleNotFoundError("absent optional extra")
    return real_import(name, *args, **kwargs)
pdf.importlib.import_module = import_module
def download(url, destination):
    assert url == "https://files.pythonhosted.org/fixture.whl"
    with urllib.request.urlopen(address, timeout=5) as response:
        destination.write_bytes(response.read())
pdf._download_wheel = download
assert callable(pdf._ensure_pdf().open)
'''
    command = [sys.executable, "-B", "-c", script, str(state.lock), str(state.data), state.address]
    first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    second = None
    try:
        assert state.entered.wait(5)
        second = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.1)
        state.release.set()
        for child in (first, second):
            stdout, stderr = child.communicate(timeout=10)
            assert child.returncode == 0, (stdout, stderr)
    finally:
        state.release.set()
        for child in (first, second):
            if child is not None and child.poll() is None:
                child.kill()
                child.wait()
    assert state.requests == 1


def test_concurrent_failure_shared_but_next_call_retries(wheel_fixture):
    state = wheel_fixture
    state.failure = True
    state.release.clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(pdf._ensure_pdf)
        assert state.entered.wait(3)
        second = pool.submit(pdf._ensure_pdf)
        time.sleep(0.05)
        assert not second.done()
        state.release.set()
        for future in (first, second):
            with pytest.raises(pdf.PdfUnavailable, match="Check your internet connection"):
                future.result(timeout=5)
    assert state.requests == 1
    assert installed_entries(state) == []
    state.failure = False
    assert callable(pdf._ensure_pdf().open)
    assert state.requests == 2


def test_existing_verified_install_reused_after_module_unloaded(wheel_fixture):
    state = wheel_fixture
    module = pdf._ensure_pdf()
    sys.path.remove(str(state.root / state.digest))
    del sys.modules["fitz"]
    reloaded = pdf._ensure_pdf()
    assert reloaded is not module
    assert state.requests == 1
    assert Path(reloaded.__file__).is_relative_to(state.root / state.digest)


def test_selected_cache_cannot_be_inside_runtime(wheel_fixture, monkeypatch):
    state = wheel_fixture
    monkeypatch.setattr(pdf, "runtime_install_root", lambda: state.data)
    with pytest.raises(pdf.PdfUnavailable, match="outside the application"):
        pdf._ensure_pdf()
    assert not state.root.exists()
    assert state.requests == 0


def test_packaged_lock_comes_from_runtime_not_working_directory(tmp_path, monkeypatch):
    prefix = tmp_path / "resources/runtime/python"
    monkeypatch.setattr(sys, "prefix", str(prefix))
    assert pdf._lock_path() == prefix.parent / "pdf.lock.json"


def test_invalid_wheel_never_published(wheel_fixture):
    state = wheel_fixture
    with zipfile.ZipFile(state.wheel, "w") as archive:
        archive.writestr("../escape", "no")
    state.metadata["sha256"] = hashlib.sha256(state.wheel.read_bytes()).hexdigest()
    state.lock.write_text(json.dumps(state.metadata))
    with pytest.raises(pdf.PdfUnavailable, match="nothing was installed"):
        pdf._ensure_pdf()
    assert installed_entries(state) == []
    assert not (state.root / "escape").exists()


def test_native_import_failure_never_published(wheel_fixture):
    state = wheel_fixture
    with zipfile.ZipFile(state.wheel, "w") as archive:
        archive.writestr("fitz/__init__.py", "raise OSError('native library unavailable')")
    state.metadata["sha256"] = hashlib.sha256(state.wheel.read_bytes()).hexdigest()
    state.lock.write_text(json.dumps(state.metadata))
    with pytest.raises(pdf.PdfUnavailable, match="nothing was installed"):
        pdf._ensure_pdf()
    assert installed_entries(state) == []


def test_optional_extra_does_not_read_lock_or_download(monkeypatch):
    module = SimpleNamespace(open=lambda: None)
    with patch.dict(sys.modules, {"fitz": module}):
        monkeypatch.setattr(pdf, "_read_lock", MagicMock(side_effect=AssertionError("not needed")))
        assert pdf._ensure_pdf() is module


async def test_all_three_pdf_paths_use_one_first_use_install(wheel_fixture, tmp_path):
    from src.discord.attachments import AttachmentProcessor, AttachmentResult
    from src.knowledge.importer import BulkImporter
    from src.tools.handlers.files_docs import FilesDocsTools

    tools = FilesDocsTools.__new__(FilesDocsTools)
    safe_response = SimpleNamespace(status=200, body=PDF_BYTES)
    with patch("src.tools.safe_fetch.safe_fetch", AsyncMock(return_value=safe_response)):
        text = await tools._handle_analyze_pdf({"url": "https://example.org/doc.pdf"})
        assert "## Page 1\nPinned first-use PDF text" in text
        processor = AttachmentProcessor(temp_dir=str(tmp_path))
        attachment = SimpleNamespace(size=len(PDF_BYTES), filename="doc.pdf",
                                     read=AsyncMock(return_value=PDF_BYTES))
        parts = []
        await processor._handle_pdf(attachment, "c", "r", parts, AttachmentResult())
        assert "Pinned first-use PDF text" in parts[0]
        store = SimpleNamespace(ingest=AsyncMock(return_value=1))
        importer = BulkImporter(store, embedder=None)
        result = await importer.import_pdf_url("https://example.org/doc.pdf", source="fixture-pdf")
        assert result.status == "ok"
        assert "Pinned first-use PDF text" in store.ingest.call_args.args[0]
    assert wheel_fixture.requests == 1


async def test_first_use_keeps_event_loop_responsive(wheel_fixture):
    state = wheel_fixture
    state.release.clear()
    task = asyncio.create_task(pdf.ensure_pdf())
    for _ in range(100):
        if state.entered.is_set():
            break
        await asyncio.sleep(0.01)
    assert state.entered.is_set()
    assert not task.done()
    state.release.set()
    assert callable((await task).open)


async def test_handler_first_use_failure_is_nonzero_plain_reason_before_host_read(monkeypatch):
    from src.tools.handlers.files_docs import FilesDocsTools

    reason = (
        "PDF support download failed. Check your internet connection and try again; "
        "nothing was installed."
    )
    resolver = AsyncMock(side_effect=pdf.PdfUnavailable(reason))
    monkeypatch.setattr(pdf, "ensure_pdf", resolver)
    tools = FilesDocsTools.__new__(FilesDocsTools)
    tools._acquire_host = MagicMock(side_effect=AssertionError("no host read on resolver failure"))
    result = await tools._handle_analyze_pdf({"host": "localhost", "path": "/tmp/fixture.pdf"})
    assert result == (reason, 1)
    resolver.assert_awaited_once_with()
    tools._acquire_host.assert_not_called()
