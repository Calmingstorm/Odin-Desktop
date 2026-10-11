"""Locked client-only Windows tool payloads. No supplier installer is executed."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

from chromium import _cached, _sha256
from windows_archive import extract_archive
from windows_dll import audit_dll_dependencies

LOCK_PATH = Path(__file__).resolve().parent.parent / "tools-lock.win_amd64.json"


def _validate_lock(lock: dict) -> None:
    if lock.get("schema") != 1 or lock.get("platform") != "win_amd64":
        raise ValueError("Unsupported Windows tools lock")
    allowed = {
        "openssh": {"ssh.exe", "ssh-keygen.exe", "libcrypto.dll", "LICENSE.txt", "NOTICE.txt"},
        "curl": {"bin/curl.exe", "bin/curl-ca-bundle.crt", "COPYING.txt", "BUILD-MANIFEST.txt",
                 "BUILD-HASHES.txt", "README.txt"},
    }
    for name in ("openssh", "curl"):
        spec = lock[name]
        for field in ("url", "sha256", "size", "license", "provenance", "archive_root", "files",
                      "executables", "closure_sha256"):
            if not spec.get(field):
                raise ValueError(f"Missing {name} tool pin {field}")
        if not spec["url"].startswith("https://") or len(spec["sha256"]) != 64:
            raise ValueError(f"Invalid {name} tool artifact pin")
        paths = spec["files"]
        if len(paths) != len(set(path.casefold() for path in paths)):
            raise ValueError(f"Duplicate {name} tool destination")
        for path in paths:
            if path not in allowed[name] and not (name == "curl" and path.startswith("dep/")
                                                  and Path(path).name in {
                                                      "LICENSE.txt", "LICENSE.md",
                                                      "LICENSE.url", "COPYING.txt"}
                                                  and ".." not in Path(path).parts):
                raise ValueError(f"Unexpected {name} client payload: {path}")
    if set(lock["openssh"]["files"]) != allowed["openssh"]:
        raise ValueError("Incomplete OpenSSH client closure")
    if not allowed["curl"].issubset(lock["curl"]["files"]):
        raise ValueError("Incomplete curl client closure")
    if (not lock["openssh"].get("upstream_support_status")
            or not lock["openssh"].get("support_decision")):
        raise ValueError("OpenSSH support status/decision missing")
    if not lock["curl"].get("tls_backend") or not lock["curl"].get("trust_policy"):
        raise ValueError("curl TLS qualification policy missing")


def stage_tools(resources_root: Path, cache_dir: Path) -> dict:
    """Publish resources/tools transactionally, never merge a partial/old stage."""
    if sys.platform != "win32" or platform.machine() not in ("AMD64", "x86_64"):
        raise ValueError("Windows tools require Windows AMD64")
    lock = json.loads(LOCK_PATH.read_text())
    _validate_lock(lock)
    root = Path(resources_root)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "tools"
    if destination.exists() or destination.is_symlink():
        raise ValueError("Windows tools destination must be absent")
    temporary = Path(tempfile.mkdtemp(prefix=".tools-", dir=root))
    inputs = []
    try:
        for name in ("openssh", "curl"):
            spec = lock[name]
            archive = _cached(spec, Path(cache_dir) / "tools",
                              f"{name}-{spec['version']}-win_amd64.zip")
            extraction = temporary / (".extract-" + name)
            extract_archive(archive, extraction, package=name, expected_root=spec["archive_root"])
            lane = temporary / name
            lane.mkdir()
            records = []
            for relative in sorted(spec["files"]):
                source = extraction / spec["archive_root"] / relative
                records.append({"path": relative, "size": source.stat().st_size,
                                "sha256": _sha256(source)})
                target = lane / (relative[4:] if relative.startswith("bin/") else relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            content = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
            actual = hashlib.sha256(content).hexdigest()
            if actual != spec["closure_sha256"]:
                raise ValueError(f"Windows {name} client closure pin mismatch")
            shutil.rmtree(extraction)
            audit = audit_dll_dependencies(lane, roots=spec["executables"], package=name)
            inputs.append({"name": name, **spec, "files": records, "dll_audit": audit})
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"name": "tools", "platform": "win_amd64", "inputs": inputs,
            "input_lock": "app/packaging/tools-lock.win_amd64.json",
            "input_lock_sha256": _sha256(LOCK_PATH), "destination": "tools"}
