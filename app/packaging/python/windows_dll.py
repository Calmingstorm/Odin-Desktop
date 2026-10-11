"""Static PE normal/delay-import closure audit with no PATH/system search.

Not a replacement for native load tests: dynamic GetProcAddress/LoadLibrary names
are absent from PE tables. OS contracts are explicit Windows 11 baseline entries,
never a wildcard for api-ms-*. AMD64 (x64) is the default production target.
"""
import os
import stat
import struct
from pathlib import Path


class DLLAuditError(ValueError):
    def __init__(self, code, message, *, package=None, path=None):
        self.code, self.package, self.path = code, package, str(path) if path is not None else None
        super().__init__(message)

    def as_dict(self):
        return {"code": self.code, "package": self.package, "path": self.path,
                "message": str(self)}


# Windows 11 inbox DLLs used by CPython, Chromium/Node, OpenSSH and curl.
# Deliberately absent: vcruntime*, msvcp*, concrt*, libcrypto*, libssl*. These
# must ship in the bundle, even if a hosted developer machine has them.
WINDOWS_OS_DLLS = frozenset("""
advapi32.dll bcrypt.dll bcryptprimitives.dll bthprops.cpl cabinet.dll cfgmgr32.dll
combase.dll comctl32.dll comdlg32.dll crypt32.dll cryptbase.dll cryptnet.dll cryptsp.dll
d3d11.dll d3d12.dll dcomp.dll dbghelp.dll dhcpcsvc.dll dhcpcsvc6.dll
dnsapi.dll dsound.dll dwmapi.dll dwrite.dll dxgi.dll dxva2.dll gdi32.dll hid.dll
imm32.dll iphlpapi.dll kernel32.dll kernelbase.dll mpr.dll msimg32.dll
msi.dll msvcrt.dll ncrypt.dll netapi32.dll normaliz.dll ntdll.dll ole32.dll
oleacc.dll oleaut32.dll powrprof.dll propsys.dll psapi.dll rasapi32.dll
rpcrt4.dll secur32.dll setupapi.dll shell32.dll shlwapi.dll user32.dll
userenv.dll usp10.dll ucrtbase.dll uxtheme.dll version.dll wer.dll
winhttp.dll wininet.dll winmm.dll winspool.drv wintrust.dll wldap32.dll
ws2_32.dll wtsapi32.dll
""".split())
# Chromium 153's measured delay imports: Bluetooth control-panel module is a
# DLL despite .cpl, UIAutomation/audio/PDH/USB/URL/TPM APIs are inbox. Media
# Foundation requires the regular Windows 11 media-feature baseline; N editions
# without Media Feature Pack are not covered by this audit's OS assumption.
WINDOWS_OS_DLLS |= frozenset("""
uiautomationcore.dll pdh.dll mmdevapi.dll mf.dll mfplat.dll mfreadwrite.dll
winusb.dll urlmon.dll tbs.dll
""".split())
WINDOWS_OS_DLLS |= frozenset("api-ms-win-crt-" + name + "-l1-1-0.dll" for name in (
    "conio", "convert", "environment", "filesystem", "heap", "locale", "math",
    "multibyte", "private", "process", "runtime", "stdio", "string", "time", "utility"))
WINDOWS_OS_DLLS |= frozenset("""
api-ms-win-core-path-l1-1-0.dll api-ms-win-core-synch-l1-2-0.dll
api-ms-win-core-winrt-l1-1-0.dll api-ms-win-core-winrt-string-l1-1-0.dll
api-ms-win-core-winrt-error-l1-1-0.dll api-ms-win-core-libraryloader-l1-2-0.dll
api-ms-win-core-memory-l1-1-0.dll api-ms-win-core-processthreads-l1-1-0.dll
api-ms-win-core-synch-l1-1-0.dll api-ms-win-core-file-l1-1-0.dll
api-ms-win-core-heap-l1-1-0.dll api-ms-win-core-handle-l1-1-0.dll
api-ms-win-shcore-scaling-l1-1-1.dll api-ms-win-power-base-l1-1-0.dll
api-ms-win-core-realtime-l1-1-1.dll
""".split())

_MACHINES = {0x14C: "I386", 0x8664: "AMD64", 0xAA64: "ARM64"}
_NATIVE_SUFFIXES = {".exe", ".dll", ".pyd", ".drv", ".cpl"}


def _fail(code, message, package, path):
    raise DLLAuditError(code, message, package=package, path=path)


def _machine(value):
    if isinstance(value, int):
        return value
    aliases = {"X64": "AMD64", "X86_64": "AMD64", "WIN_AMD64": "AMD64", "X86": "I386"}
    value = aliases.get(str(value).upper(), str(value).upper())
    for number, name in _MACHINES.items():
        if value == name:
            return number
    raise ValueError("Unknown PE machine: " + str(value))


def read_pe_imports(path, *, expected_machine="AMD64", package=None):
    """Parse on any host; return {machine, imports, delay_imports}.

    RVA-based and legacy VA-based delay descriptors are supported. Truncated
    headers, unbacked RVAs, unterminated tables/names fail closed.
    """
    path = Path(path)
    try:
        target_machine = _machine(expected_machine)
        if target_machine not in _MACHINES:
            raise ValueError("Unsupported machine")
    except ValueError as exc:
        raise DLLAuditError("wrong_machine", "Unsupported target PE machine",
                            package=package, path=path) from exc
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DLLAuditError("pe_io", "Cannot read PE file", package=package, path=path) from exc

    def unpack(fmt, offset):
        size = struct.calcsize(fmt)
        if offset < 0 or offset + size > len(data):
            _fail("malformed_pe", "Truncated PE structure", package, path)
        return struct.unpack_from(fmt, data, offset)

    if data[:2] != b"MZ":
        _fail("malformed_pe", "Native file lacks DOS header", package, path)
    pe, = unpack("<I", 0x3C)
    if data[pe:pe + 4] != b"PE\0\0":
        _fail("malformed_pe", "Invalid PE signature", package, path)
    machine, count, _, _, _, opt_size, _ = unpack("<HHIIIHH", pe + 4)
    if machine not in _MACHINES or machine != target_machine:
        _fail("wrong_machine", "PE machine does not match bundle architecture", package, path)
    opt = pe + 24
    magic, = unpack("<H", opt)
    if magic not in (0x10B, 0x20B) or (machine == 0x14C) != (magic == 0x10B):
        _fail("malformed_pe", "Invalid PE optional-header architecture", package, path)
    dd_offset, number_offset = (112, 108) if magic == 0x20B else (96, 92)
    if opt_size < dd_offset or opt + opt_size > len(data):
        _fail("malformed_pe", "Truncated optional header", package, path)
    image_base, = unpack("<Q" if magic == 0x20B else "<I", opt + (24 if magic == 0x20B else 28))
    headers_size, = unpack("<I", opt + 60)
    if headers_size < opt + opt_size + count * 40 or headers_size > len(data):
        _fail("malformed_pe", "Invalid PE header extent", package, path)
    num_dirs, = unpack("<I", opt + number_offset)
    if num_dirs > (opt_size - dd_offset) // 8:
        _fail("malformed_pe", "Directory count exceeds optional header", package, path)
    sections = []
    for i in range(count):
        section = opt + opt_size + i * 40
        virtual_size, rva, raw_size, raw = unpack("<IIII", section + 8)
        unpack("<I", section + 36)
        if rva < headers_size or (raw_size and (raw < headers_size or raw + raw_size > len(data))):
            _fail("malformed_pe", "Unbacked/overlapping PE section", package, path)
        for old_rva, old_size, _, _ in sections:
            if max(rva, old_rva) < min(rva + max(virtual_size, raw_size), old_rva + old_size):
                _fail("malformed_pe", "Overlapping PE virtual sections", package, path)
        sections.append((rva, max(virtual_size, raw_size), raw, raw_size))

    def mapped(rva, size):
        if rva < 0 or size < 0:
            _fail("malformed_pe", "Invalid PE RVA", package, path)
        if rva < headers_size and rva + size <= min(headers_size, len(data)):
            return rva, min(headers_size, len(data))
        for start, span, raw, raw_size in sections:
            if start <= rva < start + span and rva - start + size <= raw_size:
                return raw + rva - start, raw + raw_size
        _fail("malformed_pe", "PE RVA is not file-backed", package, path)

    def name_at(rva):
        offset, end = mapped(rva, 1)
        nul = data.find(b"\0", offset, min(end, offset + 260))
        if nul < 0:
            _fail("malformed_pe", "Unterminated PE DLL name", package, path)
        try:
            name = data[offset:nul].decode("ascii")
        except UnicodeError:
            _fail("malformed_pe", "Non-ASCII PE DLL name", package, path)
        if (not name or any(c in name for c in '/\\:<>"|?*')
                or any(ord(c) < 32 for c in name) or name.endswith((".", " "))):
            _fail("unsafe_import", "DLL import is not a plain basename", package, path)
        if Path(name).suffix.casefold() not in {".dll", ".drv", ".cpl"}:
            _fail("unsafe_import", "DLL import has unexpected extension: " + name, package, path)
        return name.casefold()

    def table(index, delay=False):
        if index >= num_dirs:
            return []
        address, size = unpack("<II", opt + dd_offset + index * 8)
        if not address and not size:
            return []
        width = 32 if delay else 20
        if not address or size < width:
            _fail("malformed_pe", "Invalid PE import directory", package, path)
        offset, _ = mapped(address, size)
        names = []
        for pos in range(offset, offset + size - width + 1, width):
            values = unpack("<" + "I" * (width // 4), pos)
            if not any(values):
                return list(dict.fromkeys(names))
            if delay:
                attrs, name_rva = values[:2]
                if attrs not in (0, 1):
                    _fail("malformed_pe", "Unsupported delay import attributes", package, path)
                if not attrs:
                    name_rva -= image_base
            else:
                name_rva = values[3]
            names.append(name_at(name_rva))
        _fail("malformed_pe", "Unterminated PE import descriptor table", package, path)

    return {"machine": _MACHINES[machine], "imports": table(1), "delay_imports": table(13, True)}


def audit_dll_dependencies(bundle_root, *, roots=None, expected_machine="AMD64",
                           package=None, search_dirs=()):
    """Audit all native files or recursive closure starting at explicit roots.

    Resolution only uses importer directory, explicit bundle-relative search_dirs
    and bundle root. Multiple different same-name candidates are refused, rather
    than depending on developer loader search order. No basename-wide recursive
    search makes unrelated nested DLLs appear loadable. No PATH/system loading.
    """
    root = Path(os.path.abspath(bundle_root))
    try:
        target_machine = _machine(expected_machine)
        if target_machine not in _MACHINES:
            raise ValueError("Unsupported machine")
    except ValueError as exc:
        raise DLLAuditError("wrong_machine", "Unsupported target PE machine",
                            package=package, path=root) from exc
    if not root.is_dir():
        _fail("bundle_missing", "DLL bundle root is not a directory", package, root)
    index = {}
    for parent in (root, *root.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            _fail("bundle_reparse", "Bundle traverses link/reparse point", package, parent)
    def walk_error(error):
        raise DLLAuditError("bundle_io", "Cannot enumerate complete DLL bundle", package=package,
                            path=error.filename) from error

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        for name in dirs + files:
            path = Path(directory) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                _fail("bundle_reparse", "Bundle contains link/reparse point", package, path)
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                _fail("bundle_special", "Bundle contains special file", package, path)
            relative = path.relative_to(root).as_posix()
            key = relative.casefold()
            if key in index:
                _fail("case_collision", "Case-insensitive bundle path collision", package, relative)
            index[key] = path

    def scoped(value):
        path = Path(value)
        path = path if path.is_absolute() else root / path
        path = Path(os.path.abspath(path))
        try:
            path.relative_to(root)
        except ValueError:
            _fail("outside_bundle", "DLL search/root path outside bundle", package, value)
        return path

    directories = [scoped(value) for value in search_dirs]
    for directory in directories:
        if not directory.is_dir():
            _fail("search_directory_missing", "Explicit DLL search directory missing",
                  package, directory)
    if roots is None:
        queue = sorted((p for p in index.values()
                        if p.is_file() and p.suffix.casefold() in _NATIVE_SUFFIXES), key=str)
    else:
        queue = [scoped(value) for value in roots]
    if not queue:
        _fail("empty_native_bundle", "DLL audit found no native files to qualify", package, root)
    visited, records, os_imports = set(), [], set()
    while queue:
        path = queue.pop(0)
        key = path.relative_to(root).as_posix().casefold()
        path = index.get(key, path)
        if key in visited:
            continue
        visited.add(key)
        parsed = read_pe_imports(path, expected_machine=expected_machine, package=package)
        records.append({"path": path.relative_to(root).as_posix(), **parsed})
        for name in parsed["imports"] + parsed["delay_imports"]:
            matches = []
            for directory in [path.parent, *directories, root]:
                candidate_key = (directory / name).relative_to(root).as_posix().casefold()
                candidate = index.get(candidate_key)
                if candidate is not None and candidate.is_file() and candidate not in matches:
                    matches.append(candidate)
            if matches:
                if len(matches) > 1:
                    first = matches[0].read_bytes()
                    if any(candidate.read_bytes() != first for candidate in matches[1:]):
                        _fail("ambiguous_import",
                              "Multiple different bundled DLL candidates: " + name, package, path)
                queue.extend(matches)
            elif name in WINDOWS_OS_DLLS:
                os_imports.add(name)
            else:
                _fail("unresolved_import", "Unresolved non-OS DLL import: " + name, package, path)
    return {"machine": _MACHINES[target_machine],
            "files": sorted(records, key=lambda entry: entry["path"].casefold()),
            "os_imports": sorted(os_imports)}
