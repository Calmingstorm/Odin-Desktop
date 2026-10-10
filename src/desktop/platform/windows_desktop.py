"""Windows variants of the Desktop's own storage functions.

Each function here replaces one routed by ``@windows_variant`` and keeps that
function's contract: the same results, the same refusals and the same strict,
degraded or best-effort outcomes, on the Windows private-storage contract.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from . import win32
from .windows_files import (
    OWN_NAMESPACE,
    HeldChain,
    file_size,
    flush_object,
    held,
    open_file,
    own_sids,
    publish,
    to_fd,
)

# --- ipc_auth -----------------------------------------------------------------------------


def load_token(token_file) -> str:
    """The app's IPC credential: a private, owned, regular file of exactly 64 hex digits."""
    path = Path(token_file)
    try:
        with held(path.parent) as chain:
            handle = open_file(chain, path.name)
            try:
                if file_size(handle) != 64:
                    raise PermissionError("unsafe IPC credential file")
            except BaseException:
                win32.close(handle)
                raise
            with os.fdopen(to_fd(handle, os.O_RDONLY), "rb") as stream:
                data = stream.read(65)
    except PermissionError:
        raise PermissionError(13, "unsafe IPC credential file", str(path)) from None
    if not re.fullmatch(rb"[0-9a-fA-F]{64}", data):
        raise PermissionError(13, "invalid IPC credential", str(path))
    return data.decode("ascii")


# --- commands.JournalStore ----------------------------------------------------------------


def journal_store_init(self, path, profile_id, *, identity=None) -> None:
    from ..commands import JournalStorageError
    from ..schema import validate_domains

    self.profile_id = profile_id
    self.identity = identity
    self._depth = 0
    self._rollback_only = False
    self._closed = False
    self._directory_fd = -1
    self._windows_chain = None
    self._connection = None
    if not isinstance(profile_id, str) or not profile_id:
        raise ValueError("Expected a profile identifier")
    try:
        path = Path(path)
        # The chain stays held for the connection's lifetime: SQLite opens by path,
        # and the held folders keep that path naming them (Linux: /proc/self/fd).
        # Its folder is a private endpoint wherever it resolved: SQLite creates its
        # sidecars there with what that folder passes on.
        self._windows_chain = chain = HeldChain(path.parent, create=True, namespace=OWN_NAMESPACE,
                                                private_leaf=True)
        for name in (path.name, path.name + "-journal", path.name + "-wal", path.name + "-shm"):
            try:
                win32.close(open_file(chain, name))
            except FileNotFoundError:
                continue
            except OSError:
                raise JournalStorageError() from None
        try:
            handle = open_file(chain, path.name, write=True, create=True)
        except OSError:
            raise JournalStorageError() from None
        try:
            existing = file_size(handle) > 0
        finally:
            win32.close(handle)
        self._connection = sqlite3.connect(str(chain.child(path.name)), isolation_level=None,
                                           timeout=5)
        self._connection.row_factory = sqlite3.Row
        if existing:
            tables = {row[0] for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not validate_domains(self.connection, tables,
                                    {"journal_meta", "command_receipts", "journal_events"}):
                raise JournalStorageError()
            rows = self.connection.execute(
                "SELECT profile_id,identity FROM journal_meta").fetchall()
            if len(rows) != 1 or tuple(rows[0]) != (profile_id, identity):
                raise JournalStorageError()
            columns = {
                "journal_meta": {"singleton", "profile_id", "identity", "event_high",
                                 "event_floor"},
                "command_receipts": {"command_id", "binding", "state", "response",
                                     "created_at", "finished_at", "unknown_outcome"},
                "journal_events": {"seq", "frame"},
            }
            for table, expected_columns in columns.items():
                actual = {row[1] for row in self.connection.execute(
                    f"PRAGMA table_info({table})")}
                if actual != expected_columns:
                    raise JournalStorageError()
        self._connection.execute("PRAGMA journal_mode=DELETE")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        with self.transaction():
            tables = {row[0] for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            expected = {"journal_meta", "command_receipts", "journal_events"}
            if existing and not validate_domains(self.connection, tables, expected):
                raise JournalStorageError()
            self.connection.execute("""CREATE TABLE IF NOT EXISTS journal_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                profile_id TEXT NOT NULL, identity TEXT, event_high INTEGER NOT NULL DEFAULT 0,
                event_floor INTEGER NOT NULL DEFAULT 0)""")
            self.connection.execute("""INSERT OR IGNORE INTO journal_meta
                (singleton,profile_id,identity) VALUES (1,?,?)""", (profile_id, identity))
            row = self.connection.execute(
                "SELECT profile_id,identity FROM journal_meta").fetchone()
            if row[0] != profile_id or row[1] != identity:
                raise JournalStorageError()
            self.connection.execute("""CREATE TABLE IF NOT EXISTS command_receipts (
                command_id TEXT PRIMARY KEY, binding TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending','final','expired')),
                response TEXT, created_at REAL NOT NULL, finished_at REAL,
                unknown_outcome INTEGER NOT NULL DEFAULT 0)""")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS journal_events (
                seq INTEGER PRIMARY KEY, frame TEXT NOT NULL)""")
        # Windows barrier: flush the objects whose names this created (A5).
        for name in (path.name, path.name + "-journal", path.name + "-wal"):
            try:
                flush_object(chain, name)
            except FileNotFoundError:
                if name == path.name:
                    raise
    except Exception:
        self.close()
        raise JournalStorageError() from None


def journal_store_close(self) -> None:
    self._closed = True
    if self._connection is not None:
        try:
            self._connection.close()
        except Exception:
            pass
        self._connection = None
    chain, self._windows_chain = getattr(self, "_windows_chain", None), None
    if chain is not None:
        chain.close()


# --- management ---------------------------------------------------------------------------


def binding_key(paths) -> bytes:
    import secrets as random_secrets

    from ...permissions.persistence import write_private_atomic
    from ..commands import JournalStorageError

    path = paths.data_dir / "command-binding.key"
    try:
        with held(path.parent) as chain:
            handle = open_file(chain, path.name)
            try:
                size = file_size(handle)
            except BaseException:
                win32.close(handle)
                raise
            with os.fdopen(to_fd(handle, os.O_RDONLY), "r", encoding="ascii") as stream:
                text = stream.read(65)
    except FileNotFoundError:
        key = random_secrets.token_bytes(32)
        if not write_private_atomic(path, key.hex()):
            raise JournalStorageError() from None
        return key
    except OSError:
        raise JournalStorageError() from None
    if size != 64:
        raise JournalStorageError()
    try:
        key = bytes.fromhex(text)
    except ValueError:
        raise JournalStorageError() from None
    if len(key) != 32:
        raise JournalStorageError()
    return key


# --- provisioning -------------------------------------------------------------------------


def ensure_ssh_key(paths, authority, config) -> None:
    """Generate the profile key privately, then publish it with a no-replace rename."""
    key = paths.secrets_dir / "id_ed25519"
    if config.tools.ssh_key_path != str(key) or key.exists() or key.is_symlink():
        return
    with tempfile.TemporaryDirectory(prefix=".ssh-key-", dir=paths.secrets_dir) as temporary:
        candidate = Path(temporary) / "id_ed25519"
        try:
            subprocess.run(
                ["ssh-keygen", "-t", "ed25519", "-f", str(candidate), "-N", "", "-q",
                 "-C", f"odin-desktop:{paths.profile_id}"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("Could not provision the profile SSH key") from None
        with held(candidate.parent) as source:
            from .windows_files import ensure_private

            ensure_private(source, candidate.name)
            handle = open_file(source, candidate.name, write=True, delete=True)
            try:
                win32.flush(handle)
                with held(paths.secrets_dir):
                    try:
                        win32.rename_by_handle(handle, key, replace=False)
                    except FileExistsError:
                        return
                    try:
                        win32.flush(handle)
                    except OSError:
                        authority.durability_degraded = True
            finally:
                win32.close(handle)


# --- requests -----------------------------------------------------------------------------


def owner_display_name(config_dir) -> str:
    from ..requests import _CONTROL_CHARS, _DISPLAY_NAME_CHARS, OWNER_NAME

    if config_dir is None:
        return OWNER_NAME
    folder = Path(os.fspath(config_dir)) / "display-profile"
    try:
        with held(folder) as chain:
            security = win32.object_security(chain.handle)
            from .windows_files import dacl_is_private

            if security.owner not in own_sids() or not dacl_is_private(security):
                return OWNER_NAME
            handle = open_file(chain, "profile.json", links=False)
            try:
                oversized = file_size(handle) > 4096
            except BaseException:
                win32.close(handle)
                raise
            if oversized:
                win32.close(handle)
                return OWNER_NAME
            with os.fdopen(to_fd(handle, os.O_RDONLY), "rb") as stream:
                data = json.loads(stream.read(4097).decode("utf-8"))
    except (OSError, ValueError):
        return OWNER_NAME
    name = data.get("name") if isinstance(data, dict) else None
    if (not isinstance(name, str) or not name.strip() or len(name) > _DISPLAY_NAME_CHARS
            or _CONTROL_CHARS.search(name)):
        return OWNER_NAME
    return name


# --- resource_cleanup ---------------------------------------------------------------------


def current_boot_id() -> str | None:
    """This boot's identifier from the kernel, or None when it can't be read."""
    try:
        return win32.boot_identifier()
    except OSError:
        return None


# --- workspace_diagnostics ----------------------------------------------------------------


def workspace_collect(self) -> dict:
    from ..workspace_diagnostics import (
        COLLECTION_SECONDS,
        WALK_SECONDS,
        _git_snapshot,
        _usage,
    )

    started = time.monotonic()
    deadline = started + COLLECTION_SECONDS
    try:
        executor = self._executor_provider()
        root = Path(executor._ensure_local_workspace())
    except Exception:
        return {"status": "unavailable", "reason": "workspace_unusable", "local_only": True}
    try:
        usage = _usage(root, min(deadline, time.monotonic() + WALK_SECONDS))
        disk = {}
        if time.monotonic() < deadline:
            try:
                disk["free_bytes"] = shutil.disk_usage(root).free
            except OSError:
                pass
        git = _git_snapshot(root, deadline)
        return {"status": "ok" if usage["complete"] else "partial",
                "local_only": True, "usage": usage, "disk": disk, "git": git,
                "duration_ms": round((time.monotonic() - started) * 1000, 1)}
    except Exception:
        return {"status": "unavailable", "reason": "collection_failed", "local_only": True}


def workspace_usage(root, deadline) -> dict:
    """The same walk on held folder handles; links and other volumes are not followed."""
    from ..workspace_diagnostics import MAX_DEPTH, MAX_ENTRIES

    result = {"bytes": 0, "files": 0, "entries": 0, "symlinks_skipped": 0,
              "complete": True, "reason": None}

    def incomplete(reason):
        result["complete"] = False
        result["reason"] = result["reason"] or reason

    def walk(chain, depth, volume):
        with os.scandir(chain.path) as entries:
            for entry in entries:
                if result["entries"] >= MAX_ENTRIES or time.monotonic() >= deadline:
                    incomplete("walk_limit")
                    return
                result["entries"] += 1
                try:
                    if entry.is_symlink() or entry.is_junction():
                        result["symlinks_skipped"] += 1
                    elif entry.is_file(follow_symlinks=False):
                        result["bytes"] += entry.stat(follow_symlinks=False).st_size
                        result["files"] += 1
                    elif entry.is_dir(follow_symlinks=False):
                        if depth >= MAX_DEPTH:
                            incomplete("walk_boundary")
                            continue
                        with HeldChain(chain.path / entry.name) as child:
                            if win32.file_information(child.handle).dwVolumeSerialNumber != volume:
                                incomplete("walk_boundary")
                                continue
                            walk(child, depth + 1, volume)
                    else:
                        incomplete("special_file_skipped")
                except OSError:
                    incomplete("entry_unavailable")
                if result["reason"] == "walk_limit":
                    return

    with HeldChain(root) as chain:
        walk(chain, 0, win32.file_information(chain.handle).dwVolumeSerialNumber)
    return result


# --- ssh_sockets --------------------------------------------------------------------------


def socket_directory(paths) -> str:
    """No SSH multiplexing until phase 3 decides it; the name is never created here."""
    return str(paths.cache_dir / "ssh")


def prepare_socket_directory(value) -> None:
    from ..paths import private_directory

    private_directory(Path(value), repair_namespace=False)


# --- package_state ------------------------------------------------------------------------


@contextlib.contextmanager
def _package_reader(path):
    from ..package_state import PackageStateError

    path = Path(path)
    # The chain refuses a non-local path before anything resolves it.
    with held(path.parent) as chain:
        try:
            # Write access only so a caller's os.fsync works: Windows can't flush a
            # read-only handle. Nothing here writes.
            handle = open_file(chain, path.name, write=True)
        except FileNotFoundError:
            raise
        except OSError:
            raise PackageStateError("Unsafe package state file; original state preserved") from None
        with os.fdopen(to_fd(handle, os.O_RDWR), "rb") as stream:
            yield stream


def package_reader(path):
    # A plain generator: the routed function keeps its @contextmanager.
    with _package_reader(path) as stream:
        yield stream


def inspect_profile(paths, *, package_version=None):
    from ..package_state import (
        PackageStateError,
        _computer,
        _json,
        _record,
        _transport,
        _turns,
    )

    try:
        record = _record(paths)
        if (record and record["state"] == "pending" and package_version is not None
                and record["package_version"] != package_version):
            raise PackageStateError("Interrupted upgrade requires its compatible candidate")
        try:
            identity = _json(paths.identity_file)
        except FileNotFoundError:
            identity = None
        binding = None
        if identity is not None:
            from ..authority import OwnerAuthority
            from .windows_files import user_sid

            validator = object.__new__(OwnerAuthority)
            validator.paths = paths
            validator.owner_uid = user_sid()
            validator._validate(identity)
            binding = f"{identity['installation_id']}:{identity['owner_id']}"
            if record and record["identity"] != binding:
                raise PackageStateError("Foreign package state identity")
        elif record:
            raise PackageStateError("Package state has no owner identity")
        _transport(paths.data_dir / "transport.sqlite3", paths, binding)
        for name in ("turns.db", "turns.sqlite3"):
            _turns(paths.data_dir / "turn_state" / name)
        from .. import platform

        if platform.current_platform().computer_supported:
            _computer(paths.data_dir / "computer" / "state.sqlite3")
        return record
    except PackageStateError:
        raise
    except Exception:
        raise PackageStateError(
            "Package compatibility inspection failed; original state preserved") from None


def sync_directory(path) -> None:
    """Windows barrier for a folder: flush every file in it, the objects whose names changed."""
    with held(path) as chain:
        for entry in os.scandir(chain.path):
            if entry.is_file(follow_symlinks=False):
                flush_object(chain, entry.name)


def package_publish(path, document) -> None:
    path = Path(path)
    data = json.dumps(document, sort_keys=True).encode("utf-8")
    with held(path.parent) as chain:
        if not publish(chain, path.name, data):
            raise OSError("package state committed but its durability is unproven")


def package_backup(self):
    from ..package_state import BACKUPS_NAME, STATE_NAME, PackageStateError, _publish, _reader

    root = self.paths.data_dir / BACKUPS_NAME
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        try:
            with held(root, namespace=OWN_NAMESPACE):
                pass
        except OSError:
            raise PackageStateError("Unsafe package backup directory") from None
    backup = str(uuid.uuid4())
    destination = root / backup
    destination.mkdir(mode=0o700)
    entries = {}
    excluded = {".identity.lock", ".core.lock", "ipc.token"}

    def unreadable(error):
        raise error

    for label, source in (("config", self.paths.config_dir), ("data", self.paths.data_dir)):
        for folder, directories, files in os.walk(source, followlinks=False, onerror=unreadable):
            relative = Path(folder).relative_to(source)
            directories[:] = [d for d in directories if not (
                label == "data" and relative == Path(".") and d in {BACKUPS_NAME, "logs"})]
            target = destination / label / relative
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            for directory in directories:
                try:
                    with held(Path(folder) / directory) as chain:
                        owner = win32.object_security(chain.handle).owner
                except OSError:
                    raise PackageStateError("Unsafe package backup source directory") from None
                if owner not in own_sids():
                    raise PackageStateError("Unsafe package backup source directory")
            for name in files:
                if name in excluded or (label == "data" and relative == Path(".")
                                        and name == STATE_NAME):
                    continue
                digest = hashlib.sha256()
                with (_reader(Path(folder) / name) as stream,
                      (target / name).open("xb") as output):
                    before = os.fstat(stream.fileno())
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                        output.write(chunk)
                    after = os.fstat(stream.fileno())
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise PackageStateError("Package backup source changed")
                    output.flush()
                    os.fsync(output.fileno())
                entries[str(Path(label) / relative / name)] = digest.hexdigest()
    _publish(destination / "manifest.json", {"version": 1, "files": entries})
    from ..package_state import _sync_directory

    for folder, _, _ in os.walk(destination, topdown=False):
        _sync_directory(Path(folder))
    _sync_directory(root)
    _sync_directory(self.paths.data_dir)
    return backup
