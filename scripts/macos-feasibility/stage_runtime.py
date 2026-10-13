"""Stage the pinned macOS arm64 Python with the engine's locked dependencies, and audit every Mach-O
file.

Evidence harness for the macOS feasibility spike (phase 1); phase 4 builds the real runtime stager.

  python3 stage_runtime.py --out DIR [--cache DIR] [--uv PATH]
      DIR/python (interpreter + uv.lock dependencies), DIR/models (the pinned search model),
      DIR/report.json
  python3 stage_runtime.py --list-macho DIR
      every Mach-O file under DIR, deepest first (the signing order)
  python3 stage_runtime.py --audit DIR
      the Mach-O audit alone, as JSON

The audit finds Mach-O files by content, not by name. For every arm64 slice it requires the macOS
platform and a known minimum macOS no newer than the support floor. Each library load outside
/usr/lib and /System/Library (spelled without "..") is followed in search order: @rpath through the
binary's own run paths, then the interpreter's, each expanded against the image that declared it,
plus @loader_path and @executable_path. The first candidate that exists must be a file inside the
staged bundle, symlinks resolved; a first match outside the bundle is a problem even when a later
one is inside. A missing weak load is a warning. This approximates dyld's loader chain: it shows
that the first existing candidate is in the bundle, not full dependency closure, which is a
packaged-app check (phase 4).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOCK = json.loads((HERE / "runtime-lock.json").read_text())
FLOOR = tuple(int(part) for part in LOCK["minimum_macos"].split(".")) + (0,)
SYSTEM_LOADS = ("/usr/lib/", "/System/Library/")

MH_MAGIC_64 = 0xFEEDFACF
FAT_MAGIC, FAT_MAGIC_64 = 0xCAFEBABE, 0xCAFEBABF
CPU_TYPES = {0x0100000C: "arm64", 0x01000007: "x86_64"}
LC_BUILD_VERSION, LC_VERSION_MIN_MACOSX, LC_RPATH = 0x32, 0x24, 0x8000001C
LC_LOAD_WEAK_DYLIB = 0x80000018
PLATFORM_MACOS = 1
MH_EXECUTE = 2
LOAD_COMMANDS = {
    0xC,
    0x20,
    0x80000018,
    0x8000001F,
    0x80000023,
}  # load, lazy, weak, reexport, upward dylib


def fetch(url: str, sha256: str, destination: Path) -> Path:
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == sha256:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, open(pending, "wb") as handle:
        while chunk := response.read(1 << 20):
            handle.write(chunk)
    actual = hashlib.sha256(pending.read_bytes()).hexdigest()
    if actual != sha256:
        pending.unlink()
        raise ValueError(f"SHA-256 mismatch for {url}: {actual}")
    pending.replace(destination)
    return destination


def stage_python(out: Path, cache: Path) -> Path:
    python = LOCK["python"]
    archive = fetch(
        python["url"], python["sha256"], cache / Path(python["url"]).name.replace("%2B", "+")
    )
    with tarfile.open(archive) as bundle:
        bundle.extractall(out, filter="data")
    executable = out / "python" / "bin" / "python3.12"
    if not executable.is_file():
        raise FileNotFoundError(executable)
    return executable


def install_dependencies(executable: Path, uv: str, work: Path) -> None:
    requirements = work / "requirements.txt"
    subprocess.run(
        [
            uv,
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--no-header",
            "--output-file",
            str(requirements),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            str(executable),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--require-hashes",
            "--only-binary=:all:",
            "--no-warn-script-location",
            "-r",
            str(requirements),
        ],
        check=True,
    )


def stage_model(out: Path, cache: Path) -> dict:
    sys.path.insert(0, str(ROOT / "app" / "packaging" / "python"))
    import models  # noqa: PLC0415 - the repository's own digest-pinned model stager

    return models.stage_models(out, cache)


def macho_kind(path: Path) -> str | None:
    try:
        with open(path, "rb") as handle:
            head = handle.read(8)
    except OSError:
        return None
    if len(head) < 8:
        return None
    if struct.unpack("<I", head[:4])[0] == MH_MAGIC_64:
        return "thin"
    magic, count = struct.unpack(">II", head)
    if magic in (FAT_MAGIC, FAT_MAGIC_64) and 0 < count < 20:  # Java class files share CAFEBABE
        return "fat"
    return None


def _version(packed: int) -> tuple[int, int, int]:
    return packed >> 16, (packed >> 8) & 0xFF, packed & 0xFF


def _string(data: bytes, command: int, size: int) -> str:
    name_offset = struct.unpack_from("<I", data, command + 8)[0]
    return data[command + name_offset : command + size].split(b"\0", 1)[0].decode(errors="replace")


def _thin(data: bytes, base: int) -> dict:
    magic, cputype, _, filetype, ncmds, _, _, _ = struct.unpack_from("<IiiIIIII", data, base)
    if magic != MH_MAGIC_64:
        raise ValueError("not a 64-bit Mach-O slice")
    slice_info = {
        "arch": CPU_TYPES.get(cputype & 0xFFFFFFFF, hex(cputype)),
        "filetype": filetype,
        "platform": None,
        "minos": None,
        "loads": [],
        "weak": [],
        "rpaths": [],
    }
    offset = base + 32
    for _ in range(ncmds):
        command, size = struct.unpack_from("<II", data, offset)
        if command == LC_BUILD_VERSION:
            platform, minos = struct.unpack_from("<II", data, offset + 8)
            slice_info["platform"], slice_info["minos"] = platform, _version(minos)
        elif command == LC_VERSION_MIN_MACOSX and slice_info["minos"] is None:
            slice_info["platform"] = PLATFORM_MACOS
            slice_info["minos"] = _version(struct.unpack_from("<I", data, offset + 8)[0])
        elif command == LC_LOAD_WEAK_DYLIB:
            slice_info["weak"].append(_string(data, offset, size))
        elif command in LOAD_COMMANDS:
            slice_info["loads"].append(_string(data, offset, size))
        elif command == LC_RPATH:
            slice_info["rpaths"].append(_string(data, offset, size))
        offset += size
    return slice_info


def slices(path: Path) -> list[dict]:
    data = path.read_bytes()
    if macho_kind(path) == "thin":
        return [_thin(data, 0)]
    magic, count = struct.unpack_from(">II", data, 0)
    found = []
    for index in range(count):
        if magic == FAT_MAGIC:
            _, _, start, _, _ = struct.unpack_from(">iiIII", data, 8 + index * 20)
        else:
            _, _, start, _, _, _ = struct.unpack_from(">iiQQII", data, 8 + index * 32)
        found.append(_thin(data, start))
    return found


def list_macho(root: Path) -> list[Path]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and macho_kind(path)
    ]
    return sorted(files, key=lambda path: (-len(path.parts), str(path)))


def _system_load(load: str) -> bool:
    return load.startswith(SYSTEM_LOADS) and os.path.normpath(load) == load and ".." not in load


def _expand(path: str, image: Path, executable_dir: Path) -> Path:
    path = path.replace("@loader_path", str(image.parent))
    return Path(path.replace("@executable_path", str(executable_dir)))


def _first_candidate(load: str, candidates: list[Path], root: Path) -> tuple[str, str]:
    """("inside" | "outside" | "missing", detail): the first candidate that exists decides."""
    for candidate in candidates:
        resolved = Path(os.path.realpath(candidate))
        if resolved.is_file():
            if resolved.is_relative_to(root):
                return "inside", str(resolved.relative_to(root))
            return "outside", str(resolved)
    return "missing", load


def audit(root: Path) -> dict:
    root = Path(os.path.realpath(root))
    interpreter = root / "python" / "bin" / "python3.12"
    interpreter_rpaths: list[str] = []
    if interpreter.is_file():
        interpreter_rpaths = next(
            (item["rpaths"] for item in slices(interpreter) if item["arch"] == "arm64"), []
        )
    problems, warnings = [], []
    files = list_macho(root)
    for path in files:
        relative = str(path.relative_to(root))
        found = slices(path)
        arm64 = [item for item in found if item["arch"] == "arm64"]
        if not arm64:
            problems.append(f"{relative}: no arm64 slice ({[item['arch'] for item in found]})")
        for item in arm64:
            if item["platform"] != PLATFORM_MACOS:
                problems.append(f"{relative}: platform {item['platform']} is not macOS")
            if item["minos"] is None:
                problems.append(f"{relative}: no minimum macOS recorded")
            elif item["minos"] > FLOOR:
                problems.append(f"{relative}: needs macOS {'.'.join(map(str, item['minos']))}")
            executable_dir = path.parent if item["filetype"] == MH_EXECUTE else interpreter.parent
            loads = [(load, False) for load in item["loads"]] + [
                (load, True) for load in item["weak"]
            ]
            for load, weak in loads:
                if _system_load(load):
                    continue
                if load.startswith("@rpath/"):
                    tail = load[len("@rpath/") :]
                    candidates = [_expand(r, path, executable_dir) / tail for r in item["rpaths"]]
                    candidates += [
                        _expand(r, interpreter, interpreter.parent) / tail
                        for r in interpreter_rpaths
                    ]
                else:
                    candidates = [_expand(load, path, executable_dir)]
                where, detail = _first_candidate(load, candidates, root)
                if where == "outside":
                    problems.append(
                        f"{relative}: {load} resolves outside the bundle first: {detail}"
                    )
                elif where == "missing":
                    (warnings if weak else problems).append(f"{relative}: unresolved load {load}")
    return {
        "macho_files": len(files),
        "floor": LOCK["minimum_macos"],
        "problems": problems,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--out", type=Path)
    group.add_argument("--list-macho", type=Path)
    group.add_argument("--audit", type=Path)
    parser.add_argument(
        "--cache", type=Path, default=Path(tempfile.gettempdir()) / "odin-macos-runtime-cache"
    )
    parser.add_argument("--uv", default="uv")
    options = parser.parse_args()
    if options.list_macho:
        for path in list_macho(options.list_macho.resolve()):
            print(path)
        return 0
    if options.audit:
        report = audit(options.audit.resolve())
        print(json.dumps(report, indent=2))
        return 1 if report["problems"] else 0
    out = options.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    executable = stage_python(out, options.cache)
    with tempfile.TemporaryDirectory(prefix="stage-") as work:
        install_dependencies(executable, options.uv, Path(work))
    models = stage_model(out, options.cache)
    report = {
        "python": subprocess.run(
            [str(executable), "-c", "import sys; print(sys.version)"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "packages": json.loads(
            subprocess.run(
                [
                    str(executable),
                    "-m",
                    "pip",
                    "list",
                    "--format=json",
                    "--disable-pip-version-check",
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        ),
        "models": models,
        "audit": audit(out),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "macho_files": report["audit"]["macho_files"],
                "problems": report["audit"]["problems"],
                "packages": len(report["packages"]),
            },
            indent=2,
        )
    )
    return 1 if report["audit"]["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
