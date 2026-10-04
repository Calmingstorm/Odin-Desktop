"""Private installation/profile owner identity, not exact-action approval."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import stat
import uuid
from dataclasses import dataclass, field

from ..permissions.persistence import write_private_atomic
from .paths import ProfilePaths


@dataclass(frozen=True, slots=True)
class OwnerContext:
    installation_id: str
    profile_id: str
    owner_id: str
    runtime_id: str
    owner_uid: int
    _seal: object = field(repr=False, compare=False)


class OwnerAuthority:
    def __init__(self, paths: ProfilePaths) -> None:
        paths.create_private()
        self.paths = paths
        self.owner_uid = os.geteuid()
        self.runtime_id = str(uuid.uuid4())
        self._seal = object()
        self._runtime_lock_fd = None
        self.durability_degraded = False
        with self._locked():
            try:
                fd = os.open(paths.identity_file, os.O_RDONLY | os.O_NOFOLLOW)
            except FileNotFoundError:
                existing_config = [
                    p for p in paths.config_dir.iterdir() if p.name != ".identity.lock"
                ]
                existing_data = [p for p in paths.data_dir.iterdir() if p != paths.secrets_dir]
                if existing_config or existing_data or any(paths.secrets_dir.iterdir()):
                    raise ValueError("existing state has no identity; explicit recovery required")
                data = {
                    "version": 1,
                    "installation_id": str(uuid.uuid4()),
                    "profile_id": paths.profile_id,
                    "owner_id": str(uuid.uuid4()),
                    "owner_uid": self.owner_uid,
                }
                self.durability_degraded = not write_private_atomic(
                    paths.identity_file, json.dumps(data)
                )
            else:
                with os.fdopen(fd, "r", encoding="utf-8") as stream:
                    info = os.fstat(stream.fileno())
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_uid != self.owner_uid
                        or stat.S_IMODE(info.st_mode) != 0o600
                        or info.st_size > 4096
                    ):
                        raise PermissionError("unsafe profile identity record")
                    def unique(pairs):
                        result = {}
                        for key, value in pairs:
                            if key in result:
                                raise ValueError("duplicate profile identity key")
                            result[key] = value
                        return result
                    data = json.load(stream, object_pairs_hook=unique)
            self._validate(data)
            self.installation_id = data["installation_id"]
            self.profile_id = data["profile_id"]
            self.owner_id = data["owner_id"]

    @contextlib.contextmanager
    def _locked(self):
        fd = os.open(
            self.paths.config_dir / ".identity.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.owner_uid
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise PermissionError("unsafe profile identity lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _validate(self, data) -> None:
        if (
            not isinstance(data, dict)
            or set(data)
            != {"version", "installation_id", "profile_id", "owner_id", "owner_uid"}
            or type(data["version"]) is not int
            or data["version"] != 1
            or type(data["owner_uid"]) is not int
            or data["owner_uid"] != self.owner_uid
            or data["profile_id"] != self.paths.profile_id
        ):
            raise ValueError("foreign or invalid profile identity; explicit recovery required")
        for key in ("installation_id", "owner_id"):
            if not isinstance(data[key], str) or str(uuid.UUID(data[key])) != data[key]:
                raise ValueError("profile identity must contain canonical UUIDs")

    def authenticate_local(self, *, peer_uid: int) -> OwnerContext:
        """Mint from OS-verified peer credentials only, never a payload UID."""
        if self.durability_degraded:
            raise PermissionError(
                "profile identity durability unproven; explicit recovery required"
            )
        if type(peer_uid) is not int or peer_uid != self.owner_uid:
            raise PermissionError("local peer is not the profile owner")
        self.acquire_runtime()
        if not self._identity_current():
            raise PermissionError("profile identity changed; explicit recovery required")
        return OwnerContext(
            self.installation_id,
            self.profile_id,
            self.owner_id,
            self.runtime_id,
            self.owner_uid,
            self._seal,
        )

    def accepts(self, context: OwnerContext | None) -> bool:
        return (
            not self.durability_degraded
            and self._runtime_lock_fd is not None
            and isinstance(context, OwnerContext)
            and context._seal is self._seal
            and context.installation_id == self.installation_id
            and context.profile_id == self.profile_id
            and context.owner_id == self.owner_id
            and context.runtime_id == self.runtime_id
            and context.owner_uid == self.owner_uid
            and self._identity_current()
        )

    def _identity_current(self) -> bool:
        """Existing contexts cannot hide revoked/corrupt or rebound private storage."""
        try:
            self.paths.create_private()
            fd = os.open(self.paths.identity_file, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != self.owner_uid
                    or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_size > 4096
                ):
                    return False
                data = json.load(stream)
            self._validate(data)
            return (
                data["installation_id"] == self.installation_id
                and data["owner_id"] == self.owner_id
            )
        except (OSError, ValueError, TypeError):
            return False

    def acquire_runtime(self) -> None:
        """Hold a lifetime profile lock. PID alone is never runtime identity."""
        if self._runtime_lock_fd is not None:
            return
        self.paths.create_private()
        fd = os.open(
            self.paths.data_dir / ".core.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.owner_uid
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise PermissionError("unsafe runtime lock")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
        self._runtime_lock_fd = fd

    def release_runtime(self) -> None:
        if self._runtime_lock_fd is not None:
            os.close(self._runtime_lock_fd)
            self._runtime_lock_fd = None
            self.runtime_id = str(uuid.uuid4())
            self._seal = object()
