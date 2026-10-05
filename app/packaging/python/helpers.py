"""D14 computer helper staging, never input, installation or backend admission.

Only already-installed, hash-pinned build libraries are accepted. This module
does not download dependencies or modify the workstation. Native smoke calls
have no arguments and therefore exit before opening a display or input path.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ASSETS = Path("python/lib/python3.12/site-packages/src/computer/runtime/assets")
BASELINE = "cd7530906e9cfa10a0fa900247d7ce2a8bb33e25"
# Ubuntu 24.04 x86_64 build inputs. A different package revision requires a
# reviewed lock update, not silently copying a new system library.
LIBRARIES = (
    ("libei.so.1", "libei1", "1.2.1-1",
     "e1e7ad03d569215a036af2a79f6c038f82afc632ec5b6093f9a1f92b488391ae",
     "5b485ff8a320969d80e99b689d4c4007c4d23f2841c5b4f37e311b678b3483c3"),
    ("libxkbcommon.so.0", "libxkbcommon0", "1.6.0-1build1",
     "3eb6c7315985803a7c72cb81aa3293b763e6cfc907b70b7b2f641c2827cd90f9",
     "5eeaeb1b6e029a0274e1573765bb0bae2926ef96a3679203faa4fd00fdaeaa88"),
    ("libwayland-client.so.0", "libwayland-client0", "1.22.0-2.1build1",
     "1c22abb422953442aa12822ea51ac76d1c8be92ed143e0159e0f830776cde2b2",
     "736bf54141fa9808939ffff2691b817888ea53197484c2099e8d03b954b83e3b"),
    ("libffi.so.8", "libffi8", "3.4.6-1build1",
     "00f593fe192f2851b8ce23b25cec2488d769beb5a8f63e8c9e563071e1075153",
     "737ff68f0eb104d3b0d96b291c3a8f40a775a3ec2b53f9b2e4bcfe3188bde118"),
)
NATIVE = {"odin-computer-wayland-input": 64, "odin-hyprland-input": 64,
          "odin-hyprland-capture": 2}


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _env(home: Path) -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8",
            "SOURCE_DATE_EPOCH": "1791158400", "PYTHONDONTWRITEBYTECODE": "1"}


def _run(argv: list[str], home: Path, expected: int = 0) -> str:
    result = subprocess.run(argv, env=_env(home), cwd=home, capture_output=True,
                            text=True, timeout=120)
    if result.returncode != expected:
        raise RuntimeError(f"helper build/proof failed ({result.returncode}): "
                           f"{argv[0]}\n{result.stderr[:4000]}")
    return result.stdout.strip()


def _checked_copy(source: Path, target: Path, digest: str | None = None) -> None:
    if digest is not None and _sha(source) != digest:
        raise ValueError(f"helper locked input hash mismatch: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError(f"helper destination symlink refused: {target}")
    shutil.copyfile(source, target)
    target.chmod(0o644)


def stage_helpers(bundle_root: Path, cache_dir: Path) -> dict:
    """Stage C helpers, their DSO closure, exact sources and notices.

    The engine must already be installed by stage_python/refresh_engine. Asset
    bytes are checked against its actual importable package data, never placed
    in a parallel path which the engine would not consume.
    """
    root = Path(bundle_root).resolve()
    cache = Path(cache_dir).resolve() / "helpers"
    cache.mkdir(parents=True, exist_ok=True)
    assets = REPO / "src/computer/runtime/assets"
    entries: list[dict] = []

    def record(path: Path, source: str, license_path: str, role: str) -> None:
        entries.append({"path": path.relative_to(root).as_posix(), "sha256": _sha(path),
                        "size": path.stat().st_size, "source": source,
                        "license_path": license_path, "role": role})

    license_rel = "helpers/licenses/UPSTREAM-MIT.txt"
    license_file = root / license_rel
    _checked_copy(REPO / "maintenance/UPSTREAM-LICENSE", license_file)
    record(license_file, "maintenance/UPSTREAM-LICENSE", license_rel, "license")
    for source in sorted(assets.rglob("*")):
        if not source.is_file() or "__pycache__" in source.parts:
            continue
        rel = source.relative_to(assets)
        installed = root / ASSETS / rel
        if not installed.is_file() or _sha(installed) != _sha(source):
            raise ValueError(f"engine package asset missing or drifted: {rel}")
        record(installed, source.relative_to(REPO).as_posix(), license_rel, "engine-asset")

    # Explicit production helper source allowlist, no qualification tuples,
    # fixtures, private lab scripts or inherited runtime-qualified claims.
    source_names = (
        "assets/hyprland-input/guardian.c",
        "assets/hyprland-input/wlr-virtual-pointer-unstable-v1.xml",
        "assets/hyprland-input/virtual-keyboard-unstable-v1.xml",
        "assets/hyprland-input/scope-plugin.cpp",
        "assets/hyprland-input/scope-deadline.hpp",
        "assets/hyprland-input/scope-provenance.hpp",
        "assets/hyprland-capture/odin-hyprland-capture.c",
        "assets/hyprland-capture/wlr-screencopy-unstable-v1.xml",
        "assets/kwin-scope/odinscope.cpp", "assets/kwin-scope/odinscope.h",
        "assets/kwin-scope/metadata.json", "assets/kwin-scope/CMakeLists.txt",
    )
    for name in source_names:
        target = root / "helpers/source" / name
        _checked_copy(REPO / name, target)
        notice = license_rel
        if target.suffix == ".xml":
            # Protocol notices belong to their original authors, not Odin.
            text = ET.parse(target).getroot().findtext("copyright")
            if not text:
                raise ValueError(f"protocol copyright missing: {name}")
            notice = f"helpers/licenses/{target.stem}.txt"
            (root / notice).write_text(text.strip() + "\n", encoding="utf-8")
            record(root / notice, name + "#copyright", notice, "license")
        record(target, name, notice, "source")

    for soname, package, version, digest, notice_digest in LIBRARIES:
        lib = Path("/usr/lib/x86_64-linux-gnu") / soname
        notice = Path("/usr/share/doc") / package / "copyright"
        dest = root / "helpers/lib" / soname
        _checked_copy(lib, dest, digest)
        notice_rel = f"helpers/licenses/{package}-copyright.txt"
        _checked_copy(notice, root / notice_rel, notice_digest)
        record(dest, f"Ubuntu24.04:{package}={version}:{soname}", notice_rel, "library")
        record(root / notice_rel, f"Ubuntu24.04:{package}={version}:copyright",
               notice_rel, "license")

    versions = {"compiler": _run(["cc", "--version"], cache).splitlines()[0]}
    # scanner emits its version on stderr; record stdout/stderr explicitly.
    scanner = subprocess.run(["wayland-scanner", "--version"], env=_env(cache),
                             capture_output=True, text=True, timeout=10, check=True)
    versions["scanner"] = (scanner.stdout + scanner.stderr).strip()
    versions["linker"] = _run(["ld", "--version"], cache).splitlines()[0]
    pinned_tools = {"compiler": "cc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0",
                    "scanner": "wayland-scanner 1.22.0",
                    "linker": "GNU ld (GNU Binutils for Ubuntu) 2.42"}
    if versions != pinned_tools:
        raise ValueError("helper build toolchain differs from reviewed Ubuntu24.04 inputs")
    builds: list[dict] = []
    with tempfile.TemporaryDirectory(dir=cache, prefix="build-") as directory:
        build = Path(directory)
        common = ["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                  "-fstack-protector-strong", "-D_FORTIFY_SOURCE=2",
                  f"-ffile-prefix-map={REPO}=.", f"-ffile-prefix-map={build}=build",
                  "-Wl,--disable-new-dtags,-rpath,$ORIGIN/../lib", "-Wl,-z,relro,-z,now"]

        def compile_helper(name: str, sources: list[Path], packages: list[str],
                           extra: list[str]) -> None:
            flags = shlex.split(_run(["pkg-config", "--cflags", "--libs", *packages], cache))
            output = build / name
            argv = [*common, *extra, f"-I{build}", *map(str, sources), "-o", str(output),
                    *flags, "-lm"]
            _run(argv, cache)
            target = root / "helpers/bin" / name
            _checked_copy(output, target)
            target.chmod(0o755)
            record(target, ";".join(str(p.relative_to(REPO)) if p.is_relative_to(REPO)
                                    else p.name for p in sources), license_rel, "native-helper")
            normalized = [a.replace(str(REPO), "${REPO}").replace(str(build), "${BUILD}")
                          for a in argv]
            builds.append({"name": name, "argv": normalized,
                           "pkg_config": {p: _run(["pkg-config", "--modversion", p], cache)
                                          for p in packages}})

        compile_helper("odin-computer-wayland-input", [assets / "wayland_owned_input.c"],
                       ["libei-1.0", "xkbcommon"], ["-D_DEFAULT_SOURCE", "-U_FORTIFY_SOURCE"])
        for family, protocols in (
            ("hyprland-input", (("wlr-virtual-pointer-unstable-v1.xml", "wlr-virtual-pointer"),
                                ("virtual-keyboard-unstable-v1.xml", "virtual-keyboard"))),
            ("hyprland-capture", (("wlr-screencopy-unstable-v1.xml", "screencopy"),)),
        ):
            generated = []
            for xml, stem in protocols:
                source = REPO / "assets" / family / xml
                c_file = build / f"{stem}-protocol.c"
                _run(["wayland-scanner", "client-header", str(source),
                      str(build / f"{stem}-client.h")], cache)
                _run(["wayland-scanner", "private-code", str(source), str(c_file)], cache)
                for artifact in (c_file, build / f"{stem}-client.h"):
                    dest = root / "helpers/generated" / artifact.name
                    _checked_copy(artifact, dest)
                    record(dest, source.relative_to(REPO).as_posix(),
                           f"helpers/licenses/{source.stem}.txt", "generated-protocol")
                generated.append(c_file)
            if family == "hyprland-input":
                compile_helper("odin-hyprland-input",
                               [REPO / "assets" / family / "guardian.c", *generated],
                               ["wayland-client", "xkbcommon"], [])
            else:
                compile_helper("odin-hyprland-capture",
                               [REPO / "assets" / family / "odin-hyprland-capture.c", *generated],
                               ["wayland-client"], ["-Wconversion", "-Wshadow"])

    metadata = {"schema": 1, "feature": "computer-use-helpers", "upstream_commit": BASELINE,
                "desktop_source_commit": _run(
                    ["git", "-C", str(REPO), "rev-parse", "HEAD"], cache),
                "engine_assets": ASSETS.as_posix(), "native_directory": "helpers/bin",
                "library_directory": "helpers/lib", "files": entries,
                "build": {"tools": versions, "helpers": builds},
                "backend_admission": "deferred", "input_proof": False,
                "deferred": [
                    "Phase2 native backend admission and immutable installed helper path bindings",
                    "Root-owned helper trust and AppImage/user-owned installation policy",
                    "Exact compositor ABI plugin builds and fresh qualification (Hyprland/KWin)",
                    "X11 isolation system dependencies and bundled GI/AT-SPI runtime closure",
                    "xkb data and compositor/session integration in isolated native labs",
                ],
                "external_abi": ["Linux x86_64", "glibc dynamic loader, libc and libm"],
                "source_license": "MIT upstream notice; Desktop distribution decision pending"}
    metadata["offline_proof"] = prove_helpers(root, metadata)
    (root / "helpers/metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def prove_helpers(bundle_root: Path, metadata: dict | None = None) -> dict:
    """Verify relocatable discovery and native loading without display/input."""
    root = Path(bundle_root).resolve()
    if metadata is None:
        metadata = json.loads((root / "helpers/metadata.json").read_text())
    for row in metadata["files"]:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe helper manifest path")
        path = root / relative
        if (path.is_symlink() or not path.resolve().is_relative_to(root)
                or _sha(path) != row["sha256"]):
            raise ValueError(f"helper inventory digest/path mismatch: {relative}")
    expected = {row["path"] for row in metadata["files"]}
    actual = {p.relative_to(root).as_posix()
              for directory in (root / ASSETS, root / "helpers")
              for p in directory.rglob("*")
              if (p.is_file() or p.is_symlink()) and "__pycache__" not in p.parts
              and p != root / "helpers/metadata.json"}
    if expected != actual:
        raise ValueError("helper inventory closure mismatch")
    env_home = root / "helpers"
    # Probe actual installed Python assets and private probe import, not checkout.
    code = (
        "import importlib.resources as r,json;"
        "from src.computer.runtime.assets.wayland_probe_private import device_equal;"
        "from src.computer.runtime.wayland_probe import _ASSETS;"
        "p=r.files('src.computer.runtime').joinpath('assets');"
        "assert _ASSETS==p;"
        "assert device_equal('00:01','0:1');"
        "print(json.dumps({'package':str(p),'passwd':p.joinpath('passwd').read_text(),"
        "'session_config':p.joinpath('session.conf').read_text()}))"
    )
    loaded = json.loads(_run([str(root / "python/bin/python3.12"), "-I", "-B", "-c", code],
                             env_home))
    if Path(loaded["package"]).resolve() != (root / ASSETS).resolve():
        raise ValueError("engine helpers resolved outside bundle")
    native = []
    for name, expected in NATIVE.items():
        binary = root / "helpers/bin" / name
        _run([str(binary)], env_home, expected)
        dependencies = _run(["ldd", str(binary)], env_home)
        if "not found" in dependencies:
            raise RuntimeError("helper library unavailable")
        for soname, *_ in LIBRARIES:
            for line in dependencies.splitlines():
                if line.strip().startswith(soname + " =>"):
                    resolved = Path(line.split("=>", 1)[1].strip().split(" (", 1)[0]).resolve()
                    if resolved != (root / "helpers/lib" / soname).resolve():
                        raise ValueError(f"helper DSO resolved outside bundle: {soname}")
        allowed = {row[0] for row in LIBRARIES} | {"libc.so.6", "libm.so.6"}
        for line in dependencies.splitlines():
            if "=>" in line and line.split("=>", 1)[0].strip() not in allowed:
                raise ValueError("helper dependency not covered by inventory/ABI floor")
        native.append({"name": name, "no_argument_exit": expected, "ldd": dependencies})
    floors = set()
    for path in [*(root / "helpers/bin" / name for name in NATIVE),
                 *(root / "helpers/lib" / row[0] for row in LIBRARIES)]:
        versions = _run(["readelf", "--version-info", str(path)], env_home)
        floors.update(re.findall(r"GLIBC_([0-9]+\.[0-9]+(?:\.[0-9]+)?)", versions))
    floor = max(floors, key=lambda value: tuple(map(int, value.split("."))))
    return {"asset_package": ASSETS.as_posix(), "package_import": True,
            "config_read": bool(loaded["passwd"] and loaded["session_config"]),
            "native_loader": native, "glibc_symbol_floor": floor, "input_attempted": False,
            "scope": "offline asset discovery/config reads and pre-input usage refusal only"}
