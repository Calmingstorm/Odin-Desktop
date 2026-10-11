"""Pinned app-local MSVC release DLLs, extracted as data, never installed.

The caller owns an unpublished private CPython stage. CPython supplies the two
vcruntime140 DLLs; this helper adds only the missing ONNX C++ DLLs beside python.exe.
It neither inspects PATH/System32 nor executes the VSIX or any installer. Static
checks work on any build host; native Windows load qualification remains separate.
The return value must enter release provenance, including the license blocker.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

from windows_archive import extract_archive, validate_windows_path
from windows_closure import StageError, validate_pin
from windows_dll import read_pe_imports

LOCK = Path(__file__).resolve().parents[1] / "vc-runtime-lock.win_amd64.json"
PACKAGE = "Microsoft.VC.14.44.17.14.CRT.Redist.X64.base"
REQUIRED = {"msvcp140.dll", "msvcp140_1.dll"}
RELEASE_ROOT = "Contents/VC/Redist/MSVC/14.44.35112/x64/Microsoft.VC143.CRT"


def _ordinary(path: Path, *, directory=False):
    try:
        info = path.lstat()
    except OSError as exc:
        raise StageError("vc_runtime_path", PACKAGE, str(path)) from exc
    if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise StageError("vc_runtime_path", PACKAGE, str(path))


def _load_pin(lock_path=None):
    pin = json.loads(Path(lock_path or LOCK).read_text(encoding="utf-8"))
    validate_pin(pin, PACKAGE)
    if (pin.get("schema") != 1 or pin.get("platform") != "win_amd64"
            or pin.get("name") != PACKAGE or pin.get("version") != "14.44.35211"
            or pin.get("release_root") != RELEASE_ROOT
            or not pin.get("license_documents") or not pin.get("redistribution_conditions")
            or pin.get("license_prerequisite_verified") is not False
            or not pin.get("license_blockers")):
        raise StageError("vc_runtime_pin", PACKAGE)
    files = pin.get("files", [])
    if len(files) != 2 or {item.get("filename") for item in files} != REQUIRED:
        raise StageError("vc_runtime_files", PACKAGE)
    for item in files:
        validate_windows_path(item["filename"], package=PACKAGE)
        validate_pin({**pin, **item}, PACKAGE)
    return pin


def stage_vc_runtime(runtime_root, cache_dir, *, lock_path=None) -> dict:
    """Add exactly two verified AMD64 DLLs to a private python.exe directory.

    Refuse all existing target names, including case aliases and reparse points.
    Validation of all archive members, inner pins and PE machines precedes writes.
    On a copy failure remove only files created here; never touch CPython's DLLs.
    """
    # Deferred import reuses the runtime's verified downloader without a module
    # cycle when windows_runtime imports this helper to assemble its private stage.
    from windows_runtime import verified_download

    pin = _load_pin(lock_path)
    root = Path(os.path.abspath(runtime_root))
    for ancestor in reversed((root, *root.parents)):
        _ordinary(ancestor, directory=True)
    _ordinary(root / "python.exe")
    existing = {path.name.casefold() for path in root.iterdir()}
    if existing & REQUIRED:
        raise StageError("install_collision", PACKAGE, detail=",".join(sorted(existing & REQUIRED)))
    cache = Path(os.path.abspath(cache_dir))
    for ancestor in reversed((cache, *cache.parents)):
        if ancestor.exists() or ancestor.is_symlink():
            _ordinary(ancestor, directory=True)
    artifact = verified_download(pin, cache, PACKAGE)
    created = []
    with tempfile.TemporaryDirectory(prefix=".vc-runtime-", dir=root.parent) as temporary:
        unpacked = Path(temporary) / "unpacked"
        extract_archive(artifact, unpacked, package=PACKAGE)
        try:
            manifest = json.loads((unpacked / "manifest.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise StageError("vc_runtime_manifest", PACKAGE) from exc
        if manifest.get("id") != PACKAGE or manifest.get("version") != pin["version"]:
            raise StageError("vc_runtime_manifest", PACKAGE)
        selected = []
        supplier_files = {item["fileName"]: item["sha256"].lower()
                          for item in manifest.get("files", [])}
        for item in pin["files"]:
            relative = RELEASE_ROOT + "/" + item["filename"]
            source = unpacked / relative
            _ordinary(source)
            if source.stat().st_size != item["size"]:
                raise StageError("artifact_size", PACKAGE, relative)
            with source.open("rb") as stream:
                sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
            if sha256 != item["sha256"] or supplier_files.get("/" + relative) != sha256:
                raise StageError("artifact_hash", PACKAGE, relative)
            pe = read_pe_imports(source, expected_machine="AMD64", package=PACKAGE)
            selected.append((source, {**item, **pe, "source_path": relative,
                                     "destination": item["filename"]}))
        try:
            for source, item in selected:
                target = root / item["filename"]
                # Exclusive create, no replacing a previous stage's DLL.
                with target.open("xb") as output:
                    created.append(target)
                    with source.open("rb") as stream:
                        shutil.copyfileobj(stream, output)
        except Exception:
            for target in created:
                target.unlink(missing_ok=True)
            raise
    return {**pin, "files": [item for _, item in selected],
            "deployment": "app-local beside python.exe",
            "installer_executed": False, "host_dll_copies": False,
            "native_qualification": "pending Windows host load checks"}
