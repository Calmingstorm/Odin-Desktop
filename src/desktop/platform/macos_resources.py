"""macOS: the first-use PDF reader's pinned wheel (``src/runtime/pdf_resources``).

The installed Mac app ships the Apple-silicon lock as ``runtime/pdf.lock.json``
(``app/packaging/python/pdf.lock.macos_arm64.json``); a source run reads that file itself. The
lock is accepted only for its own platform, on Apple silicon; everything else is Odin's.
"""
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path


def pdf_lock_path() -> Path:
    """``pdf_resources._lock_path`` on macOS."""
    from src.runtime import pdf_resources

    prefix = Path(sys.prefix).resolve()
    if prefix.name == "python" and prefix.parent.name == "runtime":
        return prefix.parent / "pdf.lock.json"
    return (Path(pdf_resources.__file__).resolve().parents[2]
            / "app/packaging/python/pdf.lock.macos_arm64.json")


def read_pdf_lock() -> dict:
    """``pdf_resources._read_lock`` on macOS: the same checks, for the Mac's own lock."""
    from src.runtime.pdf_resources import PdfUnavailable, _lock_path

    try:
        lock = json.loads(_lock_path().read_text(encoding="utf-8"))
        digest = lock["sha256"]
        if (lock["schema"] != 1 or lock["package"] != "PyMuPDF"
                or lock["platform"] != "macos-arm64"
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or not lock["url"].startswith("https://")
                or not lock["wheel"].endswith(".whl")):
            raise ValueError("invalid pinned wheel")
        if platform.machine() != "arm64":
            raise PdfUnavailable("PDF support download is only available for Apple silicon Macs.")
        return lock
    except PdfUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PdfUnavailable(
            "PDF support download cannot start: the pinned wheel lock is missing or invalid."
        ) from exc
