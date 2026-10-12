"""Pinned CPython staging. Build-time stdlib only; no live-install inputs."""
from __future__ import annotations

import email
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[3]
LOCK_PATH = REPO / "app/packaging/runtime-lock.json"
SITE = Path("python/lib/python3.12/site-packages")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _download(spec: dict, cache: Path) -> Path:
    """Content-addressed cache, hash checked every use, atomic publication."""
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / spec["sha256"]
    if dest.exists():
        if sha256(dest) != spec["sha256"]:
            raise ValueError(f"Corrupt cached artifact: {dest}")
        return dest
    if not spec["url"].startswith("https://"):
        raise ValueError("Artifact URL must use HTTPS")
    fd, name = tempfile.mkstemp(dir=cache, prefix="download-")
    try:
        with os.fdopen(fd, "wb") as output:
            with urllib.request.urlopen(spec["url"], timeout=180) as response:
                if not response.url.startswith("https://"):
                    raise ValueError("Insecure artifact redirect")
                shutil.copyfileobj(response, output)
        temporary = Path(name)
        if sha256(temporary) != spec["sha256"]:
            raise ValueError(f"Artifact hash mismatch: {spec['url']}")
        temporary.replace(dest)
    finally:
        Path(name).unlink(missing_ok=True)
    return dest


def _safe_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"Unsafe archive path: {name!r}")
    return path


def _extract_tar(archive: Path, dest: Path, prefix: str) -> None:
    """Preflight all entries before writing, relative internal symlinks only."""
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        names: set[str] = set()
        links: set[PurePosixPath] = set()
        for member in members:
            path = _safe_path(member.name)
            if path.parts[0] != prefix or str(path) in names:
                raise ValueError(f"Unexpected/duplicate archive member: {member.name}")
            names.add(str(path))
            if member.issym():
                if PurePosixPath(member.linkname).is_absolute():
                    raise ValueError("Absolute archive symlink")
                target = (dest / str(path.parent) / member.linkname).resolve()
                if not target.is_relative_to((dest / prefix).resolve()):
                    raise ValueError("Escaping archive symlink")
                links.add(path)
            elif not (member.isfile() or member.isdir()):
                raise ValueError("Archive contains hardlink or special file")
        for member in members:
            if any(parent in links for parent in _safe_path(member.name).parents):
                raise ValueError("Archive entry descends through symlink")
        source.extractall(dest, members=members, filter="data")


def _env(cache: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin", "HOME": str(cache), "LANG": "C.UTF-8",
        "SOURCE_DATE_EPOCH": str(json.loads(LOCK_PATH.read_text())["source_date_epoch"]),
        "PYTHONDONTWRITEBYTECODE": "1", "PIP_CONFIG_FILE": os.devnull,
        "UV_CACHE_DIR": str(cache / "uv-cache"), "UV_PYTHON_DOWNLOADS": "never",
    }


def _run(args: list[str], cache: Path, cwd: Path | None = None) -> str:
    print("runtime:", " ".join(map(str, args)), flush=True)
    return subprocess.run(args, cwd=cwd, env=_env(cache), check=True,
                          stdout=subprocess.PIPE, text=True).stdout


def _wheel_inventory(wheels: Path, lock: dict) -> list[dict]:
    allowed = {w["hash"].removeprefix("sha256:"): (p, w)
               for p in lock["package"] for w in p.get("wheels", [])}
    inventory = []
    for wheel in sorted(wheels.glob("*.whl")):
        digest = sha256(wheel)
        if digest not in allowed:
            raise ValueError(f"Wheel absent from uv.lock: {wheel.name}")
        package, artifact = allowed[digest]
        with zipfile.ZipFile(wheel) as archive:
            for info in archive.infolist():
                _safe_path(info.filename)
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError("Wheel symlinks are not supported")
            name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
            metadata = email.message_from_bytes(archive.read(name))
            licenses = [{"path": n, "sha256": hashlib.sha256(archive.read(n)).hexdigest()}
                        for n in archive.namelist()
                        if not n.endswith("/") and re.search(
                            r"(?i)(license|copying|notice|copyright)", n)]
        inventory.append({"name": package["name"], "version": package["version"],
                          "wheel": wheel.name, "url": artifact["url"], "sha256": digest,
                          "license_expression": metadata.get("License-Expression"),
                          "license": metadata.get("License", "NOASSERTION"),
                          "license_classifiers": [v for v in metadata.get_all("Classifier", [])
                                                  if v.startswith("License ::")],
                          "license_files": licenses})
    return inventory


def refresh_engine(bundle_root: Path, cache_dir: Path) -> dict:
    """Rebuild only the noneditable engine after main or a D14 adapter changes."""
    bundle_root, cache = bundle_root.resolve(), cache_dir.resolve() / "python-runtime"
    cache.mkdir(parents=True, exist_ok=True)
    site = bundle_root / SITE
    lock = tomllib.loads((REPO / "uv.lock").read_text())
    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    python = bundle_root / "python/bin/python3.12"
    backend = next(p for p in lock["package"] if p["name"] == "setuptools")
    if backend["version"] != "84.0.0":
        raise ValueError("Review build backend pin before changing setuptools")
    wheel_spec = backend["wheels"][0]
    artifact = _download({"url": wheel_spec["url"],
                          "sha256": wheel_spec["hash"].removeprefix("sha256:")},
                         cache / "artifacts")
    with tempfile.TemporaryDirectory(dir=cache, prefix="engine-build-") as temporary:
        work = Path(temporary)
        backend_dir = work / "backend"
        with zipfile.ZipFile(artifact) as archive:
            for name in archive.namelist():
                _safe_path(name)
            archive.extractall(backend_dir)
        source = work / "source"
        source.mkdir()
        # Index allowlist, worktree bytes: includes reviewed changes before commit.
        tracked = subprocess.check_output(["git", "ls-files", "-z", "src"], cwd=REPO)
        # Reviewed newly added modules are not staged by parallel workers. Include
        # only .py files; never sweep untracked credentials, data or caches.
        filenames = set(tracked.decode().split("\0"))
        filenames.update(p.relative_to(REPO).as_posix() for p in (REPO / "src").rglob("*.py")
                         if "__pycache__" not in p.parts)
        source_manifest = []
        for filename in sorted(filenames):
            if not filename:
                continue
            original = REPO / filename
            if original.is_symlink() or not original.is_file():
                raise ValueError(f"Engine source must be regular and tracked: {filename}")
            target = source / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            source_manifest.append({"path": filename, "sha256": sha256(original)})
        shutil.copyfile(REPO / "pyproject.toml", source / "pyproject.toml")
        script = ("import sys;sys.path.insert(0,sys.argv[1]);import setuptools.build_meta;"
                  "print(setuptools.build_meta.build_wheel(sys.argv[2]))")
        _run([str(python), "-I", "-B", "-c", script,
              str(backend_dir), str(work / "dist")], cache, source)
        engine_wheel = next((work / "dist").glob("*.whl"))
        engine_hash = sha256(engine_wheel)
        shutil.rmtree(site / "src", ignore_errors=True)
        for old in site.glob("odin_desktop_engine-*.dist-info"):
            shutil.rmtree(old)
        # Purelib-only engine wheel: stdlib extraction avoids shipped installer.
        with zipfile.ZipFile(engine_wheel) as archive:
            for name in archive.namelist():
                _safe_path(name)
                if not (name.startswith("src/") or name.startswith("odin_desktop_engine-")):
                    raise ValueError(f"Unexpected engine wheel layout: {name}")
            archive.extractall(site)
        wheel_cache = cache / "engine-wheels"
        wheel_cache.mkdir(exist_ok=True)
        shutil.copyfile(engine_wheel, wheel_cache / f"{engine_hash}.whl")
    for path in site.glob("odin_desktop_engine-*.dist-info/direct_url.json"):
        path.unlink()
    for path in (site / "src").rglob("__pycache__"):
        shutil.rmtree(path)
    manifest = json.dumps(source_manifest, sort_keys=True, separators=(",", ":")).encode()
    result = {"name": project["name"], "version": project["version"],
              "wheel_sha256": engine_hash, "source_sha256": hashlib.sha256(manifest).hexdigest(),
              "source_files": source_manifest, "pyproject_sha256": sha256(REPO / "pyproject.toml"),
              "license": json.loads(LOCK_PATH.read_text())["engine_license"],
              "site_packages": SITE.as_posix(), "editable": False,
              "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO,
                                                  text=True).strip(),
              "source_note": "worktree bytes, allowlisted modules/assets; "
                             "git_head is context, not clean-tree assertion"}
    (bundle_root / "python/engine-source.json").write_text(json.dumps(result, indent=2) + "\n")
    metadata_path = bundle_root / "python/runtime-metadata.json"
    if metadata_path.exists():
        previous = json.loads(metadata_path.read_text())
        previous["engine"] = result
        metadata_path.write_text(json.dumps(previous, indent=2) + "\n")
    return result


def _stage_licenses(bundle_root: Path, cache: Path, spec: dict) -> list[dict]:
    destination = bundle_root / "python/licenses/python-build-standalone"
    destination.mkdir(parents=True, exist_ok=True)
    result = []
    for name, digest in spec["python_license_hashes"].items():
        url = ("https://raw.githubusercontent.com/astral-sh/python-build-standalone/"
               f"{spec['python_license_commit']}/{name}")
        artifact = _download({"url": url, "sha256": digest}, cache / "artifacts")
        target = destination / name
        shutil.copyfile(artifact, target)
        result.append({"path": target.relative_to(bundle_root).as_posix(),
                       "sha256": digest, "url": url})
    upstream = REPO / "maintenance/UPSTREAM-LICENSE"
    target = bundle_root / "python/licenses/UPSTREAM-LICENSE"
    shutil.copyfile(upstream, target)
    result.append({"path": target.relative_to(bundle_root).as_posix(),
                   "sha256": sha256(target), "source": "maintenance/UPSTREAM-LICENSE",
                   "license": "MIT"})
    return result


def _locked_pip(spec: dict) -> dict:
    """Named Linux exception: pip is an exact uv.lock wheel, not bootstrap pip."""
    pin = spec["pip"]
    lock = tomllib.loads((REPO / "uv.lock").read_text())
    packages = [p for p in lock["package"] if p["name"] == "pip"]
    if len(packages) != 1 or packages[0]["version"] != pin["version"]:
        raise ValueError("Pinned runtime pip differs from uv.lock")
    if (pin.get("named_change") != "linux-pinned-pip-runtime-exception"
            or not pin.get("license") or not pin.get("provenance")):
        raise ValueError("Runtime pip requires named-change, license and provenance")
    matches = [w for w in packages[0].get("wheels", [])
               if w["url"] == pin["url"]
               and w["hash"] == "sha256:" + pin["sha256"]
               and w["size"] == pin["size"]]
    if len(matches) != 1 or not pin["url"].endswith(
            f"/pip-{pin['version']}-py3-none-any.whl"):
        raise ValueError("Pinned runtime pip artifact differs from uv.lock")
    return pin


def _stage_pip(bundle_root: Path, cache: Path, spec: dict) -> dict:
    """Replace bootstrap payload with an exact wheel in an unpublished stage.

    No entrypoint or generated installer metadata is added. Validate the entire
    wheel before removing upstream pip, including a shadowing --target version.
    """
    pin = _locked_pip(spec)
    artifact = _download(pin, cache / "artifacts")
    if artifact.stat().st_size != pin["size"]:
        raise ValueError("Pinned runtime pip artifact size mismatch")
    dist_info = f"pip-{pin['version']}.dist-info"
    site = bundle_root / SITE
    with zipfile.ZipFile(artifact) as archive:
        names = set()
        payload = []
        for info in archive.infolist():
            path = _safe_path(info.filename)
            if (info.filename in names or path.parts[0] not in {"pip", dist_info}
                    or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError(f"Unexpected pinned pip wheel member: {info.filename}")
            names.add(info.filename)
            if not info.is_dir():
                payload.append({"path": (SITE / info.filename).as_posix(),
                                "sha256": hashlib.sha256(archive.read(info)).hexdigest()})
        metadata = email.message_from_bytes(archive.read(f"{dist_info}/METADATA"))
        wheel = email.message_from_bytes(archive.read(f"{dist_info}/WHEEL"))
        if (metadata.get("Name") != "pip" or metadata.get("Version") != pin["version"]
                or metadata.get("License-Expression") != pin["license"]
                or wheel.get_all("Tag") != ["py3-none-any"]
                or wheel.get("Root-Is-Purelib") != "true"):
            raise ValueError("Pinned runtime pip wheel metadata mismatch")
        with tempfile.TemporaryDirectory(dir=cache, prefix="pinned-pip-") as temporary:
            staged = Path(temporary)
            archive.extractall(staged)
            site.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(site / "pip", ignore_errors=True)
            for old in site.glob("pip-*.dist-info"):
                shutil.rmtree(old)
            for name in ("pip", dist_info):
                shutil.move(str(staged / name), str(site / name))
    return {"pin": pin, "payload": sorted(payload, key=lambda p: p["path"]),
            "license_files": [row for row in sorted(payload, key=lambda p: p["path"])
                              if re.search(r"(?i)(license|copying|notice)", row["path"])],
            "install": "exact wheel extraction; upstream bootstrap pip replaced",
            "invocation": "python/bin/python3.12 -I -B -m pip"}


def _verify_staged_pip(bundle_root: Path, previous: dict, spec: dict) -> None:
    """An old or modified cache cannot silently become a mixed pip stage."""
    pin = _locked_pip(spec)
    record = previous.get("pip", {})
    if record.get("pin") != pin or not record.get("payload"):
        raise ValueError("Pinned pip lock changed/missing; stage a new bundle root")
    expected = {row["path"]: row["sha256"] for row in record["payload"]}
    site = bundle_root / SITE
    roots = [site / "pip", *site.glob("pip-*.dist-info")]
    if any(root.is_symlink() for root in roots):
        raise ValueError("Pinned pip payload symlink; stage a new bundle root")
    actual = {p.relative_to(bundle_root).as_posix(): sha256(p)
              for root in roots for p in root.rglob("*") if p.is_file()}
    if actual != expected or any(p.is_symlink() for root in roots for p in root.rglob("*")):
        raise ValueError("Pinned pip payload changed; stage a new bundle root")


def _clean_runtime(bundle_root: Path) -> None:
    """Remove build-only entry points/ensurepip and caches; retain pinned pip."""
    site = bundle_root / SITE
    for path in (bundle_root / "python/bin").iterdir():
        if path.name not in {"python", "python3", "python3.12"}:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    shutil.rmtree(site / "bin", ignore_errors=True)
    shutil.rmtree(bundle_root / "python/lib/python3.12/ensurepip", ignore_errors=True)
    for path in (bundle_root / "python").rglob("__pycache__"):
        shutil.rmtree(path)
    for path in site.glob("*/direct_url.json"):
        path.unlink()


def _license_files(bundle_root: Path) -> list[dict]:
    return [{"path": p.relative_to(bundle_root).as_posix(), "sha256": sha256(p)}
            for p in sorted((bundle_root / "python").rglob("*"))
            if p.is_file() and p.name not in {"dependency-licenses.json"}
            and re.search(r"(?i)(license|copying|notice)", p.name)]


def measure_elf(root: Path) -> dict:
    """Required GLIBC versions, not host version or distro compatibility claims."""
    records = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        output = subprocess.check_output(["/usr/bin/readelf", "--version-info", str(path)],
                                         text=True, stderr=subprocess.DEVNULL)
        needs = (output.split("Version needs section", 1)[-1]
                 if "Version needs section" in output else "")
        versions = sorted(set(re.findall(r"\bGLIBC_(\d+\.\d+(?:\.\d+)?)\b", needs)),
                          key=lambda v: tuple(map(int, v.split("."))))
        records.append({"path": path.relative_to(root).as_posix(), "glibc_imports": versions})
    all_versions = [v for record in records for v in record["glibc_imports"]]
    return {"tool": "readelf --version-info (Version needs section)", "elf_files": records,
            "glibc_required": max(all_versions, key=lambda v: tuple(map(int, v.split("."))))
            if all_versions else None,
            "qualification": "static imported-symbol floor, not oldest-distro execution proof"}


def stage_runtime(bundle_root: Path, cache_dir: Path) -> dict:
    """Stage standalone CPython and hash-locked production wheels into root/python."""
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("Runtime lane targets Linux x86_64 only")
    bundle_root = bundle_root.resolve()
    cache = cache_dir.resolve() / "python-runtime"
    cache.mkdir(parents=True, exist_ok=True)
    bundle_root.mkdir(parents=True, exist_ok=True)
    spec = json.loads(LOCK_PATH.read_text())
    if (bundle_root / "python").exists():
        metadata_path = bundle_root / "python/runtime-metadata.json"
        previous = json.loads(metadata_path.read_text())
        _verify_staged_pip(bundle_root, previous, spec)
        if (previous["uv_lock_sha256"] != sha256(REPO / "uv.lock")
                or previous["python"] != spec["python"]):
            raise ValueError("Dependency/runtime lock changed; stage a new bundle root")
        previous["engine"] = refresh_engine(bundle_root, cache_dir)
        _clean_runtime(bundle_root)
        previous["licenses"] = _stage_licenses(bundle_root, cache, spec)
        previous["elf"] = measure_elf(bundle_root / "python")
        previous["python_license_files"] = _license_files(bundle_root)
        metadata_path.write_text(json.dumps(previous, indent=2) + "\n")
        return previous
    python_archive = _download(spec["python"], cache / "artifacts")
    uv_archive = _download(spec["uv"], cache / "artifacts")
    with tempfile.TemporaryDirectory(dir=cache, prefix="uv-") as temporary:
        _extract_tar(uv_archive, Path(temporary), "uv-x86_64-unknown-linux-gnu")
        uv = Path(temporary) / "uv-x86_64-unknown-linux-gnu/uv"
        requirements = cache / "production-requirements.txt"
        export = _run([str(uv), "export", "--frozen", "--no-dev", "--no-default-groups",
                       "--no-emit-project", "--no-header", "--no-annotate"], cache, REPO)
        if re.search(r"(?im)^\s*(?:pymupdf|mupdf|fitz)(?:\s|[=<>!~\[])", export):
            raise ValueError("Production export must exclude the first-use PDF extra")
        requirements.write_text(export)
    with tempfile.TemporaryDirectory(dir=bundle_root, prefix=".python-stage-") as temporary:
        work = Path(temporary)
        _extract_tar(python_archive, work, "python")
        python = work / "python/bin/python3.12"
        version = _run([str(python), "-I", "-B", "-c",
                        "import platform;print(platform.python_version())"], cache).strip()
        if version != spec["python"]["version"]:
            raise ValueError("CPython archive version differs from lock")
        _run([str(python), "-I", "-B", "-c",
              "import os,signal;assert hasattr(os,'pidfd_open');"
              "assert hasattr(signal,'pidfd_send_signal');"
              "fd=os.pidfd_open(os.getpid());os.close(fd)"], cache)
        wheels = cache / "wheelhouse" / sha256(requirements)
        wheels.mkdir(parents=True, exist_ok=True)
        _run([str(python), "-I", "-B", "-m", "pip", "download", "--disable-pip-version-check",
              "--require-hashes", "--only-binary=:all:", "--dest", str(wheels),
              "--index-url", "https://pypi.org/simple", "-r", str(requirements)], cache)
        dependencies = _wheel_inventory(wheels, tomllib.loads((REPO / "uv.lock").read_text()))
        if any(item["name"] in {"pymupdf", "mupdf", "fitz"} for item in dependencies):
            raise ValueError("PDF wheel found in production wheelhouse")
        _run([str(python), "-I", "-B", "-m", "pip", "install", "--disable-pip-version-check",
              "--no-index", "--no-deps", "--no-compile", "--require-hashes", "--only-binary=:all:",
              "--find-links", str(wheels), "--target", str(work / SITE),
              "-r", str(requirements)], cache)
        pip = _stage_pip(work, cache, spec)
        _run([str(python), "-I", "-B", "-c",
              "import pip,importlib.metadata as m;"
              f"assert pip.__version__ == m.version('pip') == {spec['pip']['version']!r}"], cache)
        (work / "python").rename(bundle_root / "python")
    engine = refresh_engine(bundle_root, cache_dir)
    _clean_runtime(bundle_root)
    libc = measure_elf(bundle_root / "python")
    result = {"schema": 1, "python": spec["python"], "build_tool": spec["uv"], "pip": pip,
              "executable": "python/bin/python3.12", "site_packages": SITE.as_posix(),
              "runtime_args": ["-I", "-B", "-m", "src"],
              "uv_lock_sha256": sha256(REPO / "uv.lock"),
              "requirements_sha256": sha256(requirements),
              "dependencies": dependencies, "engine": engine, "elf": libc,
              "license_blockers": [spec["engine_license_note"]] if spec.get("engine_license_note") else []}
    result["licenses"] = _stage_licenses(bundle_root, cache, spec)
    result["python_license_files"] = _license_files(bundle_root)
    (bundle_root / "python/runtime-metadata.json").write_text(json.dumps(result, indent=2) + "\n")
    (bundle_root / "python/dependency-licenses.json").write_text(
        json.dumps(dependencies, indent=2) + "\n")
    return result
