"""Transactional Windows runtime assembly using preselected locked wheel bytes.

No installer/resolver runs during assembly. Build-only setuptools is isolated in
a temporary directory, and never enters the shipped Python import path.
"""
from __future__ import annotations

import base64
import csv
import email
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import parse_tag
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version
from windows_archive import extract_archive, preflight_archive, validate_windows_path
from windows_closure import (
    TAGS,
    StageError,
    exact_artifacts,
    marker_matches,
    production_closure,
    select_wheel,
    validate_pin,
)
from windows_dll import DLLAuditError, audit_dll_dependencies, read_pe_imports
from windows_vc_runtime import stage_vc_runtime

REPO = Path(__file__).resolve().parents[3]
SITE = Path("python/Lib/site-packages")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verified_download(pin: dict, cache: Path, package: str = "") -> Path:
    validate_pin(pin, package)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / pin["sha256"]

    def verify(path):
        if (path.is_symlink() or not path.is_file()
                or getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
            raise StageError("artifact_type", package, str(path))
        if path.stat().st_size != pin["size"]:
            raise StageError("artifact_size", package)
        if digest(path) != pin["sha256"]:
            raise StageError("artifact_hash", package)

    if target.exists() or target.is_symlink():
        verify(target)
        return target
    fd, filename = tempfile.mkstemp(dir=cache, prefix=".download-")
    temporary = Path(filename)
    try:
        with os.fdopen(fd, "wb") as output:
            with urllib.request.urlopen(pin["url"], timeout=180) as response:
                if not response.url.startswith("https://"):
                    raise StageError("artifact_redirect", package)
                remaining = pin["size"]
                while chunk := response.read(min(1024 * 1024, remaining + 1)):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise StageError("artifact_size", package)
                    output.write(chunk)
        verify(temporary)
        os.replace(temporary, target)
    except StageError:
        raise
    except Exception as exc:
        raise StageError("artifact_download", package) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return target


def playwright_tag_exception(archive: zipfile.ZipFile, pin: dict,
                             filename_tags: set, tags: set) -> dict | None:
    """One reviewed supplier artifact only; content is checked before admission."""
    if pin["name"] != "playwright":
        return None
    lock = json.loads(Path(__file__).with_name("chromium.lock.win_amd64.json").read_text())
    supplier = lock["playwright"]
    exception = supplier["wheel_tag_exception"]
    if (pin["version"] != supplier["version"]
            or any(pin[key] != exception[key] for key in ("filename", "sha256", "size"))
            or any(pin[key] != supplier[key] for key in ("sha256", "size"))
            or filename_tags != parse_tag(exception["filename_tag"])
            or tags != parse_tag(exception["wheel_tag"])):
        return None
    driver = supplier["driver"]
    try:
        names = archive.namelist()
        required = {driver["path"], "playwright/driver/package/cli.js",
                    "playwright/driver/package/browsers.json"}
        if not required <= set(names):
            return None
        # Supplier .sh install helpers are inert data, not a foreign driver.
        # Refuse other native payloads, even if disguised with another suffix.
        for path in names:
            if not path.startswith("playwright/driver/") or path.endswith("/"):
                continue
            with archive.open(path) as stream:
                magic = stream.read(4)
            if path != driver["path"] and (
                    Path(path).name.casefold() in {"node", "node.exe"}
                    or Path(path).suffix.casefold() in {".exe", ".dll", ".pyd", ".so", ".dylib"}
                    or magic[:2] == b"MZ" or magic == b"\x7fELF"
                    or magic in {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
                                 b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
                                 b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}):
                return None
        node = archive.read(driver["path"])
        browsers = archive.read("playwright/driver/package/browsers.json")
        if (len(node) != driver["size"]
                or hashlib.sha256(node).hexdigest() != driver["sha256"]
                or hashlib.sha256(browsers).hexdigest() != supplier["browsers_json_sha256"]):
            return None
        with tempfile.TemporaryDirectory(prefix="playwright-driver-check-") as temporary:
            executable = Path(temporary) / "node.exe"
            executable.write_bytes(node)
            pe = read_pe_imports(executable, expected_machine="AMD64", package="playwright")
        return {**exception, "driver": driver, "driver_machine": pe["machine"],
                "foreign_driver_absent": True}
    except (KeyError, OSError, zipfile.BadZipFile, DLLAuditError):
        return None


def inspect_wheel(artifact: Path, pin: dict, closure: list[dict], *,
                  engine=False, build_backend=False) -> dict:
    """Check filename, tags, METADATA, WHEEL, RECORD, licensing and selected edges."""
    package = pin["name"]
    if build_backend:
        lock = tomllib.loads((REPO / "uv.lock").read_text())
        backend = next(p for p in lock["package"] if p["name"] == "setuptools")
        expected = select_wheel(backend)
        if any(pin.get(key) != expected[key]
               for key in ("name", "version", "filename", "sha256", "size")):
            raise StageError("backend_pin", package, pin.get("filename"))
    preflight_archive(artifact, package=package)
    filename = pin["filename"]
    try:
        name, version, _, filename_tags = parse_wheel_filename(filename)
    except Exception as exc:
        raise StageError("wheel_name_invalid", package, filename) from exc
    if name != canonicalize_name(package) or version != Version(pin["version"]):
        raise StageError("wheel_identity_mismatch", package, filename)
    if not filename_tags.intersection(TAGS):
        raise StageError("wheel_platform_tag", package, filename)
    if artifact.stat().st_size != pin["size"] or digest(artifact) != pin["sha256"]:
        raise StageError("wheel_pin_mismatch", package, filename)
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
        # Only the installed distribution's top-level metadata owns this wheel.
        # Vendored dist-info (e.g. setuptools/_vendor) is RECORD-covered data.
        metadata_paths = [n for n in names if n.endswith(".dist-info/METADATA")
                          and len(n.split("/")) == 2]
        if len(metadata_paths) != 1:
            raise StageError("wheel_metadata", package, filename)
        dist = metadata_paths[0].rsplit("/", 1)[0]
        dist_identity = dist.removesuffix(".dist-info").rsplit("-", 1)
        if (len(dist_identity) != 2 or canonicalize_name(dist_identity[0]) != name
                or dist_identity[1] != pin["version"]):
            raise StageError("wheel_metadata", package, dist)
        metadata = email.message_from_bytes(archive.read(metadata_paths[0]))
        if (canonicalize_name(metadata.get("Name", "")) != name
                or metadata.get("Version") != pin["version"]):
            raise StageError("wheel_metadata", package, filename)
        if metadata.get("Requires-Python"):
            try:
                supported = Version("3.12.15") in SpecifierSet(metadata["Requires-Python"])
            except Exception as exc:
                raise StageError("wheel_metadata", package, filename) from exc
            if not supported:
                raise StageError("python_abi", package, filename)
        try:
            wheel = email.message_from_bytes(archive.read(dist + "/WHEEL"))
            record_bytes = archive.read(dist + "/RECORD")
        except KeyError as exc:
            raise StageError("wheel_metadata", package, filename) from exc
        tags = set()
        try:
            for value in wheel.get_all("Tag", []):
                tags.update(parse_tag(value))
        except Exception as exc:
            raise StageError("wheel_tag_mismatch", package, filename) from exc
        tag_exception = None
        if tags != filename_tags:
            tag_exception = playwright_tag_exception(archive, pin, filename_tags, tags)
        if (tags != filename_tags and tag_exception is None
                or wheel.get("Wheel-Version") != "1.0"):
            raise StageError("wheel_tag_mismatch", package, filename)
        record = {}
        try:
            rows = list(csv.reader(io.StringIO(record_bytes.decode("utf-8"))))
        except (UnicodeError, csv.Error) as exc:
            raise StageError("wheel_record", package, filename) from exc
        for row in rows:
            if len(row) != 3 or row[0] in record:
                raise StageError("wheel_record", package, filename)
            record[row[0]] = row[1:]
        files = {n for n in names if not n.endswith("/")}
        for path in files:
            # The exact locked backend stays in build scratch, never the runtime.
            # Its standard .pth is inert: -I plus sys.path insertion does not
            # process .pth files. It remains covered by outer RECORD validation.
            if build_backend and path == "distutils-precedence.pth":
                continue
            if (path.endswith((".pth", "/direct_url.json"))
                    or path.split("/", 1)[0] in {"sitecustomize.py", "usercustomize.py"}):
                raise StageError("python_path_injection", package, path)
        if set(record) != files:
            raise StageError("wheel_record", package, filename)
        for path, (checksum, size) in record.items():
            data = archive.read(path)
            if path == dist + "/RECORD":
                if checksum or size:
                    raise StageError("wheel_record", package, path)
                continue
            encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            if checksum != "sha256=" + encoded or size != str(len(data)):
                raise StageError("wheel_record", package, path)
        notices = [{"path": n, "sha256": hashlib.sha256(archive.read(n)).hexdigest()}
                   for n in sorted(files)
                   if re.search(r"(?i)(license|copying|notice|copyright)", n)]
        license_text = metadata.get("License-Expression") or metadata.get("License")
        classifiers = [v for v in metadata.get_all("Classifier", []) if v.startswith("License ::")]
        if not engine and not (notices or classifiers
                               or (license_text and license_text != "UNKNOWN")):
            raise StageError("license_missing", package, filename)
        selected = {canonicalize_name(item["name"]): item for item in closure}
        required_names = set()
        for value in metadata.get_all("Requires-Dist", []):
            try:
                requirement = Requirement(value)
            except Exception as exc:
                raise StageError("wheel_metadata", package, filename,
                                 detail="invalid Requires-Dist") from exc
            if not marker_matches(str(requirement.marker) if requirement.marker else None,
                                  set(pin.get("extras", []))):
                continue
            dependency = selected.get(canonicalize_name(requirement.name))
            required_names.add(canonicalize_name(requirement.name))
            if (requirement.url or dependency is None
                    or Version(dependency["version"]) not in requirement.specifier
                    or not requirement.extras <= set(dependency.get("extras", []))):
                raise StageError("metadata_dependency_mismatch", package,
                                 detail=canonicalize_name(requirement.name))
        if "selected_dependencies" in pin and required_names != set(pin["selected_dependencies"]):
            raise StageError("metadata_dependency_mismatch", package,
                             detail="lock and METADATA dependency sets differ")
        return {**pin, **({"wheel_tag_exception": tag_exception} if tag_exception else {}),
                "license": license_text or ("MIT" if engine else None),
                "license_classifiers": classifiers, "license_files": notices}


def install_wheel(artifact: Path, pin: dict, site: Path, scratch: Path) -> list[str]:
    """Wheel spread with explicit schemes, no script generation or file overwrite."""
    unpacked = scratch / pin["sha256"]
    extract_archive(artifact, unpacked, package=pin["name"])
    mappings = []
    omitted = []
    for original in sorted(unpacked.rglob("*")):
        if not original.is_file():
            continue
        relative = original.relative_to(unpacked)
        parts = relative.parts
        if parts[0].endswith(".data"):
            # Runtime has no C-extension build interface. Record omitted headers.
            if len(parts) >= 3 and parts[1] == "headers":
                omitted.append(relative.as_posix())
                continue
            if len(parts) < 3 or parts[1] not in {"purelib", "platlib"}:
                raise StageError("wheel_layout", pin["name"], relative.as_posix())
            relative = Path(*parts[2:])
        validate_windows_path(relative.as_posix(), package=pin["name"])
        target = site / relative
        if target.exists():
            raise StageError("install_collision", pin["name"], relative.as_posix())
        mappings.append((original, target))
    folded = [target.relative_to(site).as_posix().casefold() for _, target in mappings]
    existing = {path.relative_to(site).as_posix().casefold() for path in site.rglob("*")}
    if len(folded) != len(set(folded)) or existing.intersection(folded):
        raise StageError("install_collision", pin["name"])
    for original, target in mappings:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
    return omitted


def native_environment(work: Path) -> dict[str, str]:
    """Only the OS and private build scratch, never caller Python/PATH settings."""
    systemroot = os.environ.get("SystemRoot", r"C:\Windows")
    return {"SystemRoot": systemroot, "WINDIR": systemroot,
            "PATH": str(Path(systemroot) / "System32"),
            "TEMP": str(work), "TMP": str(work), "USERPROFILE": str(work),
            "PYTHONDONTWRITEBYTECODE": "1", "PIP_CONFIG_FILE": os.devnull}


def native_run(python: Path, script: str, args: list[str], work: Path) -> str:
    try:
        result = subprocess.run([str(python), "-I", "-B", "-c", script, *args],
                                cwd=work, env=native_environment(work), check=True,
                                text=True, capture_output=True, timeout=300)
        return result.stdout.strip()
    except Exception as exc:
        raise StageError("native_load_failure", path=python.name,
                         detail="isolated native subprocess failed") from exc


def build_engine(repo: Path, python: Path, scratch: Path, lock: dict,
                 project: dict, cache: Path, closure: list[dict]) -> tuple[Path, dict, dict]:
    backends = [p for p in lock["package"] if p["name"] == "setuptools"]
    if (len(backends) != 1 or backends[0]["version"] != "84.0.0"
            or set(backends[0].get("source", {})) != {"registry"}):
        raise StageError("backend_pin", "setuptools")
    backend = backends[0]
    backend_pin = select_wheel(backend)
    backend_artifact = verified_download(backend_pin, cache, "setuptools")
    inspect_wheel(backend_artifact, backend_pin, [], build_backend=True)
    backend_dir = scratch / "backend"
    extract_archive(backend_artifact, backend_dir, package="setuptools")
    source = scratch / "source"
    source.mkdir()
    tracked = subprocess.check_output(["git", "-C", str(repo), "ls-files", "-z", "src"])
    source_files = []
    omitted_source_files = []
    for filename in sorted(filter(None, tracked.decode().split("\0"))):
        if filename.startswith("src/computer/runtime/assets/"):
            omitted_source_files.append(filename)
            continue
        original = repo / filename
        if original.is_symlink() or not original.is_file():
            raise StageError("engine_source", path=filename)
        target = source / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        source_files.append({"path": filename, "sha256": digest(original)})
    shutil.copyfile(repo / "pyproject.toml", source / "pyproject.toml")
    dist = scratch / "dist"
    dist.mkdir()
    native_run(python, "import os,sys;os.chdir(sys.argv[1]);sys.path.insert(0,sys.argv[2]);"
               "import setuptools.build_meta;setuptools.build_meta.build_wheel(sys.argv[3])",
               [str(source), str(backend_dir), str(dist)], scratch)
    wheels = list(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise StageError("engine_wheel", project["name"])
    artifact = wheels[0]
    pin = {"name": project["name"], "version": project["version"], "filename": artifact.name,
           "sha256": digest(artifact), "size": artifact.stat().st_size,
           "license": "MIT", "provenance": "reviewed source tree", "extras": []}
    record = inspect_wheel(artifact, pin, closure, engine=True)
    record.update({"editable": False, "source_files": source_files,
                   "omitted_linux_assets": omitted_source_files,
                   "pyproject_sha256": digest(repo / "pyproject.toml")})
    return artifact, pin, record


def validate_lock(spec: dict, closure: list[dict]) -> None:
    if spec.get("platform") not in {"win_amd64", "windows-amd64"}:
        raise StageError("runtime_platform")
    if spec.get("python", {}).get("version") != "3.12.15":
        raise StageError("python_abi")
    for name in ("python", "uv", "pip"):
        validate_pin(spec.get(name, {}), name)
    pip = next((item for item in closure if item["name"] == "pip"), None)
    if pip is None or any(pip[key] != spec["pip"][key]
                          for key in ("version", "url", "sha256", "size")):
        raise StageError("pip_pin", "pip")
    if "x86_64-pc-windows-msvc-install_only" not in spec["python"]["url"]:
        raise StageError("runtime_platform", "python")
    if "x86_64-pc-windows-msvc" not in spec["uv"]["url"]:
        raise StageError("runtime_platform", "uv")


def stage_windows_runtime(repo: Path, dest: Path, cache_dir: Path) -> dict:
    """Publish root/python only after all native checks; refuse previous stages."""
    if platform.system() != "Windows":
        raise StageError("wrong_os", "python")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise StageError("wrong_arch", "python")
    repo, dest, cache = Path(repo).resolve(), Path(dest).absolute(), Path(cache_dir).resolve()
    # Do not resolve away a reparse destination and then call it trusted.
    for path in [dest, *dest.parents]:
        if (path.is_symlink()
                or (path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400)):
            raise StageError("destination_reparse", path=str(path))
    if (dest / "python").exists():
        raise StageError("previous_stage", "python")
    spec = json.loads((repo / "app/packaging/runtime-lock.win_amd64.json").read_text())
    lock = tomllib.loads((repo / "uv.lock").read_text())
    project = tomllib.loads((repo / "pyproject.toml").read_text())["project"]
    closure = production_closure(lock, project)
    validate_lock(spec, closure)
    dest.mkdir(parents=True, exist_ok=True)
    cache = cache / "windows-python/artifacts"
    python_archive = verified_download(spec["python"], cache, "python")
    # uv is a reviewed build input, not needed for dependency resolution here.
    verified_download(spec["uv"], cache, "uv")
    with tempfile.TemporaryDirectory(dir=dest, prefix=".python-stage-") as temporary:
        work = Path(temporary)
        unpack = work / "unpack"
        extract_archive(python_archive, unpack, package="python", expected_root="python")
        runtime = unpack / "python"
        python = runtime / "python.exe"
        if not python.is_file() or not (runtime / "Lib").is_dir():
            raise StageError("runtime_layout", "python")
        version = native_run(python, "import platform;print(platform.python_version())", [], work)
        if version != spec["python"]["version"]:
            raise StageError("python_abi", "python")
        site = unpack / SITE
        # CPython's bootstrapping packages are replaced, never overlaid.
        if site.exists():
            shutil.rmtree(site)
        site.mkdir(parents=True)
        for entry in (runtime / "Scripts", runtime / "Lib/ensurepip"):
            if entry.exists():
                shutil.rmtree(entry)
        wheel_scratch = work / "wheel-spread"
        wheel_scratch.mkdir()
        dependencies = []
        for pin in closure:
            artifact = verified_download(pin, cache, pin["name"])
            dependencies.append(inspect_wheel(artifact, pin, closure))
            dependencies[-1]["omitted_build_headers"] = install_wheel(
                artifact, pin, site, wheel_scratch)
        exact_artifacts(closure, dependencies)
        artifact, engine_pin, engine = build_engine(
            repo, python, work, lock, project, cache, closure)
        install_wheel(artifact, engine_pin, site, wheel_scratch)
        pruned = prune_foreign_payloads(site)
        vc_runtime = stage_vc_runtime(
            runtime, cache, lock_path=repo / "app/packaging/vc-runtime-lock.win_amd64.json")
        # NumPy explicitly registers numpy.libs via its wheel loader, not PATH.
        dll_search = [runtime / "DLLs", runtime]
        numpy_libs = site / "numpy.libs"
        if numpy_libs.is_dir():
            dll_search.append(numpy_libs)
        dlls = audit_dll_dependencies(runtime, search_dirs=tuple(dll_search))
        loads = native_run(python,
            "import sys,site,json,sqlite3,cryptography.hazmat.bindings._rust;"
            "import onnxruntime,sqlite_vec,pip,struct,importlib.metadata as md;"
            "from pathlib import Path;root=Path(sys.executable).parent.resolve();"
            "assert sys.flags.isolated and not site.ENABLE_USER_SITE;"
            "assert all(Path(p).resolve().is_relative_to(root) for p in sys.path);"
            "assert struct.calcsize('P')==8 and sys.version_info[:2]==(3,12);"
            "expected=json.loads(sys.argv[1]);"
            "assert all(md.version(n)==v for n,v in expected.items());"
            "assert pip.__version__==expected['pip'];"
            "assert not {'setuptools','uv','wheel'}.intersection("
            "{p.name for p in (root/'Lib/site-packages').iterdir()});"
            "db=sqlite3.connect(':memory:');db.enable_load_extension(True);sqlite_vec.load(db);"
            "print(json.dumps({'cryptography':True,'onnxruntime':True,'sqlite':sqlite3.sqlite_version,"
            "'sqlite_vec':db.execute('select vec_version()').fetchone()[0],'isolated':True}))",
            [json.dumps({p["name"]: p["version"] for p in closure})], work)
        licenses = [{"path": p.relative_to(unpack).as_posix(), "sha256": digest(p)}
                    for p in sorted(runtime.rglob("*")) if p.is_file()
                    and re.search(r"(?i)(license|copying|notice|copyright)", p.name)]
        if not (runtime / "LICENSE.txt").is_file():
            raise StageError("license_missing", "python", "python/LICENSE.txt")
        upstream = repo / "maintenance/UPSTREAM-LICENSE"
        legal = runtime / "licenses"
        legal.mkdir(exist_ok=True)
        shutil.copyfile(upstream, legal / "UPSTREAM-LICENSE")
        licenses.append({"path": "python/licenses/UPSTREAM-LICENSE", "sha256": digest(upstream),
                         "license": "MIT"})
        result = {"schema": 1, "platform": "win_amd64", "python": spec["python"],
                  "build_tool": spec["uv"], "pip": spec["pip"],
                  "executable": "python/python.exe", "site_packages": SITE.as_posix(),
                  "runtime_args": ["-I", "-B", "-m", "src"],
                  "uv_lock_sha256": digest(repo / "uv.lock"), "extras": [],
                  "dependencies": dependencies, "engine": engine, "dll_audit": dlls,
                  "pruned_foreign_payloads": pruned,
                  "vc_runtime": vc_runtime,
                  "license_blockers": vc_runtime["license_blockers"],
                  "native_loads": json.loads(loads), "licenses": licenses}
        (runtime / "runtime-metadata.json").write_text(json.dumps(result, indent=2) + "\n")
        (runtime / "dependency-licenses.json").write_text(json.dumps(dependencies, indent=2) + "\n")
        if (dest / "python").exists():
            raise StageError("previous_stage", "python")
        # Windows rename refuses existing destinations. Never replace a stage.
        os.rename(runtime, dest / "python")
    return result


def stage_runtime(bundle_root: Path, cache_dir: Path) -> dict:
    return stage_windows_runtime(REPO, bundle_root, cache_dir)


def prune_foreign_payloads(site: Path) -> list[dict]:
    """Remove named supplier development payloads unusable on Windows amd64."""
    selected = []
    completion = site / "tqdm/completion.sh"
    if completion.is_file():
        selected.append(completion)
    for name in ("w32.exe", "t32.exe", "w64-arm.exe", "t64-arm.exe"):
        path = site / "pip/_vendor/distlib" / name
        if path.is_file():
            selected.append(path)
    scripts = site / "playwright/driver/package/bin"
    for path in sorted(scripts.glob("*.sh")):
        selected.append(path)
    records = []
    for path in selected:
        records.append({"path": path.relative_to(site).as_posix(), "sha256": digest(path),
                        "reason": "foreign platform supplier development payload"})
        path.unlink()
    return records
