"""Package compatibility before writable attachment, not a replacement store."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import uuid
from pathlib import Path

from ..turn_state.codec import CODEC_VERSION
from ..turn_state.store import SCHEMA_VERSION
from .paths import ProfilePaths
from .protocol import PROTOCOL_MAJOR, PROTOCOL_MINOR
from .schema import validate_domains

STATE_NAME = "package-state.json"
BACKUPS_NAME = "package-backups"
STORAGE_VERSION = 1
RECORD_VERSION = 1


class PackageStateError(RuntimeError):
    """Upgrade did not establish compatible durable state. No weaker startup."""


def compatibility() -> dict:
    from ..computer.store import STORE_SCHEMA_VERSION

    return {"protocol_major": PROTOCOL_MAJOR, "protocol_minor": PROTOCOL_MINOR,
            "storage": STORAGE_VERSION, "turn_schema": SCHEMA_VERSION,
            "checkpoint": CODEC_VERSION, "computer": STORE_SCHEMA_VERSION}


def _check_versions(value):
    current = compatibility()
    if (not isinstance(value, dict) or set(value) != set(current)
            or any(type(v) is not int or v < 0 for v in value.values())
            or value["protocol_major"] != current["protocol_major"]
            or any(value[k] > current[k] for k in current if k != "protocol_major")):
        raise PackageStateError("Package state is incompatible; original state preserved")


@contextlib.contextmanager
def _reader(path: Path):
    """Anchor every directory without creating, chmodding or following links."""
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    fd = None
    try:
        for name in path.parts[1:-1]:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1):
            raise PackageStateError("Unsafe package state file; original state preserved")
        with os.fdopen(fd, "rb") as stream:
            fd = None
            yield stream
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)


def _json(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PackageStateError("Ambiguous package state record")
            result[key] = value
        return result

    with _reader(path) as stream:
        if os.fstat(stream.fileno()).st_size > 1024 * 1024:
            raise PackageStateError("Oversized package state record")
        return json.load(stream, object_pairs_hook=unique)


def _record(paths):
    try:
        record = _json(paths.data_dir / STATE_NAME)
    except FileNotFoundError:
        return None
    if (not isinstance(record, dict) or set(record) != {
            "record_version", "profile_id", "identity", "package_version",
            "compatibility", "state", "backup"}
            or type(record["record_version"]) is not int
            or record["record_version"] != RECORD_VERSION
            or record["profile_id"] != paths.profile_id
            or not isinstance(record["package_version"], str)
            or not isinstance(record["identity"], str)
            or record["state"] not in {"pending", "committed"}
            or not isinstance(record["backup"], str)):
        raise PackageStateError("Invalid package state record; explicit recovery required")
    try:
        if str(uuid.UUID(record["backup"])) != record["backup"]:
            raise ValueError()
    except ValueError:
        raise PackageStateError("Invalid package backup identity") from None
    _check_versions(record["compatibility"])
    return record


@contextlib.contextmanager
def _database(path):
    """Inspect a private copy with WAL. SQLite cannot create SHM in profile.

    immutable=1 on the source would ignore WAL and miss newer committed state.
    SQLite may recover only our disposable copy, never the owned original.
    """
    with tempfile.TemporaryDirectory(prefix="odin-package-inspect-") as root:
        copied = Path(root) / path.name
        for suffix in ("", "-wal", "-journal"):
            try:
                with _reader(Path(str(path) + suffix)) as source:
                    with (Path(str(copied) + suffix)).open("xb") as output:
                        os.chmod(output.name, 0o600)
                        while chunk := source.read(1024 * 1024):
                            output.write(chunk)
            except FileNotFoundError:
                if not suffix:
                    yield None
                    return
        db = sqlite3.connect(copied)
        try:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise PackageStateError("Unreadable package storage")
            yield db
        finally:
            db.close()


def _transport(path, paths, identity):
    with _database(path) as db:
        if db is None:
            return
        if db.execute("PRAGMA user_version").fetchone()[0] > STORAGE_VERSION:
            raise PackageStateError("Newer transport storage; original state preserved")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {"journal_meta": {"singleton", "profile_id", "identity", "event_high",
                                    "event_floor"},
                   "command_receipts": {"command_id", "binding", "state", "response", "created_at",
                                        "finished_at", "unknown_outcome"},
                   "journal_events": {"seq", "frame"}}
        if not validate_domains(db, tables, set(columns)):
            raise PackageStateError("Incompatible transport schema; original state preserved")
        for table, expected in columns.items():
            if {r[1] for r in db.execute(f"PRAGMA table_info({table})")} != expected:
                raise PackageStateError("Incompatible transport columns")
        rows = db.execute("SELECT profile_id,identity FROM journal_meta").fetchall()
        if rows != [(paths.profile_id, identity)]:
            raise PackageStateError("Foreign transport journal; original state preserved")


def _turns(path):
    # D17 retains the inherited optional-ledger failed-open startup behavior.
    # A directory at the DB slot is unavailability, not a newer checkpoint.
    # Symlinks and actual unreadable/incompatible databases still refuse.
    try:
        if stat.S_ISDIR(path.lstat().st_mode):
            return
    except FileNotFoundError:
        return
    with _database(path) as db:
        if db is None:
            return
        if db.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
            raise PackageStateError("Newer turn storage; original fences preserved")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables != {"turns", "operations"}:
            raise PackageStateError("Incompatible turn storage; original fences preserved")
        from ..turn_state.store import _DDL

        with contextlib.closing(sqlite3.connect(":memory:")) as reference:
            reference.executescript(_DDL)
            for table, legacy in (("turns", {"payload_digest"}), ("operations", {"effect_class"})):
                expected = {r[1] for r in reference.execute(f"PRAGMA table_info({table})")}
                actual = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                if not expected - legacy <= actual <= expected:
                    raise PackageStateError("Incompatible turn columns; original fences preserved")
        for version, payload in db.execute("SELECT schema_version,payload FROM turns"):
            if type(version) is not int or version != SCHEMA_VERSION:
                raise PackageStateError("Incompatible checkpoint schema; original fences preserved")
            if payload is not None:
                document = json.loads(payload)
                codec = document.get("codec_version") if isinstance(document, dict) else None
                if type(codec) is not int or not 1 <= codec <= CODEC_VERSION:
                    raise PackageStateError("Incompatible checkpoint codec; fences preserved")


def _computer(path):
    from ..computer.store import STORE_SCHEMA_VERSION, ComputerStore

    with _database(path) as db:
        if db is None:
            return
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, STORE_SCHEMA_VERSION}:
            raise PackageStateError("Newer computer storage; quarantine preserved")
        validator = object.__new__(ComputerStore)
        validator.db = db
        if version == 0:
            validator._validate_base_schema()
        else:
            validator._validate_current_schema(allow_obsolete_restrictions=True)


def inspect_profile(paths: ProfilePaths, *, package_version: str | None = None) -> dict | None:
    """No profile writes, locks, defaults, migrations, or ledger boot sweeps."""
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
            from .authority import OwnerAuthority

            validator = object.__new__(OwnerAuthority)
            validator.paths = paths
            validator.owner_uid = os.geteuid()
            validator._validate(identity)
            if stat.S_IMODE(paths.identity_file.lstat().st_mode) != 0o600:
                raise PackageStateError("Unsafe profile identity; original state preserved")
            binding = f"{identity['installation_id']}:{identity['owner_id']}"
            if record and record["identity"] != binding:
                raise PackageStateError("Foreign package state identity")
        elif record:
            raise PackageStateError("Package state has no owner identity")
        _transport(paths.data_dir / "transport.sqlite3", paths, binding)
        for name in ("turns.db", "turns.sqlite3"):
            _turns(paths.data_dir / "turn_state" / name)
        _computer(paths.data_dir / "computer" / "state.sqlite3")
        return record
    except PackageStateError:
        raise
    except Exception:
        raise PackageStateError(
            "Package compatibility inspection failed; original state preserved") from None


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish(path, document):
    fd, temporary = tempfile.mkstemp(prefix=".package-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(document, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class PackageUpgrade:
    """Two durable phases around existing migration owners under runtime lock.

    Existing owners migrate; this seam never restores or rewrites their stores.
    Interrupted startup resumes compatible idempotent owners, not external work.
    """

    def __init__(self, paths, authority, package_version):
        self.paths, self.authority = paths, authority
        self.package_version = package_version
        self.record = None

    def _owned(self):
        if (self.authority.durability_degraded or not self.authority._runtime_current()
                or not self.authority._identity_current()):
            raise PackageStateError("Package migration requires durable runtime ownership")

    def prepare(self):
        self._owned()
        with self.authority._locked():
            record = inspect_profile(self.paths)
            identity = f"{self.authority.installation_id}:{self.authority.owner_id}"
            if record:
                self._verify_backup(record)
                with _reader(self.paths.data_dir / STATE_NAME) as stream:
                    os.fsync(stream.fileno())
                _sync_directory(self.paths.data_dir)
            if (record and record["state"] == "committed"
                    and record["package_version"] == self.package_version
                    and record["compatibility"] == compatibility()):
                return
            if record and record["state"] == "pending":
                if (record["package_version"] != self.package_version
                        or record["compatibility"] != compatibility()):
                    raise PackageStateError("Interrupted upgrade requires its compatible candidate")
            else:
                backup = self._backup()
                record = {"record_version": RECORD_VERSION, "profile_id": self.paths.profile_id,
                          "identity": identity, "package_version": self.package_version,
                          "compatibility": compatibility(), "state": "pending", "backup": backup}
                _publish(self.paths.data_dir / STATE_NAME, record)
            self.record = record

    def _backup(self):
        root = self.paths.data_dir / BACKUPS_NAME
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            info = root.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077):
                raise PackageStateError("Unsafe package backup directory")
        backup = str(uuid.uuid4())
        destination = root / backup
        destination.mkdir(mode=0o700)
        entries = {}
        excluded = {".identity.lock", ".core.lock", "ipc.token"}
        for label, source in (("config", self.paths.config_dir), ("data", self.paths.data_dir)):
            for folder, directories, files in os.walk(source, followlinks=False):
                relative = Path(folder).relative_to(source)
                directories[:] = [d for d in directories if not (
                    label == "data" and relative == Path(".") and d in {BACKUPS_NAME, "logs"})]
                target = destination / label / relative
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                for directory in directories:
                    info = (Path(folder) / directory).lstat()
                    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
                        raise PackageStateError("Unsafe package backup source directory")
                for name in files:
                    if name in excluded or (label == "data" and relative == Path(".")
                                            and name == STATE_NAME):
                        continue
                    digest = hashlib.sha256()
                    with (_reader(Path(folder) / name) as stream,
                          (target / name).open("xb") as output):
                        os.fchmod(output.fileno(), 0o600)
                        before = os.fstat(stream.fileno())
                        while chunk := stream.read(1024 * 1024):
                            digest.update(chunk)
                            output.write(chunk)
                        after = os.fstat(stream.fileno())
                        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                            raise PackageStateError("Package backup source changed")
                        output.flush()
                        os.fsync(output.fileno())
                    entries[str(Path(label) / relative / name)] = digest.hexdigest()
        _publish(destination / "manifest.json", {"version": 1, "files": entries})
        for folder, _, _ in os.walk(destination, topdown=False):
            _sync_directory(Path(folder))
        _sync_directory(root)
        _sync_directory(self.paths.data_dir)
        return backup

    def _verify_backup(self, record):
        root = self.paths.data_dir / BACKUPS_NAME / record["backup"]
        manifest = _json(root / "manifest.json")
        if (not isinstance(manifest, dict) or set(manifest) != {"version", "files"}
                or manifest["version"] != 1 or not isinstance(manifest["files"], dict)):
            raise PackageStateError("Invalid package backup; explicit recovery required")
        for name, expected in manifest["files"].items():
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or path.parts[0] not in {"config", "data"}:
                raise PackageStateError("Invalid package backup path")
            digest = hashlib.sha256()
            with _reader(root / path) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise PackageStateError("Package backup integrity unproven; state preserved")

    def commit(self):
        self._owned()
        if self.record is None:
            return
        with self.authority._locked():
            current = inspect_profile(self.paths)
            if current != self.record:
                raise PackageStateError("Package upgrade record changed")
            self._verify_backup(current)
            _publish(self.paths.data_dir / STATE_NAME, {**current, "state": "committed"})
            self.record = None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Desktop package state compatibility")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        paths = ProfilePaths.from_app(args.profile, token_file=args.token_file,
                                      data_dir=args.data_dir)
        from ..version import get_version

        inspect_profile(paths, package_version=get_version())
    except (PackageStateError, OSError, ValueError):
        print("Odin Desktop state is incompatible or unavailable; original state preserved")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
