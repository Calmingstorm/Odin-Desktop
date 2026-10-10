"""Resolve optional PyMuPDF, downloading only the hash-pinned first-use wheel.

An installed ``.[pdf]`` extra always wins. Desktop candidates ship the lock,
not PyMuPDF. A verified wheel is expanded privately, checked in a separate
interpreter, then atomically published under the profile's data directory.
Threads share an in-flight result; a file lock also serializes separate cores.
Failures are not cached, so an offline first use can be retried later.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import Future
from pathlib import Path, PurePosixPath
from types import ModuleType

from ..desktop.paths import private_directory
from ..desktop.platform import locks
from ..runtime_paths import runtime_install_root, runtime_profile_paths

_MAX_WHEEL_BYTES = 100 * 1024 * 1024
_MAX_EXPANDED_BYTES = 400 * 1024 * 1024
_guard = threading.Lock()
_inflight: Future | None = None


class PdfUnavailableError(RuntimeError):
    """A plain, caller-visible reason why PDF support cannot load."""


# Keep the short public contract supplied to callers and candidate qualification.
PdfUnavailable = PdfUnavailableError


def _lock_path() -> Path:
    prefix = Path(sys.prefix).resolve()
    if prefix.name == "python" and prefix.parent.name == "runtime":
        return prefix.parent / "pdf.lock.json"
    return Path(__file__).resolve().parents[2] / "app/packaging/python/pdf.lock.json"


def _read_lock() -> dict:
    try:
        lock = json.loads(_lock_path().read_text(encoding="utf-8"))
        digest = lock["sha256"]
        if (lock["schema"] != 1 or lock["package"] != "PyMuPDF"
                or lock["platform"] != "linux-x86_64"
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or not lock["url"].startswith("https://")
                or not lock["wheel"].endswith(".whl")):
            raise ValueError("invalid pinned wheel")
        if sys.platform != "linux" or os.uname().machine != "x86_64":
            raise PdfUnavailable("PDF support download is only available for Linux x86_64.")
        return lock
    except PdfUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PdfUnavailable(
            "PDF support download cannot start: the pinned wheel lock is missing or invalid."
        ) from exc


def pdf_available() -> bool:
    """Whether analyze_pdf can run here, without importing or downloading anything.

    True when PyMuPDF is importable, or when its pinned first-use download can
    start (a valid lock for this platform): Decision F keeps the tool offered.
    """
    try:
        if importlib.util.find_spec("fitz") is not None:
            return True
    except (ImportError, ValueError):
        pass
    try:
        _read_lock()
    except PdfUnavailable:
        return False
    return True


def _download_wheel(url: str, destination: Path) -> None:
    """Bounded TLS-verified download. Test/qualification fixtures replace this."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response, destination.open("wb") as out:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > _MAX_WHEEL_BYTES:
                    raise PdfUnavailable(
                        "PDF support download is too large; nothing was installed."
                    )
                out.write(chunk)
    except (OSError, urllib.error.URLError) as exc:
        raise PdfUnavailable(
            "PDF support download failed. Check your internet connection and try again; "
            "nothing was installed."
        ) from exc


def _extract_wheel(wheel: Path, destination: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        entries = archive.infolist()
        if sum(entry.file_size for entry in entries) > _MAX_EXPANDED_BYTES:
            raise ValueError("wheel expands beyond the size limit")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename
                    or stat.S_ISLNK(mode)):
                raise ValueError("unsafe wheel member")
            # This pinned wheel is a pure site-packages layout, not a pip script
            # installer. Never execute .pth hooks or relocate wheel .data files.
            if path.suffix == ".pth" or any(part.endswith(".data") for part in path.parts):
                raise ValueError("unsupported wheel layout")
        archive.extractall(destination)


def _validate_install(directory: Path) -> None:
    # Validate BEFORE rename. Isolated Python ignores ambient user site/PYTHONPATH;
    # require fitz itself to originate in our staged wheel, not an installed extra.
    probe = (
        "import sys,pathlib; root=pathlib.Path(sys.argv[1]).resolve(); "
        "sys.path.insert(0,str(root)); import fitz; "
        "assert pathlib.Path(fitz.__file__).resolve().is_relative_to(root); "
        "assert callable(fitz.open)"
    )
    subprocess.run([sys.executable, "-I", "-B", "-c", probe, str(directory)],
                   check=True, timeout=30, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def _load_install(directory: Path) -> ModuleType:
    path = str(directory)
    sys.path.insert(0, path)
    importlib.invalidate_caches()
    try:
        return importlib.import_module("fitz")
    except Exception:
        sys.path.remove(path)
        # A partial import must not poison the next first-use attempt.
        for name, module in list(sys.modules.items()):
            location = getattr(module, "__file__", None)
            if location and Path(location).resolve().is_relative_to(directory):
                sys.modules.pop(name, None)
        raise


def _install_pdf() -> ModuleType:
    lock = _read_lock()
    root = (runtime_profile_paths().data_dir / "resources/pdf").resolve()
    # A selected XDG/profile path must not accidentally modify the installed
    # engine or its Python prefix, even if an ancestor is a symlink.
    for immutable in (runtime_install_root().resolve(), Path(sys.prefix).resolve()):
        if root == immutable or immutable in root.parents:
            raise PdfUnavailable(
                "PDF support download needs a user-writable data folder outside the application."
            )
    private_directory(root)
    installed = root / lock["sha256"]
    with (root / ".install.lock").open("a+b") as mutex:
        locks.lock_exclusive(mutex)
        if installed.is_dir():
            try:
                return _load_install(installed)
            except Exception:
                shutil.rmtree(installed)
        with tempfile.TemporaryDirectory(prefix=".download-", dir=root) as temporary:
            work = Path(temporary)
            wheel = work / "download.whl"
            _download_wheel(lock["url"], wheel)
            with wheel.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != lock["sha256"]:
                raise PdfUnavailable(
                    "PDF support download failed verification (SHA-256 mismatch); "
                    "nothing was installed. Try again."
                )
            stage = work / "site-packages"
            stage.mkdir(mode=0o700)
            _extract_wheel(wheel, stage)
            _validate_install(stage)
            stage.rename(installed)
            try:
                return _load_install(installed)
            except Exception:
                shutil.rmtree(installed)
                raise


def _ensure_pdf() -> ModuleType:
    """Synchronous resolver; use ensure_pdf from async application call sites."""
    global _inflight
    try:
        return importlib.import_module("fitz")
    except Exception:
        pass
    with _guard:
        if _inflight is not None:
            future, owner = _inflight, False
        else:
            future = _inflight = Future()
            owner = True
    if not owner:
        return future.result()
    try:
        # Another thread may have completed between the initial import and lock.
        try:
            module = importlib.import_module("fitz")
        except Exception:
            module = _install_pdf()
        future.set_result(module)
        return module
    except Exception as exc:
        if isinstance(exc, PdfUnavailable):
            error = exc
        elif isinstance(exc, PermissionError):
            error = PdfUnavailable(
                "PDF support download needs a writable user data folder; nothing was installed."
            )
        else:
            error = PdfUnavailable(
                "PDF support download could not be installed or loaded; "
                "nothing was installed. Try again."
            )
        future.set_exception(error)
        if error is exc:
            raise
        raise error from exc
    finally:
        with _guard:
            _inflight = None


async def ensure_pdf() -> ModuleType:
    """Keep first-use network, extraction and file-lock waits off the event loop."""
    return await asyncio.to_thread(_ensure_pdf)
