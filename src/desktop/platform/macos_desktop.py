"""macOS variants of Desktop helpers outside the IPC and process boundary.

SSH control sockets: macOS's sun_path holds 104 bytes with its NUL, so the bound is 103 (Linux's is
107), keeping the same 17 bytes for OpenSSH's temporary suffix. The per-user temporary folder is too
long for the 37-byte registry socket name, so the fallback root is root's sticky /private/tmp, the
canonical form of macOS's /tmp link. Linux's rules hold: the managed components are this user's,
mode 0700, and are walked and created without following links.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

SOCKET_PATH_LIMIT = 103
STICKY_TMP = Path("/private/tmp")


def _fallback_root() -> Path:
    return STICKY_TMP / f"odin-desktop-{os.geteuid()}"


def check_socket_path(path: str) -> None:
    """ssh_sockets.check_socket_path with macOS's bound."""
    from ..ssh_sockets import OPENSSH_TEMP_SUFFIX_BYTES

    required = max(len(os.fsencode(path)), len(os.fsencode(os.path.abspath(path))))
    required += OPENSSH_TEMP_SUFFIX_BYTES
    if "\0" in path or required > SOCKET_PATH_LIMIT:
        raise ValueError(
            "Desktop SSH control socket path is too long or invalid: "
            f"{required} bytes including OpenSSH's {OPENSSH_TEMP_SUFFIX_BYTES}-byte "
            f"temporary suffix; maximum {SOCKET_PATH_LIMIT}. "
            "Choose a shorter tools.ssh_pool.socket_dir."
        )


def socket_directory(paths) -> str:
    """ssh_sockets.socket_directory: a valid XDG runtime root first, then /private/tmp."""
    from ..ssh_sockets import _fits, _runtime_root

    profile = paths.profile_id
    compact = "p-" + hashlib.sha256(profile.encode()).hexdigest()[:12]
    runtime = _runtime_root(sticky_tmp=STICKY_TMP)
    roots = [runtime / "odin-desktop"] if runtime is not None else []
    roots.append(_fallback_root())
    for root in roots:
        for namespace in dict.fromkeys((profile, compact)):
            candidate = str(root / namespace / "ssh")
            if _fits(candidate):
                return candidate
    raise ValueError("No bounded Desktop SSH runtime directory is available")


def prepare_socket_directory(value: str) -> None:
    """ssh_sockets.prepare_socket_directory with the /private/tmp fallback root."""
    from ..ssh_sockets import _open_directory

    path = Path(value)
    fallback = _fallback_root()
    if path.parent.parent == fallback:
        root = fallback
    else:
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        root = Path(runtime) / "odin-desktop" if runtime else None
        if root is None or path.parent.parent != root:
            return
        fd = _open_directory(root.parent, sticky_tmp=STICKY_TMP)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise PermissionError("Unsafe Desktop SSH XDG runtime root")
        finally:
            os.close(fd)
    fd = _open_directory(path, create_from=root, sticky_tmp=STICKY_TMP)
    os.close(fd)
