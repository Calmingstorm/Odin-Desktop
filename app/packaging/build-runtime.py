#!/usr/bin/env python3
"""Stage the locked runtime once; both candidate formats consume these bytes."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FONTS = REPO / 'app/src/renderer/src/assets/fonts'

# Archive checked against upstream v44.5.1 SHASUMS256.txt. Executable and
# notice hashes measured from that archive, never from a developer install.
WINDOWS_ELECTRON = {
    'version': '44.5.1', 'platform': 'win32-x64',
    'url': 'https://github.com/electron/electron/releases/download/v44.5.1/electron-v44.5.1-win32-x64.zip',
    'sha256': '9b382492dcfee91f8f9e92c91f7972550a1b95d2299cac72279dab33a600d7db',
    'size': 157998329,
    'executable_sha256': '49b61a030a520fc36a4b8fa5cce53fb4e935a7bdbbe4b80e9222f598e49cc7fa',
    'license': 'MIT with bundled third-party notices',
    'license_files': ['LICENSE', 'LICENSES.chromium.html'],
    'provenance': 'https://github.com/electron/electron/releases/download/v44.5.1/SHASUMS256.txt',
    'notice_sha256': {
        'LICENSE': '5154e165bd6c2cc0cfbcd8916498c7abab0497923bafcd5cb07673fe8480087d',
        'LICENSES.chromium.html':
            '7b328b8c7463ac9bfc7dc648c751533517c8441a0b5b21047d6c0b2620e60d70',
    },
}


def stage_font_notices(legal: Path) -> list[str]:
    """Bundle renderer OFL font licenses as readable legal/fonts resources."""
    target = legal / 'fonts'
    target.mkdir(exist_ok=True)
    names = sorted(path.name for path in FONTS.glob('OFL-*.txt'))
    for name in names:
        shutil.copyfile(FONTS / name, target / name)
    return names
sys.path.insert(0, str(HERE / 'python'))
from manifest import digest, inventory  # noqa: E402


def sealing_module():
    spec = importlib.util.spec_from_file_location('bundle_sealing', HERE / 'finalize-manifest.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_inventory(repo: Path) -> list[dict]:
    tracked = subprocess.check_output(
        ['git', '-C', str(repo), 'ls-files', '-z']).decode().split('\0')
    # Development's newly added engine modules are deliberately included, not an
    # arbitrary sweep of ignored caches, credentials or user data.
    names = set(filter(None, tracked))
    names.update(path.relative_to(repo).as_posix() for path in (repo / 'src').rglob('*.py')
                 if '__pycache__' not in path.parts)
    names.update(path.relative_to(repo).as_posix() for path in (repo / 'app/packaging').rglob('*')
                 if path.suffix in {'.py', '.json'} and '__pycache__' not in path.parts)
    result = []
    for name in sorted(names):
        path = repo / name
        if path.is_symlink():
            result.append({'path': name, 'type': 'symlink', 'target': os.readlink(path)})
        elif path.is_file():
            result.append({'path': name, 'size': path.stat().st_size, 'sha256': digest(path)})
        else:
            raise ValueError(f'Missing/nonordinary source input: {name}')
    return result


def committed_inventory(repo: Path, commit: str) -> list[dict]:
    """Git-object bytes, independent of core.autocrlf/checkout filters."""
    archive = subprocess.check_output(['git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf',
                                       '-C', str(repo), 'archive', commit])
    result = []
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for member in stream.getmembers():
            if member.isdir():
                continue
            if member.issym():
                result.append({'path': member.name, 'type': 'symlink', 'target': member.linkname})
            elif member.isfile():
                data = stream.extractfile(member).read()
                result.append({'path': member.name, 'size': len(data),
                               'sha256': hashlib.sha256(data).hexdigest()})
            else:
                raise ValueError(f'Nonordinary git source entry: {member.name}')
    return sorted(result, key=lambda item: item['path'])


def source_record(repo: Path, mode: str) -> dict:
    if mode not in {'release', 'worktree'}:
        raise ValueError('Unknown provenance mode')
    commit = subprocess.check_output(
        ['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain',
                                     '--untracked-files=normal'], text=True)
    if mode == 'release' and dirty:
        raise ValueError('Release provenance requires a clean committed revision; '
                         'worktree bytes refused')
    files = committed_inventory(repo, commit) if mode == 'release' else source_inventory(repo)
    encoded = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    return {'commit': commit, 'mode': mode, 'immutable': mode == 'release',
            'source_manifest_sha256': hashlib.sha256(encoded).hexdigest(), 'files': files,
            'uv_lock_sha256': next(item['sha256'] for item in files if item['path'] == 'uv.lock'),
            'npm_lock_sha256': next(item['sha256'] for item in files
                                    if item['path'] == 'app/package-lock.json')}


@contextlib.contextmanager
def immutable_source(repo: Path, source: dict, cache: Path):
    """Use only git-object bytes for releases, never the mutable checkout."""
    if source['mode'] != 'release':
        yield repo
        return
    with tempfile.TemporaryDirectory(prefix='release-source-', dir=cache) as temporary:
        snapshot = Path(temporary)
        archive = subprocess.check_output(['git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf',
                                           '-C', str(repo), 'archive', source['commit']])
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(snapshot, filter='data')
        for item in source['files']:
            path = snapshot / item['path']
            if item.get('type') == 'symlink':
                if not path.is_symlink() or os.readlink(path) != item['target']:
                    raise ValueError(f'Immutable source mismatch: {item["path"]}')
            elif (path.is_symlink() or digest(path) != item['sha256']
                  or path.stat().st_size != item['size']):
                raise ValueError(f'Immutable source mismatch: {item["path"]}')
        # Existing Linux engine staging uses git ls-files as its allowlist.
        subprocess.run(['git', '-c', 'init.templateDir=', 'init', '-q', str(snapshot)], check=True)
        subprocess.run(['git', '-C', str(snapshot), 'fetch', '-q', '--no-tags', str(repo),
                        source['commit']], check=True)
        subprocess.run(['git', '-C', str(snapshot), 'reset', '--soft', source['commit']],
                       check=True)
        subprocess.run(['git', '-C', str(snapshot), 'read-tree', source['commit']], check=True)
        yield snapshot


def stage_build(stage: Path, cache: Path, platform: str, source: dict,
                inventory_only: bool, electron: Path) -> dict:
    runtime = stage / 'runtime'
    runtime.mkdir(exist_ok=True)
    inputs = []
    lanes = ['runtime', 'chromium', 'models', 'pdf']
    lanes.append('tools' if platform == 'win32' else 'helpers')
    for lane in lanes:
        metadata = stage / f'{lane}-metadata.json'
        if not inventory_only:
            module_name = 'windows_runtime' if lane == 'runtime' and platform == 'win32' else lane
            module = importlib.import_module(module_name)
            if lane == 'runtime' and platform == 'win32':
                result = module.stage_windows_runtime(REPO, runtime, cache)
            else:
                function = getattr(module, f'stage_{lane}')
                result = function(stage if lane == 'tools' else runtime, cache)
            metadata.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        inputs.append(json.loads(metadata.read_text()))
    if platform == 'win32':
        from windows_dll import audit_dll_dependencies
        audits = []
        # Each supplier closure is audited in its actual loader root. Do not
        # make an unrelated Python DLL appear loadable by a browser or SSH.
        for name, root in [('chromium', runtime / 'browser'), ('tools', stage / 'tools')]:
            seal = sealing_module()
            seal.windows_inventory(root)
            audit = audit_dll_dependencies(root, package=name)
            audits.append({'lane': name, 'audit': audit})
        inputs.append({'dll_audits': audits, 'native_execution': 'not implied by static audit'})
    legal = stage / 'legal'
    legal.mkdir(exist_ok=True)
    (legal / 'resource-provenance.json').write_text(
        json.dumps(inputs, indent=2, sort_keys=True) + '\n')
    shutil.copyfile(REPO / 'maintenance/UPSTREAM-LICENSE', legal / 'UPSTREAM-LICENSE')
    stage_font_notices(legal)
    app_inputs = json.loads((HERE / 'app-inputs.json').read_text())
    if platform == 'win32':
        app_inputs['electron'] = WINDOWS_ELECTRON
        app_inputs['builder_binaries'] = []
    executable = electron / ('electron.exe' if platform == 'win32' else 'electron')
    if digest(executable) != app_inputs['electron']['executable_sha256']:
        raise ValueError('Pinned Electron executable digest mismatch; '
                         'provision the reviewed version')
    for name in ['LICENSE', 'LICENSES.chromium.html']:
        if (platform == 'win32'
                and digest(electron / name) != WINDOWS_ELECTRON['notice_sha256'][name]):
            raise ValueError(f'Pinned Windows Electron notice digest mismatch: {name}')
        shutil.copyfile(electron / name, legal / ('Electron-' + name))
    if platform == 'linux':
        # Preserve the Linux payload normalization and symlink contract exactly.
        for directory in [runtime, legal]:
            for path in [directory, *directory.rglob('*')]:
                if path.is_symlink():
                    continue
                if path.is_dir():
                    path.chmod(0o755)
                elif path.is_file():
                    path.chmod(0o755 if stat.S_IMODE(path.stat().st_mode) & 0o111 else 0o644)
    seal = sealing_module()
    if platform == 'win32':
        files = seal.windows_inventory(stage, exclude=('bundle-manifest.json',))
    else:
        files = inventory(runtime) + inventory(legal, prefix='legal')
    seal.assert_platform_resources(files, platform)
    manifest = {
        'schema': 1, 'platform': platform,
        'product': {'name': 'odin-desktop',
                    'version': json.loads((REPO / 'app/package.json').read_text())['version'],
                    'channel': 'unreleased-candidate'},
        'source': source, 'inputs': [app_inputs, *inputs],
        'files': sorted(files, key=lambda item: item['path']),
    }
    (stage / 'bundle-manifest.json').write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return {'files': len(manifest['files']),
            'bytes': sum(item['size'] for item in manifest['files']),
            'manifest_sha256': digest(stage / 'bundle-manifest.json')}


def main() -> None:
    global REPO, HERE, FONTS
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path, default=REPO / '.packaging-stage')
    parser.add_argument('--cache', type=Path, default=Path(os.environ.get(
        'ODIN_PACKAGING_CACHE', Path.home() / '.cache/odin-desktop-packaging')))
    parser.add_argument('--inventory-only', action='store_true')
    parser.add_argument('--platform', choices=['linux', 'win32'], default=sys.platform)
    parser.add_argument('--provenance', choices=['worktree', 'release'], default='worktree')
    options = parser.parse_args()
    stage, cache = options.stage.resolve(), options.cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    if options.platform != sys.platform:
        raise ValueError('Native runtime staging requires the selected host OS')
    if options.inventory_only and options.provenance == 'release':
        raise ValueError('Release builds refuse inventory-only reused worktree stages')
    source_repo = REPO
    source = source_record(source_repo, options.provenance)
    electron = source_repo / 'app/node_modules/electron/dist'
    with immutable_source(source_repo, source, cache) as repo:
        REPO, HERE = repo, repo / 'app/packaging'
        FONTS = repo / 'app/src/renderer/src/assets/fonts'
        sys.path.insert(0, str(HERE / 'python'))
        if options.platform == 'win32' and not options.inventory_only:
            if stage.exists():
                raise ValueError('Windows stage target already exists; refusing stage mixing')
            stage.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                    prefix='.runtime-stage-', dir=stage.parent) as temporary:
                work = Path(temporary) / 'resources'
                work.mkdir()
                result = stage_build(work, cache, options.platform, source, False, electron)
                if source_record(source_repo, options.provenance) != source:
                    raise ValueError('Source changed during runtime build; stage not published')
                os.replace(work, stage)
        else:
            stage.mkdir(parents=True, exist_ok=True)
            if options.inventory_only:
                prior = json.loads((stage / 'bundle-manifest.json').read_text())
                if (prior.get('platform', 'linux') != options.platform
                        or prior.get('source') != source):
                    raise ValueError('Inventory-only requires unchanged source '
                                     'and platform provenance')
            result = stage_build(stage, cache, options.platform, source,
                                 options.inventory_only, electron)
            if source_record(source_repo, options.provenance) != source:
                raise ValueError('Source changed during runtime build')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if callable(getattr(exc, 'as_dict', None)):
            print(json.dumps({'status': 'refused', 'reason': exc.as_dict()},
                             sort_keys=True), file=sys.stderr)
            raise SystemExit(1) from None
        raise
