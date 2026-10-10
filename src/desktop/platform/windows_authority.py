"""Windows: ``OwnerAuthority``'s storage and principal.

The principal is the user's SID string where Linux uses the effective uid. It is
kept in the same ``owner_uid`` attribute and ``OwnerContext`` field, so contexts
compare exactly as on Linux; the identity record names it ``owner_sid``. Files
follow the private-storage contract, and the locks are held without delete
sharing, so a locked file can't be replaced while it is held.
"""
from __future__ import annotations

import json
import msvcrt
import os
import uuid

from . import win32
from .windows_files import file_size, held, matches_path, open_file, to_fd, user_sid

_RECORD_KEYS = {"version", "installation_id", "profile_id", "owner_id", "owner_sid"}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate profile identity key")
        result[key] = value
    return result


def _read_identity(paths):
    """The identity record, or FileNotFoundError when there is none."""
    with held(paths.config_dir) as chain:
        handle = open_file(chain, paths.identity_file.name, links=False)
        try:
            if file_size(handle) > 4096:
                raise PermissionError("unsafe profile identity record")
        except BaseException:
            win32.close(handle)
            raise
        with os.fdopen(to_fd(handle, os.O_RDONLY), "r", encoding="utf-8") as stream:
            return json.load(stream, object_pairs_hook=_unique)


def owner_authority_init(self, paths, *, app_bootstrap: bool = False) -> None:
    from ...permissions.persistence import write_private_atomic

    paths.create_private()
    self.paths = paths
    self.owner_uid = user_sid()
    self.runtime_id = str(uuid.uuid4())
    self._seal = object()
    self._runtime_lock_fd = None
    self.durability_degraded = False
    with self._locked():
        try:
            data = _read_identity(paths)
        except FileNotFoundError:
            app_config, app_data = (
                self._app_bootstrap_files() if app_bootstrap else (set(), set())
            )
            existing_config = [
                p for p in paths.config_dir.iterdir()
                if p.name != ".identity.lock" and p not in app_config
            ]
            existing_data = [p for p in paths.data_dir.iterdir()
                             if p != paths.secrets_dir and p not in app_data]
            if existing_config or existing_data or any(paths.secrets_dir.iterdir()):
                raise ValueError("existing state has no identity; explicit recovery required")
            data = {
                "version": 1,
                "installation_id": str(uuid.uuid4()),
                "profile_id": paths.profile_id,
                "owner_id": str(uuid.uuid4()),
                "owner_sid": self.owner_uid,
            }
            self.durability_degraded = not write_private_atomic(
                paths.identity_file, json.dumps(data)
            )
        except PermissionError:
            raise PermissionError("unsafe profile identity record") from None
        self._validate(data)
        self.installation_id = data["installation_id"]
        self.profile_id = data["profile_id"]
        self.owner_id = data["owner_id"]


def _app_bootstrap_files(self) -> tuple[set, set]:
    def owned_file(path, *, token=False):
        try:
            with held(path.parent) as chain:
                win32.close(open_file(chain, path.name))
        except OSError:
            raise PermissionError("unsafe app bootstrap file") from None

    config, data = set(), set()
    for name in ("ipc.token", "app-state.json", "app-state.json.tmp"):
        path = self.paths.config_dir / name
        if path.exists() or path.is_symlink():
            owned_file(path, token=name == "ipc.token")
            config.add(path)
    for name in ("drafts.json", "drafts.json.tmp"):
        drafts = self.paths.data_dir / name
        if drafts.exists() or drafts.is_symlink():
            owned_file(drafts)
            data.add(drafts)
    logs = self.paths.data_dir / "logs"
    if logs.exists() or logs.is_symlink():
        from ..paths import private_directory

        private_directory(logs)
        for path in logs.iterdir():
            if path.name not in {"core.log", "core.log.1"}:
                raise ValueError("existing engine logs have no identity")
            owned_file(path)
        data.add(logs)
    return config, data


def _locked(self):
    # A plain generator: the routed method keeps its @contextmanager.
    with held(self.paths.config_dir) as chain:
        try:
            handle = open_file(chain, ".identity.lock", write=True, create=True, lock=True)
        except PermissionError:
            raise PermissionError("unsafe profile identity lock") from None
        fd = to_fd(handle, os.O_RDWR)
        try:
            from . import locks

            locks.lock_exclusive(fd)
            yield
        finally:
            os.close(fd)


def _validate(self, data) -> None:
    if (
        not isinstance(data, dict)
        or set(data) != _RECORD_KEYS
        or type(data["version"]) is not int
        or data["version"] != 1
        or type(data["owner_sid"]) is not str
        or data["owner_sid"] != self.owner_uid
        or data["profile_id"] != self.paths.profile_id
    ):
        raise ValueError("foreign or invalid profile identity; explicit recovery required")
    for key in ("installation_id", "owner_id"):
        if not isinstance(data[key], str) or str(uuid.UUID(data[key])) != data[key]:
            raise ValueError("profile identity must contain canonical UUIDs")


def authenticate_local(self, *, peer_uid):
    """Mint from the OS-verified peer SID only, never a payload value."""
    from ..authority import OwnerContext

    if self.durability_degraded:
        raise PermissionError(
            "profile identity durability unproven; explicit recovery required"
        )
    if type(peer_uid) is not str or peer_uid != self.owner_uid:
        raise PermissionError("local peer is not the profile owner")
    self.acquire_runtime()
    if not self._identity_current() or not self._runtime_current():
        raise PermissionError("profile identity changed; explicit recovery required")
    return OwnerContext(
        self.installation_id,
        self.profile_id,
        self.owner_id,
        self.runtime_id,
        self.owner_uid,
        self._seal,
    )


def _identity_current(self) -> bool:
    try:
        self.paths.create_private()
        data = _read_identity(self.paths)
        self._validate(data)
        return (
            data["installation_id"] == self.installation_id
            and data["owner_id"] == self.owner_id
        )
    except (OSError, ValueError, TypeError):
        return False


def acquire_runtime(self) -> None:
    if self._runtime_lock_fd is not None:
        if not self._runtime_current():
            raise PermissionError("profile ownership lock changed")
        return
    self.paths.create_private()
    with held(self.paths.config_dir) as chain:
        try:
            handle = open_file(chain, ".core.lock", write=True, create=True, lock=True)
        except PermissionError:
            raise PermissionError("unsafe runtime lock") from None
        fd = to_fd(handle, os.O_RDWR)
        try:
            from . import locks

            locks.lock_exclusive(fd, blocking=False)
            if not matches_path(handle, chain.child(".core.lock")):
                raise PermissionError("profile ownership lock changed")
        except BaseException:
            os.close(fd)
            raise
    self._runtime_lock_fd = fd


def _runtime_current(self) -> bool:
    if self._runtime_lock_fd is None:
        return False
    try:
        handle = msvcrt.get_osfhandle(self._runtime_lock_fd)
        return matches_path(handle, self.paths.config_dir / ".core.lock")
    except OSError:
        return False
