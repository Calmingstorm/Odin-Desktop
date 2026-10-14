"""The Mach-O audit for the macOS arm64 runtime (phase 1's evidence harness, made the lane's check).

Mach-O files are found by content, not by name. Every arm64 slice must be built for macOS with a
known minimum no newer than the support floor. Each library load outside /usr/lib and
/System/Library (spelled without "..") is followed in search order: @rpath through the binary's own
run paths, then the interpreter's, each expanded against the image that declared it, plus
@loader_path and @executable_path. The first candidate that exists must be a file inside the staged
root, links resolved; a first match outside it is a problem even when a later one is inside. A
missing weak load is a warning. This approximates dyld's loader chain: it shows that the first
existing candidate is in the bundle, not full dependency closure, which the packaged smoke checks.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

SYSTEM_LOADS = ("/usr/lib/", "/System/Library/")
MH_MAGIC_64 = 0xFEEDFACF
FAT_MAGIC, FAT_MAGIC_64 = 0xCAFEBABE, 0xCAFEBABF
CPU_TYPES = {0x0100000C: "arm64", 0x01000007: "x86_64"}
LC_BUILD_VERSION, LC_VERSION_MIN_MACOSX, LC_RPATH = 0x32, 0x24, 0x8000001C
LC_LOAD_WEAK_DYLIB = 0x80000018
# load, lazy, weak, reexport and upward dylib
LOAD_COMMANDS = {0xC, 0x20, 0x80000018, 0x8000001F, 0x80000023}
PLATFORM_MACOS = 1
MH_EXECUTE = 2


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
    offset = struct.unpack_from("<I", data, command + 8)[0]
    return data[command + offset:command + size].split(b"\0", 1)[0].decode(errors="replace")


def _thin(data: bytes, base: int) -> dict:
    magic, cputype, _, filetype, ncmds, _, _, _ = struct.unpack_from("<IiiIIIII", data, base)
    if magic != MH_MAGIC_64:
        raise ValueError("not a 64-bit Mach-O slice")
    found = {"arch": CPU_TYPES.get(cputype & 0xFFFFFFFF, hex(cputype)), "filetype": filetype,
             "platform": None, "minos": None, "loads": [], "weak": [], "rpaths": []}
    offset = base + 32
    for _ in range(ncmds):
        command, size = struct.unpack_from("<II", data, offset)
        if command == LC_BUILD_VERSION:
            platform, minos = struct.unpack_from("<II", data, offset + 8)
            found["platform"], found["minos"] = platform, _version(minos)
        elif command == LC_VERSION_MIN_MACOSX and found["minos"] is None:
            found["platform"] = PLATFORM_MACOS
            found["minos"] = _version(struct.unpack_from("<I", data, offset + 8)[0])
        elif command == LC_LOAD_WEAK_DYLIB:
            found["weak"].append(_string(data, offset, size))
        elif command in LOAD_COMMANDS:
            found["loads"].append(_string(data, offset, size))
        elif command == LC_RPATH:
            found["rpaths"].append(_string(data, offset, size))
        offset += size
    return found


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
    """Every Mach-O file under root, deepest first (the signing order)."""
    files = [path for path in root.rglob("*")
             if path.is_file() and not path.is_symlink() and macho_kind(path)]
    return sorted(files, key=lambda path: (-len(path.parts), str(path)))


def _system_load(load: str) -> bool:
    return load.startswith(SYSTEM_LOADS) and os.path.normpath(load) == load and ".." not in load


def _expand(path: str, image: Path, executable_dir: Path) -> Path:
    return Path(path.replace("@loader_path", str(image.parent))
                .replace("@executable_path", str(executable_dir)))


def _first_candidate(load: str, candidates: list[Path], root: Path) -> tuple[str, str]:
    """("inside" | "outside" | "missing", detail): the first candidate that exists decides."""
    for candidate in candidates:
        resolved = Path(os.path.realpath(candidate))
        if resolved.is_file():
            if resolved.is_relative_to(root):
                return "inside", str(resolved.relative_to(root))
            return "outside", str(resolved)
    return "missing", load


def audit(root: Path, floor: str, interpreter: str = "python/bin/python3.12") -> dict:
    root = Path(os.path.realpath(root))
    limit = tuple(int(part) for part in floor.split(".")) + (0,)
    python = root / interpreter
    python_rpaths: list[str] = []
    if python.is_file():
        python_rpaths = next((item["rpaths"] for item in slices(python) if item["arch"] == "arm64"),
                             [])
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
            elif item["minos"] > limit:
                problems.append(f"{relative}: needs macOS {'.'.join(map(str, item['minos']))}")
            executable_dir = path.parent if item["filetype"] == MH_EXECUTE else python.parent
            loads = [(load, False) for load in item["loads"]]
            loads += [(load, True) for load in item["weak"]]
            for load, weak in loads:
                if _system_load(load):
                    continue
                if load.startswith("@rpath/"):
                    tail = load[len("@rpath/"):]
                    candidates = [_expand(r, path, executable_dir) / tail for r in item["rpaths"]]
                    candidates += [_expand(r, python, python.parent) / tail for r in python_rpaths]
                else:
                    candidates = [_expand(load, path, executable_dir)]
                where, detail = _first_candidate(load, candidates, root)
                if where == "outside":
                    problems.append(
                        f"{relative}: {load} resolves outside the bundle first: {detail}")
                elif where == "missing":
                    (warnings if weak else problems).append(f"{relative}: unresolved load {load}")
    return {"tool": "Mach-O load commands (macos_macho.audit)", "macho_files": len(files),
            "floor": floor, "problems": problems, "warnings": warnings,
            "qualification": "first existing load candidate in the bundle, not full closure"}
