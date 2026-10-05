"""Closed inventory of immutable engine resources, including relocatable links."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def inventory(root: Path, prefix: str = 'runtime', exclude: tuple[str, ...] = ()) -> list[dict]:
    root = root.resolve()
    result = []
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if relative in exclude:
            continue
        name = f'{prefix}/{relative}' if prefix else relative
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            target = os.readlink(path)
            if os.path.isabs(target) or not path.resolve().is_relative_to(root):
                raise ValueError(f'Escaping bundle link: {relative}')
            if not path.exists():
                raise ValueError(f'Broken bundle link: {relative}')
            result.append({'path': name, 'type': 'symlink', 'target': target,
                           'sha256': hashlib.sha256(target.encode()).hexdigest(),
                           'size': len(target.encode()), 'mode': mode})
        elif path.is_file():
            result.append({'path': name, 'type': 'file', 'sha256': digest(path),
                           'size': path.stat().st_size, 'mode': mode})
        elif not path.is_dir():
            raise ValueError(f'Special bundle file: {relative}')
    return result


def verify(resources: Path) -> dict:
    manifest = json.loads((resources / 'bundle-manifest.json').read_text())
    if manifest.get('schema') != 1:
        raise ValueError('Unsupported bundle manifest schema')
    files = manifest.get('files')
    if not isinstance(files, list) or not files:
        raise ValueError('Empty bundle manifest')
    names = [item['path'] for item in files]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate manifest path')
    actual = inventory(resources, prefix='', exclude=('bundle-manifest.json',))
    if files != actual:
        expected = {item['path']: item for item in files}
        observed = {item['path']: item for item in actual}
        changed = sorted(name for name in expected.keys() | observed.keys()
                         if expected.get(name) != observed.get(name))
        raise ValueError('Bundle inventory/digest mismatch: ' + ', '.join(changed[:20]))
    return {'files': len(actual), 'bytes': sum(item['size'] for item in actual),
            'manifest_sha256': digest(resources / 'bundle-manifest.json')}
