"""Windows variants of Odin-origin functions in the Desktop engine.

Each replaces one function routed by ``@windows_variant``. The storage variants
keep their consumer contract: the same strict, degraded or best-effort outcome
after the commit point, and the old value kept with a raise before it (phase 2
plan, A5). The config validators read Linux-only computer-use paths as POSIX
paths, as Linux does, so a profile's settings mean the same on both systems.
Functions marked "lifted" are the Linux body with only its POSIX steps
replaced; ``tests/test_desktop_platform_variants.py`` pins each Linux original,
so a change there forces a review here.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path, PurePosixPath

from . import win32
from .windows_files import (
    HeldChain,
    ensure_private,
    file_size,
    flush_object,
    flush_path,
    held,
    namespace_of,
    open_file,
    open_plain,
    open_stream,
    publish,
    read_file,
    remove,
    rename_member,
    retire,
    to_fd,
    tombstones,
    user_sid,
)

_WRITE_NEW = win32.GENERIC_WRITE | win32.DELETE | win32.READ_CONTROL | win32.FILE_READ_ATTRIBUTES


def _publish_path(path, data: bytes, *, create: bool = False) -> bool:
    """A5 replace of ``path``: False means committed but durability unproven."""
    path = Path(path)
    namespace = namespace_of(path.parent) if create else frozenset()
    with held(path.parent, create=create, namespace=namespace) as chain:
        return publish(chain, path.name, data)


# --- permissions/persistence ----------------------------------------------------------------


def write_private_atomic(path, content):
    """Publish a complete private file; return whether durability is proven."""
    from src.permissions.persistence import log

    durable = _publish_path(path, content.encode("utf-8"), create=True)
    if not durable:
        log.error("Private state committed but its final flush failed; durability degraded")
    return durable


# --- permissions/host_access ----------------------------------------------------------------


def host_access_default_host(self):
    from src.permissions.host_access import StoreCorruptError, _unique_keys, _validate

    try:
        path = Path(self._path)
        with held(path.parent) as chain:
            handle = open_file(chain, path.name, links=False)
            try:
                oversized = file_size(handle) > 65536
            except BaseException:
                win32.close(handle)
                raise
            if oversized:
                win32.close(handle)
                return ""
            with os.fdopen(to_fd(handle, os.O_RDONLY), "r", encoding="utf-8") as stream:
                data = json.load(stream, object_pairs_hook=_unique_keys)
        _validate(data)
        return data.get("default_host", "")
    except (OSError, ValueError, TypeError, StoreCorruptError):
        return ""


# --- config/persistence ---------------------------------------------------------------------


def config_file_lock(target):
    """Same-user rendezvous in the user's private temp folder (a plain generator)."""
    import hashlib

    from src.config.migrations import _config_identity
    from src.config.persistence import ConfigPersistError

    owner = hashlib.sha256(user_sid().encode()).hexdigest()[:16]
    directory = Path(tempfile.gettempdir()) / f"odin-config-locks-{owner}"
    directory.mkdir(mode=0o700, exist_ok=True)
    try:
        chain = HeldChain(directory)
    except OSError:
        raise ConfigPersistError(
            "unsafe config lock directory ownership or permissions") from None
    try:
        security = win32.object_security(chain.handle)
        from .windows_files import dacl_is_private, own_sids

        if security.owner not in own_sids() or not dacl_is_private(security):
            raise ConfigPersistError("unsafe config lock directory ownership or permissions")
        try:
            handle = open_file(chain, _config_identity(target), write=True, create=True,
                               lock=True)
        except OSError:
            raise ConfigPersistError("unsafe config lock file ownership or permissions") from None
        fd = to_fd(handle, os.O_RDWR)
        try:
            from . import locks

            locks.lock_exclusive(fd)
            yield
        finally:
            os.close(fd)
    finally:
        chain.close()


def dump_atomic(document, config_path, orig_mode, *, raw_text=None, sequence_indent=None):
    """Serialize *document* over *config_path*; the directory barrier stays best effort."""
    import io

    from ruamel.yaml import YAML

    from src.config.persistence import ConfigPersistError

    ry = YAML()
    ry.preserve_quotes = True
    if sequence_indent is not None:
        ry.indent(mapping=2, sequence=sequence_indent, offset=2)
    buf = io.StringIO()
    if raw_text is None:
        ry.dump(document, buf)
    else:
        buf.write(raw_text)
    config_path = Path(config_path)
    try:
        # The commit point is the rename; its final flush is a durability nicety only,
        # as on Linux, so its result is not an error.
        _publish_path(config_path, buf.getvalue().encode("utf-8"))
    except PermissionError as exc:
        if "owner-owned" in str(exc):
            raise ConfigPersistError(
                "cannot preserve config file ownership during atomic write") from None
        raise


# --- config/migrations ----------------------------------------------------------------------


def atomic_write_marker(marker, record):
    marker = Path(marker)
    marker.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, indent=2, sort_keys=True) + "\n"
    # The rename commits; the final flush stays best effort, as on Linux.
    _publish_path(marker, encoded.encode("utf-8"))


def claim_legacy_marker(legacy_marker, config_id):
    """Fail-if-exists claim: a flushed temp renamed by handle without replacing."""
    from src.config.migrations import (
        MigrationCompletionError,
        _legacy_claim_path,
        _read_claim_owner,
    )

    claim = _legacy_claim_path(Path(legacy_marker))
    try:
        claim.parent.mkdir(parents=True, exist_ok=True)
        with held(claim.parent) as chain:
            temporary = f".{claim.name}.{secrets.token_hex(16)}.tmp"
            handle = win32.create_file(
                chain.child(temporary),
                _WRITE_NEW,
                win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE | win32.FILE_SHARE_DELETE,
                win32.CREATE_NEW, win32.FILE_FLAG_OPEN_REPARSE_POINT | win32.FILE_ATTRIBUTE_NORMAL)
            published = False
            try:
                win32.write_all(handle, (config_id + "\n").encode("ascii"))
                win32.flush(handle)
                try:
                    win32.rename_by_handle(handle, chain.child(claim.name), replace=False)
                except FileExistsError:
                    owner = _read_claim_owner(claim)
                    return owner == config_id
                published = True
                with contextlib.suppress(OSError):
                    win32.flush(handle)
                return True
            finally:
                if not published:
                    with contextlib.suppress(OSError):
                        win32.delete_by_handle(handle)
                win32.close(handle)
    except OSError as exc:
        raise MigrationCompletionError(
            "could not claim legacy ceiling-migration provenance") from exc


# --- llm/account_key ------------------------------------------------------------------------


def read_established_key(key_path):
    from src.llm.account_key import _KEY_BYTES, _KeyReadResult, log

    key_path = Path(key_path)
    try:
        with held(key_path.parent) as chain:
            handle = open_file(chain, key_path.name, links=False)
            try:
                size = file_size(handle)
            except BaseException:
                win32.close(handle)
                raise
            if size != _KEY_BYTES:
                win32.close(handle)
                log.warning("Refusing account key %s: %d bytes is not the generated "
                            "%d-byte shape.", key_path, size, _KEY_BYTES)
                return _KeyReadResult(material=None)
            with os.fdopen(to_fd(handle, os.O_RDONLY), "rb") as stream:
                material = stream.read(_KEY_BYTES)
    except FileNotFoundError:
        return _KeyReadResult(material=None, missing=True)
    except OSError as exc:
        log.warning("Refusing account key %s: %s", key_path, exc)
        return _KeyReadResult(material=None)
    if len(material) != _KEY_BYTES:
        log.warning("Refusing account key %s: %d bytes is not the generated %d-byte shape.",
                    key_path, len(material), _KEY_BYTES)
        return _KeyReadResult(material=None)
    return _KeyReadResult(material=material)


def fsync_parent(key_path):
    """Best effort, as on Linux: flush the published key itself."""
    with contextlib.suppress(OSError):
        flush_path(key_path)


def create_key(key_path):
    from src.llm.account_key import _KEY_BYTES, DEFAULT_KEY_PATH, _read_established_key, log

    key_path = Path(key_path)
    material = secrets.token_bytes(_KEY_BYTES)
    try:
        if key_path == DEFAULT_KEY_PATH:
            from ..paths import private_directory

            private_directory(key_path.parent)
        else:
            key_path.parent.mkdir(parents=True, exist_ok=True)
        with held(key_path.parent) as chain:
            temporary = f".{key_path.name}.{secrets.token_hex(16)}.tmp"
            handle = win32.create_file(
                chain.child(temporary),
                _WRITE_NEW,
                win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE | win32.FILE_SHARE_DELETE,
                win32.CREATE_NEW, win32.FILE_FLAG_OPEN_REPARSE_POINT | win32.FILE_ATTRIBUTE_NORMAL)
            published = False
            try:
                win32.write_all(handle, material)
                win32.flush(handle)
                try:
                    win32.rename_by_handle(handle, chain.child(key_path.name), replace=False)
                except FileExistsError:
                    return _read_established_key(key_path).material
                published = True
                with contextlib.suppress(OSError):
                    win32.flush(handle)
                return material
            finally:
                if not published:
                    with contextlib.suppress(OSError):
                        win32.delete_by_handle(handle)
                win32.close(handle)
    except OSError as exc:
        log.warning("Could not create account key %s: %s — account-scoped evidence "
                    "is skipped this boot.", key_path, exc)
        return None


# --- llm/window_observer --------------------------------------------------------------------


def read_store_bytes(path):
    from src.llm.window_observer import _MAX_STORE_BYTES

    try:
        handle = open_plain(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError(f"unreadable store file: {exc}") from exc
    try:
        size = file_size(handle)
    except BaseException:
        win32.close(handle)
        raise
    if size > _MAX_STORE_BYTES:
        win32.close(handle)
        raise ValueError(f"store file too large ({size} bytes)")
    with os.fdopen(to_fd(handle, os.O_RDONLY), "rb") as stream:
        return stream.read(size)


def window_persist_locked(self, state=None):
    from src.llm.window_observer import DEFAULT_STORE_PATH

    payload = json.dumps(self._state if state is None else state, indent=2, sort_keys=True)
    directory = self._path.parent
    if self._path == DEFAULT_STORE_PATH:
        from ..paths import private_directory

        private_directory(directory)
    else:
        directory.mkdir(parents=True, exist_ok=True)
    if not _publish_path(self._path, payload.encode("utf-8")):
        # Linux raises when the directory fsync after the replace fails.
        raise OSError("window store committed but its durability is unproven")


# --- audit/logger ---------------------------------------------------------------------------


def _marker_tombstones(marker) -> list[str]:
    marker = Path(marker)
    try:
        with held(marker.parent) as chain:
            return tombstones(chain, marker.name)
    except FileNotFoundError:
        return []


def _retire_marker(marker) -> None:
    """Durable removal of the append intent; the tombstone is then removed best effort."""
    marker = Path(marker)
    with held(marker.parent) as chain:
        tombstone = retire(chain, marker.name)
        with contextlib.suppress(OSError):
            remove(chain, tombstone)


def _settle_repair(marker) -> None:
    """Settlement in every starting state (phase 2 plan A5, B3s).

    Ensure an active marker, retire it, flush every other tombstone; only then
    delete the tombstones. Any failure before that raises and keeps them all.
    """
    marker = Path(marker)
    with held(marker.parent) as chain:
        if not marker.exists():
            text = (b"Audit append outcome uncertain. Preserve log bytes; "
                    b"operator repair required.\n")
            if not publish(chain, marker.name, text):
                raise OSError("audit repair marker durability unproven")
        others = tombstones(chain, marker.name)
        retired = retire(chain, marker.name)
        for name in others:
            flush_object(chain, name, links=False)
        for name in (*others, retired):
            with contextlib.suppress(OSError):
                remove(chain, name)


def audit_logger_init(self, path=None, *, hmac_key="", classify_failures=True,
                      result_cap=None, tool_input_cap=None, max_bytes=None, max_files=None):
    """Linux's constructor, plus: a matching tombstone also means repair is required."""
    from src.audit.logger import (
        DEFAULT_MAX_BYTES,
        DEFAULT_MAX_FILES,
        DEFAULT_RESULT_CAP,
        DEFAULT_TOOL_INPUT_CAP,
        AuditLogger,
    )

    AuditLogger.__init__.linux_original(
        self, path, hmac_key=hmac_key, classify_failures=classify_failures,
        result_cap=DEFAULT_RESULT_CAP if result_cap is None else result_cap,
        tool_input_cap=DEFAULT_TOOL_INPUT_CAP if tool_input_cap is None else tool_input_cap,
        max_bytes=DEFAULT_MAX_BYTES if max_bytes is None else max_bytes,
        max_files=DEFAULT_MAX_FILES if max_files is None else max_files)
    if _marker_tombstones(self._repair_marker):
        self.repair_required = True
        self.durability_degraded = True


def _audit_lines(path, flush: bool) -> list[str]:
    """Read the log through its verified handle; with ``flush``, flush that handle too."""
    path = Path(path)
    with held(path.parent) as chain, open_stream(
            chain, path.name, "r+" if flush else "r", encoding="utf-8") as stream:
        lines = stream.readlines()
        if flush:
            os.fsync(stream.fileno())
        return lines


def _verify_audit(path, key: str) -> dict:
    """``verify_log``, reading through the verified handle."""
    from src.audit.signer import verify_segment

    path = Path(path)
    if not os.path.lexists(path):
        return {"valid": True, "total": 0, "verified": 0, "unsigned_prefix": 0,
                "first_bad": None, "error": None}
    try:
        with held(path.parent) as chain, open_stream(chain, path.name, "rb") as handle:
            result = verify_segment(handle, os.fstat(handle.fileno()).st_size, key)
    except Exception as exc:
        return {"valid": False, "total": 0, "verified": 0, "unsigned_prefix": 0,
                "first_bad": None, "error": str(exc)}
    result.pop("reason", None)
    return result


async def audit_append_durable(self, line: str) -> None:
    """Linux's durable append, with its I/O under the held folder.

    The log is opened (created if missing) and verified through its handle before
    any byte is written; the intent marker is published and retired by A5. The
    outcomes are Linux's.
    """
    from src.audit.logger import write_private_atomic

    intent = False
    try:
        with held(self.path.parent) as chain, open_stream(
                chain, self.path.name, "a", encoding="utf-8", newline="", create=True) as f:
            if not write_private_atomic(
                self._repair_marker,
                "Audit append pending or uncertain; operator repair required.\n",
            ):
                self.repair_required = True
                raise OSError("Audit intent durability unproven")
            intent = True
            written = await asyncio.to_thread(f.write, line)
            if written != len(line):
                raise OSError("Short audit append")
            await asyncio.to_thread(f.flush)
            await asyncio.to_thread(os.fsync, f.fileno())
        # Durable retirement (rename by handle, flush), not unlink + folder fsync.
        _retire_marker(self._repair_marker)
    except BaseException:
        if intent:
            self._quarantine_uncertain_append()
        elif self._repair_marker.exists():
            self.repair_required = True
        raise


def audit_maybe_rotate(self) -> None:
    """Linux's rotation, every removal and rename by handle under the held folder."""
    from src.audit.logger import GENESIS_HASH, log

    name = self.path.name
    try:
        chain = HeldChain(self.path.parent)
    except OSError:
        return
    with chain:
        try:
            handle = open_file(chain, name, links=False)
        except OSError:
            return  # absent or unusable, where Linux's stat finds nothing or fails
        try:
            small = file_size(handle) < self._max_bytes
        finally:
            win32.close(handle)
        if small:
            return
        try:
            remove(chain, f"{name}.{self._max_files}", missing_ok=True)
            for i in range(self._max_files - 1, 0, -1):
                rename_member(chain, f"{name}.{i}", f"{name}.{i + 1}", missing_ok=True)
            rename_member(chain, name, f"{name}.1")
            if self._signer is not None:
                # New file = new chain from genesis, as on Linux.
                self._signer.prev_hmac = GENESIS_HASH
            log.info("Rotated audit log at %d bytes", self._max_bytes)
        except OSError as e:
            log.error("Audit log rotation failed: %s", e)


async def audit_open_read_snapshot(self):
    """Linux's descriptor snapshot, each generation opened and verified in the held folder."""
    from src.audit.logger import log

    opened = []
    seen = set()
    async with self._persist_lock:
        try:
            chain = HeldChain(self.path.parent)
        except OSError as exc:
            log.error("Failed to open audit log %s: %s", self.path, exc)
            return opened
        with chain:
            for path in self._rotated_paths_newest_first():
                try:
                    handle = open_stream(chain, path.name, "rb")
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    log.error("Failed to open audit log %s: %s", path, exc)
                    continue
                try:
                    stat = os.fstat(handle.fileno())
                except OSError as exc:
                    handle.close()
                    log.error("Failed to open audit log %s: %s", path, exc)
                    continue
                identity = (stat.st_dev, stat.st_ino)
                if identity in seen:
                    handle.close()
                    continue
                seen.add(identity)
                opened.append((handle, stat))
    return opened


# --- scheduler/history ----------------------------------------------------------------------


def _read_text_lines(path) -> list[str]:
    path = Path(path)
    with held(path.parent) as chain, open_stream(chain, path.name, "r",
                                                 encoding="utf-8") as stream:
        return stream.readlines()


def _append_text(path, text: str) -> None:
    path = Path(path)
    with held(path.parent) as chain, open_stream(
            chain, path.name, "a", encoding="utf-8", newline="", create=True) as stream:
        stream.write(text)


def record_interrupted_sync(self, pending: dict) -> None:
    """Linux's strict recovery append, under the held folder.

    ``a+`` there: created if missing, never truncated. The one flush of the
    file's handle after the write is both its data barrier and the barrier for its
    creation (A5). Any read, parse, write or flush failure propagates instead of
    claiming success, so the scheduler's outbox stays.
    """
    from src.scheduler.history import UTC, datetime

    evidence = ("schedule_id", "status", "run_binding", "error")
    if pending.get("status") != "unknown":
        raise ValueError("Interrupted recovery history must have unknown status")
    with held(self.path.parent) as chain, open_stream(
            chain, self.path.name, "a+", encoding="utf-8", newline="", create=True) as file:
        file.seek(0)
        entries = [json.loads(line) for line in file if line.strip()]
        recorded = any(
            all(entry.get(key) == pending.get(key) for key in evidence)
            for entry in entries
        )
        if not recorded:
            entry = {"timestamp": datetime.now(UTC).isoformat(), **pending}
            file.write(json.dumps(entry, default=str) + "\n")
        file.flush()
        os.fsync(file.fileno())


# --- sessions/manager -----------------------------------------------------------------------


def atomic_json(path, data):
    from src.sessions.manager import _PublishedButUnsyncedError

    if not _publish_path(path, json.dumps(data, indent=2).encode("utf-8")):
        raise _PublishedButUnsyncedError("replacement visible; its final flush failed")


# --- agents/results -------------------------------------------------------------------------


def publish_result(directory, snapshot):
    from src.agents.results import result_path

    path = result_path(Path(directory), snapshot["id"])
    data = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    # Linux: mkdir(0o700); here the missing folders are created private under the chain.
    if not _publish_path(path, data, create=True):
        raise OSError("agent result committed but its durability is unproven")


# --- turn_state/store -----------------------------------------------------------------------


def turn_state_init(self, db_path, *, blob_dir=None, lease_ttl=None):
    """Hold both folders and establish privacy before SQLite opens anything.

    The folders are created private under their chains and kept held for the
    store's lifetime; SQLite and the blobs then use the held, canonical paths, so
    an alias in the given path can't redirect them after the check. If this fails,
    the optional ledger stays off for this process, as Linux leaves it when its
    own setup fails, and nothing is written.
    """
    import threading

    from src.turn_state.store import DEFAULT_LEASE_TTL, TurnStateStore, log

    lease_ttl = DEFAULT_LEASE_TTL if lease_ttl is None else lease_ttl
    database = Path(db_path)
    blobs = Path(blob_dir) if blob_dir else database.parent / "blobs"
    self._windows_chain = self._windows_blob_chain = None
    chains = []
    try:
        chains.append(HeldChain(database.parent, create=True,
                                namespace=namespace_of(database.parent)))
        chains.append(HeldChain(blobs, create=True, namespace=namespace_of(blobs)))
        database_chain, blob_chain = chains
        for entry in os.scandir(blob_chain.path):
            is_folder = entry.is_dir(follow_symlinks=False)
            ensure_private(blob_chain, entry.name, directory=is_folder)
        for suffix in ("", "-wal", "-shm", "-journal"):
            ensure_private(database_chain, database.name + suffix)
    except Exception:
        for chain in chains:
            chain.close()
        log.exception(
            "TurnStateStore init failed — checkpoint durability DISABLED "
            "for this process (turns run legacy, work is not preserved)"
        )
        self.db_path = str(db_path)
        self.lease_ttl = lease_ttl
        self._blob_dir = blobs
        self._write_lock = threading.Lock()
        self._conn = None
        self.legacy_effect_free_reconciled = 0
        return
    try:
        TurnStateStore.__init__.linux_original(
            self, str(database_chain.child(database.name)), blob_dir=str(blob_chain.path),
            lease_ttl=lease_ttl)
    except BaseException:
        for chain in chains:
            chain.close()
        raise
    if self._conn is None:
        for chain in chains:
            chain.close()
    else:
        self._windows_chain, self._windows_blob_chain = database_chain, blob_chain


def turn_state_close(self):
    """Linux's close, then the folders held since construction are released."""
    from src.turn_state.store import TurnStateStore

    TurnStateStore.close.linux_original(self)
    for attribute in ("_windows_chain", "_windows_blob_chain"):
        chain = getattr(self, attribute, None)
        setattr(self, attribute, None)
        if chain is not None:
            chain.close()


def store_blob_sync(self, data: bytes) -> str:
    """Linux's content-addressed write in the held blob folder.

    A verified temporary file, flushed and renamed by its handle, as Linux's
    tmp + fsync + replace; neither system adds a folder barrier.
    """
    from src.turn_state.store import TurnStateUnavailableError

    digest = hashlib.sha256(data).hexdigest()
    chain = getattr(self, "_windows_blob_chain", None)
    try:
        if chain is None:
            raise OSError("the blob folder is not held")
        try:
            win32.close(open_file(chain, digest, links=False))
        except FileNotFoundError:
            publish(chain, digest, data)
    except OSError as exc:
        raise TurnStateUnavailableError(f"blob write failed: {exc}") from exc
    return f"blob:{digest}"


def load_blob_sync(self, ref: str) -> bytes:
    """Linux's read and digest check, through a verified handle in the held folder."""
    from src.turn_state.store import TurnStateUnavailableError

    digest = ref.split(":", 1)[1] if ref.startswith("blob:") else ref
    chain = getattr(self, "_windows_blob_chain", None)
    try:
        if chain is None:
            raise OSError("the blob folder is not held")
        data = read_file(chain, digest, links=False)
    except (OSError, ValueError) as exc:
        raise TurnStateUnavailableError(f"blob read failed: {ref}") from exc
    if hashlib.sha256(data).hexdigest() != digest:
        raise TurnStateUnavailableError(f"blob digest mismatch: {ref}")
    return data


def restrict_db_modes(self):
    """Best effort, as on Linux: keep the database and sidecars private."""
    database = Path(self.db_path)
    try:
        with held(database.parent) as chain:
            for suffix in ("", "-wal", "-shm"):
                with contextlib.suppress(OSError):
                    ensure_private(chain, database.name + suffix)
    except OSError:
        pass


def _windows_resolve_workspace(*args, **kwargs):
    from .windows_workspace import resolve_workspace

    return resolve_workspace(*args, **kwargs)


# Lifted from the Linux original.
async def audit_initialize_chain(self) -> None:
    """Report historical breaks, but resume from the actual settled tail.

    Integrity and append settlement are independent: old tamper evidence
    must not stop recording new actions. Only an uncertain tail fences
    writes. A restart can settle a stale intent without rewriting history.
    """
    from src.audit.logger import GENESIS_HASH, json, log, os  # noqa: I001
    async with self._persist_lock:
        if self._chain_initialized:
            return
        if not os.path.lexists(self.path):
            self._chain_initialized = True
            return
        try:
            # Windows: read, and flush when a repair is due, through the verified handle.
            lines = await asyncio.to_thread(_audit_lines, self.path, self.repair_required)
        except Exception as exc:
            # An unreadable file proves neither a broken chain nor a torn
            # append. Retry initialization before the next persist.
            self.durability_degraded = True
            log.error("Audit tail unavailable (%s); durability=degraded", type(exc).__name__)
            return

        if self._signer:
            result = await asyncio.to_thread(
                _verify_audit, self.path, self._signer._key.decode())
            self._historical_break = not result["valid"]
            if self._historical_break:
                log.error(
                    "Audit historical chain break at line %s; durability=degraded; "
                    "resuming from the actual tail", result["first_bad"],
                )
        self.durability_degraded = self._historical_break
        try:
            predecessor = GENESIS_HASH
            # Do not stop at the first historical verification failure: the
            # next append links to the tail actually present on disk.
            for line in reversed(lines):
                if not line.strip():
                    continue
                if not line.endswith("\n"):
                    raise ValueError("Unsettled audit tail")
                entry = json.loads(line)
                tail_hmac = entry.get("_hmac") if isinstance(entry, dict) else None
                if isinstance(tail_hmac, str) and tail_hmac:
                    predecessor = tail_hmac
                break
            if self._signer:
                self._signer.prev_hmac = predecessor
        except Exception as exc:
            log.error(
                "Audit tail unsettled (%s); durability=repair_required", type(exc).__name__,
            )
            self._quarantine_uncertain_append()
        else:
            if self.repair_required:
                try:
                    # Windows settlement: marker ensured, retired, every tombstone flushed.
                    _settle_repair(self._repair_marker)
                except OSError:
                    self._quarantine_uncertain_append()
                else:
                    self.repair_required = False
                    log.info(
                        "Cleared stale audit append marker; tail is complete and parseable",
                    )
        self._chain_initialized = True


# Lifted from the Linux original.
async def history_append(self, line: str) -> None:
    from src.scheduler.history import log  # noqa: I001
    try:
        await asyncio.to_thread(_append_text, self.path, line)
    except Exception as e:
        log.error("Failed to write schedule history: %s", e)

    self._records_since_prune += 1
    if self._records_since_prune >= self._auto_prune_interval:
        self._records_since_prune = 0
        await self._prune_locked()


# Lifted from the Linux original.
async def history_query(
    self,
    schedule_id: str | None = None,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Query history entries (most recent first).

    Args:
        schedule_id: Filter to a specific schedule. None = all.
        status: Filter by status (success/failure).
        limit: Max entries to return.
    """
    from src.scheduler.history import json, log  # noqa: I001
    if not os.path.lexists(self.path):
        return []

    results: list[dict] = []
    try:
        lines = await asyncio.to_thread(_read_text_lines, self.path)
    except Exception as e:
        log.error("Failed to read schedule history: %s", e)
        return []

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if schedule_id and entry.get("schedule_id") != schedule_id:
            continue
        if status and entry.get("status") != status:
            continue

        results.append(entry)
        if len(results) >= limit:
            break

    return results


# Lifted from the Linux original.
async def prune_locked(self) -> int:
    """Compact history file, keeping only the most recent entries per schedule.

    Returns the number of entries removed.
    """
    from src.scheduler.history import MAX_TOTAL_ENTRIES, asyncio, json, log, os  # noqa: I001
    if not os.path.lexists(self.path):
        return 0

    try:
        lines = await asyncio.to_thread(_read_text_lines, self.path)
    except Exception as e:
        log.error("Failed to read history for pruning: %s", e)
        return 0

    # Parse all entries
    entries: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if len(entries) <= MAX_TOTAL_ENTRIES:
        return 0

    # Keep most recent N per schedule
    from collections import defaultdict
    by_schedule: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        sid = entry.get("schedule_id", "unknown")
        by_schedule[sid].append(entry)

    kept: list[dict] = []
    for sid, sid_entries in by_schedule.items():
        # Entries are in chronological order; keep last N
        kept.extend(sid_entries[-self._max_per_schedule:])

    # Sort by timestamp to maintain chronological order
    kept.sort(key=lambda e: e.get("timestamp", ""))

    removed = len(entries) - len(kept)
    if removed > 0:
        try:
            content = "".join(json.dumps(e, default=str) + "\n" for e in kept)
            # Windows: A5 replace in the held folder (a verified temporary file,
            # flushed, renamed by handle, flushed again).
            durable = await asyncio.to_thread(
                _publish_path, self.path, content.encode("utf-8"))
            if not durable:
                raise OSError("pruned history committed but its final flush failed")
            log.info("Pruned %d history entries", removed)
        except Exception as e:
            log.error("Failed to write pruned history: %s", e)
            return 0

    return removed


# Lifted from the Linux original.
def ensure_local_workspace(self) -> str:
    """Resolve and re-validate the cwd for local user commands.

    Raises :class:`WorkspaceError` if the configured directory is unusable.
    Deliberately no fallback: inheriting the process cwd is exactly the
    behaviour that let a bare `rm -rf data` delete the live install.
    """
    # Validated on EVERY call, not cached (PR #239 round-3 review): the
    # configured VALUE is restart-required, but existence, type, ownership
    # and mode are mutable filesystem state. Caching them meant fail-closed
    # only applied to the first command — replacing the directory with a
    # symlink into the install afterwards was accepted, and a post-
    # validation chmod was ignored. The check is a handful of stat calls.
    workspace = str(
        _windows_resolve_workspace(
            self.config.local_working_dir,
            protected_roots=self._protected_roots(),
        )
    )
    self._local_workspace = workspace
    self._local_workspace_resolved = True
    return workspace


# Lifted from the Linux original.
def check_local_workspace(config):
    """Verify the local command workspace against the full live config.

    Local user commands FAIL CLOSED when this directory is missing, wrongly
    owned, or not 0700 — deliberately, because falling back to the install
    directory is the hazard this exists to remove. That makes it an operator-
    visible dependency: without this check a broken workspace shows up as
    every run_command failing, with nothing in the startup report to say why.
    """
    from src.health.startup import DiagnosticResult, _workspace_protected_roots  # noqa: I001
    from src.tools.workspace import WorkspaceError, provisioning_hint

    # Production passes the full Config so independently relocated sessions,
    # context, logs, credentials, and other state are protected exactly as the
    # startup migration and executor protect them. Accept ToolsConfig directly
    # only for focused callers/tests; that intentionally yields the reduced
    # fallback contract.
    tools_config = getattr(config, "tools", config)
    full_config = config if tools_config is not config else None
    configured = getattr(tools_config, "local_working_dir", "") or ""
    try:
        workspace = _windows_resolve_workspace(
            configured,
            protected_roots=_workspace_protected_roots(full_config),
        )
    except WorkspaceError as exc:
        return DiagnosticResult(
            name="local_workspace",
            passed=False,
            detail=f"Local command workspace unusable: {exc}",
            recommendation=provisioning_hint(configured),
            metadata={"configured": configured},
        )
    except Exception as exc:  # pragma: no cover - defensive
        return DiagnosticResult(
            name="local_workspace",
            passed=False,
            detail=f"Local command workspace check failed: {exc}",
            recommendation=provisioning_hint(configured),
            metadata={"configured": configured},
        )
    # A legacy-config fallback is usable, so this still passes — but it must
    # be visible in the report an operator reads, not buried as a path they
    # would have to notice (cross-review of PR #239 round 13).
    from src.tools.workspace import startup_fallback

    fallback = startup_fallback()
    if fallback is not None and str(workspace) == fallback[0]:
        _active, intended, reason = fallback
        return DiagnosticResult(
            name="local_workspace",
            passed=True,
            detail=(
                f"Local command workspace ready at FALLBACK {workspace} — the "
                f"configured default {intended!r} could not be provisioned ({reason})"
            ),
            recommendation=provisioning_hint(intended),
            metadata={
                "path": str(workspace),
                "configured": intended,
                "fallback": True,
            },
        )
    return DiagnosticResult(
        name="local_workspace",
        passed=True,
        detail=f"Local command workspace ready: {workspace}",
        metadata={"path": str(workspace)},
    )


# Lifted from the Linux original.
def validate_hyprland_path(cls, value: str) -> str:
    if value and (
        len(value) > 4096
        or not PurePosixPath(value).is_absolute()
        or ".." in PurePosixPath(value).parts
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("Hyprland paths must be explicit absolute local paths")
    return value


# Lifted from the Linux original.
def validate_wayland_guardian_binary(cls, value: str) -> str:
    if (
        not value
        or len(value) > 4096
        or not PurePosixPath(value).is_absolute()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("computer.wayland_guardian_binary must be an absolute executable path")
    return value
