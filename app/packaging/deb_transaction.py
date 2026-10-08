#!/usr/bin/env python3
"""Root package fence. No app/core starts, stops or signals, including abort hooks.

Embedded in maintainer scripts, since preinst cannot import installed resources.
The root lease inode and lifetime evidence survive removal, purge and reboot.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path('/var/lib/odin-desktop/package-ownership')
INSTALL = Path('/opt/odin-desktop')
LEGACY_INSTALL = Path('/opt/Odin')
APPARMOR = Path('/etc/apparmor.d')
APPARMOR_PARSER = Path('/sbin/apparmor_parser')
BUILD_VERSION = None  # Generated hooks bind this to their actual candidate version.
UNWIND = frozenset({'abort-install', 'abort-upgrade', 'abort-remove', 'abort-deconfigure'})
BOOT_ID_SHAPE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


class Refusal(RuntimeError):  # noqa: N818
    pass


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_name(path.name + '.new')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temp.exists():
            temp.unlink()


def provision(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o755)
    for path in (root.parent, root):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise Refusal('Package ownership directory is not root-owned and immutable')
    fd = os.open(root / 'lease', os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022 or info.st_nlink != 1):
            raise Refusal('Package lease inode is not trusted')
    finally:
        os.close(fd)
    receipts = root / 'receipts'
    if not receipts.exists():
        receipts.mkdir(mode=0o1777)
        receipts.chmod(0o1777)
    info = receipts.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o1777:
        raise Refusal('Lifetime receipt registry is not trusted')


@contextmanager
def exclusive(root: Path):
    provision(root)
    fd = os.open(root / 'lease', os.O_RDONLY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Refusal('Exit Odin and its core before changing the package') from error
        yield
    finally:
        os.close(fd)


def legacy_process_check(install: Path, proc: Path = Path('/proc')) -> None:
    """P4.1 had no leases: inspect exact package-owned exe/maps/argv paths."""
    prefix = str(install) + '/'
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            exe = os.readlink(entry / 'exe')
            if exe.startswith(prefix):
                raise Refusal('An installed Odin app or core is still running')
            maps = (entry / 'maps').read_text()
            if any(row.split(maxsplit=5)[-1].startswith(prefix)
                   for row in maps.splitlines() if len(row.split(maxsplit=5)) == 6):
                raise Refusal('An installed Odin resource is still mapped')
            cmd = (entry / 'cmdline').read_bytes().split(b'\0')
            if any(arg.decode(errors='replace').startswith(prefix) for arg in cmd):
                raise Refusal('An installed Odin core is still running')
        except FileNotFoundError:
            continue
        except PermissionError as error:
            raise Refusal('Cannot establish stopped legacy package ownership') from error


def boot_identity(proc: Path) -> str | None:
    try:
        value = (proc / 'sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        return None
    return value if BOOT_ID_SHAPE.fullmatch(value) else None


def clean_receipts(root: Path, proc: Path = Path('/proc')) -> None:
    """A durable clean role receipt, not missing PID, is cleanup evidence.

Launch owners validate their own Exit AND resource/quarantine evidence before
committing clean. Missing/malformed/running/unknown does not mean clean. Nothing
a lifetime held survives the boot it ran in, so a receipt recording an earlier
boot no longer fences. One without a well-formed, readable boot identity stays fenced.
"""
    boot = boot_identity(proc)
    for receipt in (root / 'receipts').iterdir():
        try:
            fd = os.open(receipt, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'r') as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_size > 65536):
                    raise Refusal('Untrusted lifetime receipt; replacement remains fenced')
                value = json.load(stream)
        except (OSError, ValueError) as error:
            raise Refusal('Unreadable lifetime receipt; replacement remains fenced') from error
        if not isinstance(value, dict):
            raise Refusal('Previous app/core cleanup is unresolved; package unchanged')
        recorded = value.get('boot_id')
        if isinstance(recorded, str) and BOOT_ID_SHAPE.fullmatch(recorded) and boot:
            if recorded != boot:
                continue
            if value.get('state') != 'clean':
                raise Refusal('An Odin session ended without confirmed cleanup since this '
                              'computer started. Restart the computer, then try again; '
                              'package unchanged')
        if value.get('state') != 'clean':
            raise Refusal('Previous app/core cleanup is unresolved; package unchanged')


def trusted_profile(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022 or info.st_nlink != 1):
            raise Refusal('AppArmor profile is not root-owned and immutable')
        return stream.read()


def profile_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def apparmor_profile(root: Path, install: Path, directory: Path, parser: Path,
                     *, remove: bool = False) -> None:
    """Install/load only our profile; never overwrite or remove foreign bytes.

    Paths are function seams for isolated tests, never environment overrides.
    The ownership digest survives unpack/removal of the immutable source.
    """
    receipt = root / 'apparmor-profile.json'
    owned = None
    if receipt.exists():
        try:
            owned = json.loads(trusted_profile(receipt))['sha256']
        except (ValueError, KeyError, TypeError) as error:
            raise Refusal('AppArmor ownership receipt is unreadable') from error
    target = directory / 'odin-desktop'
    exists = target.exists() or target.is_symlink()
    if remove:
        if owned is None:
            return
        if exists:
            content = trusted_profile(target)
            if profile_digest(content) != owned:
                # A locally replaced profile is no longer ours to unload/delete.
                return
            run_apparmor_parser(parser, '-R', target)
            target.unlink()
        receipt.unlink()
        return
    source = install / 'resources' / 'apparmor-profile'
    for parent in (install, source.parent):
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022):
            raise Refusal('AppArmor source directory is not immutable')
    content = trusted_profile(source)
    directory.mkdir(parents=True, exist_ok=True, mode=0o755)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022):
        raise Refusal('AppArmor destination directory is not trusted')
    if exists:
        previous = trusted_profile(target)
        if previous != content and profile_digest(previous) != owned:
            raise Refusal('Refusing to overwrite another AppArmor profile')
    temp = target.with_name(target.name + '.new')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    atomic_json(receipt, {'sha256': profile_digest(content)})
    run_apparmor_parser(parser, '-r', target)


def run_apparmor_parser(parser: Path, operation: str, target: Path) -> None:
    # Match builder behavior on systems without AppArmor; never search PATH.
    if parser.is_file() and os.access(parser, os.X_OK):
        try:
            subprocess.run([str(parser), operation, str(target)], check=True)
        except subprocess.CalledProcessError as error:
            raise Refusal('AppArmor parser failed; package fence retained') from error


def launcher_link_matches(launcher: Path, targets: tuple[str, ...],
                          legacy_install: Path) -> bool:
    """Follow bounded link text, accepting terminal targets without accessing them.

    Inspect parent links component-wise too: readlink on an unchecked parent alias
    could otherwise enter the legacy tree. Neither stat nor resolve is used, and
    an unapproved legacy path is rejected before any filesystem call on it.
    """
    current = os.path.abspath(launcher)
    forbidden = tuple(os.path.abspath(path) for path in (LEGACY_INSTALL, legacy_install))
    seen = set()
    for _ in range(40):
        if current in targets:
            return True
        if (current in seen
                or any(current == path or current.startswith(path + '/')
                       for path in forbidden)):
            return False
        seen.add(current)
        parts = Path(current).parts[1:]
        prefix = '/'
        for index, part in enumerate(parts):
            if part == '..':
                prefix = os.path.dirname(prefix)
                continue
            prefix = os.path.join(prefix, part)
            if prefix in forbidden:
                return False
            if prefix in targets:
                return index == len(parts) - 1
            try:
                text = os.readlink(prefix)
            except OSError as error:
                if error.errno == errno.EINVAL:  # This component is not a symlink.
                    continue
                return False
            destination = (text if os.path.isabs(text)
                           else os.path.join(os.path.dirname(prefix), text))
            # Preserve '..' until preceding directory symlinks have been expanded.
            current = os.path.join(destination, *parts[index + 1:])
            break
        else:
            return False
    return False


def transaction(script: str, args: list[str], *, root: Path = ROOT, install: Path = INSTALL,
                proc: Path = Path('/proc'), launcher: Path = Path('/usr/bin/odin-desktop'),
                apparmor_dir: Path = APPARMOR, apparmor_parser: Path = APPARMOR_PARSER,
                legacy_install: Path = LEGACY_INSTALL) -> None:
    if os.geteuid() != 0:
        raise Refusal('Maintainer transaction requires root')
    operation = args[0] if args else ''
    if operation in UNWIND:
        # dpkg's error unwind after a refused change restores the previous version and
        # changes nothing here. Waiting on the lease failed it while Odin ran, leaving the
        # old version half-configured and apt blocked instead of installed.
        return
    marker = root / 'transaction.json'
    with exclusive(root):
        current = None
        if marker.exists():
            try:
                current = json.loads(marker.read_text())
            except (OSError, ValueError) as error:
                raise Refusal('Interrupted package fence is unreadable') from error
            if not isinstance(current, dict) or current.get('version') != 1:
                raise Refusal('Interrupted package fence is incompatible')
        if (script in {'preinst', 'prerm'}
                and operation in {'install', 'upgrade', 'remove', 'deconfigure'}):
            if (script == 'preinst' and operation == 'upgrade' and install.exists()
                    and not (install / 'resources/ownership.py').is_file()):
                raise Refusal(
                    'Unguarded predecessor cannot be upgraded live; use an externally '
                    'fenced offline remove/install transition')
            legacy_process_check(install, proc)
            # Only upgrades may inspect the old product-name directory. A foreign
            # /opt/Odin is not ours; never provision, repair or remove anything there.
            legacy_launcher_target = None
            if (operation == 'upgrade'
                    and (legacy_install / 'resources/ownership.py').is_file()):
                legacy_process_check(legacy_install, proc)
                legacy_launcher_target = str(legacy_install / 'odin-desktop')
            clean_receipts(root, proc)
            if current and current.get('operation') not in {'install', 'upgrade', operation}:
                raise Refusal('Different interrupted package transaction is pending')
            atomic_json(marker, {'version': 1, 'operation': operation, 'script': script,
                                 'arguments': args, 'target_version': BUILD_VERSION,
                                 'legacy_launcher_target': legacy_launcher_target,
                                 'lease_inode': (root / 'lease').stat().st_ino})
            return
        if ((script == 'postinst' and operation == 'configure')
                or (script == 'postrm' and operation in {'remove', 'purge'})):
            if current is None:
                if script == 'postrm':
                    apparmor_profile(root, install, apparmor_dir, apparmor_parser, remove=True)
                    return
                raise Refusal('Package configure has no ownership preflight')
            if current.get('lease_inode') != (root / 'lease').stat().st_ino:
                raise Refusal('Package lease identity changed during the transaction')
            if script == 'postinst' and (current.get('operation') not in {'install', 'upgrade'}
                                        or current.get('target_version') != BUILD_VERSION):
                raise Refusal('Configure does not match the pending package transaction')
            if script == 'postrm' and current.get('operation') not in {'remove', 'deconfigure'}:
                raise Refusal('Removal does not match the pending package transaction')
            target = str(install / 'odin-desktop')
            if script == 'postinst':
                apparmor_profile(root, install, apparmor_dir, apparmor_parser)
                if launcher.is_symlink():
                    if os.readlink(launcher) != target:
                        legacy_target = (current.get('legacy_launcher_target')
                                         if current.get('operation') == 'upgrade'
                                         and current.get('script') == 'preinst' else None)
                        # Older candidates used update-alternatives. Only the
                        # exact existing package target may transition to a direct link.
                        # Read only the link text, not its destination: dpkg may have
                        # already removed the old executable, and a foreign old path
                        # must never be inspected outside upgrade preflight.
                        targets = (target,) if legacy_target is None else (target, legacy_target)
                        if not launcher_link_matches(launcher, targets, legacy_install):
                            raise Refusal('Refusing to overwrite another launcher')
                        launcher.unlink()
                        launcher.symlink_to(target)
                elif launcher.exists():
                    raise Refusal('Refusing to overwrite another launcher')
                else:
                    launcher.symlink_to(target)
            else:
                apparmor_profile(root, install, apparmor_dir, apparmor_parser, remove=True)
                if launcher.is_symlink() and os.readlink(launcher) == target:
                    launcher.unlink()
            marker.unlink()
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        # Upgrade postrm and abort hooks retain the fence. Interrupted is not clean.


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('script', choices=['preinst', 'postinst', 'prerm', 'postrm'])
    parser.add_argument('arguments', nargs='*')
    args = parser.parse_args(argv)
    try:
        transaction(args.script, args.arguments)
    except (Refusal, OSError) as error:
        print(f'Odin package ownership refusal: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
