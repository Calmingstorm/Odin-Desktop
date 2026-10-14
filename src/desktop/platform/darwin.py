"""macOS primitives for the Desktop engine, through libSystem.

Each structure's size is checked before use, and a missing or changed interface fails closed:
no member here falls back to a weaker mechanism. The process-identity calls come from libproc, a
private-but-exported interface (the same header as proc_pidinfo). They were qualified on macOS 26
and 27 for a current identity, a stale PID version and an exec; their absence returns ENOSYS.
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.platform != "darwin":
    raise ImportError("darwin primitives are macOS-only")

_libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)

_CS_DARWIN_USER_TEMP_DIR = 65537
PROC_PIDLISTFDS = 1
PROC_PIDUNIQIDENTIFIERINFO = 17
ACL_TYPE_EXTENDED = 0x00000100
ACL_FIRST_ENTRY = 0
ACL_NEXT_ENTRY = -1
ACL_EXTENDED_ALLOW = 1


class _UniqInfo(ctypes.Structure):
    _fields_ = [
        ("uuid", ctypes.c_uint8 * 16),
        ("uniqueid", ctypes.c_uint64),
        ("puniqueid", ctypes.c_uint64),
        ("idversion", ctypes.c_int32),
        ("orig_ppidversion", ctypes.c_int32),
        ("reserve3", ctypes.c_uint64),
        ("reserve4", ctypes.c_uint64),
    ]


class _AuditToken(ctypes.Structure):
    _fields_ = [("val", ctypes.c_uint32 * 8)]


class _FdInfo(ctypes.Structure):
    _fields_ = [("proc_fd", ctypes.c_int32), ("proc_fdtype", ctypes.c_uint32)]


for _struct, _size in ((_UniqInfo, 56), (_AuditToken, 32), (_FdInfo, 8)):
    if ctypes.sizeof(_struct) != _size:
        raise ImportError(f"unexpected {_struct.__name__} layout: {ctypes.sizeof(_struct)} bytes")

_libc.confstr.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t]
_libc.confstr.restype = ctypes.c_size_t
_libc.getpeereid.argtypes = [
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_uint32),
    ctypes.POINTER(ctypes.c_uint32),
]
_libc.getpeereid.restype = ctypes.c_int
_libc.sysctlbyname.argtypes = [
    ctypes.c_char_p,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_size_t),
    ctypes.c_void_p,
    ctypes.c_size_t,
]
_libc.sysctlbyname.restype = ctypes.c_int
_libc.proc_pidinfo.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint64,
    ctypes.c_void_p,
    ctypes.c_int,
]
_libc.proc_pidinfo.restype = ctypes.c_int
_libc.acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
_libc.acl_get_fd_np.restype = ctypes.c_void_p
_libc.acl_get_entry.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
_libc.acl_get_entry.restype = ctypes.c_int
_libc.acl_get_tag_type.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
_libc.acl_get_tag_type.restype = ctypes.c_int
_libc.acl_free.argtypes = [ctypes.c_void_p]
_libc.acl_free.restype = ctypes.c_int
try:
    _signal_by_token = _libc.proc_signal_with_audittoken
    _signal_by_token.argtypes = [ctypes.POINTER(_AuditToken), ctypes.c_int]
    _signal_by_token.restype = ctypes.c_int  # 0 or an errno value, not -1 with errno
except AttributeError:
    _signal_by_token = None


@dataclass(frozen=True)
class ProcessIdentity:
    """One process incarnation: its unique ID, plus the PID version the kernel checks."""

    pid: int
    uniqueid: int
    idversion: int


def user_temp_root() -> Path:
    """The per-user temporary folder macOS assigns, verified private, as a canonical path.

    confstr can fall back to a shared folder when its helper fails, so the result is checked rather
    than trusted: it must be an existing directory owned by this user, with mode 0700, reached
    without a link at its last component.
    """
    size = _libc.confstr(_CS_DARWIN_USER_TEMP_DIR, None, 0)
    if size == 0:
        raise OSError(ctypes.get_errno() or errno.ENOENT, "no per-user temporary folder")
    buffer = ctypes.create_string_buffer(size)
    _libc.confstr(_CS_DARWIN_USER_TEMP_DIR, buffer, size)
    named = Path(os.fsdecode(buffer.value))
    if not named.is_absolute() or ".." in named.parts:
        raise PermissionError(
            errno.EACCES, "the per-user temporary folder is not absolute", str(named)
        )
    path = Path(os.path.realpath(named))
    info = os.lstat(path)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise PermissionError(
            errno.EACCES, "the per-user temporary folder is not private", str(path)
        )
    return path


def peer_uid(sock) -> int:
    """The connected peer's effective UID from the kernel (getpeereid), never from the client."""
    uid, gid = ctypes.c_uint32(), ctypes.c_uint32()
    ctypes.set_errno(0)
    if _libc.getpeereid(sock.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
        error = ctypes.get_errno() or errno.EIO
        raise OSError(error, os.strerror(error))
    return int(uid.value)


def boot_identity() -> str | None:
    """This boot's session UUID (kern.bootsessionuuid), or None when it cannot be read."""
    size = ctypes.c_size_t(0)
    if _libc.sysctlbyname(b"kern.bootsessionuuid", None, ctypes.byref(size), None, 0) != 0:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if _libc.sysctlbyname(b"kern.bootsessionuuid", buffer, ctypes.byref(size), None, 0) != 0:
        return None
    value = buffer.value.decode("ascii", "replace").strip()
    return value or None


def process_identity(pid: int) -> ProcessIdentity | None:
    """The identity of the process at pid, or None when it is gone or not readable."""
    info = _UniqInfo()
    ctypes.set_errno(0)
    size = _libc.proc_pidinfo(
        pid, PROC_PIDUNIQIDENTIFIERINFO, 0, ctypes.byref(info), ctypes.sizeof(info)
    )
    if size != ctypes.sizeof(info):
        return None
    return ProcessIdentity(pid, int(info.uniqueid), int(info.idversion))


def signal_identity(identity: ProcessIdentity, signal_number: int) -> int:
    """Signal exactly that incarnation: 0, or an errno (ESRCH when it is gone or has exec'd)."""
    if _signal_by_token is None:
        return errno.ENOSYS
    token = _AuditToken()
    token.val[5] = identity.pid
    token.val[7] = identity.idversion & 0xFFFFFFFF
    return int(_signal_by_token(ctypes.byref(token), signal_number))


def open_descriptor_count() -> int | None:
    """Descriptors open in this process, as the kernel lists them (PROC_PIDLISTFDS), or None.

    The sizing call reports the descriptor table's size; the listing call fills one entry per open
    descriptor. A buffer that comes back full may be truncated, so it is retried larger.
    """
    pid = os.getpid()
    entry = ctypes.sizeof(_FdInfo)
    needed = _libc.proc_pidinfo(pid, PROC_PIDLISTFDS, 0, None, 0)
    if needed <= 0:
        return None
    slots = needed // entry + 64
    for _attempt in range(4):
        buffer = (_FdInfo * slots)()
        filled = _libc.proc_pidinfo(
            pid, PROC_PIDLISTFDS, 0, ctypes.byref(buffer), ctypes.sizeof(buffer)
        )
        if filled <= 0 or filled % entry:
            return None
        if filled < ctypes.sizeof(buffer):
            return filled // entry
        slots *= 2
    return None


def allow_entries(fd: int) -> int:
    """The extended ACL's allow entries on fd's file; 0 without an ACL. Raises if unreadable.

    The owner already has its access through the mode bits, so an allow entry can only widen
    access to someone else. Deny entries only narrow it and are not counted.
    """
    ctypes.set_errno(0)
    acl = _libc.acl_get_fd_np(fd, ACL_TYPE_EXTENDED)
    if not acl:
        error = ctypes.get_errno()
        if error == errno.ENOENT:  # the file has no extended ACL
            return 0
        raise OSError(error or errno.EIO, "the access control list is unreadable")
    try:
        allowed = 0
        entry = ctypes.c_void_p()
        which = ACL_FIRST_ENTRY
        while _libc.acl_get_entry(acl, which, ctypes.byref(entry)) == 0:
            which = ACL_NEXT_ENTRY
            tag = ctypes.c_int()
            if _libc.acl_get_tag_type(entry, ctypes.byref(tag)) != 0:
                raise OSError(errno.EIO, "the access control list is unreadable")
            if tag.value == ACL_EXTENDED_ALLOW:
                allowed += 1
        return allowed
    finally:
        _libc.acl_free(acl)


# --- Routed variants --------------------------------------------------------------------------


def current_boot_id() -> str | None:
    """resource_cleanup.current_boot_id: this boot's session UUID, in Linux's lowercase shape."""
    import re

    value = boot_identity()
    if value is None:
        return None
    value = value.lower()
    shape = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    return value if re.fullmatch(shape, value) else None


def process_descriptor_usage() -> tuple[int, int | float]:
    """health.checker._process_descriptor_usage: the open descriptors and the soft limit.

    As on Linux, nothing is guessed: an unreadable count or limit raises.
    """
    import resource

    descriptors = open_descriptor_count()
    if descriptors is None:
        raise NotImplementedError("Descriptor metrics are unavailable on this platform")
    soft_limit, _hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    return descriptors, soft_limit
