"""Install-relative Windows payloads; source execution keeps the OS copies."""
from __future__ import annotations

import errno
import os
import stat
import sys
from pathlib import Path

_CA_ENV = frozenset({"CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR"})


def packaged_root() -> Path | None:
    prefix = Path(sys.prefix).absolute()
    bundled = prefix.name.casefold() == "python" and prefix.parent.name.casefold() == "runtime"
    runtime = prefix.parent if bundled else None
    value = os.environ.get("ODIN_DESKTOP_BUNDLE_ROOT")
    if value is None and runtime is None:
        return None
    supplied = Path(value) if value is not None else runtime
    if not supplied.is_absolute():
        raise ValueError("Packaged Windows resources root must be absolute")
    if runtime is not None and supplied.resolve() != runtime.resolve():
        raise ValueError("Packaged Windows runtime root does not match interpreter")
    # The app env selects resources/runtime, not resources itself. The actual
    # bundled interpreter proves the same location even with the env omitted.
    return supplied.parent


def packaged_file(relative: str) -> Path | None:
    root = packaged_root()
    if root is None:
        return None
    path = root / relative
    for part in [root, *[root / p for p in reversed(path.relative_to(root).parents)
                         if p != Path(".")], path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            raise FileNotFoundError(
                errno.ENOENT, "Packaged Windows payload missing; repair installation",
                str(path)) from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise FileNotFoundError(errno.ENOENT, "Packaged Windows payload is a reparse alias",
                                    str(part))
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise FileNotFoundError(errno.ENOENT, "Packaged Windows payload is not an ordinary file",
                                str(path))
    return path


def curl_policy_args() -> list[str]:
    """Pinned Mozilla CA data only; never curlrc, CWD CA discovery or native roots."""
    ca = packaged_file("tools/curl/curl-ca-bundle.crt")
    return [] if ca is None else ["--disable", "--no-ca-native", "--cacert", str(ca)]


def curl_environment() -> dict[str, str] | None:
    if packaged_root() is None:
        return None
    return {key: value for key, value in os.environ.items() if key.upper() not in _CA_ENV}
