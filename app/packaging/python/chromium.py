"""Build-time-only pinned Chromium staging. Runtime never invokes a downloader."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

LOCK_PATH = Path(__file__).with_name("chromium.lock.json")
REPOSITORY = Path(__file__).resolve().parents[3]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cached(spec: dict, cache: Path, filename: str) -> Path:
    """Verify cached bytes on every use; never silently replace corrupt inputs."""
    cache.mkdir(parents=True, exist_ok=True)
    artifact = cache / filename
    if artifact.exists():
        if _sha256(artifact) != spec["sha256"]:
            raise ValueError(f"Chromium input hash mismatch: {artifact}")
        return artifact
    fd, temporary = tempfile.mkstemp(prefix=filename + ".", suffix=".download", dir=cache)
    try:
        with os.fdopen(fd, "wb") as output:
            with urllib.request.urlopen(spec["url"], timeout=120) as response:
                shutil.copyfileobj(response, output)
        if _sha256(Path(temporary)) != spec["sha256"]:
            raise ValueError(f"Chromium downloaded input hash mismatch: {spec['url']}")
        os.replace(temporary, artifact)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return artifact


def _validate_playwright(lock: dict, uv_lock: Path, wheel: Path) -> None:
    packages = tomllib.loads(uv_lock.read_text())["package"]
    package = next(item for item in packages if item["name"] == "playwright")
    pin = lock["playwright"]
    if package["version"] != pin["version"] or not any(
        item["url"] == pin["url"] and item["hash"] == "sha256:" + pin["sha256"]
        for item in package["wheels"]
    ):
        raise ValueError("Chromium lock does not match uv.lock's pinned Playwright wheel")
    with zipfile.ZipFile(wheel) as archive:
        browsers = json.loads(archive.read("playwright/driver/package/browsers.json"))
    browser = next(
        item for item in browsers["browsers"] if item["name"] == lock["chromium"]["name"]
    )
    if (browser["revision"], browser["browserVersion"]) != (
        lock["chromium"]["revision"], lock["chromium"]["version"]
    ):
        raise ValueError("Chromium version/revision does not match pinned Playwright browsers.json")


def _extract(archive_path: Path, destination: Path, archive_root: str) -> None:
    """Extract ordinary files only, normalizing modes and rejecting unsafe entries."""
    with zipfile.ZipFile(archive_path) as archive:
        seen = set()
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (path.is_absolute() or ".." in path.parts or "\\" in member.filename
                    or not path.parts or path.parts[0] != archive_root
                    or member.filename in seen or stat.S_ISLNK(mode)
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError(f"Unsafe Chromium archive member: {member.filename}")
            seen.add(member.filename)
            target = destination.joinpath(*path.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                target.chmod(0o755)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if mode & 0o111 else 0o644)


def stage_chromium(bundle_root: Path, cache_dir: Path) -> dict:
    """Stage D14 under ``bundle_root/browser/chromium``; paths in metadata are relative.

    The supplied root is resources/runtime, not resources itself. Downloads are
    allowed only here during the build. A warmed cache works without networking.
    Repeated staging verifies the complete existing tree rather than overwriting it.
    """
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise ValueError("Chromium lock currently supports Linux x86_64 only")
    lock = json.loads(LOCK_PATH.read_text())
    pin = lock["chromium"]
    cache = Path(cache_dir) / "chromium"
    wheel = _cached(lock["playwright"], cache, f"playwright-{lock['playwright']['version']}.whl")
    _validate_playwright(lock, REPOSITORY / "uv.lock", wheel)
    archive = _cached(pin, cache, f"chrome-headless-shell-linux64-{pin['version']}.zip")
    destination = Path(bundle_root) / "browser" / "chromium"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".chromium-", dir=destination.parent))
    try:
        temporary.chmod(0o755)
        _extract(archive, temporary, pin["archive_root"])
        executable = temporary / pin["executable"]
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("Pinned Chromium archive has no executable headless shell")
        if _sha256(temporary / pin["license_file"]) != pin["license_sha256"]:
            raise ValueError("Pinned Chromium license content mismatch")
        if destination.exists():
            expected = sorted(path.relative_to(temporary) for path in temporary.rglob("*"))
            actual = sorted(path.relative_to(destination) for path in destination.rglob("*"))
            if actual != expected or destination.is_symlink():
                raise ValueError("Existing Chromium resource closure mismatch")
            if destination.stat().st_mode & 0o7777 != 0o755:
                raise ValueError("Existing Chromium resource root mode mismatch")
            for relative in expected:
                staged = temporary / relative
                existing = destination / relative
                if (existing.is_symlink() or existing.is_dir() != staged.is_dir()
                        or existing.stat().st_mode & 0o7777 != staged.stat().st_mode & 0o7777
                        or staged.is_file() and _sha256(existing) != _sha256(staged)):
                    raise ValueError(f"Existing Chromium resource mismatch: {relative}")
        else:
            os.replace(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    prefix = "browser/chromium/"
    return {
        "name": "chromium", "distribution": pin["name"], "platform": lock["platform"],
        "version": pin["version"], "revision": pin["revision"],
        "playwright_version": lock["playwright"]["version"],
        "source": pin["url"], "sha256": pin["sha256"],
        "executable": prefix + pin["executable"],
        "executable_sha256": _sha256(destination / pin["executable"]),
        "license": pin["license"], "licenses": [prefix + pin["license_file"]],
        "license_sha256": pin["license_sha256"],
        "provenance": {
            "playwright_wheel": lock["playwright"],
            "input_lock": "app/packaging/python/chromium.lock.json",
        },
        "sandbox_required": True,
        "files": sum(path.is_file() for path in destination.rglob("*")),
        "bytes": sum(path.stat().st_size for path in destination.rglob("*") if path.is_file()),
    }
