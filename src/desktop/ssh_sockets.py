"""Bounded, private Desktop SSH paths. Never rewrite a configured path."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from .paths import ProfilePaths

# Supported Desktop platform is Linux (108 bytes including NUL). OpenSSH
# reserves '.' plus sixteen random characters while publishing ControlPath.
SOCKET_PATH_LIMIT = 107
OPENSSH_TEMP_SUFFIX_BYTES = 17
REGISTRY_SOCKET_NAME = "host-" + "0" * 32


def check_socket_path(path: str) -> None:
    required = max(len(os.fsencode(path)), len(os.fsencode(os.path.abspath(path))))
    required += OPENSSH_TEMP_SUFFIX_BYTES
    if "\0" in path or required > SOCKET_PATH_LIMIT:
        raise ValueError(
            "Desktop SSH control socket path is too long or invalid: "
            f"{required} bytes including OpenSSH's {OPENSSH_TEMP_SUFFIX_BYTES}-byte "
            f"temporary suffix; maximum {SOCKET_PATH_LIMIT}. "
            "Choose a shorter tools.ssh_pool.socket_dir."
        )


def _fits(directory: str) -> bool:
    try:
        check_socket_path(os.path.join(directory, REGISTRY_SOCKET_NAME))
    except ValueError:
        return False
    return True


def _open_directory(path: Path, *, create_from: Path | None = None) -> int:
    """No-follow, held descriptor walk. Never chmod an existing directory.

    Root/current-UID ancestors must not be writable by others, except root's
    sticky /tmp. Managed namespace components must be this UID's exact 0700.
    """
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("SSH runtime root must be an absolute local path")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    current = Path("/")
    try:
        for name in path.parts[1:]:
            current /= name
            private = create_from is not None and (
                current == create_from or create_from in current.parents
            )
            if private:
                try:
                    os.mkdir(name, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            mode = stat.S_IMODE(info.st_mode)
            if private:
                trusted = info.st_uid == os.geteuid() and mode == 0o700
            else:
                trusted = info.st_uid in {0, os.geteuid()} and (
                    not mode & 0o022 or (
                        current == Path("/tmp") and info.st_uid == 0 and mode & stat.S_ISVTX
                    )
                )
            if not trusted:
                raise PermissionError(f"Unsafe Desktop SSH runtime directory: {current}")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _runtime_root() -> Path | None:
    value = os.environ.get("XDG_RUNTIME_DIR")
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        return None
    try:
        fd = _open_directory(path)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                return None
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return None
    return path


def socket_directory(paths: ProfilePaths) -> str:
    """Select without creating anything, independently of HOME length."""
    profile = paths.profile_id
    compact = "p-" + hashlib.sha256(profile.encode()).hexdigest()[:12]
    runtime = _runtime_root()
    roots = ([runtime / "odin-desktop"] if runtime is not None else [])
    roots.append(Path(f"/tmp/odin-desktop-{os.geteuid()}"))
    for root in roots:
        for namespace in dict.fromkeys((profile, compact)):
            candidate = str(root / namespace / "ssh")
            if _fits(candidate):
                return candidate
    raise ValueError("No bounded Desktop SSH runtime directory is available")


def effective_socket_directory(value: str, paths: ProfilePaths) -> str:
    """Runtime correction of only the exact too-long provisioned default."""
    if value == str(paths.cache_dir / "ssh-sockets") and not _fits(value):
        return socket_directory(paths)
    return value


def prepare_socket_directory(value: str) -> None:
    """Reject planted managed namespaces; custom paths keep pool policy."""
    path = Path(value)
    fallback = Path(f"/tmp/odin-desktop-{os.geteuid()}")
    if path.parent.parent == fallback:
        root = fallback
    else:
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        root = Path(runtime) / "odin-desktop" if runtime else None
        if root is None or path.parent.parent != root:
            return
        fd = _open_directory(root.parent)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise PermissionError("Unsafe Desktop SSH XDG runtime root")
        finally:
            os.close(fd)
    fd = _open_directory(path, create_from=root)
    os.close(fd)


def normalize_config_sockets(config, paths: ProfilePaths):
    config.tools.ssh_pool.socket_dir = effective_socket_directory(
        config.tools.ssh_pool.socket_dir, paths
    )
    return config
