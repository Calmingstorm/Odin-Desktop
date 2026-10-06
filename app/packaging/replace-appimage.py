#!/usr/bin/env python3
"""Explicit user-run, offline same-path AppImage replacement. Never imported by the app."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path


class ReplacementError(ValueError):
    pass


def digest_fd(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while chunk := os.read(fd, 1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def owned_regular(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ReplacementError('Image must be an ordinary file owned by the invoking user')
    return info


def write_transaction(path, value):
    pending = path.with_name(path.name + '.writing')
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        owned_regular(fd)
        value_bytes = memoryview(json.dumps(value, sort_keys=True).encode())
        while value_bytes:
            value_bytes = value_bytes[os.write(fd, value_bytes):]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(pending, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def retire_transaction(path):
    path.unlink()
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def replace_locked(source, destination, expected, transaction):
    """Caller holds the unified exclusive lifetime lease and checked Exit receipts."""
    if os.getuid() == 0:
        raise ReplacementError('Run as the ordinary AppImage owner, not root')
    if not re.fullmatch('[0-9a-f]{64}', expected):
        raise ReplacementError('Supply the local new image SHA-256 explicitly')
    source = Path(source).absolute()
    destination = Path(destination).absolute()
    transaction = Path(transaction)
    if source == destination:
        raise ReplacementError('Source and destination must differ')
    # Resolve the directory once; all executable operations below are dirfd-relative.
    parent = destination.parent.resolve(strict=True)
    destination = parent / destination.name
    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    source_fd = destination_fd = stage_fd = None
    try:
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        owned_regular(source_fd)
        header = os.read(source_fd, 12)
        if not header.startswith(b'\x7fELF') or header[8:11] != b'AI\x02':
            raise ReplacementError('Source is not a type-2 AppImage')
        if digest_fd(source_fd) != expected:
            raise ReplacementError('New image SHA-256 does not match')
        destination_fd = os.open(destination.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        original = owned_regular(destination_fd)
        old_header = os.read(destination_fd, 12)
        if not old_header.startswith(b'\x7fELF') or old_header[8:11] != b'AI\x02':
            raise ReplacementError('Destination is not an existing type-2 AppImage')
        old_hash = digest_fd(destination_fd)
        if transaction.exists():
            fd = os.open(transaction, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                owned_regular(fd)
                previous = json.loads(os.read(fd, 64 * 1024))
            finally:
                os.close(fd)
            if (not isinstance(previous, dict) or previous.get('schema') != 1
                    or previous.get('destination') != str(destination)
                    or previous.get('new_sha256') != expected
                    or not re.fullmatch(r'\.odin-appimage-[0-9a-f]{32}\.pending',
                                        previous.get('stage', ''))):
                raise ReplacementError('Interrupted transaction differs; inspect manually')
            if old_hash not in {previous.get('old_sha256'), expected}:
                raise ReplacementError('Destination changed during interruption; inspect manually')
            # Exact recorded stage only, never glob cleanup or old executable unlinking.
            try:
                stage_info = os.stat(previous['stage'], dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if (not stat.S_ISREG(stage_info.st_mode) or stage_info.st_uid != os.getuid()
                        or previous.get('stage_identity') != [
                            stage_info.st_dev, stage_info.st_ino]):
                    raise ReplacementError('Interrupted stage ownership changed')
                os.unlink(previous['stage'], dir_fd=directory)
                os.fsync(directory)
            if old_hash == expected:
                retire_transaction(transaction)
                return {'status': 'recovered', 'sha256': expected, 'destination': str(destination)}
        stage = '.odin-appimage-' + uuid.uuid4().hex + '.pending'
        record = {'schema': 1, 'destination': str(destination), 'stage': stage,
                  'old_sha256': old_hash, 'new_sha256': expected}
        write_transaction(transaction, record)
        stage_fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                           0o600, dir_fd=directory)
        staged_info = os.fstat(stage_fd)
        record['stage_identity'] = [staged_info.st_dev, staged_info.st_ino]
        os.fsync(directory)
        write_transaction(transaction, record)
        os.lseek(source_fd, 0, os.SEEK_SET)
        while chunk := os.read(source_fd, 1024 * 1024):
            view = memoryview(chunk)
            while view:
                view = view[os.write(stage_fd, view):]
        os.fchmod(stage_fd, 0o755)
        os.fsync(stage_fd)
        os.close(stage_fd)
        stage_fd = None
        checked = os.open(stage, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            if digest_fd(checked) != expected:
                raise ReplacementError('Staged image changed; executable was not replaced')
        finally:
            os.close(checked)
        current = os.stat(destination.name, dir_fd=directory, follow_symlinks=False)
        if ((current.st_dev, current.st_ino) != (original.st_dev, original.st_ino)
                or digest_fd(destination_fd) != old_hash):
            raise ReplacementError('Destination identity changed; executable was not replaced')
        current_stage = os.stat(stage, dir_fd=directory, follow_symlinks=False)
        if (current_stage.st_dev, current_stage.st_ino) != (staged_info.st_dev, staged_info.st_ino):
            raise ReplacementError('Staged image identity changed; executable was not replaced')
        os.replace(stage, destination.name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
        retire_transaction(transaction)
        return {'status': 'replaced', 'sha256': expected, 'destination': str(destination)}
    finally:
        for fd in (stage_fd, destination_fd, source_fd, directory):
            if fd is not None:
                os.close(fd)


def replace(source, destination, expected, env=None):
    # Shared lease/receipt implementation supplied with the launcher. This helper
    # never quiesces, signals, acknowledges, installs, executes or downloads.
    if os.getuid() == 0:
        raise ReplacementError('Run as the ordinary AppImage owner, not root')
    from ownership import ownership_paths, replacement_guard
    paths = ownership_paths(kind='appimage', env=env)
    with replacement_guard(paths, check_receipts=True):
        return replace_locked(source, destination, expected,
                              paths.directory / 'appimage-replacement.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    try:
        result = replace(args.source, args.destination, args.sha256)
    except (OSError, ValueError, RuntimeError) as error:
        print('Replacement refused: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
