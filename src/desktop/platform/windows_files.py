"""Windows private storage: held folder chains, private files and publication barriers.

The contract (phase 2 plan, A2 and A5):

* **Held chain.** A path is resolved once to its final form (Windows' counterpart of
  Linux's ``realpath``), then every folder from the volume root down is opened and
  held without delete sharing. Each one is checked not to be a reparse point and to
  have an admitted owner. While the chain is held no component can be renamed,
  deleted or replaced, so a path under it names the held objects.
* **Volumes.** Private state lives on local fixed NTFS volumes only.
* **Private objects.** Our folders and files may grant access only to the user,
  OWNER RIGHTS, SYSTEM and Administrators. A null DACL, an allow entry for anyone
  else, or an entry type we can't read refuses. Our own namespace objects are
  repaired to the private descriptor when the user owns them, as Linux repairs 0700.
* **Barriers.** A Windows barrier flushes the object whose name changed, through a
  handle naming it. Microsoft documents that file-system metadata is cached and that a
  file must be flushed to store its metadata changes. This is recorded as a Windows
  platform delta, not as equivalence with a POSIX folder fsync, and not as a
  power-loss proof.
"""
from __future__ import annotations

import ctypes
import errno
import functools
import msvcrt
import ntpath
import os
import re
import secrets
import time
from contextlib import contextmanager
from pathlib import Path

from . import win32

_RENAME_RETRIES = 50
_RENAME_RETRY_SECONDS = 0.02


@functools.cache
def user_sid() -> str:
    return win32.current_user_sid()


@functools.cache
def own_sids() -> frozenset[str]:
    """Owners that mean "ours": the user, and the owner this process gives new objects.

    Linux compares ``st_uid`` with the effective uid. On Windows an elevated
    administrator's new objects are owned by the Administrators group, so that
    default owner counts as ours too; for an ordinary process both are the user.
    """
    return frozenset({user_sid(), win32.default_owner_sid()})


def _admitted() -> frozenset[str]:
    return frozenset({user_sid(), win32.OWNER_RIGHTS_SID, win32.SYSTEM_SID,
                      win32.ADMINISTRATORS_SID})


def _trusted_ancestor_owners() -> frozenset[str]:
    return frozenset({user_sid(), win32.SYSTEM_SID, win32.ADMINISTRATORS_SID,
                      win32.TRUSTED_INSTALLER_SID})


def dacl_is_private(security: win32.ObjectSecurity) -> bool:
    """True when nobody outside the admitted principals is granted anything.

    A null DACL grants everyone, so it is not private. A valid empty DACL grants
    nobody and is. Deny entries and inherit-only entries grant nothing on this
    object. Any other entry type fails closed.
    """
    if not security.dacl_present:
        return False
    admitted = _admitted()
    for kind, flags, mask, sid in security.aces:
        if kind == win32.ACCESS_DENIED_ACE_TYPE:
            continue
        if kind != win32.ACCESS_ALLOWED_ACE_TYPE:
            return False
        if flags & win32.INHERIT_ONLY_ACE or not mask:
            continue
        if sid not in admitted:
            return False
    return True


def _refuse(reason: str, path) -> PermissionError:
    return PermissionError(errno.EACCES, reason, str(path))


def canonical(path) -> Path:
    """Resolve once, then require an absolute local drive path."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in str(path)):
        raise ValueError("private paths must be absolute")
    resolved = os.path.realpath(path)
    if resolved.startswith("\\\\?\\") and resolved[5:6] == ":":
        resolved = resolved[4:]
    resolved = Path(resolved)
    drive = ntpath.splitdrive(str(resolved))[0]
    if len(drive) != 2 or drive[1] != ":":
        raise _refuse("private state needs a local fixed NTFS volume", resolved)
    return resolved


def _open_directory(path, *, repair: bool = False):
    access = win32.FILE_READ_ATTRIBUTES | win32.READ_CONTROL | win32.SYNCHRONIZE
    if repair:
        access |= win32.WRITE_DAC
    return win32.create_file(
        path, access, win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE, win32.OPEN_EXISTING,
        win32.FILE_FLAG_BACKUP_SEMANTICS | win32.FILE_FLAG_OPEN_REPARSE_POINT)


def _create_directory(path) -> None:
    with win32.SecurityDescriptor(win32.PRIVATE_SDDL) as descriptor:
        attributes = descriptor.attributes()
        if not win32.CreateDirectoryW(str(path), attributes):
            code = ctypes.get_last_error()
            if code != win32.ERROR_ALREADY_EXISTS:
                raise win32.error(code, path)


def _reparse_flags(directory: bool) -> int:
    flags = win32.FILE_FLAG_OPEN_REPARSE_POINT
    return flags | win32.FILE_FLAG_BACKUP_SEMANTICS if directory else flags


def same_object(first, second) -> bool:
    a, b = win32.file_information(first), win32.file_information(second)
    return ((a.dwVolumeSerialNumber, a.nFileIndexHigh, a.nFileIndexLow)
            == (b.dwVolumeSerialNumber, b.nFileIndexHigh, b.nFileIndexLow))


def _repair_dacl(held_handle, path, *, directory: bool) -> None:
    """Open a second handle with WRITE_DAC while the first keeps the object in place."""
    flags = _reparse_flags(directory)
    writer = win32.create_file(
        path, win32.FILE_READ_ATTRIBUTES | win32.READ_CONTROL | win32.WRITE_DAC,
        win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE | win32.FILE_SHARE_DELETE,
        win32.OPEN_EXISTING, flags)
    try:
        if not same_object(held_handle, writer):
            raise _refuse("private path changed while it was being repaired", path)
        win32.set_private_dacl(writer)
    finally:
        win32.close(writer)


def _verify_directory(handle, path, *, namespace: bool, kind: str) -> None:
    tag = win32.attribute_tag(handle)
    if tag.FileAttributes & win32.FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError(errno.ELOOP, "a link in a private path is refused", str(path))
    if not tag.FileAttributes & win32.FILE_ATTRIBUTE_DIRECTORY:
        raise NotADirectoryError(errno.ENOTDIR, "not a folder", str(path))
    security = win32.object_security(handle)
    if namespace:
        if security.owner in own_sids():
            if not dacl_is_private(security):
                _repair_dacl(handle, path, directory=True)
                if not dacl_is_private(win32.object_security(handle)):
                    raise _refuse(f"{kind} directory must be owner-private (0700)", path)
            return
        if security.owner in (win32.SYSTEM_SID, win32.ADMINISTRATORS_SID):
            return  # Usable, but not ours to repair (Linux: a root-owned folder).
        raise _refuse(f"foreign {kind} ancestor", path)
    if security.owner not in _trusted_ancestor_owners():
        raise _refuse(f"foreign {kind} ancestor", path)


class HeldChain:
    """Folder handles held from the volume root down to ``path``."""

    def __init__(self, path, *, create: bool = False, namespace=frozenset(), kind: str = "profile",
                 repair: bool = True):
        self.path = canonical(path)
        self.handles: list[int] = []
        try:
            parts = self.path.parts
            current = Path(parts[0])
            handle = _open_directory(current, repair=False)
            self.handles.append(handle)
            if (win32.volume_filesystem(handle) != "NTFS"
                    or win32.drive_type(parts[0]) != win32.DRIVE_FIXED):
                raise _refuse("private state needs a local fixed NTFS volume", current)
            for name in parts[1:]:
                current = current / name
                owned = repair and current in namespace
                try:
                    handle = _open_directory(current)
                except FileNotFoundError:
                    if not create:
                        raise
                    _create_directory(current)
                    handle = _open_directory(current)
                self.handles.append(handle)
                _verify_directory(handle, current, namespace=owned, kind=kind)
            final = win32.final_path(self.handles[-1])
            if ntpath.normcase(final) != ntpath.normcase(str(self.path)):
                raise _refuse(f"{kind} path changed while it was being held", self.path)
        except BaseException:
            self.close()
            raise

    @property
    def handle(self) -> int:
        return self.handles[-1]

    def child(self, name: str) -> Path:
        if not name or ntpath.basename(name) != name or name in {".", ".."}:
            raise ValueError("a private object name is a single path component")
        return self.path / name

    def close(self) -> None:
        while self.handles:
            win32.close(self.handles.pop())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@contextmanager
def held(path, **options):
    chain = HeldChain(path, **options)
    try:
        yield chain
    finally:
        chain.close()


_PROFILE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def namespace_of(path) -> frozenset[Path]:
    """Every folder from ``odin-desktop\\<profile>`` down is ours to keep private.

    Linux tightens only the ``odin-desktop`` and profile folders: a POSIX child is
    no more open than the private folder above it. A Windows child is checked
    against its own DACL, so each folder below the profile is kept private too.
    """
    parts = canonical(path).parts
    for index, name in enumerate(parts[:-1]):
        if name.lower() == "odin-desktop" and _PROFILE_COMPONENT.fullmatch(parts[index + 1]):
            return frozenset(Path(*parts[:end]) for end in range(index + 1, len(parts) + 1))
    return frozenset()


def private_directory(path, *, repair_namespace: bool = True) -> None:
    """The Windows ``paths.private_directory``: create missing folders private; check the rest."""
    resolved = canonical(path)
    namespace = namespace_of(resolved) if repair_namespace else frozenset()
    with held(resolved, create=True, namespace=namespace):
        pass


# --- Files ---------------------------------------------------------------------------------

def verify_file(handle, path, *, links: bool = True,
                owner_only: bool = True) -> win32.BY_HANDLE_FILE_INFORMATION:
    tag = win32.attribute_tag(handle)
    if tag.FileAttributes & win32.FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError(errno.ELOOP, "a link in a private path is refused", str(path))
    if tag.FileAttributes & win32.FILE_ATTRIBUTE_DIRECTORY:
        raise IsADirectoryError(errno.EISDIR, "a folder where a file belongs", str(path))
    info = win32.file_information(handle)
    if links and info.nNumberOfLinks != 1:
        raise _refuse("private file has other links", path)
    security = win32.object_security(handle)
    if owner_only and security.owner not in own_sids():
        raise _refuse("private state must be a regular owner-owned file", path)
    if not dacl_is_private(security):
        raise _refuse("private file is readable by others", path)
    return info


def open_file(chain: HeldChain, name: str, *, write: bool = False, create: bool = False,
              exclusive: bool = False, delete: bool = False, links: bool = True) -> int:
    """Open ``name`` inside the held folder and verify it through its handle."""
    path = chain.child(name)
    access = win32.GENERIC_READ | win32.READ_CONTROL | win32.FILE_READ_ATTRIBUTES
    if write:
        access |= win32.GENERIC_WRITE
    if delete:
        access |= win32.DELETE
    disposition = (win32.CREATE_NEW if exclusive else win32.OPEN_ALWAYS if create
                   else win32.OPEN_EXISTING)
    handle = win32.create_file(
        path, access, win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE | win32.FILE_SHARE_DELETE,
        disposition, win32.FILE_FLAG_OPEN_REPARSE_POINT | win32.FILE_ATTRIBUTE_NORMAL)
    try:
        verify_file(handle, path, links=links)
    except BaseException:
        win32.close(handle)
        raise
    return handle


def to_fd(handle: int, flags: int) -> int:
    """Hand ``handle`` to a C runtime descriptor, which then owns it."""
    try:
        return msvcrt.open_osfhandle(handle, flags)
    except BaseException:
        win32.close(handle)
        raise


def read_file(chain: HeldChain, name: str, *, limit: int | None = None) -> bytes:
    fd = to_fd(open_file(chain, name), os.O_RDONLY)
    with os.fdopen(fd, "rb") as stream:
        return stream.read() if limit is None else stream.read(limit)


def _rename(handle, name: str, *, replace: bool) -> None:
    """Rename by handle, retrying briefly while a reader holds the target without delete sharing."""
    for attempt in range(_RENAME_RETRIES):
        try:
            win32.rename_by_handle(handle, name, replace=replace)
            return
        except OSError as exc:
            if (exc.winerror not in (win32.ERROR_SHARING_VIOLATION, win32.ERROR_ACCESS_DENIED)
                    or attempt == _RENAME_RETRIES - 1):
                raise
            time.sleep(_RENAME_RETRY_SECONDS)


def _check_existing_target(chain: HeldChain, name: str) -> None:
    path = chain.child(name)
    try:
        handle = win32.create_file(
            path, win32.FILE_READ_ATTRIBUTES | win32.READ_CONTROL,
            win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE | win32.FILE_SHARE_DELETE,
            win32.OPEN_EXISTING, win32.FILE_FLAG_OPEN_REPARSE_POINT)
    except FileNotFoundError:
        return
    try:
        verify_file(handle, path, links=False)
    finally:
        win32.close(handle)


def publish(chain: HeldChain, name: str, data: bytes) -> bool:
    """Replace ``name`` with ``data``.

    Before the rename every failure leaves the old file and raises. After it the new
    content is committed and visible; the result says whether the final flush of the
    published file succeeded (durability proven) or not (committed, unproven).
    """
    _check_existing_target(chain, name)
    temporary = f".{name}.{secrets.token_hex(16)}.tmp"
    handle = win32.create_file(
        chain.child(temporary),
        win32.GENERIC_WRITE | win32.DELETE | win32.READ_CONTROL | win32.FILE_READ_ATTRIBUTES,
        win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE | win32.FILE_SHARE_DELETE, win32.CREATE_NEW,
        win32.FILE_FLAG_OPEN_REPARSE_POINT | win32.FILE_ATTRIBUTE_NORMAL)
    committed = False
    try:
        verify_file(handle, chain.child(temporary))
        win32.write_all(handle, data)
        win32.flush(handle)
        _rename(handle, name, replace=True)
        committed = True
        try:
            win32.flush(handle)
        except OSError:
            return False
        return True
    except BaseException:
        if not committed:
            try:
                win32.delete_by_handle(handle)
            except OSError:
                pass
        raise
    finally:
        win32.close(handle)


def flush_object(chain: HeldChain, name: str, *, links: bool = True) -> None:
    """The creation barrier: flush an existing file through a handle naming it."""
    handle = open_file(chain, name, write=True, links=links)
    try:
        win32.flush(handle)
    finally:
        win32.close(handle)


def remove(chain: HeldChain, name: str, *, missing_ok: bool = False) -> None:
    try:
        handle = open_file(chain, name, delete=True, links=False)
    except FileNotFoundError:
        if missing_ok:
            return
        raise
    try:
        win32.delete_by_handle(handle)
    finally:
        win32.close(handle)


def tombstone_pattern(name: str) -> re.Pattern[str]:
    return re.compile(re.escape(name) + r"\.retiring-[0-9a-f]{32}")


def tombstones(chain: HeldChain, name: str) -> list[str]:
    pattern = tombstone_pattern(name)
    return sorted(entry for entry in os.listdir(chain.path) if pattern.fullmatch(entry))


def retire(chain: HeldChain, name: str) -> str:
    """Durable removal: rename ``name`` by handle to a new tombstone, then flush that handle.

    The rename is the visible commit point: afterwards the name is gone and the
    tombstone exists. A failed flush raises and leaves the tombstone in place, where
    it still counts as the original's uncertain state.
    """
    handle = open_file(chain, name, write=True, delete=True, links=False)
    try:
        for _ in range(8):
            tombstone = f"{name}.retiring-{secrets.token_hex(16)}"
            try:
                _rename(handle, tombstone, replace=False)
                break
            except FileExistsError:
                continue
        else:
            raise FileExistsError(errno.EEXIST, "no free tombstone name", str(chain.child(name)))
        win32.flush(handle)
        return tombstone
    finally:
        win32.close(handle)


def ensure_private(chain: HeldChain, name: str, *, directory: bool = False) -> None:
    """Verify an existing object of ours, repairing its DACL when the user owns it."""
    path = chain.child(name)
    flags = _reparse_flags(directory)
    try:
        handle = win32.create_file(
            path, win32.FILE_READ_ATTRIBUTES | win32.READ_CONTROL,
            win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE, win32.OPEN_EXISTING, flags)
    except FileNotFoundError:
        return
    try:
        tag = win32.attribute_tag(handle)
        if tag.FileAttributes & win32.FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError(errno.ELOOP, "a link in a private path is refused", str(path))
        if bool(tag.FileAttributes & win32.FILE_ATTRIBUTE_DIRECTORY) != directory:
            raise _refuse("unexpected object type in private storage", path)
        security = win32.object_security(handle)
        if security.owner not in own_sids():
            raise _refuse("private state must be a regular owner-owned file", path)
        if not dacl_is_private(security):
            _repair_dacl(handle, path, directory=directory)
            if not dacl_is_private(win32.object_security(handle)):
                raise _refuse("private file is readable by others", path)
    finally:
        win32.close(handle)
