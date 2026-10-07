#!/usr/bin/env python3
"""Install lifetime leases. Filesystem barrier only, never process control."""
from __future__ import annotations

import argparse
import fcntl
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
    if kind != 'appimage':
        raise OwnershipError('Unsupported installation kind')
    home = Path(env.get('HOME') or Path.home())
    state = Path(env.get('XDG_STATE_HOME') or home / '.local/state')
    return OwnershipPaths(state / 'odin-desktop/install-ownership/appimage')


def _open(paths):
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


def _pending(paths):
    if paths.pending.exists() or (paths.directory / 'appimage-replacement.json').exists():
        raise OwnershipError('Package replacement is pending; finish the external transaction')


def _read(path):
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
    if (core.get('version') != 1 or core.get('state') != 'complete'
            or (previous is not None and not (isinstance(previous, dict) and _earlier_boot(
                previous.get('boot_id'), _boot_id())))
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
            fcntl.flock(self.fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            _pending(paths)
            self.initial_core = _fingerprint(self.core_cleanup)
            self.initial_app = _fingerprint(self.app_cleanup)
            self.receipt = None
            self.record = {'version': 1, 'role': role, 'state': 'running',
                           'uid': os.getuid(), 'boot_id': _boot_id(),
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
            self.receipt = self.paths.receipts / (
                f'{os.getuid()}-{uuid.uuid4().hex}-{self.role}.json')
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
            os.close(self.fd)
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
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
        os.close(fd)


def _profile(env):
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


def main(argv=None, *, sysctl_root=Path('/proc/sys')):
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['exec', 'hold'])
    parser.add_argument('--kind', choices=['deb', 'appimage'], required=True)
    parser.add_argument('--role', choices=['app', 'core'], default='app')
    parser.add_argument('--app-cleanup', type=Path)
    parser.add_argument('--core-cleanup', type=Path)
    argv = list(sys.argv[1:] if argv is None else argv)
    command = []
    if '--' in argv:
        separator = argv.index('--')
        command, argv = argv[separator + 1:], argv[:separator]
    args = parser.parse_args(argv)
    app_cleanup, core_cleanup = _profile(os.environ)
    try:
        if args.action == 'exec':
            if not command:
                raise OwnershipError('No executable was specified')
            if args.kind == 'appimage':
                reason = _appimage_sandbox_refusal(sysctl_root)
                if reason is not None:
                    _show_appimage_refusal(reason)
                    return 78
            paths = ownership_paths(args.kind)
            fd = _open(paths)
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                _pending(paths)
                # Outer launcher owns the install lease, not the app journal.
                # Primary app and core register independent role receipts.
                return subprocess.run(command, check=False).returncode
            finally:
                os.close(fd)
        # Logout, system stop and Ctrl+C signal this guardian together with the app.
        # Dying first would leave a cleanly exiting app's receipt running; its
        # lifetime ends at the app's stdin EOF instead. SIGKILL still ends it, unclean.
        for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(number, signal.SIG_IGN)
        with acquire_lifetime(ownership_paths(args.kind), args.role,
                              args.app_cleanup or app_cleanup,
                              args.core_cleanup or core_cleanup, provisional=True) as lease:
            if args.action == 'hold':
                print('READY', flush=True)
                # The app commits admission after its read-only state check.
                # EOF before ADMIT is a refused start, not unknown cleanup.
                if sys.stdin.readline() != 'ADMIT\n':
                    return 0
                lease.begin()
                print('ADMITTED', flush=True)
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
