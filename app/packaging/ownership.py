#!/usr/bin/env python3
"""Install lifetime leases. Filesystem barrier only, never process control."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

DEB_ROOT = Path('/var/lib/odin-desktop/package-ownership')


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


def _clean(app_cleanup, core_cleanup, role):
    core = _read(core_cleanup)
    resources = core.get('resources')
    if (core.get('version') != 1 or core.get('state') != 'complete'
            or core.get('previous_unknown') is not None
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
                or current.get('unsaved') or current.get('unreceipted', 0)
                or app.get('warning') is not None):
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
    def __init__(self, paths, role, app_cleanup, core_cleanup):
        self.paths, self.role = paths, role
        self.app_cleanup, self.core_cleanup = Path(app_cleanup), Path(core_cleanup)
        self.fd = _open(paths)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            _pending(paths)
            self.initial_core = _fingerprint(self.core_cleanup)
            self.initial_app = _fingerprint(self.app_cleanup)
            self.receipt = paths.receipts / f'{os.getuid()}-{uuid.uuid4().hex}-{role}.json'
            self.record = {'version': 1, 'role': role, 'state': 'running',
                           'uid': os.getuid(), 'app_cleanup': str(self.app_cleanup),
                           'core_cleanup': str(self.core_cleanup)}
            _write(self.receipt, self.record)
        except BaseException:
            self.close()
            raise

    def finish(self):
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


def acquire_lifetime(paths, role, app_cleanup, core_cleanup):
    if role not in {'app', 'core'}:
        raise OwnershipError('Unsupported lifetime role')
    return Lease(paths, role, app_cleanup, core_cleanup)


@contextmanager
def replacement_guard(paths, check_receipts=True):
    fd = _open(paths)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise OwnershipError('Exit both app and core before replacement') from error
        if check_receipts:
            for path in paths.receipts.iterdir():
                receipt = _read(path)
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


def main(argv=None):
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
        with acquire_lifetime(ownership_paths(args.kind), args.role,
                              args.app_cleanup or app_cleanup,
                              args.core_cleanup or core_cleanup) as lease:
            if args.action == 'hold':
                print('READY', flush=True)
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
