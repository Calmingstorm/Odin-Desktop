"""Build-time-only staging and offline proof for D14 PDF support."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tomllib
import zipfile

LOCK_PATH = Path(__file__).with_name("pdf.lock.json")
REPOSITORY = Path(__file__).resolve().parents[3]


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _locked_wheel(lock: dict) -> dict:
    packages = tomllib.loads((REPOSITORY / "uv.lock").read_text())["package"]
    package = next(item for item in packages if item["name"] == "pymupdf")
    wheel = next((item for item in package["wheels"]
                  if item["url"] == lock["url"]), None)
    if (package["version"] != lock["version"] or wheel is None
            or wheel["hash"] != "sha256:" + lock["sha256"]
            or Path(lock["url"]).name != lock["wheel"]):
        raise ValueError("PDF lock does not match uv.lock's pinned PyMuPDF wheel")
    return wheel


def _pdf_smoke(python: Path, site: Path, destination: Path) -> dict:
    """Run real fitz open/page extraction with networking disabled."""
    script = """import fitz, json
doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 72), 'D14 offline PDF proof')
data = doc.tobytes()
doc.close()
doc = fitz.open(stream=data, filetype='pdf')
text = doc[0].get_text().strip()
assert doc.page_count == 1 and text == 'D14 offline PDF proof', (doc.page_count, text)
print(json.dumps({'module': fitz.__file__, 'version': fitz.VersionBind,
                  'pages': doc.page_count, 'text': text}))
"""
    env = {"PATH": "/usr/bin:/bin", "HOME": str(destination), "LANG": "C.UTF-8",
           "PYTHONPATH": str(site), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONNOUSERSITE": "1", "http_proxy": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9",
           "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""}
    # -I deliberately ignores PYTHONPATH; add the staged site explicitly in script.
    isolated = "import sys;sys.path.insert(0, %r);%s" % (str(site), script)
    result = subprocess.run([str(python), "-I", "-B", "-c", isolated], env=env,
                            cwd=destination, check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # PyMuPDF currently emits a deprecation warning on stdout through legacy
    # ``fitz`` import; parse the final machine-readable line, not that warning.
    return json.loads(result.stdout.strip().splitlines()[-1])


def _engine_smoke(python: Path, site: Path, destination: Path) -> dict:
    """Exercise analyze_pdf's real extraction handler with a local fixture."""
    # Importing the engine under its actual package name preserves its relative
    # imports while using only staged production dependencies in the child.
    script = """import asyncio, json, sys
sys.path.insert(0, %r)
from src.tools.handlers.files_docs import FilesDocsTools
import fitz
doc = fitz.open(); page = doc.new_page(); page.insert_text((72,72), 'D14 engine PDF proof')
payload = doc.tobytes(); doc.close()
class Stub:
    def _acquire_host(self, name):
        return type('Lease', (), {'target': type('Target', (), {'address':'local','ssh_user':'none','key_path':None,'known_hosts_path':None,'port':22,'host_key_alias':None})(),
                                  'release': lambda self: None,
                                  'run': lambda self, operation: asyncio.sleep(0, result=(payload, ''))})()
result = asyncio.run(FilesDocsTools._handle_analyze_pdf(Stub(), {'host':'offline-proof','path':'/fixture.pdf'}))
assert result.strip() == '## Page 1\\nD14 engine PDF proof', repr(result)
print(json.dumps({'handler':'src.tools.handlers.files_docs.FilesDocsTools._handle_analyze_pdf', 'text':result}))
""" % str(site)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(destination), "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
           "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9",
           "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
           "NO_PROXY": ""}
    result = subprocess.run([str(python), "-I", "-B", "-c", script], env=env,
                            cwd=destination, check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=30)
    return json.loads(result.stdout.strip().splitlines()[-1])


def stage_pdf(bundle_root: Path, cache_dir: Path) -> dict:
    """Stage locked PyMuPDF native engine/license and prove offline PDF extraction.

    ``bundle_root`` is resources/runtime. The runtime's CPython/wheelhouse is
    prepared by the Python runtime stage; this function never downloads or
    installs dependencies.
    """
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise ValueError("PDF lock currently supports Linux x86_64 only")
    root = Path(bundle_root).resolve()
    cache = Path(cache_dir).resolve() / "python-runtime"
    lock = json.loads(LOCK_PATH.read_text())
    _locked_wheel(lock)
    wheel_path = cache / "wheelhouse" / "45bfdaefa770693596fb031cea883f69188b0dc93e0b8fc51f8f3a57ad72381c" / lock["wheel"]
    if not wheel_path.is_file() or _sha256(wheel_path) != lock["sha256"]:
        raise ValueError(f"Locked PyMuPDF wheel missing or corrupt: {wheel_path}")
    python = root / "python/bin/python3.12"
    site = root / "python/lib/python3.12/site-packages"
    if not python.is_file() or not site.is_dir():
        raise FileNotFoundError("Staged CPython runtime/site-packages are required before PDF staging")
    if not (site / "pymupdf-1.28.2.dist-info").is_dir():
        raise FileNotFoundError("Locked PyMuPDF is absent from staged production runtime")
    with zipfile.ZipFile(wheel_path) as archive:
        license_bytes = archive.read(lock["license_file"])
    if hashlib.sha256(license_bytes).hexdigest() != lock["license_sha256"]:
        raise ValueError("PyMuPDF license text hash mismatch")
    license_path = root / "python/licenses/pymupdf/COPYING"
    if license_path.exists() and _sha256(license_path) != lock["license_sha256"]:
        raise ValueError(f"Existing PDF license digest differs: {license_path}")
    license_path.parent.mkdir(parents=True, exist_ok=True)
    license_path.write_bytes(license_bytes)
    proof = _pdf_smoke(python, site, root)
    engine_proof = _engine_smoke(python, site, root)
    if proof["version"] != lock["version"]:
        license_path.unlink(missing_ok=True)
        raise ValueError(f"Staged PyMuPDF version mismatch: {proof['version']}")
    wheel_sha = _sha256(wheel_path)
    native = []
    for relative in ("pymupdf/_mupdf.so", "pymupdf/_extra.so",
                     "pymupdf/libmupdf.so.28.2", "pymupdf/libmupdfcpp.so.28.2"):
        path = site / relative
        if not path.is_file():
            raise ValueError(f"Required PyMuPDF/MuPDF native component missing: {relative}")
        native.append({"path": "python/lib/python3.12/site-packages/" + relative,
                       "sha256": _sha256(path), "size": path.stat().st_size})
    proof["wheel_sha256"] = wheel_sha
    return {
        "name": "pymupdf", "distribution": "PyMuPDF", "version": lock["version"],
        "platform": lock["platform"], "wheel": lock["wheel"], "wheel_sha256": wheel_sha,
        "source": lock["url"], "license": lock["license"],
        "licenses": [{"path": "python/licenses/pymupdf/COPYING",
                      "sha256": lock["license_sha256"], "source": lock["license_file"]}],
        "native_components": native,
        "provenance": {"input_lock": "app/packaging/python/pdf.lock.json",
                       "production_lock": "uv.lock", "wheel_sha256": lock["sha256"]},
        "offline_proof": {"method": "isolated subprocess; proxies point to closed localhost port",
                          "version": proof["version"], "pages": proof["pages"],
                          "extracted_text": proof["text"], "module": proof["module"],
                          "engine_handler": engine_proof},
    }
