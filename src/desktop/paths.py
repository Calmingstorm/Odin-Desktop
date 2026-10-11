"""Explicit Linux XDG namespaces. Never adopt another installation's state."""
from __future__ import annotations

import errno
import os
import re
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .platform.variants import windows_variant


def _namespace_directories(path: Path) -> frozenset[Path]:
    """Only the paired odin-desktop/<valid-profile> components are ours."""
    parts = path.parts
    return frozenset(
        Path(*parts[:end])
        for index, name in enumerate(parts[:-1])
        if name == "odin-desktop" and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", parts[index + 1]
        )
        for end in (index + 1, index + 2)
    )


def _repair_namespace_directory(fd: int, path: Path, namespace: frozenset[Path],
                                *, kind: str) -> None:
    if path not in namespace:
        return
    info = os.fstat(fd)
    if info.st_uid != os.geteuid():
        if info.st_uid == 0:
            return  # Root-owned directories are usable, but not ours to chmod.
        raise PermissionError(errno.EACCES, f"foreign {kind} ancestor", str(path))
    if stat.S_IMODE(info.st_mode) != 0o700:
        os.fchmod(fd, 0o700)


@windows_variant("src.desktop.platform.windows_files:private_directory")
def private_directory(path: Path, *, repair_namespace: bool = True) -> None:
    """Create missing folders 0700; accept existing modes under D17.

    Only owned Desktop namespace components are tightened, never unrelated
    ancestors or configured socket folders. Resolve directory links once, then
    check real folders and their owners through held no-follow descriptors.
    """
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("private paths must be absolute")
    path = Path(os.path.realpath(path))
    namespace = _namespace_directories(path) if repair_namespace else frozenset()
    current = Path("/")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in path.parts[1:]:
            current /= name
            try:
                os.mkdir(name, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            try:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as exc:
                raise OSError(exc.errno, exc.strerror, str(current)) from None
            os.close(fd)
            fd = child
            _repair_namespace_directory(fd, current, namespace, kind="profile")
            info = os.fstat(fd)
            if info.st_uid not in {0, os.geteuid()}:
                raise PermissionError(errno.EACCES, "foreign profile ancestor", str(current))
    finally:
        os.close(fd)


@dataclass(frozen=True, slots=True)
class ProfilePaths:
    profile_id: str
    config_dir: Path
    data_dir: Path
    cache_dir: Path
    secrets_dir: Path

    @classmethod
    def from_xdg(
        cls,
        profile_id: str = "default",
        *,
        environ: Mapping[str, str] | None = None,
        home: Path | str | None = None,
    ) -> ProfilePaths:
        if not sys.platform.startswith("linux"):
            raise NotImplementedError("desktop provisioning is Linux-only")
        if not isinstance(profile_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", profile_id
        ):
            raise ValueError("invalid profile identifier")
        env = os.environ if environ is None else environ
        home_path = Path(home) if home is not None else Path.home()
        if not home_path.is_absolute() or ".." in home_path.parts:
            raise ValueError("home must be absolute")
        def root(key: str, fallback: str) -> Path:
            path = Path(env[key]) if env.get(key) else home_path / fallback
            if not path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in str(path)):
                raise ValueError(f"{key} must be an absolute local path")
            return path / "odin-desktop" / profile_id
        config = root("XDG_CONFIG_HOME", ".config")
        data = root("XDG_DATA_HOME", ".local/share")
        cache = root("XDG_CACHE_HOME", ".cache")
        roots = (config, data, cache)
        if any(
            a == b or a in b.parents or b in a.parents
            for i, a in enumerate(roots)
            for b in roots[i + 1 :]
        ):
            raise ValueError("config, data and cache namespaces must be nonoverlapping")
        return cls(profile_id, config, data, cache, data / "secrets")

    @classmethod
    def from_app(
        cls, profile_id: str, *, token_file: Path, data_dir: Path,
        environ: Mapping[str, str] | None = None, home: Path | str | None = None,
    ) -> ProfilePaths:
        """Select the app's explicit roots, never an existing Odin installation.

        The token remains app-owned. No file is opened or provisioned here.
        Cache uses the same XDG/profile namespace as the app.
        """
        from .platform import current_platform

        defaults = current_platform().profile_paths(profile_id, environ=environ, home=home)
        token_file, data_dir = Path(token_file), Path(data_dir)
        for path in (token_file, data_dir):
            if (not path.is_absolute() or ".." in path.parts
                    or any(ord(c) < 32 for c in str(path))):
                raise ValueError("app paths must be absolute local paths")
        roots = (token_file.parent, data_dir, defaults.cache_dir)
        if any(a == b or a in b.parents or b in a.parents
               for i, a in enumerate(roots) for b in roots[i + 1:]):
            raise ValueError("config, data and cache namespaces must be nonoverlapping")
        return cls(profile_id, *roots, data_dir / "secrets")

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.yml"

    @property
    def identity_file(self) -> Path:
        return self.config_dir / "profile.json"

    @property
    def environment_file(self) -> Path:
        return self.secrets_dir / "environment"

    def create_private(self) -> None:
        for path in (self.config_dir, self.data_dir, self.cache_dir, self.secrets_dir):
            private_directory(path)
