"""Stage only the first-use PDF download pin, never PyMuPDF or MuPDF bytes."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import shutil
import tomllib

LOCK_PATH = Path(__file__).with_name("pdf.lock.json")
REPOSITORY = Path(__file__).resolve().parents[3]


def _locked_wheel(lock: dict) -> dict:
    packages = tomllib.loads((REPOSITORY / "uv.lock").read_text())["package"]
    package = next(item for item in packages if item["name"] == "pymupdf")
    wheel = next((item for item in package["wheels"] if item["url"] == lock["url"]), None)
    if (package["version"] != lock["version"] or wheel is None
            or wheel["hash"] != "sha256:" + lock["sha256"]
            or Path(lock["url"]).name != lock["wheel"]):
        raise ValueError("PDF lock does not match uv.lock's optional PyMuPDF wheel")
    project = next(item for item in packages if item["name"] == "odin-desktop-engine")
    if any(item["name"] == "pymupdf" for item in project.get("dependencies", [])):
        raise ValueError("PyMuPDF must not be a production dependency")
    if not any(item["name"] == "pymupdf"
               for item in project.get("optional-dependencies", {}).get("pdf", [])):
        raise ValueError("PyMuPDF must remain in the optional pdf extra")
    return wheel


def is_pdf_payload(name: str) -> bool:
    """Package paths, including legacy fitz and license/native/wheel names."""
    parts = PurePosixPath(name).parts
    return any("pymupdf" in part.casefold() or "mupdf" in part.casefold()
               or part.casefold() in {"fitz", "fitz.py"} for part in parts)


def assert_no_pdf_payload(root: Path) -> dict:
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        if is_pdf_payload(name):
            raise ValueError("PyMuPDF/MuPDF is not distributed: " + name)
    return {"pymupdf_mupdf_files": 0, "policy": "pinned download on first use"}


def stage_pdf(bundle_root: Path, cache_dir: Path) -> dict:
    """Copy the immutable download lock. No wheel/license staging or download."""
    root = Path(bundle_root).resolve()
    lock = json.loads(LOCK_PATH.read_text())
    _locked_wheel(lock)
    assert_no_pdf_payload(root)
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LOCK_PATH, root / "pdf.lock.json")
    return {"name": "pdf-first-use", "version": lock["version"],
            "distribution": "not bundled", "download": {"url": lock["url"],
            "sha256": lock["sha256"], "wheel": lock["wheel"]},
            "provenance": {"input_lock": "app/packaging/python/pdf.lock.json",
                           "optional_dependency_lock": "uv.lock"},
            "installed_payload": [], "licenses": []}
