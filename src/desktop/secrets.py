"""Profile credentials in the Linux keyring, never in a fallback vault file."""

from __future__ import annotations

import hashlib
import re

from .paths import ProfilePaths


class SecretStoreError(RuntimeError):
    """The keyring is unavailable, locked, or rejected an operation."""


class ProfileSecretStore:
    """Lazy Secret Service adapter with an injectable isolated-test backend."""

    def __init__(self, paths: ProfilePaths, *, backend=None):
        self.paths = paths
        identity = str(paths.config_dir.absolute()).encode("utf-8")
        self.namespace = (
            f"odin-desktop:{paths.profile_id}:{hashlib.sha256(identity).hexdigest()[:24]}"
        )
        self.durability_degraded = False
        self._backend = backend

    def _name(self, name):
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,511}", name
        ):
            raise ValueError("invalid secret identifier")
        return name

    def _adapter(self):
        if self._backend is None:
            try:
                # Automatic selection could choose a third-party file backend.
                from keyring.backends.SecretService import Keyring

                self._backend = Keyring()
            except Exception:
                raise SecretStoreError("Profile keyring is unavailable") from None
        return self._backend

    def set(self, name, value) -> bool:
        name = self._name(name)
        if not isinstance(value, str) or len(value.encode("utf-8")) > 65536:
            raise ValueError("secret must be a bounded string")
        try:
            self._adapter().set_password(self.namespace, name, value)
        except Exception:
            raise SecretStoreError(
                "Profile keyring could not store the credential (unavailable or locked)"
            ) from None
        return True

    def get(self, name):
        name = self._name(name)
        try:
            value = self._adapter().get_password(self.namespace, name)
            if value is not None and not isinstance(value, str):
                raise TypeError
            return value
        except Exception:
            raise SecretStoreError(
                "Profile keyring could not read the credential (unavailable or locked)"
            ) from None

    def delete(self, name) -> bool:
        name = self._name(name)
        try:
            adapter = self._adapter()
            if adapter.get_password(self.namespace, name) is not None:
                adapter.delete_password(self.namespace, name)
        except Exception:
            raise SecretStoreError(
                "Profile keyring could not clear the credential (unavailable or locked)"
            ) from None
        return True

    clear = delete
