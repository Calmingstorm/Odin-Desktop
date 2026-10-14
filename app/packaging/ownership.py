#!/usr/bin/env python3
"""Install lifetime leases. Filesystem barrier only, never process control.

On macOS (the per-user ``macos`` installation, a .dmg) the lease is the AppImage kind's flock on
``~/Library/odin-desktop/.install-ownership/macos``, inside the engine's private namespace (the dot
keeps it apart from every profile); its folders are checked, never repaired (``_open_darwin``). A
.dmg has no installer hook, so nothing replaces the app under a held lease: upgrading is Quit,
check the cleanup result, then replace. The app's start does the rest (``_darwin_start_check``):
it refuses resources that differ from the app's manifest, and after a replacement it judges the
earlier lifetimes as Linux's and Windows' replacement guards do, before the profile opens. The
resources (Contents/Resources) are everything Odin ships in the app; the rest of the bundle,
Electron's executable and frameworks and Info.plist, isn't checked here. In the signed app, that
code is covered by the Developer ID signature, which macOS checks as the code loads.

On Windows (the per-user ``nsis`` installation) the lease is a ``LockFileEx`` lock on one fixed
byte of ``lease``, a private file outside the install tree, in
``%LOCALAPPDATA%/odin-desktop/install-ownership/nsis``: shared for the app and the core, exclusive
for a replacement. The byte is at offset ``0x7FFFFFFF00000000``, length 1, so it never blocks the
file's own reads or writes. The bundled engine's Windows file helpers open and verify the file by
handle, without following a link, and the open handle refuses deletion, so the lease can't be
replaced while it's held.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

WINDOWS = sys.platform == 'win32'
DARWIN = sys.platform == 'darwin'
if not WINDOWS:
    import fcntl

DEB_ROOT = Path('/var/lib/odin-desktop/package-ownership')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
_BOOT_ID_SHAPE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


class OwnershipError(RuntimeError):
    pass


class PendingReplacement(OwnershipError):  # noqa: N818
    """A package transaction is unfinished; the Windows guardian exits PENDING_EXIT for it."""


# The Windows app names the remedy for this refusal (run the installer again); others exit 1.
PENDING_EXIT = 75


# Windows' publish primitive writes ".<name>.<32 hex>.tmp" beside its target and renames it into
# place; one that is still there is an interrupted write's leftover, never a published file.
_PUBLISH_LEFTOVER = re.compile(r'\..+\.[0-9a-f]{32}\.tmp')
# _write's own on Linux and the Mac: "<receipt>.<32 hex>.pending", for a receipt's exact name.
_POSIX_PUBLISH_LEFTOVER = re.compile(r'[0-9]+-[0-9a-f]{32}-(?:app|core)\.json\.[0-9a-f]{32}\.pending')

# The Mac start check's refusals. Each has its own exit, which the app words with the remedy.
MAC_FILES_CHANGED = 80  # the app's files differ from its manifest: reinstall it
MAC_STILL_STOPPING = 81  # an earlier lifetime still holds the lease: wait, then open it again
MAC_RESTART = 82  # replaced after a lifetime this boot that didn't end clean: restart the Mac
MAC_LASTING = 83  # replaced, and an earlier lifetime can't be judged: a restart won't change it
BUNDLE_RECORD = 'bundle.json'
# Beside the manifest's files, the check accepts only Finder's folder settings, which nothing runs.
# Bytecode caches are refused: Python runs a valid cache in place of its unchanged source, and the
# app writes none (every interpreter it starts runs -B).
_TOLERATED_EXTRA = re.compile(r'(?:.+/)?\.DS_Store')
_DIGEST = re.compile(r'[0-9a-f]{64}')


class StartRefusal(OwnershipError):  # noqa: N818 - PendingReplacement's naming
    """macOS: the start check refused; ``code`` is its exit."""

    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code


@dataclass(frozen=True)
class OwnershipPaths:
    directory: Path

    @property
    def lease(self):
        return self.directory / 'lease'

    @property
    def pending(self):
        return self.directory / 'transaction.json'

    @property
    def receipts(self):
        return self.directory / 'receipts'


def ownership_paths(kind='appimage', env=None):
    env = os.environ if env is None else env
    if kind == 'deb':
        return OwnershipPaths(DEB_ROOT)
    if kind == 'nsis':
        local = env.get('LOCALAPPDATA') or ''
        if not re.fullmatch(r'[A-Za-z]:[\\/].*', local) or '..' in re.split(r'[\\/]', local):
            raise OwnershipError('LOCALAPPDATA must be an absolute local folder')
        return OwnershipPaths(Path(local) / 'odin-desktop' / 'install-ownership' / 'nsis')
    if kind == 'macos':
        home = Path(env.get('HOME') or Path.home())
        return OwnershipPaths(home / 'Library' / 'odin-desktop' / '.install-ownership' / 'macos')
    if kind != 'appimage':
        raise OwnershipError('Unsupported installation kind')
    home = Path(env.get('HOME') or Path.home())
    state = Path(env.get('XDG_STATE_HOME') or home / '.local/state')
    return OwnershipPaths(state / 'odin-desktop/install-ownership/appimage')


def _open(paths):
    if WINDOWS:
        return _open_windows(paths)
    if DARWIN and paths.directory != DEB_ROOT:
        return _open_darwin(paths)
    if paths.directory != DEB_ROOT:
        paths.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        paths.receipts.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(paths.lease, os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    else:
        fd = os.open(paths.lease, os.O_RDONLY | os.O_NOFOLLOW)
    info = os.fstat(fd)
    directory = paths.directory.lstat()
    owner = 0 if paths.directory == DEB_ROOT else os.getuid()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner
            or info.st_nlink != 1 or info.st_mode & 0o022
            or not stat.S_ISDIR(directory.st_mode) or directory.st_uid != owner
            or directory.st_mode & 0o022):
        os.close(fd)
        raise OwnershipError('Install lease ownership is not trusted')
    return fd


def _allow_entries(fd):
    """macOS: the extended ACL's allow entries on fd's file, as the engine reads them."""
    from src.desktop.platform import darwin

    return darwin.allow_entries(fd)


def _darwin_folder(parent, name, path, *, owned, root=False):
    """One folder of the Mac lease's chain, opened below ``parent``, which this closes."""
    try:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
        try:
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        except OSError as error:
            raise OwnershipError(
                f'Unsafe install ownership folder {path}: {error.strerror}') from None
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        if owned:
            safe = (info.st_uid == os.geteuid() and not info.st_mode & (0o022 if root else 0o077)
                    and not _allow_entries(fd))
        else:
            safe = info.st_uid in {0, os.geteuid()}
        if not safe:
            raise OwnershipError(f'Unsafe install ownership folder: {path}')
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_darwin(paths):
    """macOS: the lease, and every folder above it, checked through held no-follow descriptors.

    The folders above ``odin-desktop`` aren't ours: a missing one is created 0700, and an existing
    one need only be root's or this user's; none is changed or inspected further. ``odin-desktop``
    (the engine's namespace root, which the profiles share) and the lease's own folders below it
    are created 0700 when missing. An existing one must be a real folder (never a link), this
    user's, carry no ACL allow entry (an inheritable one would reach every file created below it)
    and give group and other no write on ``odin-desktop`` and no access at all below it. The
    lease file must be a private regular file of this user's, with one link and no allow entry.
    Unsafe existing state is refused, never repaired."""
    parts = paths.directory.parts
    if 'odin-desktop' not in parts[:-1]:
        raise OwnershipError('The Mac lease must be inside the odin-desktop namespace')
    split = parts.index('odin-desktop')
    outside = Path(os.path.realpath(Path(*parts[:split])))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    current = Path('/')
    for name in outside.parts[1:]:
        current /= name
        fd = _darwin_folder(fd, name, current, owned=False)
    for depth, name in enumerate(parts[split:]):
        current /= name
        fd = _darwin_folder(fd, name, current, owned=True, root=depth == 0)
    try:
        os.close(_darwin_folder(os.dup(fd), 'receipts', current / 'receipts', owned=True))
        try:
            lease = os.open('lease', os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        except OSError as error:
            raise OwnershipError(f'Install lease is not trusted: {error.strerror}') from None
    finally:
        os.close(fd)
    try:
        info = os.fstat(lease)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1
                or info.st_mode & 0o077 or _allow_entries(lease)):
            raise OwnershipError('Install lease ownership is not trusted')
    except BaseException:
        os.close(lease)
        raise
    return lease


def _open_windows(paths):
    """The lease's handle: its folders created private, the file verified by handle (this
    user's, private, one link, no reparse point), and its delete sharing refused."""
    from src.desktop.platform import windows_files

    windows_files.private_directory(paths.receipts)
    with windows_files.held(paths.directory) as chain:
        return windows_files.open_file(chain, 'lease', create=True, lock=True)


def _lock(fd, *, exclusive):
    """A non-blocking whole-lease lock; one already held elsewhere raises BlockingIOError."""
    if WINDOWS:
        from src.desktop.platform import win32

        win32.lock(fd, blocking=False, shared=not exclusive)
    else:
        fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)


def _close(fd):
    if WINDOWS:
        from src.desktop.platform import win32

        win32.close(fd)
    else:
        os.close(fd)


def _owner():
    """Who holds a lifetime: the uid, or on Windows the user's SID."""
    if WINDOWS:
        from src.desktop.platform.windows_files import user_sid

        return user_sid()
    return os.getuid()


def _pending(paths):
    if paths.pending.exists() or (paths.directory / 'appimage-replacement.json').exists():
        raise PendingReplacement('Package replacement is pending; finish the external transaction')


def _read(path):
    if WINDOWS:
        from src.desktop.platform import windows_files

        # A regular file reached without following a link, as O_NOFOLLOW reads one.
        fd = windows_files.to_fd(windows_files.open_plain(path), os.O_RDONLY)
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise OwnershipError('Cleanup evidence is not an object')
        return value
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OwnershipError('Cleanup evidence is not a regular file')
        with os.fdopen(fd, 'r') as stream:
            fd = None
            value = json.load(stream)
            if not isinstance(value, dict):
                raise OwnershipError('Cleanup evidence is not an object')
            return value
    finally:
        if fd is not None:
            os.close(fd)


def _fingerprint(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def _boot_id():
    """This boot's kernel identity, or None when it cannot be read or is malformed."""
    if WINDOWS:
        # The kernel's boot identifier GUID, the same source and shape the core records.
        from src.desktop.platform import win32

        value = win32.boot_identifier()
        return value if value and _BOOT_ID_SHAPE.fullmatch(value) else None
    if DARWIN:
        # kern.bootsessionuuid, lowercased: the same source and shape the core records.
        from src.desktop.platform import darwin

        try:
            value = darwin.current_boot_id()
        except OSError:
            return None
        return value if value and _BOOT_ID_SHAPE.fullmatch(value) else None
    try:
        value = BOOT_ID.read_text().strip()
    except OSError:
        return None
    return value if _BOOT_ID_SHAPE.fullmatch(value) else None


def _earlier_boot(recorded, current):
    """No process or native resource of a lifetime survives the boot it ran in.

    Only a well-formed kernel boot identity that differs from a readable current one
    counts. A missing or malformed one, as from an older candidate, stays fenced.
    """
    return bool(isinstance(recorded, str) and _BOOT_ID_SHAPE.fullmatch(recorded)
                and current and recorded != current)


def _clean(app_cleanup, core_cleanup, role):
    # Judge this lifetime's own Exit. A core unknown the shared profile retains from
    # this boot fences it too: installation kinds keep separate receipts. Once the boot
    # it happened in has ended, nothing it held survives and it no longer fences; the
    # retained notice and history stay visible and are never cleared here.
    core = _read(core_cleanup)
    resources = core.get('resources')
    previous = core.get('previous_unknown')
    # The newest unresolved lifetime's boot decides; the retained notice is the first one.
    # Only a journal written before that binding existed uses the notice's own boot: an
    # empty binding (a boot that could not be read) stays fenced.
    if 'latest_unknown_boot_id' in core:
        latest = core['latest_unknown_boot_id']
    else:
        latest = previous.get('boot_id') if isinstance(previous, dict) else None
    if (core.get('version') != 1 or core.get('state') != 'complete'
            or (previous is not None and not _earlier_boot(latest, _boot_id()))
            or not isinstance(resources, dict)
            or not {'computer', 'processes'}.issubset(resources)
            or any(row.get('state') not in {'released', 'not_started'}
                   for row in resources.values() if isinstance(row, dict))
            or any(not isinstance(row, dict) for row in resources.values())):
        raise OwnershipError('Core resource cleanup is unresolved')
    if role == 'app':
        app = _read(app_cleanup)
        current = app.get('current', app)
        if (not isinstance(current, dict) or current.get('state') != 'process-exited'
                or current.get('shutdownAccepted') is not True
                or current.get('processOutcome') not in {'exited', 'not-running'}
                or current.get('unsaved') or current.get('unreceipted', 0)):
            raise OwnershipError('Current app Exit is not clean')


def _write(path, value):
    if WINDOWS:
        from src.desktop.platform.windows_engine import write_private_atomic

        # Flushed, renamed by handle and the rename flushed, as the fsyncs below do.
        if not write_private_atomic(path, json.dumps(value, sort_keys=True)):
            raise OwnershipError('Lifetime receipt is not durable')
        return
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.pending')
    # The Mac's are private to this user, as everything in its namespace is.
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600 if DARWIN else 0o644)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temp.exists():
            temp.unlink()


def _raise(error):
    raise error


def _bundle_walk(root):
    """Every entry below ``root`` in a fixed order, never following a link: (relative, lstat).
    A folder that can't be read raises: an inventory with a gap in it never passes."""
    for directory, folders, files in os.walk(root, onerror=_raise):
        folders.sort()
        base = Path(directory)
        for name in sorted(folders + files):
            path = base / name
            yield path.relative_to(root).as_posix(), path.lstat()


def _bundle_metadata(root):
    """One digest of every entry's metadata. A copy, a replacement or a write changes it; reading
    doesn't. An attribute change (ctime) does too, which costs one full check, never a refusal."""
    value = hashlib.sha256()
    for relative, info in _bundle_walk(root):
        value.update(f'{relative}\0{info.st_mode}\0{info.st_size}\0{info.st_mtime_ns}\0'
                     f'{info.st_ctime_ns}\0{info.st_ino}\n'.encode('utf-8', 'surrogateescape'))
    return value.hexdigest()


def _listed(path, info, item):
    """Whether one entry is as the manifest lists it (``manifest.inventory``'s fields). A link's
    own mode isn't compared: macOS doesn't use it, and a copy takes it from the umask."""
    if stat.S_ISLNK(info.st_mode):
        return item.get('type') == 'symlink' and os.readlink(path) == item.get('target')
    if not stat.S_ISREG(info.st_mode):
        return False
    if (item.get('type') != 'file' or item.get('size') != info.st_size
            or item.get('mode') != stat.S_IMODE(info.st_mode)):
        return False
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() == item.get('sha256')


def _verify_bundle(resources, manifest):
    """Every file and link the manifest lists, as it lists them, and nothing else beside them but
    the tolerated extras. Raises a StartRefusal naming the first differences; a file that can't be
    read counts as changed."""
    try:
        listed = json.loads(manifest.read_bytes())
        files = listed['files']
        expected = {item['path']: item for item in files}
        if listed.get('schema') != 1 or not files or len(expected) != len(files):
            raise ValueError('unsupported manifest')
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise StartRefusal(MAC_FILES_CHANGED,
                           'The app\'s resource manifest is unreadable') from None
    changed, extra = [], []
    try:
        entries = list(_bundle_walk(resources))
    except OSError as error:
        raise StartRefusal(MAC_FILES_CHANGED,
                           f'The app\'s resources can\'t be read: {error.strerror}') from None
    for relative, info in entries:
        if relative == 'bundle-manifest.json' or stat.S_ISDIR(info.st_mode):
            continue
        item = expected.pop(relative, None)
        if item is None:
            if not _TOLERATED_EXTRA.fullmatch(relative):
                extra.append(relative)
            continue
        try:
            unchanged = _listed(resources / relative, info, item)
        except OSError:
            unchanged = False
        if not unchanged:
            changed.append(relative)
    if expected or changed or extra:
        details = {'missing': sorted(expected)[:5], 'changed': changed[:5], 'extra': extra[:5]}
        difference = json.dumps(details, sort_keys=True)
        raise StartRefusal(MAC_FILES_CHANGED, f'App files differ from its manifest: {difference}')


def _bundle_record(paths):
    """The last app that passed, from a whole version-1 record. Anything else (none, unreadable,
    another version, a missing or malformed digest) is None: everything is checked again and the
    earlier lifetimes are judged, as at a first start."""
    try:
        record = _read(paths.directory / BUNDLE_RECORD)
    except (OSError, ValueError, OwnershipError):
        return None
    if (set(record) != {'version', 'manifest', 'files'} or type(record['version']) is not int
            or record['version'] != 1
            or not all(isinstance(record[key], str) and _DIGEST.fullmatch(record[key])
                       for key in ('manifest', 'files'))):
        return None
    return record


def _darwin_start_check(paths, fd, resources):
    """macOS: the app's resources, and after they change, the earlier lifetimes.

    Raises StartRefusal.

    A .dmg has no replacement transaction, so this is where Linux's and Windows' replacement
    guards run on the Mac: at the first start after a replacement, before the profile opens.
    ``bundle.json`` records the last app that passed (its manifest's digest and one digest of every
    entry's metadata), so an unchanged start is a metadata walk. Otherwise every file is checked
    against the app's manifest. When the manifest itself changed, as a replacement changes it, the
    earlier lifetimes are judged as the replacement guards judge them: one that ran in this boot
    must have ended clean. Every other holder must have released the lease first, so a lifetime
    still running is never judged as an old one. After an unclean lifetime with no replacement,
    the start goes ahead, as on Linux and Windows: the cleanup notice reports it. The record is
    written only once every check has passed."""
    manifest = resources / 'bundle-manifest.json'
    try:
        identity = _fingerprint(manifest)
        observed = _bundle_metadata(resources)
    except OSError as error:
        raise StartRefusal(MAC_FILES_CHANGED,
                           f'The app\'s resources can\'t be read: {error.strerror}') from None
    if identity is None:
        raise StartRefusal(MAC_FILES_CHANGED, 'The app has no resource manifest')
    record = _bundle_record(paths)
    if record == {'version': 1, 'manifest': identity, 'files': observed}:
        return
    _verify_bundle(resources, manifest)
    if record is None or record['manifest'] != identity:
        try:
            _lock(fd, exclusive=True)
        except BlockingIOError:
            raise StartRefusal(MAC_STILL_STOPPING,
                               'An earlier Odin lifetime still holds the install lease') from None
        try:
            code, refusals = receipts_verdict(paths)
        except Exception as error:  # noqa: BLE001 - however it fails, it can't be judged
            code, refusals = RECEIPTS_LASTING, [f'{type(error).__name__}: {error}']
        if code:
            raise StartRefusal(MAC_RESTART if code == RECEIPTS_RESTART else MAC_LASTING,
                               '; '.join(refusals))
    _write(paths.directory / BUNDLE_RECORD,
           {'version': 1, 'manifest': identity, 'files': observed})


class Lease:
    def __init__(self, paths, role, app_cleanup, core_cleanup, *, provisional=False,
                 resources=None):
        self.paths, self.role = paths, role
        self.app_cleanup, self.core_cleanup = Path(app_cleanup), Path(core_cleanup)
        self.fd = _open(paths)
        try:
            if DARWIN and resources is not None:
                _darwin_start_check(paths, self.fd, Path(resources))
            _lock(self.fd, exclusive=False)
            _pending(paths)
            self.initial_core = _fingerprint(self.core_cleanup)
            self.initial_app = _fingerprint(self.app_cleanup)
            self.receipt = None
            self.record = {'version': 1, 'role': role, 'state': 'running',
                           'uid': _owner(), 'boot_id': _boot_id(),
                           'app_cleanup': str(self.app_cleanup),
                           'core_cleanup': str(self.core_cleanup)}
            if not provisional:
                self.begin()
        except BaseException:
            self.close()
            raise

    def begin(self):
        """Publish admission only after read-only compatibility succeeds.

        A provisional lease still fences replacement, but has acquired no
        profile, process or native resource whose cleanup requires attestation.
        """
        if self.receipt is None:
            # Windows' receipts folder is already this user's, and a full SID in the name could
            # push the publish's temporary name past MAX_PATH; the record still names the SID.
            owner = '' if WINDOWS else f'{os.getuid()}-'
            self.receipt = self.paths.receipts / (
                f'{owner}{uuid.uuid4().hex}-{self.role}.json')
            _write(self.receipt, self.record)

    def finish(self):
        if self.receipt is None:
            return
        if _fingerprint(self.core_cleanup) == self.initial_core:
            raise OwnershipError('No new core cleanup receipt for this lifetime')
        if self.role == 'app' and _fingerprint(self.app_cleanup) == self.initial_app:
            raise OwnershipError('No new app Exit receipt for this lifetime')
        _clean(self.app_cleanup, self.core_cleanup, self.role)
        _write(self.receipt, {**self.record, 'state': 'clean'})

    def close(self):
        if self.fd is not None:
            _close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def acquire_lifetime(paths, role, app_cleanup, core_cleanup, *, provisional=False, resources=None):
    """``resources``: the Mac app's own folder, whose start check runs first (the app role only)."""
    if role not in {'app', 'core'}:
        raise OwnershipError('Unsupported lifetime role')
    if resources is not None and role != 'app':
        raise OwnershipError('Only the app checks its files at start')
    return Lease(paths, role, app_cleanup, core_cleanup, provisional=provisional,
                 resources=resources)


def _receipt_files(paths):
    leftover = _PUBLISH_LEFTOVER if WINDOWS else _POSIX_PUBLISH_LEFTOVER
    for path in paths.receipts.iterdir():
        if leftover.fullmatch(path.name):
            # A write cut off by a kill or a power cut: never renamed into place, so never a
            # receipt. An interrupted begin admitted nothing (the app and core wait for it before
            # any work), and an interrupted finish left the receipt it was replacing, which fences
            # on its own. Read, it would fence every later replacement until removed by hand.
            continue
        yield path


def _judge(receipt, boot):
    """One receipt: a lifetime from an earlier boot no longer fences; one from this boot must have
    ended clean, its record complete and its cleanup evidence intact. Raises when it fences."""
    if _earlier_boot(receipt.get('boot_id'), boot):
        return
    if receipt.get('state') != 'clean':
        raise OwnershipError('Unresolved lifetime evidence blocks replacement')
    if not all(key in receipt for key in ('app_cleanup', 'core_cleanup', 'role')):
        raise OwnershipError('Incomplete lifetime receipt blocks replacement')
    _clean(receipt['app_cleanup'], receipt['core_cleanup'], receipt['role'])


def verify_receipts(paths):
    """Replacement's receipt verdict: raises at the first receipt that fences."""
    if not paths.receipts.is_dir():
        return  # no lifetime has ever been admitted here
    boot = _boot_id()
    for path in _receipt_files(paths):
        _judge(_read(path), boot)


# The receipts verdict's answers. Restart is 3, never 1: Python exits 1 on any unexpected failure,
# and that must never read as restart advice.
RECEIPTS_LASTING = 2
RECEIPTS_RESTART = 3


def _refusal(path, error):
    reason = str(error) if isinstance(error, OwnershipError) else f'{type(error).__name__}: {error}'
    return f'{path.name}: {reason}'


def receipts_verdict(paths):
    """The Windows installer's question, over every receipt, with the same judgement.

    0: replacement may proceed. RECEIPTS_RESTART: only receipts bound to this boot refuse it, and
    a restart ends them: each records this boot's well-formed identity, which is readable, so once
    another boot runs, _judge returns before reading anything else and none fences. That holds
    whatever made one refuse, so every failure while judging a bound receipt is a restart one.
    RECEIPTS_LASTING: something a restart won't change refuses it, such as a receipt that can't be
    read, or one that records no well-formed boot (a lifetime admitted while the boot identity was
    unreadable) and so never becomes an earlier boot's. A lasting refusal outranks restart advice
    whatever order the folder lists them in, and one receipt's failure, of any kind, never stops
    the others being judged. Returns the code and every refusal."""
    if not paths.receipts.is_dir():
        return 0, []
    boot = _boot_id()
    restart, lasting = [], []
    for path in _receipt_files(paths):
        try:
            receipt = _read(path)
        except Exception as error:  # noqa: BLE001 - however it fails, it can't be read
            lasting.append(_refusal(path, error))
            continue
        try:
            _judge(receipt, boot)
        except Exception as error:  # noqa: BLE001 - a receipt not shown clean, for any reason
            recorded = receipt.get('boot_id')
            bound = boot is not None and isinstance(recorded, str) and bool(
                _BOOT_ID_SHAPE.fullmatch(recorded))
            (restart if bound else lasting).append(_refusal(path, error))
    code = RECEIPTS_LASTING if lasting else RECEIPTS_RESTART if restart else 0
    return code, lasting + restart


@contextmanager
def replacement_guard(paths, check_receipts=True):
    fd = _open(paths)
    try:
        try:
            _lock(fd, exclusive=True)
        except BlockingIOError as error:
            raise OwnershipError('Exit both app and core before replacement') from error
        if check_receipts:
            verify_receipts(paths)
        yield
    finally:
        _close(fd)


def _profile(env):
    if WINDOWS:
        root = Path(env.get('LOCALAPPDATA') or '') / 'odin-desktop' / 'default'
        return root / 'default-cleanup-state.json', root / 'data' / 'resource-cleanup.json'
    home = Path(env.get('HOME') or Path.home())
    if DARWIN:
        root = home / 'Library' / 'odin-desktop' / 'default'
        return root / 'default-cleanup-state.json', root / 'data' / 'resource-cleanup.json'
    config = Path(env.get('XDG_CONFIG_HOME') or home / '.config') / 'odin-desktop/default'
    data = Path(env.get('XDG_DATA_HOME') or home / '.local/share') / 'odin-desktop/default'
    return config.parent / 'default-cleanup-state.json', data / 'resource-cleanup.json'


def _appimage_sandbox_refusal(sysctl_root=Path('/proc/sys')):
    """Conservative policy check, not a probe of effective per-process permission.

    The Python argument is a unit-test seam only. Production has no environment
    variable or command-line switch to substitute sysctls or bypass this check.
    """
    checks = (
        ('kernel/apparmor_restrict_unprivileged_userns', lambda value: value != 0),
        ('kernel/unprivileged_userns_clone', lambda value: value != 1),
        ('user/max_user_namespaces', lambda value: value <= 0),
    )
    for relative, restricted in checks:
        try:
            value = int((sysctl_root / relative).read_text().strip())
        except FileNotFoundError:
            # Optional sysctls are absent on kernels without these policies.
            continue
        except (OSError, ValueError):
            return f'Cannot verify the user-namespace policy ({relative}).'
        if restricted(value):
            return f'The user-namespace policy is restricted ({relative}={value}).'
    return None


def _show_appimage_refusal(reason, *, dialog=Path('/usr/bin/zenity')):
    message = (
        'Odin Desktop AppImage cannot start safely on this system.\n'
        f'{reason}\n'
        'Install the Odin Desktop .deb package instead. The AppImage preflight '
        'conservatively refuses restricted user namespaces, even if a local '
        'exception might allow them. Electron was not started.\n'
        'Do not disable the Chromium sandbox or weaken system security settings.'
    )
    print(message, file=sys.stderr, flush=True)
    # A terminal still receives the complete failure if no desktop/dialog exists.
    # Never launch Electron just to display its own startup failure.
    if (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')) and dialog.is_file():
        try:
            subprocess.run([str(dialog), '--error', '--title=Odin Desktop cannot start',
                            '--text=' + message, '--no-markup', '--width=520',
                            '--timeout=15'], check=False, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _print_token():
    """This process's token facts as one JSON line, for the Windows app's elevated-start check.
    The app runs it before anything else, so it reads the token and writes nothing."""
    if not WINDOWS:
        raise OwnershipError('Token facts are read on Windows only')
    from src.desktop.platform import win32

    sys.stdout.buffer.write(json.dumps(win32.token_facts(), sort_keys=True).encode('ascii') + b'\n')
    sys.stdout.buffer.flush()
    return 0


def _acknowledge(word):
    """One protocol line as exact bytes: Windows' text stdout would turn its newline into CRLF."""
    sys.stdout.buffer.write(word.encode('ascii') + b'\n')
    sys.stdout.buffer.flush()


def main(argv=None, *, sysctl_root=Path('/proc/sys')):
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['exec', 'hold', 'token', 'receipts'])
    parser.add_argument('--kind', choices=['deb', 'appimage', 'nsis', 'macos'])
    parser.add_argument('--role', choices=['app', 'core'], default='app')
    parser.add_argument('--app-cleanup', type=Path)
    parser.add_argument('--core-cleanup', type=Path)
    # The Mac app's folder for its start check: by default the folder this file ships in.
    parser.add_argument('--resources', type=Path)
    argv = list(sys.argv[1:] if argv is None else argv)
    command = []
    if '--' in argv:
        separator = argv.index('--')
        command, argv = argv[separator + 1:], argv[:separator]
    args = parser.parse_args(argv)
    if args.action == 'token':
        try:
            return _print_token()
        except (OwnershipError, OSError) as error:
            print(f'Odin install ownership refusal: {error}', file=sys.stderr)
            return 1
    if args.kind is None:
        parser.error('the following arguments are required: --kind')
    if args.action == 'receipts':
        # Read-only: the Windows installer holds the lease exclusively and asks for the verdict
        # (receipts_verdict: RECEIPTS_RESTART a restart ends the refusal, RECEIPTS_LASTING it
        # doesn't). The installer words the two differently.
        try:
            code, refusals = receipts_verdict(ownership_paths(args.kind))
        except Exception as error:  # noqa: BLE001 - never Python's own exit 1, never a crash
            code, refusals = RECEIPTS_LASTING, [f'{type(error).__name__}: {error}']
        for refusal in refusals:
            print(f'Odin install ownership refusal: {refusal}', file=sys.stderr)
        return code
    app_cleanup, core_cleanup = _profile(os.environ)
    try:
        if args.action == 'exec':
            if not command:
                raise OwnershipError('No executable was specified')
            if args.kind == 'nsis':
                raise OwnershipError('The Windows app holds its own lease; there is no launcher')
            if args.kind == 'macos':
                raise OwnershipError('The Mac app holds its own lease; there is no launcher')
            if args.kind == 'appimage':
                reason = _appimage_sandbox_refusal(sysctl_root)
                if reason is not None:
                    _show_appimage_refusal(reason)
                    return 78
            paths = ownership_paths(args.kind)
            fd = _open(paths)
            try:
                _lock(fd, exclusive=False)
                _pending(paths)
                # Outer launcher owns the install lease, not the app journal.
                # Primary app and core register independent role receipts.
                return subprocess.run(command, check=False).returncode
            finally:
                os.close(fd)
        # Logout, system stop and Ctrl+C signal this guardian together with the app.
        # Dying first would leave a cleanly exiting app's receipt running; its
        # lifetime ends at the app's stdin EOF instead. SIGKILL still ends it, unclean.
        for name in ('SIGTERM', 'SIGINT', 'SIGHUP'):
            if hasattr(signal, name):  # Windows has no SIGHUP
                signal.signal(getattr(signal, name), signal.SIG_IGN)
        resources = None
        if args.kind == 'macos' and args.role == 'app':
            resources = args.resources or Path(__file__).resolve().parent
        with acquire_lifetime(ownership_paths(args.kind), args.role,
                              args.app_cleanup or app_cleanup,
                              args.core_cleanup or core_cleanup, provisional=True,
                              resources=resources) as lease:
            if args.action == 'hold':
                _acknowledge('READY')
                # The app commits admission after its read-only state check.
                # EOF before ADMIT is a refused start, not unknown cleanup.
                if sys.stdin.readline() != 'ADMIT\n':
                    return 0
                lease.begin()
                _acknowledge('ADMITTED')
                sys.stdin.read()
                result = 0
            try:
                lease.finish()
            except (OwnershipError, OSError, ValueError):
                pass
            return result
    except PendingReplacement as error:
        print(f'Odin install ownership refusal: {error}', file=sys.stderr)
        return PENDING_EXIT if args.kind == 'nsis' else 1
    except StartRefusal as error:
        print(f'Odin install ownership refusal: {error}', file=sys.stderr)
        return error.code
    except (OwnershipError, OSError, ValueError) as error:
        print(f'Odin install ownership refusal: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
