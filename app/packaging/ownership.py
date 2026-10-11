#!/usr/bin/env python3
"""Install lifetime leases. Filesystem barrier only, never process control.

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
if not WINDOWS:
    import fcntl

DEB_ROOT = Path('/var/lib/odin-desktop/package-ownership')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
_BOOT_ID_SHAPE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


class OwnershipError(RuntimeError):
    pass


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
    if kind != 'appimage':
        raise OwnershipError('Unsupported installation kind')
    home = Path(env.get('HOME') or Path.home())
    state = Path(env.get('XDG_STATE_HOME') or home / '.local/state')
    return OwnershipPaths(state / 'odin-desktop/install-ownership/appimage')


def _open(paths):
    if WINDOWS:
        return _open_windows(paths)
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
        raise OwnershipError('Package replacement is pending; finish the external transaction')


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
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
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


class Lease:
    def __init__(self, paths, role, app_cleanup, core_cleanup, *, provisional=False):
        self.paths, self.role = paths, role
        self.app_cleanup, self.core_cleanup = Path(app_cleanup), Path(core_cleanup)
        self.fd = _open(paths)
        try:
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


def acquire_lifetime(paths, role, app_cleanup, core_cleanup, *, provisional=False):
    if role not in {'app', 'core'}:
        raise OwnershipError('Unsupported lifetime role')
    return Lease(paths, role, app_cleanup, core_cleanup, provisional=provisional)


@contextmanager
def replacement_guard(paths, check_receipts=True):
    fd = _open(paths)
    try:
        try:
            _lock(fd, exclusive=True)
        except BlockingIOError as error:
            raise OwnershipError('Exit both app and core before replacement') from error
        if check_receipts:
            boot = _boot_id()
            for path in paths.receipts.iterdir():
                receipt = _read(path)
                if _earlier_boot(receipt.get('boot_id'), boot):
                    continue
                if receipt.get('state') != 'clean':
                    raise OwnershipError('Unresolved lifetime evidence blocks replacement')
                if not all(key in receipt for key in ('app_cleanup', 'core_cleanup', 'role')):
                    raise OwnershipError('Incomplete lifetime receipt blocks replacement')
                _clean(receipt['app_cleanup'], receipt['core_cleanup'], receipt['role'])
        yield
    finally:
        _close(fd)


def _profile(env):
    if WINDOWS:
        root = Path(env.get('LOCALAPPDATA') or '') / 'odin-desktop' / 'default'
        return root / 'default-cleanup-state.json', root / 'data' / 'resource-cleanup.json'
    home = Path(env.get('HOME') or Path.home())
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
    parser.add_argument('action', choices=['exec', 'hold', 'token'])
    parser.add_argument('--kind', choices=['deb', 'appimage', 'nsis'])
    parser.add_argument('--role', choices=['app', 'core'], default='app')
    parser.add_argument('--app-cleanup', type=Path)
    parser.add_argument('--core-cleanup', type=Path)
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
    app_cleanup, core_cleanup = _profile(os.environ)
    try:
        if args.action == 'exec':
            if not command:
                raise OwnershipError('No executable was specified')
            if args.kind == 'nsis':
                raise OwnershipError('The Windows app holds its own lease; there is no launcher')
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
        with acquire_lifetime(ownership_paths(args.kind), args.role,
                              args.app_cleanup or app_cleanup,
                              args.core_cleanup or core_cleanup, provisional=True) as lease:
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
    except (OwnershipError, OSError, ValueError) as error:
        print(f'Odin install ownership refusal: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
