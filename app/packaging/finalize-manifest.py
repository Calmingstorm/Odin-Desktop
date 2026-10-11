#!/usr/bin/env python3
"""Builder hook: inventory integrity, not an authenticity/signature boundary."""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'python'))
from manifest import digest, inventory, verify

SELF_METADATA = ('bundle-manifest.json',)
REPARSE_POINT = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)

# pip 26.2.1 inert upstream wheel-data launchers: named P1 Linux exception,
# not permission for arbitrary Windows runtime executables.
PIP_LINUX_LAUNCHER_DATA = {
    't32.exe': ('6b4195e640a85ac32eb6f9628822a622057df1e459df7c17a12f97aeabc9415b', 97792),
    't64-arm.exe': ('ebc4c06b7d95e74e315419ee7e88e1d0f71e9e9477538c00a93a9ff8c66a6cfc', 182784),
    't64.exe': ('81a618f21cb87db9076134e70388b6e9cb7c2106739011b6a51772d22cae06b7', 108032),
    'w32.exe': ('47872cc77f8e18cf642f868f23340a468e537e64521d9a3a416c8b84384d064b', 91648),
    'w64-arm.exe': ('c5dc9884a8f458371550e09bd396e5418bf375820a31b9899f6499bf391c7b2e', 168448),
    'w64.exe': ('7a319ffaba23a017d7b1e18ba726ba6c54c53d6446db55f92af53c279894f8ad', 101888),
}


def ordinary_windows_path(path: Path) -> os.stat_result:
    """lstat before traversal. Junctions and all other reparse tags are refused."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & REPARSE_POINT:
        raise ValueError(f'Windows resource reparse point: {path}')
    return info


def windows_inventory(root: Path, prefix: str = '', exclude: tuple[str, ...] = ()) -> list[dict]:
    # Do not resolve first: that would hide a junction/symlink in the supplied root.
    root = root.absolute()
    for parent in [*reversed(root.parents), root]:
        ordinary_windows_path(parent)
    if not stat.S_ISDIR(ordinary_windows_path(root).st_mode):
        raise ValueError(f'Windows resource root is not a directory: {root}')
    entries: list[dict] = []
    identities: set[str] = set()

    def visit(directory: Path) -> None:
        with os.scandir(directory) as scanner:
            children = sorted(scanner, key=lambda item: item.name)
        for child in children:
            path = Path(child.path)
            relative = path.relative_to(root).as_posix()
            component = child.name
            device = component.split('.')[0].upper()
            if (component.endswith((' ', '.')) or any(c in component for c in ':\\<>"|?*')
                    or any(ord(c) < 32 for c in component)
                    or device in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'}
                    or device in {f'{kind}{n}' for kind in ('COM', 'LPT') for n in '123456789¹²³'}):
                raise ValueError(f'Unsafe Windows resource path: {relative}')
            identity = relative.casefold()
            if identity in identities:
                raise ValueError(f'Windows resource case collision: {relative}')
            identities.add(identity)
            info = ordinary_windows_path(path)
            if stat.S_ISDIR(info.st_mode):
                visit(path)
            elif stat.S_ISREG(info.st_mode):
                if relative not in exclude:
                    name = f'{prefix}/{relative}' if prefix else relative
                    entries.append({'path': name, 'type': 'file', 'size': info.st_size,
                                    'sha256': digest(path), 'mode': stat.S_IMODE(info.st_mode)})
            else:
                raise ValueError(f'Special Windows resource file: {relative}')

    visit(root)
    return sorted(entries, key=lambda item: item['path'])


def assert_platform_resources(files: list[dict], platform: str) -> None:
    """Pure engine modules may carry both backends; executable payloads may not."""
    for item in files:
        name = item['path'].casefold()
        if platform == 'win32':
            # ownership.py is cross-platform: the installed Windows app's guardian holds the
            # per-user nsis lease through it (phase 4b).
            bad = (name == 'apparmor-profile'
                   or name.startswith(('runtime/helpers/', 'runtime/python/bin/'))
                   or name.endswith(('.so', '.sh', '.appimage'))
                   or '/chrome-headless-shell-linux64/' in name)
        else:
            bad = (name.startswith('tools/') or name.endswith(('.exe', '.dll', '.msi'))
                   or '/chrome-headless-shell-win64/' in name)
            prefix = 'runtime/python/lib/python3.12/site-packages/pip/_vendor/distlib/'
            if name.startswith(prefix):
                pin = PIP_LINUX_LAUNCHER_DATA.get(name[len(prefix):])
                if pin and (item.get('sha256'), item.get('size')) == pin:
                    bad = False
        if bad:
            raise ValueError(f'Forbidden {platform} resource payload: {item["path"]}')


def resource_inventory(resources: Path, platform: str) -> list[dict]:
    if platform not in {'win32', 'linux'}:
        raise ValueError(f'Unsupported bundle platform: {platform}')
    function = windows_inventory if platform == 'win32' else inventory
    files = function(resources, prefix='', exclude=SELF_METADATA)
    assert_platform_resources(files, platform)
    return files


def verify_resources(resources: Path, *, release: bool = False) -> dict:
    manifest_path = resources / 'bundle-manifest.json'
    if sys.platform == 'win32':
        windows_inventory(resources, exclude=SELF_METADATA)
        ordinary_windows_path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    source = manifest.get('source', {})
    if release and (source.get('mode') != 'release' or source.get('immutable') is not True):
        raise ValueError('Release verification refuses worktree/unbound source provenance')
    platform = manifest.get('platform', 'linux')
    if platform == 'linux':
        result = verify(resources)
        assert_platform_resources(manifest['files'], platform)
        return result
    if platform != 'win32' or manifest.get('schema') != 1:
        raise ValueError('Unsupported bundle manifest schema/platform')
    ordinary_windows_path(manifest_path)
    files = manifest.get('files')
    if not isinstance(files, list) or not files:
        raise ValueError('Empty bundle manifest')
    names = [item['path'] for item in files]
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError('Duplicate Windows manifest path')
    actual = resource_inventory(resources, platform)
    if files != actual:
        expected = {item['path']: item for item in files}
        observed = {item['path']: item for item in actual}
        missing = sorted(expected.keys() - observed.keys())
        extra = sorted(observed.keys() - expected.keys())
        modified = sorted(name for name in expected.keys() & observed.keys()
                          if expected[name] != observed[name])
        differences = {'missing': missing[:20], 'extra': extra[:20], 'modified': modified[:20]}
        raise ValueError('Bundle exact-set mismatch: ' + json.dumps(differences, sort_keys=True))
    return {'files': len(actual), 'bytes': sum(item['size'] for item in actual),
            'manifest_sha256': digest(manifest_path)}


def finalize(resources: Path, *, release: bool = False) -> dict:
    manifest_path = resources / 'bundle-manifest.json'
    if sys.platform == 'win32':
        ordinary_windows_path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != 1:
        raise ValueError('Unsupported bundle manifest schema')
    source = manifest.get('source', {})
    if release and (source.get('mode') != 'release' or source.get('immutable') is not True):
        raise ValueError('Release sealing refuses worktree/unbound source provenance')
    platform = manifest.get('platform', 'linux')
    if platform == 'win32':
        ordinary_windows_path(manifest_path)
    manifest['files'] = resource_inventory(resources, platform)
    temporary = resources / '.bundle-manifest.tmp'
    if temporary.exists():
        raise ValueError('Unexpected manifest temporary file')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        os.replace(temporary, manifest_path)
    finally:
        temporary.unlink(missing_ok=True)
    return verify_resources(resources, release=release)


if __name__ == '__main__':
    result = finalize(Path(sys.argv[1]), release=os.environ.get('ODIN_PACKAGING_RELEASE') == '1')
    print(json.dumps(result))
