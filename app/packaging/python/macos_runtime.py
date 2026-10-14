"""Pinned CPython staging for the macOS arm64 app (phase 4): the Linux recipe, the Mac's inputs.

python-build-standalone for aarch64-apple-darwin, uv for Apple silicon (only to export the locked
requirements), the production wheels from uv.lock (binary only and hash-checked, downloaded by the
staged interpreter, so their tags are the Mac's), the exact uv.lock pip wheel, and the engine built
from the source, all as runtime.py stages them. Its helpers are reused; its own lock supplies them
the source date, engine license, license commit and dependency source, which this lock must equal.
In place of readelf's glibc floor, every Mach-O file is audited against the support floor
(macos_macho.audit). The runtime is staged once, into a new root.
"""
from __future__ import annotations

import json
import platform
import re
import tempfile
import tomllib
from pathlib import Path

from macos_macho import audit

import runtime as linux

LOCK_PATH = linux.REPO / "app/packaging/runtime-lock.macos_arm64.json"
NAMED_PIP = "macos-pinned-pip-runtime-exception"
SHARED = ("source_date_epoch", "engine_license", "python_license_commit", "dependency_source")
PDF = re.compile(r"(?im)^\s*(?:pymupdf|mupdf|fitz)(?:\s|[=<>!~\[])")


def lock() -> dict:
    spec = json.loads(LOCK_PATH.read_text())
    shared = json.loads(linux.LOCK_PATH.read_text())
    for key in SHARED:
        if spec[key] != shared[key]:
            raise ValueError(f"The macOS runtime lock's {key} differs from runtime-lock.json's")
    return spec


def _download(spec: dict, cache: Path) -> Path:
    artifact = linux._download(spec, cache)
    if artifact.stat().st_size != spec["size"]:
        raise ValueError(f"Artifact size mismatch: {spec['url']}")
    return artifact


def stage_macos_runtime(repo: Path, bundle_root: Path, cache_dir: Path) -> dict:
    """Stage standalone CPython and the hash-locked production wheels into bundle_root/python."""
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("The macOS runtime lane targets Apple silicon only")
    if Path(repo).resolve() != linux.REPO.resolve():
        raise ValueError("The macOS runtime lane stages its own repository's source")
    spec = lock()
    bundle_root = bundle_root.resolve()
    cache = cache_dir.resolve() / "python-runtime"
    cache.mkdir(parents=True, exist_ok=True)
    bundle_root.mkdir(parents=True, exist_ok=True)
    if (bundle_root / "python").exists():
        raise ValueError("The macOS runtime is staged once; stage a new bundle root")
    python_archive = _download(spec["python"], cache / "artifacts")
    uv_archive = _download(spec["uv"], cache / "artifacts")
    with tempfile.TemporaryDirectory(dir=cache, prefix="uv-") as temporary:
        linux._extract_tar(uv_archive, Path(temporary), "uv-aarch64-apple-darwin")
        uv = Path(temporary) / "uv-aarch64-apple-darwin/uv"
        export = linux._run([str(uv), "export", "--frozen", "--no-dev", "--no-default-groups",
                             "--no-emit-project", "--no-header", "--no-annotate"],
                            cache, linux.REPO)
    if PDF.search(export):
        raise ValueError("Production export must exclude the first-use PDF extra")
    requirements = cache / "production-requirements.txt"
    requirements.write_text(export)
    with tempfile.TemporaryDirectory(dir=bundle_root, prefix=".python-stage-") as temporary:
        work = Path(temporary)
        linux._extract_tar(python_archive, work, "python")
        python = work / "python/bin/python3.12"
        version = linux._run([str(python), "-I", "-B", "-c",
                              "import platform;print(platform.python_version())"], cache).strip()
        if version != spec["python"]["version"]:
            raise ValueError("CPython archive version differs from lock")
        # The engine's macOS process and file primitives are libSystem calls through ctypes.
        linux._run([str(python), "-I", "-B", "-c",
                    "import ctypes;system=ctypes.CDLL('/usr/lib/libSystem.B.dylib');"
                    "system.proc_pidinfo;system.renameatx_np;system.confstr"], cache)
        wheels = cache / "wheelhouse" / linux.sha256(requirements)
        wheels.mkdir(parents=True, exist_ok=True)
        linux._run([str(python), "-I", "-B", "-m", "pip", "download", "--disable-pip-version-check",
                    "--require-hashes", "--only-binary=:all:", "--dest", str(wheels),
                    "--index-url", "https://pypi.org/simple", "-r", str(requirements)], cache)
        dependencies = linux._wheel_inventory(
            wheels, tomllib.loads((linux.REPO / "uv.lock").read_text()))
        if any(item["name"] in {"pymupdf", "mupdf", "fitz"} for item in dependencies):
            raise ValueError("PDF wheel found in production wheelhouse")
        linux._run([str(python), "-I", "-B", "-m", "pip", "install", "--disable-pip-version-check",
                    "--no-index", "--no-deps", "--no-compile", "--require-hashes",
                    "--only-binary=:all:", "--find-links", str(wheels),
                    "--target", str(work / linux.SITE), "-r", str(requirements)], cache)
        pip = linux._stage_pip(work, cache, spec, named=NAMED_PIP)
        linux._run([str(python), "-I", "-B", "-c",
                    "import pip,importlib.metadata as m;"
                    f"assert pip.__version__ == m.version('pip') == {spec['pip']['version']!r}"],
                   cache)
        (work / "python").rename(bundle_root / "python")
    engine = linux.refresh_engine(bundle_root, cache_dir)
    linux._clean_runtime(bundle_root)
    macho = audit(bundle_root / "python", spec["minimum_macos"], "bin/python3.12")
    if macho["problems"]:
        raise ValueError("Mach-O audit failed: " + "; ".join(macho["problems"][:8]))
    result = {"schema": 1, "platform": spec["platform"], "python": spec["python"],
              "build_tool": spec["uv"], "pip": pip, "executable": "python/bin/python3.12",
              "site_packages": linux.SITE.as_posix(), "runtime_args": ["-I", "-B", "-m", "src"],
              "uv_lock_sha256": linux.sha256(linux.REPO / "uv.lock"),
              "requirements_sha256": linux.sha256(requirements),
              "dependencies": dependencies, "engine": engine, "macho": macho,
              "minimum_macos": spec["minimum_macos"], "license_blockers": []}
    result["licenses"] = linux._stage_licenses(bundle_root, cache, spec)
    result["python_license_files"] = linux._license_files(bundle_root)
    (bundle_root / "python/runtime-metadata.json").write_text(json.dumps(result, indent=2) + "\n")
    (bundle_root / "python/dependency-licenses.json").write_text(
        json.dumps(dependencies, indent=2) + "\n")
    return result
