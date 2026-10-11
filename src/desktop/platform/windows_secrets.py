"""Windows: the profile's credentials encrypted with the user's login (DPAPI).

One file per (service, name) in the profile's private ``secrets\\dpapi`` folder.
The file name is a SHA-256 of the store's namespace (its ``service``), and the
same namespace is DPAPI's entropy, so another profile's ciphertext never
decrypts here. A failure raises; the store reports it as unavailable.
"""
from __future__ import annotations

import hashlib

from . import win32
from .windows_files import OWN_NAMESPACE, held, publish, read_file, remove

_LIMIT = 1 << 20  # A DPAPI blob of the store's 64 KiB maximum is far below this.


class DpapiSecretBackend:
    def __init__(self, paths):
        self.directory = paths.secrets_dir / "dpapi"

    @staticmethod
    def _file(service: str, name: str) -> str:
        return hashlib.sha256(f"{service}\0{name}".encode()).hexdigest() + ".dpapi"

    def _chain(self):
        return held(self.directory, create=True, namespace=OWN_NAMESPACE)

    def get_password(self, service: str, name: str) -> str | None:
        with self._chain() as chain:
            try:
                blob = read_file(chain, self._file(service, name), limit=_LIMIT + 1)
            except FileNotFoundError:
                return None
        if len(blob) > _LIMIT:
            raise ValueError("credential file is too large")
        return win32.unprotect(blob, service.encode("utf-8")).decode("utf-8")

    def set_password(self, service: str, name: str, value: str) -> None:
        blob = win32.protect(value.encode("utf-8"), service.encode("utf-8"))
        with self._chain() as chain:
            if not publish(chain, self._file(service, name), blob):
                # Visible but not proven on disk: the store has no degraded outcome, so
                # report the write as failed and let the caller retry it.
                raise OSError("credential stored but its durability is unproven")

    def delete_password(self, service: str, name: str) -> None:
        with self._chain() as chain:
            remove(chain, self._file(service, name), missing_ok=True)

    def unlock(self) -> bool:
        """DPAPI is open whenever the user is signed in."""
        return True
