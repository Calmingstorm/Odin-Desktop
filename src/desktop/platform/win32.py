"""Windows API bindings for the Desktop engine (ctypes), imported only on Windows.

Every call is declared with exact argument and result types: handles are
pointer-sized and must never be truncated. Failures raise ``OSError`` built from
the Windows error code, so Python picks the usual subclass (for example
``FileNotFoundError`` or ``PermissionError``) and keeps ``winerror``.
"""
from __future__ import annotations

import ctypes
import errno
import sys
import uuid
from ctypes import wintypes

if sys.platform != "win32":  # pragma: no cover - callers import this only on Windows
    raise ImportError("the Windows API bindings load only on Windows")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")

HANDLE = wintypes.HANDLE
DWORD = wintypes.DWORD
BOOL = wintypes.BOOL
PVOID = ctypes.c_void_p
INVALID_HANDLE_VALUE = HANDLE(-1).value

# Access rights.
DELETE = 0x00010000
READ_CONTROL = 0x00020000
WRITE_DAC = 0x00040000
SYNCHRONIZE = 0x00100000
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_READ_ATTRIBUTES = 0x0080
FILE_LIST_DIRECTORY = 0x0001
FILE_TRAVERSE = 0x0020

# Sharing and creation.
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
FILE_SHARE_DELETE = 0x4
CREATE_NEW = 1
CREATE_ALWAYS = 2
OPEN_EXISTING = 3
OPEN_ALWAYS = 4

# Attributes and flags.
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000

# File information classes.
FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
FILE_DISPOSITION_INFO_EX_CLASS = 21
FILE_RENAME_INFO_EX_CLASS = 22
FILE_DISPOSITION_FLAG_DELETE = 0x1
FILE_DISPOSITION_FLAG_POSIX_SEMANTICS = 0x2
FILE_RENAME_FLAG_REPLACE_IF_EXISTS = 0x1
FILE_RENAME_FLAG_POSIX_SEMANTICS = 0x2

# Errors.
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_ACCESS_DENIED = 5
ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33
ERROR_FILE_EXISTS = 80
ERROR_ALREADY_EXISTS = 183
ERROR_NOT_FOUND = 1168

# Security.
TOKEN_QUERY = 0x0008
TOKEN_USER_CLASS = 1
TOKEN_OWNER_CLASS = 4
SE_FILE_OBJECT = 1
OWNER_SECURITY_INFORMATION = 0x1
DACL_SECURITY_INFORMATION = 0x4
PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
SDDL_REVISION_1 = 1
SE_DACL_PRESENT = 0x0004
SE_DACL_PROTECTED = 0x1000
ACCESS_ALLOWED_ACE_TYPE = 0
ACCESS_DENIED_ACE_TYPE = 1
INHERIT_ONLY_ACE = 0x08

# Volumes and locks.
DRIVE_FIXED = 3
LOCKFILE_FAIL_IMMEDIATELY = 0x1
LOCKFILE_EXCLUSIVE_LOCK = 0x2

CRYPTPROTECT_UI_FORBIDDEN = 0x1
SYSTEM_BOOT_ENVIRONMENT_INFORMATION_CLASS = 90


class SECURITY_ATTRIBUTES(ctypes.Structure):  # noqa: N801 - the Windows API's own name
    _fields_ = [("nLength", DWORD), ("lpSecurityDescriptor", PVOID), ("bInheritHandle", BOOL)]


class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):  # noqa: N801 - the Windows API's own name
    _fields_ = [
        ("dwFileAttributes", DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", DWORD),
        ("nFileSizeHigh", DWORD),
        ("nFileSizeLow", DWORD),
        ("nNumberOfLinks", DWORD),
        ("nFileIndexHigh", DWORD),
        ("nFileIndexLow", DWORD),
    ]


class FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):  # noqa: N801 - the Windows API's own name
    _fields_ = [("FileAttributes", DWORD), ("ReparseTag", DWORD)]


class FILE_DISPOSITION_INFO_EX(ctypes.Structure):  # noqa: N801 - the Windows API's own name
    _fields_ = [("Flags", DWORD)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", DWORD),
        ("OffsetHigh", DWORD),
        ("hEvent", HANDLE),
    ]


class DATA_BLOB(ctypes.Structure):  # noqa: N801 - the Windows API's own name
    _fields_ = [("cbData", DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class ACL_HEADER(ctypes.Structure):  # noqa: N801 - the Windows API's own name
    _fields_ = [("AclRevision", ctypes.c_ubyte), ("Sbz1", ctypes.c_ubyte),
                ("AclSize", wintypes.WORD), ("AceCount", wintypes.WORD), ("Sbz2", wintypes.WORD)]


class ACE_HEADER(ctypes.Structure):  # noqa: N801 - the Windows API's own name
    _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte),
                ("AceSize", wintypes.WORD)]


class ACCESS_ACE(ctypes.Structure):  # noqa: N801 - the Windows API's own name
    """The fixed part shared by allow and deny ACEs; the SID starts at SidStart."""

    _fields_ = [("Header", ACE_HEADER), ("Mask", DWORD), ("SidStart", DWORD)]


def _declare(function, argtypes, restype=BOOL):
    function.argtypes = argtypes
    function.restype = restype
    return function


GetCurrentProcess = _declare(kernel32.GetCurrentProcess, [], HANDLE)
CloseHandle = _declare(kernel32.CloseHandle, [HANDLE])
LocalFree = _declare(kernel32.LocalFree, [PVOID], PVOID)
CreateFileW = _declare(
    kernel32.CreateFileW,
    [wintypes.LPCWSTR, DWORD, DWORD, ctypes.POINTER(SECURITY_ATTRIBUTES), DWORD, DWORD, HANDLE],
    HANDLE,
)
CreateDirectoryW = _declare(
    kernel32.CreateDirectoryW, [wintypes.LPCWSTR, ctypes.POINTER(SECURITY_ATTRIBUTES)])
GetFileInformationByHandle = _declare(
    kernel32.GetFileInformationByHandle, [HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION)])
GetFileInformationByHandleEx = _declare(
    kernel32.GetFileInformationByHandleEx, [HANDLE, ctypes.c_int, PVOID, DWORD])
SetFileInformationByHandle = _declare(
    kernel32.SetFileInformationByHandle, [HANDLE, ctypes.c_int, PVOID, DWORD])
GetFinalPathNameByHandleW = _declare(
    kernel32.GetFinalPathNameByHandleW, [HANDLE, wintypes.LPWSTR, DWORD, DWORD], DWORD)
FlushFileBuffers = _declare(kernel32.FlushFileBuffers, [HANDLE])
WriteFile = _declare(
    kernel32.WriteFile,
    [HANDLE, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD), ctypes.POINTER(OVERLAPPED)])
GetVolumeInformationByHandleW = _declare(
    kernel32.GetVolumeInformationByHandleW,
    [HANDLE, wintypes.LPWSTR, DWORD, ctypes.POINTER(DWORD), ctypes.POINTER(DWORD),
     ctypes.POINTER(DWORD), wintypes.LPWSTR, DWORD],
)
GetDriveTypeW = _declare(kernel32.GetDriveTypeW, [wintypes.LPCWSTR], wintypes.UINT)
LockFileEx = _declare(
    kernel32.LockFileEx, [HANDLE, DWORD, DWORD, DWORD, DWORD, ctypes.POINTER(OVERLAPPED)])
UnlockFileEx = _declare(
    kernel32.UnlockFileEx, [HANDLE, DWORD, DWORD, DWORD, ctypes.POINTER(OVERLAPPED)])
OpenProcessToken = _declare(
    advapi32.OpenProcessToken, [HANDLE, DWORD, ctypes.POINTER(HANDLE)])
GetTokenInformation = _declare(
    advapi32.GetTokenInformation, [HANDLE, ctypes.c_int, PVOID, DWORD, ctypes.POINTER(DWORD)])
ConvertSidToStringSidW = _declare(
    advapi32.ConvertSidToStringSidW, [PVOID, ctypes.POINTER(wintypes.LPWSTR)])
ConvertStringSidToSidW = _declare(
    advapi32.ConvertStringSidToSidW, [wintypes.LPCWSTR, ctypes.POINTER(PVOID)])
ConvertStringSecurityDescriptorToSecurityDescriptorW = _declare(
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW,
    [wintypes.LPCWSTR, DWORD, ctypes.POINTER(PVOID), ctypes.POINTER(wintypes.ULONG)],
)
GetSecurityInfo = _declare(
    advapi32.GetSecurityInfo,
    [HANDLE, ctypes.c_int, DWORD, ctypes.POINTER(PVOID), ctypes.POINTER(PVOID),
     ctypes.POINTER(PVOID), ctypes.POINTER(PVOID), ctypes.POINTER(PVOID)],
    DWORD,
)
SetSecurityInfo = _declare(
    advapi32.SetSecurityInfo, [HANDLE, ctypes.c_int, DWORD, PVOID, PVOID, PVOID, PVOID], DWORD)
GetSecurityDescriptorDacl = _declare(
    advapi32.GetSecurityDescriptorDacl,
    [PVOID, ctypes.POINTER(BOOL), ctypes.POINTER(PVOID), ctypes.POINTER(BOOL)],
)
GetSecurityDescriptorControl = _declare(
    advapi32.GetSecurityDescriptorControl,
    [PVOID, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(DWORD)],
)
GetAce = _declare(advapi32.GetAce, [PVOID, DWORD, ctypes.POINTER(PVOID)])
IsValidSid = _declare(advapi32.IsValidSid, [PVOID])
CryptProtectData = _declare(
    crypt32.CryptProtectData,
    [ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB), PVOID, PVOID, DWORD,
     ctypes.POINTER(DATA_BLOB)],
)
CryptUnprotectData = _declare(
    crypt32.CryptUnprotectData,
    [ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DATA_BLOB), PVOID,
     PVOID, DWORD, ctypes.POINTER(DATA_BLOB)],
)
NtQuerySystemInformation = _declare(
    ntdll.NtQuerySystemInformation,
    [ctypes.c_int, PVOID, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)],
    ctypes.c_long,
)


def error(code: int | None = None, filename=None) -> OSError:
    """An ``OSError`` for a Windows error code; the subclass follows ``winerror``."""
    code = ctypes.get_last_error() if code is None else code
    return OSError(0, ctypes.FormatError(code).strip(), None if filename is None else str(filename),
                   code)


def check(result, filename=None):
    if not result:
        raise error(filename=filename)
    return result


def close(handle) -> None:
    if handle not in (None, 0, INVALID_HANDLE_VALUE):
        CloseHandle(handle)


def create_file(path, access, share, disposition, flags, attributes=None) -> int:
    """``CreateFileW``; raises on failure and returns a real handle."""
    handle = CreateFileW(str(path), access, share, attributes, disposition, flags, None)
    if handle in (None, INVALID_HANDLE_VALUE):
        raise error(filename=path)
    return handle


# --- Security identifiers and descriptors ---------------------------------------------------

SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
OWNER_RIGHTS_SID = "S-1-3-4"
TRUSTED_INSTALLER_SID = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
# Python's own os.mkdir(path, 0o700) descriptor on Windows: SYSTEM, Administrators and
# the owner, inherited by files and folders, with inheritance from above blocked.
PRIVATE_SDDL = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)"


def sid_string(sid) -> str:
    text = wintypes.LPWSTR()
    check(ConvertSidToStringSidW(sid, ctypes.byref(text)))
    try:
        return text.value
    finally:
        LocalFree(ctypes.cast(text, PVOID))


def _token_sid(information_class: int) -> str:
    token = HANDLE()
    check(OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)))
    try:
        needed = DWORD()
        GetTokenInformation(token, information_class, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value)
        check(GetTokenInformation(token, information_class, buffer, needed, ctypes.byref(needed)))
        # TOKEN_USER and TOKEN_OWNER both start with the SID pointer.
        sid = ctypes.cast(buffer, ctypes.POINTER(PVOID)).contents.value
        return sid_string(sid)
    finally:
        close(token.value)


def current_user_sid() -> str:
    """The SID string of this process's token user."""
    return _token_sid(TOKEN_USER_CLASS)


def default_owner_sid() -> str:
    """The owner given to objects this process creates.

    It is the user for an ordinary process. An elevated administrator's token
    usually names the Administrators group instead.
    """
    return _token_sid(TOKEN_OWNER_CLASS)


class SecurityDescriptor:
    """A self-relative descriptor from SDDL, freed with ``LocalFree``."""

    def __init__(self, sddl: str):
        self.pointer = PVOID()
        check(ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, SDDL_REVISION_1, ctypes.byref(self.pointer), None))

    def attributes(self) -> SECURITY_ATTRIBUTES:
        return SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), self.pointer, False)

    def dacl(self):
        present, defaulted, acl = BOOL(), BOOL(), PVOID()
        check(GetSecurityDescriptorDacl(self.pointer, ctypes.byref(present), ctypes.byref(acl),
                                        ctypes.byref(defaulted)))
        return acl if present.value else None

    def close(self) -> None:
        if self.pointer:
            LocalFree(self.pointer)
            self.pointer = PVOID()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class ObjectSecurity:
    """An object's owner and DACL as read from its handle."""

    __slots__ = ("owner", "dacl_present", "protected", "aces")

    def __init__(self, owner, dacl_present, protected, aces):
        self.owner = owner
        self.dacl_present = dacl_present
        self.protected = protected
        self.aces = aces  # tuple of (type, flags, mask, sid string or None)


def object_security(handle) -> ObjectSecurity:
    owner, dacl, descriptor = PVOID(), PVOID(), PVOID()
    status = GetSecurityInfo(
        handle, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
        ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
    if status:
        raise error(status)
    try:
        control, revision = wintypes.WORD(), DWORD()
        check(GetSecurityDescriptorControl(descriptor, ctypes.byref(control),
                                           ctypes.byref(revision)))
        present = bool(control.value & SE_DACL_PRESENT) and bool(dacl.value)
        aces = []
        if present:
            header = ctypes.cast(dacl, ctypes.POINTER(ACL_HEADER)).contents
            for index in range(header.AceCount):
                ace = PVOID()
                check(GetAce(dacl, index, ctypes.byref(ace)))
                ace_header = ctypes.cast(ace, ctypes.POINTER(ACE_HEADER)).contents
                if ace_header.AceType in (ACCESS_ALLOWED_ACE_TYPE, ACCESS_DENIED_ACE_TYPE):
                    fixed = ctypes.cast(ace, ctypes.POINTER(ACCESS_ACE)).contents
                    sid = ace.value + ACCESS_ACE.SidStart.offset
                    if not IsValidSid(sid):
                        raise error(ERROR_ACCESS_DENIED)
                    aces.append((ace_header.AceType, ace_header.AceFlags, fixed.Mask,
                                 sid_string(sid)))
                else:
                    aces.append((ace_header.AceType, ace_header.AceFlags, None, None))
        return ObjectSecurity(sid_string(owner), present,
                              bool(control.value & SE_DACL_PROTECTED), tuple(aces))
    finally:
        LocalFree(descriptor)


def set_private_dacl(handle) -> None:
    """Replace the object's DACL with the private descriptor's, protected from inheritance."""
    with SecurityDescriptor(PRIVATE_SDDL) as descriptor:
        status = SetSecurityInfo(
            handle, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, descriptor.dacl(), None)
    if status:
        raise error(status)


# --- Files and volumes ----------------------------------------------------------------------

def file_information(handle) -> BY_HANDLE_FILE_INFORMATION:
    info = BY_HANDLE_FILE_INFORMATION()
    check(GetFileInformationByHandle(handle, ctypes.byref(info)))
    return info


def attribute_tag(handle) -> FILE_ATTRIBUTE_TAG_INFO:
    info = FILE_ATTRIBUTE_TAG_INFO()
    check(GetFileInformationByHandleEx(handle, FILE_ATTRIBUTE_TAG_INFO_CLASS, ctypes.byref(info),
                                       ctypes.sizeof(info)))
    return info


def final_path(handle) -> str:
    """The handle's normalized DOS path, without the ``\\\\?\\`` prefix for drive paths."""
    size = 512
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        length = GetFinalPathNameByHandleW(handle, buffer, size, 0)
        if not length:
            raise error()
        if length < size:
            value = buffer.value
            break
        size = length + 1
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\") and len(value) > 6 and value[5] == ":":
        return value[4:]
    return value


def volume_filesystem(handle) -> str:
    name = ctypes.create_unicode_buffer(64)
    check(GetVolumeInformationByHandleW(handle, None, 0, None, None, None, name, 64))
    return name.value


def drive_type(root: str) -> int:
    return GetDriveTypeW(root)


def flush(handle) -> None:
    check(FlushFileBuffers(handle))


def write_all(handle, data: bytes) -> None:
    view = memoryview(data)
    while view:
        chunk = bytes(view[:1 << 20])
        written = DWORD()
        check(WriteFile(handle, chunk, len(chunk), ctypes.byref(written), None))
        if written.value <= 0:
            raise error(ERROR_ACCESS_DENIED)
        view = view[written.value:]


def rename_by_handle(handle, new_name: str, *, replace: bool) -> None:
    """Rename the open file within its own folder (``new_name`` is a leaf name)."""
    encoded = new_name.encode("utf-16-le")
    # FILE_RENAME_INFO: a DWORD of flags (padded to the handle's alignment), the root
    # directory handle (NULL: same folder), the name's byte length, then the name.
    offset = ctypes.sizeof(ctypes.c_void_p) * 2 + ctypes.sizeof(DWORD)
    # Room for the terminating null and the structure's own trailing padding.
    size = offset + len(encoded) + 8
    buffer = ctypes.create_string_buffer(size)
    flags = FILE_RENAME_FLAG_POSIX_SEMANTICS
    if replace:
        flags |= FILE_RENAME_FLAG_REPLACE_IF_EXISTS
    ctypes.memmove(buffer, DWORD(flags).value.to_bytes(4, "little"), 4)
    ctypes.memmove(ctypes.addressof(buffer) + offset - ctypes.sizeof(DWORD),
                   len(encoded).to_bytes(4, "little"), 4)
    ctypes.memmove(ctypes.addressof(buffer) + offset, encoded, len(encoded))
    check(SetFileInformationByHandle(handle, FILE_RENAME_INFO_EX_CLASS, buffer, size), new_name)


def delete_by_handle(handle) -> None:
    info = FILE_DISPOSITION_INFO_EX(
        FILE_DISPOSITION_FLAG_DELETE | FILE_DISPOSITION_FLAG_POSIX_SEMANTICS)
    check(SetFileInformationByHandle(handle, FILE_DISPOSITION_INFO_EX_CLASS, ctypes.byref(info),
                                     ctypes.sizeof(info)))


# --- Locks ----------------------------------------------------------------------------------

# Windows byte-range locks are mandatory. Locking one byte far beyond any real data
# excludes other lockers without ever blocking the file's own reads or writes.
LOCK_OFFSET_HIGH = 0x7FFFFFFF


def lock(handle, *, blocking: bool) -> None:
    overlapped = OVERLAPPED(0, 0, 0, LOCK_OFFSET_HIGH, None)
    flags = LOCKFILE_EXCLUSIVE_LOCK | (0 if blocking else LOCKFILE_FAIL_IMMEDIATELY)
    if not LockFileEx(handle, flags, 0, 1, 0, ctypes.byref(overlapped)):
        code = ctypes.get_last_error()
        if code == ERROR_LOCK_VIOLATION and not blocking:
            raise BlockingIOError(errno.EAGAIN, "the lock is held by another owner")
        raise error(code)


def unlock(handle) -> None:
    overlapped = OVERLAPPED(0, 0, 0, LOCK_OFFSET_HIGH, None)
    check(UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped)))


# --- DPAPI ----------------------------------------------------------------------------------

def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _take(blob: DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        LocalFree(ctypes.cast(blob.pbData, PVOID))


def protect(data: bytes, entropy: bytes) -> bytes:
    source, _keep = _blob(data)
    salt, _keep_salt = _blob(entropy)
    result = DATA_BLOB()
    check(CryptProtectData(ctypes.byref(source), None, ctypes.byref(salt), None, None,
                           CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(result)))
    return _take(result)


def unprotect(data: bytes, entropy: bytes) -> bytes:
    source, _keep = _blob(data)
    salt, _keep_salt = _blob(entropy)
    result = DATA_BLOB()
    check(CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(salt), None, None,
                             CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(result)))
    return _take(result)


# --- Boot identity --------------------------------------------------------------------------

def boot_identifier() -> str | None:
    """This boot's identifier GUID from the kernel, or None if it can't be read."""
    buffer = ctypes.create_string_buffer(32)
    returned = wintypes.ULONG()
    status = NtQuerySystemInformation(SYSTEM_BOOT_ENVIRONMENT_INFORMATION_CLASS, buffer, 32,
                                      ctypes.byref(returned))
    if status != 0 or returned.value < 16:
        return None
    value = uuid.UUID(bytes_le=buffer.raw[:16])
    return None if value.int == 0 else str(value)
