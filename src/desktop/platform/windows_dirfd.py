"""Windows: the ``os`` calls ``apply_patch`` makes, over held handles (phase 3 plan C4).

``apply_plan`` is Odin's transaction, unchanged. On Linux it works through
directory descriptors: ``openat`` without following links, ``renameat2`` that
never replaces, ``fstat`` identities. A patch on this computer runs in a child
process of its own, where :class:`WindowsOs` stands in for the ``os`` module of
``apply_patch`` and gives those calls their meaning on Windows:

* A directory descriptor holds its folder open without delete sharing, so no
  one can rename or remove it while the patch runs. The root holds every folder
  above it the same way, from the volume down. A path below a held folder
  therefore names the same objects throughout, as a descriptor would.
* Folders the patch created itself are held with delete access, so the patch
  can still publish them under their final name and roll them back.
* No-follow opens refuse reparse points (symbolic links and junctions).
  Names are single components that Windows takes as written: no separators,
  streams, devices, wildcards or trailing dots and spaces.
* Renames never replace, and deletes take the name away at once (POSIX
  semantics, NTFS). Directory flushes are the journal's.
* Owner-only modes are privacy: entries created with one get a private DACL as they are
  created, and ``fchmod`` to one makes the entry private by its handle. An original keeps
  its descriptor exactly (bytes, not text: conditional entries and protected inherited ones
  survive), and a later ``fchmod`` sets that back as it was. Other mode bits have no Windows
  meaning: an entry this run made takes the folder's inherited ACL, as a new file would.
* A retained artifact that can't be inspected or made private is reported as such with the
  rollback, never raised over it, and never called private.
* An entry this run put in place (created, or renamed there) is remembered by its path: a
  later look at that name that is refused (not "absent") answers with what was put there,
  so the transaction's bookkeeping never loses an entry it just moved.
"""
from __future__ import annotations

import contextlib
import ctypes
import errno
import msvcrt
import ntpath
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from . import win32
from .windows_files import canonical, same_object

_DIRECTORY_ACCESS = (win32.FILE_LIST_DIRECTORY | win32.FILE_TRAVERSE | win32.FILE_READ_ATTRIBUTES
                     | win32.READ_CONTROL | win32.SYNCHRONIZE)
_HELD_SHARE = win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE  # never delete: nothing moves
_ALL_SHARE = win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE | win32.FILE_SHARE_DELETE
_NO_FOLLOW = win32.FILE_FLAG_OPEN_REPARSE_POINT | win32.FILE_FLAG_BACKUP_SEMANTICS
_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]|[. ]$')
_DEVICES = re.compile(r"(?i)(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(COM|LPT)[0-9¹²³])(\..*)?")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")

def _private(mode: int) -> bool:
    return not mode & 0o077


def _identity(handle) -> tuple[int, int, int]:
    info = win32.file_information(handle)
    return info.dwVolumeSerialNumber, info.nFileIndexHigh, info.nFileIndexLow


def _saved_dacl(handle) -> bytes:
    """The object's DACL as a self-relative descriptor, its control bits included."""
    descriptor = win32.PVOID()
    status = win32.GetSecurityInfo(handle, win32.SE_FILE_OBJECT, win32.DACL_SECURITY_INFORMATION,
                                   None, None, None, None, ctypes.byref(descriptor))
    if status:
        raise win32.error(status)
    try:
        return ctypes.string_at(descriptor, win32.GetSecurityDescriptorLength(descriptor))
    finally:
        win32.LocalFree(descriptor)


def _restore_saved(handle, saved: bytes) -> None:
    """Exactly the DACL ``saved`` holds, protection included: set as given, with no
    inheritance worked out again (the folder above is the one it was saved under)."""
    buffer = ctypes.create_string_buffer(saved, len(saved))
    win32.check(win32.SetKernelObjectSecurity(handle, win32.DACL_SECURITY_INFORMATION, buffer))


def _inherit(handle) -> None:
    """The folder's inherited ACL alone, as a new entry there would have."""
    with win32.SecurityDescriptor("D:") as descriptor:
        status = win32.SetSecurityInfo(
            handle, win32.SE_FILE_OBJECT,
            win32.DACL_SECURITY_INFORMATION | win32.UNPROTECTED_DACL_SECURITY_INFORMATION,
            None, None, descriptor.dacl(), None)
    if status:
        raise win32.error(status)


def _key(path) -> str:
    return ntpath.normcase(str(path))


def _lstat_fd(fd: int, link: bool):
    """``lstat`` of the entry ``fd`` holds: a reparse point reports itself as a link."""
    info = os.fstat(fd)
    if not link:
        return info
    return LinkStat(stat.S_IFLNK | (info.st_mode & 0o777), info.st_ino, info.st_dev,
                    info.st_nlink, 0, 0, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextlib.contextmanager
def _private_attributes(mode: int):
    """Security attributes that make a new entry private as it is created, for owner-only
    modes; otherwise none (the folder's inherited ACL)."""
    if not _private(mode):
        yield None
        return
    with win32.SecurityDescriptor(win32.PRIVATE_SDDL) as descriptor:
        yield descriptor.attributes()


def _name(name: str) -> str:
    """A single component Windows will use exactly as written."""
    if (not isinstance(name, str) or name in {"", ".", ".."} or _BAD_NAME.search(name)
            or _DEVICES.fullmatch(name)):
        raise OSError(errno.EINVAL, "this name can't be used as written on Windows", name)
    return name


def _is_link(handle) -> bool:
    return bool(win32.attribute_tag(handle).FileAttributes & win32.FILE_ATTRIBUTE_REPARSE_POINT)


def _is_directory(handle) -> bool:
    return bool(win32.attribute_tag(handle).FileAttributes & win32.FILE_ATTRIBUTE_DIRECTORY)


@dataclass(frozen=True)
class LinkStat:
    """What ``lstat`` reports for a reparse point: a link, never its target."""

    st_mode: int
    st_ino: int
    st_dev: int
    st_nlink: int
    st_uid: int
    st_gid: int
    st_size: int
    st_mtime_ns: int
    st_ctime_ns: int


class WindowsOs:
    """``apply_patch``'s ``os`` for one patch run, in the run's own process."""

    O_RDONLY = os.O_RDONLY
    O_RDWR = os.O_RDWR
    O_CREAT = os.O_CREAT
    O_EXCL = os.O_EXCL
    # Bits Windows' os lacks; only this class reads them.
    O_NONBLOCK = 0x0800_0000
    O_DIRECTORY = 0x1000_0000
    O_NOFOLLOW = 0x2000_0000
    O_CLOEXEC = 0x4000_0000
    SEEK_SET = os.SEEK_SET
    stat_result = os.stat_result
    read = staticmethod(os.read)
    write = staticmethod(os.write)
    lseek = staticmethod(os.lseek)
    fsencode = staticmethod(os.fsencode)
    strerror = staticmethod(os.strerror)

    def __init__(self) -> None:
        self._folders: dict[int, Path] = {}  # directory descriptor -> the folder it holds
        self._chains: dict[int, list[int]] = {}  # root descriptor -> the folders above it
        self._created: set[str] = set()  # folders this run made, by normalized path
        self._original_security: dict[tuple[int, int, int], bytes] = {}  # entry -> DACL before
        self._made: set[tuple[int, int, int]] = set()  # files this run created
        self._placed: dict[str, object] = {}  # path -> lstat of what this run put there
        # Retained artifacts whose privacy isn't verified, with why: (label, reason).
        self.unverified: list[tuple[str, str]] = []

    # --- Paths -------------------------------------------------------------------------------

    def folder(self, fd: int) -> Path:
        try:
            return self._folders[fd]
        except KeyError:
            raise OSError(errno.EBADF, "not a held folder") from None

    def _path(self, name, dir_fd) -> Path:
        if dir_fd is None:
            raise OSError(errno.EINVAL, "apply_patch names entries relative to a held folder")
        return self.folder(dir_fd) / _name(name)

    def _held(self, path: Path) -> int | None:
        key = ntpath.normcase(str(path))
        for fd, folder in self._folders.items():
            if ntpath.normcase(str(folder)) == key:
                return fd
        return None

    # --- Opening -----------------------------------------------------------------------------

    def _hold_folder(self, path: Path, *, deletable: bool) -> int:
        # A folder this run made may also be published and given its final ACL.
        access = _DIRECTORY_ACCESS | (win32.DELETE | win32.WRITE_DAC if deletable else 0)
        handle = win32.create_file(path, access, _HELD_SHARE, win32.OPEN_EXISTING, _NO_FOLLOW)
        try:
            if _is_link(handle):
                raise OSError(errno.ELOOP, "a link is refused", str(path))
            if not _is_directory(handle):
                raise NotADirectoryError(errno.ENOTDIR, "not a folder", str(path))
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
        except BaseException:
            win32.close(handle)
            raise
        self._folders[fd] = path
        return fd

    def _open_root(self, path, flags) -> int:
        """The root, held with every folder above it, from the volume down."""
        if not isinstance(path, str) or not _WINDOWS_ABSOLUTE.match(path):
            raise OSError(errno.EINVAL, "the root must be an absolute local path", str(path))
        admitted = None
        if flags & self.O_NOFOLLOW:
            # Held, without delete sharing and with data access (attribute-only handles
            # don't count in sharing checks), until the root below is held: nothing can
            # rename or replace the admitted folder meanwhile, and the root must be it.
            admitted = win32.create_file(path, _DIRECTORY_ACCESS, _HELD_SHARE,
                                         win32.OPEN_EXISTING, _NO_FOLLOW)
            if _is_link(admitted):
                win32.close(admitted)
                raise OSError(errno.ELOOP, "a link is refused", path)
        chain: list[int] = []
        try:
            resolved = canonical(path)  # local fixed drives only, resolved once
            current = Path(resolved.parts[0])
            for name in resolved.parts[1:]:
                handle = win32.create_file(current, _DIRECTORY_ACCESS, _HELD_SHARE,
                                           win32.OPEN_EXISTING, _NO_FOLLOW)
                chain.append(handle)
                if _is_link(handle):
                    raise OSError(errno.ELOOP, "a link is refused", str(current))
                current = current / name
            fd = self._hold_folder(current, deletable=False)
            handle = msvcrt.get_osfhandle(fd)
            problem = None
            if win32.volume_filesystem(handle) != "NTFS":
                # Renames that never replace and deletes that take the name at once.
                problem = OSError(errno.EOPNOTSUPP, "apply_patch on Windows needs an NTFS volume",
                                  path)
            elif (ntpath.normcase(win32.final_path(handle)) != ntpath.normcase(str(resolved))
                    or (admitted is not None and not same_object(admitted, handle))):
                problem = OSError(errno.ESTALE, "the root changed while it was being held", path)
            if problem is not None:
                self.close(fd)
                raise problem
        except BaseException:
            for handle in chain:
                win32.close(handle)
            raise
        finally:
            if admitted is not None:
                win32.close(admitted)
        self._chains[fd] = chain
        return fd

    def open(self, path, flags, mode=0o777, *, dir_fd=None) -> int:
        if dir_fd is None:
            if not flags & self.O_DIRECTORY:
                raise OSError(errno.EINVAL, "only the root is opened by its full path", str(path))
            return self._open_root(path, flags)
        target = self._path(path, dir_fd)
        if flags & self.O_DIRECTORY:
            return self._hold_folder(target,
                                     deletable=ntpath.normcase(str(target)) in self._created)
        writing = flags & (os.O_WRONLY | os.O_RDWR)
        access = win32.GENERIC_READ | win32.FILE_READ_ATTRIBUTES | (
            win32.GENERIC_WRITE if writing else 0)
        if flags & self.O_CREAT:
            disposition = win32.CREATE_NEW if flags & self.O_EXCL else win32.OPEN_ALWAYS
            access |= win32.READ_CONTROL | win32.WRITE_DAC  # its creator sets its final ACL
        else:
            disposition = win32.OPEN_EXISTING
        with _private_attributes(mode if flags & self.O_CREAT else 0o777) as attributes:
            handle = win32.create_file(target, access, _ALL_SHARE, disposition,
                                       win32.FILE_FLAG_OPEN_REPARSE_POINT
                                       | win32.FILE_ATTRIBUTE_NORMAL, attributes)
        try:
            if _is_link(handle):
                raise OSError(errno.ELOOP, "a link is refused", str(target))
            created = flags & self.O_CREAT and flags & self.O_EXCL
            if created:
                self._made.add(_identity(handle))
            fd = msvcrt.open_osfhandle(handle, os.O_RDWR if writing else os.O_RDONLY)
        except BaseException:
            win32.close(handle)
            raise
        if created:
            self._placed[_key(target)] = os.fstat(fd)
        return fd

    # --- Reading entries ---------------------------------------------------------------------

    def stat(self, path, *, dir_fd=None, follow_symlinks=True):
        """``lstat`` relative to a held folder; a reparse point reports itself as a link."""
        if follow_symlinks:
            raise OSError(errno.EINVAL, "apply_patch reads entries without following links")
        target = self._path(path, dir_fd)
        try:
            handle = win32.create_file(target, win32.FILE_READ_ATTRIBUTES, _ALL_SHARE,
                                       win32.OPEN_EXISTING, _NO_FOLLOW)
        except (FileNotFoundError, NotADirectoryError):
            self._placed.pop(_key(target), None)
            raise
        except OSError:
            # Refused, not absent: what this run put at this name is still what it put.
            known = self._placed.get(_key(target))
            if known is None:
                raise
            return known
        link = _is_link(handle)
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
        try:
            return _lstat_fd(fd, link)
        finally:
            os.close(fd)

    fstat = staticmethod(os.fstat)

    # --- Changing entries --------------------------------------------------------------------

    def mkdir(self, path, mode=0o777, *, dir_fd=None) -> None:
        target = self._path(path, dir_fd)
        with _private_attributes(mode) as attributes:
            if not win32.CreateDirectoryW(str(target), attributes):
                raise win32.error(filename=str(target))
        self._created.add(ntpath.normcase(str(target)))

    def _open_for_delete(self, target: Path, *, directory: bool) -> tuple[int, bool]:
        """A handle that may rename or delete ``target``: a held folder's own, or a new one."""
        if directory:
            held = self._held(target)
            if held is not None:
                return msvcrt.get_osfhandle(held), False
        handle = win32.create_file(target, win32.DELETE | win32.FILE_READ_ATTRIBUTES, _ALL_SHARE,
                                   win32.OPEN_EXISTING, _NO_FOLLOW)
        if _is_directory(handle) and not _is_link(handle) and not directory:
            win32.close(handle)
            raise IsADirectoryError(errno.EISDIR, "a folder where a file belongs", str(target))
        if directory and (_is_link(handle) or not _is_directory(handle)):
            win32.close(handle)
            raise NotADirectoryError(errno.ENOTDIR, "not a folder", str(target))
        return handle, True

    def _delete(self, path, dir_fd, *, directory: bool) -> None:
        target = self._path(path, dir_fd)
        handle, owned = self._open_for_delete(target, directory=directory)
        try:
            win32.delete_by_handle(handle)
        finally:
            if owned:
                win32.close(handle)
        self._placed.pop(_key(target), None)

    def rmdir(self, path, *, dir_fd=None) -> None:
        self._delete(path, dir_fd, directory=True)

    def unlink(self, path, *, dir_fd=None) -> None:
        self._delete(path, dir_fd, directory=False)

    def rename_noreplace(self, source, destination, *, src_dir_fd, dst_dir_fd) -> None:
        """Atomic, and never over an existing entry (``renameat2(RENAME_NOREPLACE)``)."""
        old = self._path(source, src_dir_fd)
        new = self._path(destination, dst_dir_fd)
        held = self._held(old)
        old_key, new_key = _key(old), _key(new)

        def moved(key: str) -> str:
            return new_key + key[len(old_key):]

        if held is not None:
            win32.rename_by_handle(msvcrt.get_osfhandle(held), new, replace=False)
            for fd, folder in list(self._folders.items()):  # the folder and what it holds
                if folder == old or old in folder.parents:
                    self._folders[fd] = new / folder.relative_to(old)
            inside = lambda key: key == old_key or key.startswith(old_key + "\\")  # noqa: E731
            self._created = {moved(key) if inside(key) else key for key in self._created}
            self._placed = {moved(key) if inside(key) else key: info
                            for key, info in self._placed.items()}
            self._placed[new_key] = os.fstat(held)
            return
        handle = win32.create_file(old, win32.DELETE | win32.FILE_READ_ATTRIBUTES, _ALL_SHARE,
                                   win32.OPEN_EXISTING, _NO_FOLLOW)
        try:
            link = _is_link(handle)
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)  # owns the handle from here
        except BaseException:
            win32.close(handle)
            raise
        try:
            win32.rename_by_handle(msvcrt.get_osfhandle(fd), new, replace=False)
            self._placed.pop(old_key, None)
            self._placed[new_key] = _lstat_fd(fd, link)
        finally:
            os.close(fd)

    def make_private(self, path, dir_fd) -> str | None:
        """Make a retained artifact private; why it couldn't be, or None."""
        try:
            target = self._path(path, dir_fd)
            handle = win32.create_file(target, win32.READ_CONTROL | win32.WRITE_DAC
                                       | win32.FILE_READ_ATTRIBUTES, _ALL_SHARE,
                                       win32.OPEN_EXISTING, _NO_FOLLOW)
            try:
                if _is_link(handle):
                    raise OSError(errno.ELOOP, "a link is refused", str(target))
                win32.set_private_dacl(handle)
            finally:
                win32.close(handle)
        except OSError as exc:
            return f"could not be made private: {type(exc).__name__}: {exc}"
        return None

    def chmod(self, path, mode, *, dir_fd=None, follow_symlinks=True) -> None:
        """An owner-only mode makes a retained artifact private (``apply_patch`` uses it for
        nothing else; in the child :func:`artifact_paths` stands in for its one caller)."""
        if follow_symlinks:
            raise OSError(errno.EINVAL, "apply_patch changes entries without following links")
        if _private(mode) and (problem := self.make_private(path, dir_fd)):
            self.unverified.append((str(path), problem))

    @contextlib.contextmanager
    def _security_handle(self, fd):
        """A handle that may change ``fd``'s DACL: a held folder's own, else the file reopened
        by its handle (no path is involved)."""
        handle = msvcrt.get_osfhandle(fd)
        if fd in self._folders:
            yield handle
            return
        reopened = win32.ReOpenFile(handle, win32.READ_CONTROL | win32.WRITE_DAC
                                    | win32.FILE_READ_ATTRIBUTES, _ALL_SHARE, 0)
        if reopened in (None, win32.INVALID_HANDLE_VALUE):
            raise win32.error()
        try:
            yield reopened
        finally:
            win32.close(reopened)

    def _made_here(self, fd, key) -> bool:
        folder = self._folders.get(fd)
        if folder is not None:
            return ntpath.normcase(str(folder)) in self._created
        return key in self._made

    def fchmod(self, fd, mode) -> None:
        """Owner-only: private, by the handle; an original remembers what it had. Any other
        mode gives an original back what it had, and gives an entry this run made the
        folder's inherited ACL, as a new file would have. Untouched entries keep theirs."""
        with self._security_handle(fd) as handle:
            key = _identity(handle)
            made = self._made_here(fd, key)
            if _private(mode):
                if not made:
                    self._original_security.setdefault(key, _saved_dacl(handle))
                win32.set_private_dacl(handle)
            elif key in self._original_security:
                _restore_saved(handle, self._original_security.pop(key))
            elif made:
                _inherit(handle)

    @staticmethod
    def fchown(fd, uid, gid) -> None:
        """Ownership stays the creating user's."""

    def fsync(self, fd) -> None:
        if fd not in self._folders:  # a folder's entries are the journal's to make durable
            os.fsync(fd)

    def close(self, fd) -> None:
        self._folders.pop(fd, None)
        try:
            os.close(fd)
        finally:
            for handle in self._chains.pop(fd, []):
                win32.close(handle)

    @staticmethod
    def geteuid() -> int:
        return 0  # what os.fstat reports for every owner on Windows

    getegid = geteuid


# --- In place of apply_patch.py's own (windows_patch.main installs them) ------------------------


def _shim() -> WindowsOs:
    from ...tools import apply_patch

    if not isinstance(apply_patch.os, WindowsOs):
        raise RuntimeError("apply_patch runs in a process of its own on Windows")
    return apply_patch.os


def rename_noreplace(source, destination, *, src_dir_fd, dst_dir_fd) -> None:
    """In place of ``_rename_noreplace``: a rename that never replaces, by handle."""
    _shim().rename_noreplace(source, destination, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)


def directory_registry_init(self, root_value, *, rename_noreplace) -> None:
    """In place of ``_DirectoryRegistry.__init__``: a local Windows root, held from its volume."""
    from ...tools.apply_patch import PatchError

    shim = _shim()
    if not isinstance(root_value, str) or not _WINDOWS_ABSOLUTE.match(root_value):
        raise PatchError("root must be an absolute path")
    flags = shim.O_RDONLY | shim.O_DIRECTORY | shim.O_CLOEXEC | shim.O_NOFOLLOW
    try:
        root_fd = shim.open(root_value, flags)
    except OSError as exc:
        raise PatchError(
            f"root must be an existing non-symlink directory: {type(exc).__name__}: {exc}"
        ) from exc
    self.root_value = root_value.rstrip("\\/") or root_value
    self._fds = {(): root_fd}
    self._flags = flags
    self._rename_noreplace = rename_noreplace
    self._created = []


def artifact_paths(prepared, stages) -> list[str]:
    """In place of ``_artifact_paths``: the retained artifacts now private. Every artifact
    name the run allocated is looked at, whatever its bookkeeping says (a name chosen at
    random holds nothing else). One that can't be inspected or made private is recorded with
    why, and left out of the private list, never raised over the rollback's own failures
    (Odin's order and file-only rule kept)."""
    from ...tools import apply_patch

    shim = _shim()
    paths: list[str] = []
    for artifact in [item["recovery"] for item in prepared if item.get("recovery") is not None]:
        _keep_private(shim, apply_patch, artifact, paths)
    for artifact in stages:
        _keep_private(shim, apply_patch, artifact, paths)
    return paths


def _keep_private(shim: WindowsOs, apply_patch, artifact, paths: list[str]) -> None:
    try:
        info = apply_patch._entry_info(artifact["parent_fd"], artifact["name"])
    except OSError as exc:
        shim.unverified.append(
            (artifact["label"], f"could not be inspected: {type(exc).__name__}: {exc}"))
        return
    if info is None or not stat.S_ISREG(info.st_mode):
        return
    if problem := shim.make_private(artifact["name"], artifact["parent_fd"]):
        shim.unverified.append((artifact["label"], problem))
    else:
        paths.append(artifact["label"])


def directory_registry_display(self, parent_label: str, name: str) -> str:
    """In place of ``_DirectoryRegistry.display``: the entry's path as Windows writes it."""
    relative = f"{parent_label}/{name}" if parent_label else name
    return f"{self.root_value}\\{relative.replace('/', chr(92))}"
