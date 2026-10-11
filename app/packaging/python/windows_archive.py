"""Fail-closed zip/tar.gz extraction under Windows filename semantics.

The whole member list and destination are checked before mkdir/open. Only plain
files/directories are materialized, never archive permission bits or links. Use
an absent/empty private stage: this is not a merge extractor and does not protect
against another process concurrently replacing destination directories.
"""
import os
import re
import shutil
import stat
import struct
import tarfile
import zipfile
from contextlib import contextmanager
from pathlib import Path


class ArchiveSafetyError(ValueError):
    def __init__(self, code, message, *, package=None, path=None):
        self.code, self.package, self.path = code, package, str(path) if path is not None else None
        super().__init__(message)

    def as_dict(self):
        return {"code": self.code, "package": self.package, "path": self.path,
                "message": str(self)}


_DEVICE = re.compile(
    r"^(?:con|prn|aux|nul|clock\$|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])$", re.I)
_REPARSE_POINT = 0x400


def _fail(code, message, package, path):
    raise ArchiveSafetyError(code, message, package=package, path=path)


def validate_windows_path(name, *, package=None):
    """Return a relative slash path, refusing Windows aliases and traversal."""
    if not isinstance(name, str) or not name:
        _fail("unsafe_path", "Empty or non-text archive path", package, name)
    path = name.replace("\\", "/")
    if path.startswith("/") or re.match(r"^[a-zA-Z]:", path):
        _fail("absolute_path", "Absolute, drive or UNC archive path", package, name)
    path = path[:-1] if path.endswith("/") else path
    parts = path.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            _fail("path_traversal", "Empty, dot or traversal path component", package, name)
        if ":" in part:
            _fail("alternate_data_stream", "Colon/alternate data stream in archive path",
                  package, name)
        if part.endswith((".", " ")):
            _fail("path_alias", "Trailing dot or space aliases a Windows destination",
                  package, name)
        if any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF
               or c in '<>"|?*' for c in part):
            _fail("unsafe_path", "Invalid Windows filename character", package, name)
        if _DEVICE.fullmatch(part.split(".", 1)[0].rstrip(" ")):
            _fail("reserved_device", "Reserved Windows device filename", package, name)
    return "/".join(parts)


@contextmanager
def _open_archive(archive, package):
    archive = Path(archive)
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as opened:
                yield "zip", opened
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive, "r:gz") as opened:
                yield "tar", opened
        else:
            _fail("archive_format", "Expected zip/wheel or tar.gz archive", package, archive)
    except ArchiveSafetyError:
        raise
    except (OSError, EOFError, tarfile.TarError, zipfile.BadZipFile,
            RuntimeError, NotImplementedError) as exc:
        raise ArchiveSafetyError("archive_format", "Unreadable or unsupported archive",
                                 package=package, path=archive) from exc


def _plan(kind, opened, *, package, expected_root):
    root = (validate_windows_path(expected_root, package=package)
            if expected_root is not None else None)
    entries, seen, components = [], {}, {}
    members = opened.infolist() if kind == "zip" else opened.getmembers()
    for member in members:
        name = member.filename if kind == "zip" else member.name
        path = validate_windows_path(name, package=package)
        if root is not None and path != root and not path.startswith(root + "/"):
            _fail("unexpected_layout", "Archive member lies outside expected root", package, name)
        if kind == "zip":
            if member.orig_filename != name:
                _fail("unsafe_path", "NUL-truncated ZIP filename", package, member.orig_filename)
            mode = member.external_attr >> 16
            filetype = stat.S_IFMT(mode)
            is_dir = member.is_dir() or bool(member.external_attr & 0x10)
            if member.external_attr & _REPARSE_POINT:
                _fail("reparse_point", "ZIP reparse-point member", package, name)
            if filetype not in (0, stat.S_IFREG, stat.S_IFDIR):
                _fail("link_or_special", "ZIP link or special-file member", package, name)
            if filetype == stat.S_IFDIR:
                is_dir = True
            if is_dir and (member.file_size or filetype == stat.S_IFREG):
                _fail("member_type", "Conflicting ZIP directory metadata", package, name)
            if member.flag_bits & 1:
                _fail("encrypted_archive", "Encrypted ZIP member", package, name)
            if member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED,
                                             zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
                _fail("archive_format", "Unsupported ZIP compression", package, name)
            # Older Unix ZIP encodings can carry a link target/type solely in
            # extra fields, even when the central directory looks ordinary.
            extra = member.extra
            while extra:
                if len(extra) < 4:
                    _fail("archive_format", "Truncated ZIP extra field", package, name)
                tag, length = struct.unpack_from("<HH", extra)
                if length > len(extra) - 4:
                    _fail("archive_format", "Truncated ZIP extra payload", package, name)
                payload, extra = extra[4:4 + length], extra[4 + length:]
                if tag == 0x000D and length > 12:
                    _fail("link_or_special", "PKWARE Unix ZIP link/device payload", package, name)
                if tag == 0x756E:  # ASi Unix: CRC32, mode, size/device, uid, gid, target.
                    if length < 14:
                        _fail("archive_format", "Truncated ASi Unix ZIP metadata", package, name)
                    asi_mode, = struct.unpack_from("<H", payload, 4)
                    if stat.S_IFMT(asi_mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or length > 14:
                        _fail("link_or_special", "ASi Unix ZIP link/device payload", package, name)
        else:
            is_dir = member.isdir()
            if not (is_dir or member.isreg()) or member.issparse() or member.linkname:
                _fail("link_or_special", "TAR link, sparse or special-file member", package, name)
        key = path.casefold()
        if key in seen:
            _fail("duplicate_destination" if seen[key][0] == path else "case_collision",
                  "Duplicate or case-insensitive archive destination", package, name)
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            component = "/".join(parts[:i])
            canonical = component.casefold()
            if canonical in components and components[canonical] != component:
                _fail("case_collision", "Case alias in archive directory tree", package, name)
            components[canonical] = component
        seen[key] = (path, is_dir)
        entries.append((member, path, is_dir))
    for _, path, is_dir in entries:
        parts = path.split("/")
        for i in range(1, len(parts)):
            ancestor = seen.get("/".join(parts[:i]).casefold())
            if ancestor is not None and not ancestor[1]:
                _fail("destination_conflict", "File used as an archive directory", package, path)
        if root is not None and path == root and not is_dir:
            _fail("unexpected_layout", "Expected archive root is a file", package, path)
    if root is not None and not entries:
        _fail("unexpected_layout", "Expected root absent from empty archive", package, root)
    if kind == "zip":
        # Validate *every* local header as well as the central directory before
        # writing. ZipFile.open checks filename drift, overlaps and local flags;
        # the content is not decompressed here (CRC/I/O remains extraction-time).
        for member, path, _ in entries:
            try:
                with opened.open(member):
                    pass
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
                raise ArchiveSafetyError("archive_format",
                                         "Unsafe or inconsistent ZIP local header",
                                         package=package, path=path) from exc
    return entries


def preflight_archive(archive, *, package=None, expected_root=None):
    """Check every member; return all normalized relative destinations."""
    with _open_archive(archive, package) as (kind, opened):
        plan = _plan(kind, opened, package=package, expected_root=expected_root)
        return tuple(path for _, path, _ in plan)


def _check_destination(destination, package):
    destination = Path(os.path.abspath(destination))
    for path in reversed((destination, *destination.parents)):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
            _fail("destination_reparse", "Destination traverses link/reparse point", package, path)
        if not stat.S_ISDIR(info.st_mode):
            _fail("destination_conflict", "Destination ancestor is not an ordinary directory",
                  package, path)
    if destination.exists() and any(destination.iterdir()):
        _fail("destination_not_empty", "Extraction refuses to merge into an existing tree",
              package, destination)
    return destination


def extract_archive(archive, destination, *, package=None, expected_root=None):
    """Preflight all members before writes, then extract to a private empty stage.

    Returns normalized file destinations (directories excluded). Content/I/O
    failures may leave a partial private stage; callers must never publish it.
    """
    with _open_archive(archive, package) as (kind, opened):
        entries = _plan(kind, opened, package=package, expected_root=expected_root)
        destination = _check_destination(destination, package)
        destination.mkdir(parents=True, exist_ok=True)
        files = []
        for member, relative, is_dir in entries:
            target = destination.joinpath(*relative.split("/"))
            # A failed write is the destination's problem (Windows' 260-character path limit,
            # permissions), not an unreadable archive, so it's reported with its path.
            try:
                if is_dir:
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = opened.open(member) if kind == "zip" else opened.extractfile(member)
                if source is None:
                    _fail("member_type", "Archive file has no content stream", package, relative)
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
            except OSError as exc:
                raise ArchiveSafetyError(
                    "extract_io", f"Couldn't write {target} ({len(str(target))} characters): "
                    f"{exc.strerror or exc}", package=package, path=relative) from exc
            files.append(relative)
        return tuple(files)
