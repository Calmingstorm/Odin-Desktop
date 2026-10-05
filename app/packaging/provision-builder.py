#!/usr/bin/env python3
"""Hash-checked build tools; electron-builder cannot silently choose new bytes."""
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import zipfile
import hashlib

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE / 'python'))
from runtime import _download, sha256

inputs = json.loads((HERE / 'app-inputs.json').read_text())
cache = Path(os.environ.get('ODIN_PACKAGING_CACHE', Path.home() / '.cache/odin-desktop-packaging'))
tools = cache / 'builder-tools-v1'
archives = cache / 'builder-inputs'
tools.mkdir(parents=True, exist_ok=True)
electron_archive = _download(inputs['electron'], archives)
electron_dir = REPO / 'app/node_modules/electron/dist'
with zipfile.ZipFile(electron_archive) as archive:
    for member in archive.infolist():
        if member.is_dir():
            continue
        path = PurePosixPath(member.filename)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Unsafe Electron archive entry')
        installed = electron_dir.joinpath(*path.parts)
        if not installed.is_file() or sha256(installed) != hashlib.sha256(archive.read(member)).hexdigest():
            raise ValueError('Installed Electron differs from pinned archive: ' + member.filename)
seven = REPO / 'app/node_modules/7zip-bin/linux/x64/7za'
# npm --ignore-scripts deliberately skips 7zip-bin's chmod installer. These
# locked npm bytes are a project-local build tool, not a system modification.
seven.chmod(0o755)
for resource in inputs['builder_binaries']:
    archive = _download(resource, archives)
    target = tools / resource['cache_directory']
    marker = target / '.odin-input-sha256'
    inventory_path = target / '.odin-input-files.json'
    if target.exists():
        if not marker.exists() or marker.read_text().strip() != resource['sha256']:
            raise ValueError('Build tool cache has unreviewed provenance: ' + str(target))
        if inventory_path.exists():
            observed = {p.relative_to(target).as_posix(): sha256(p)
                        for p in target.rglob('*') if p.is_file()
                        and p.name not in {'.odin-input-sha256', '.odin-input-files.json'}}
            if observed != json.loads(inventory_path.read_text()):
                raise ValueError('Build tool cache content changed: ' + str(target))
            continue
        raise ValueError('Build tool cache has no digest inventory; use a fresh tool cache')
    target.parent.mkdir(parents=True, exist_ok=True)
    listing = subprocess.check_output([str(seven), 'l', '-slt', str(archive)], text=True)
    entries = listing.split('----------\n', 1)[-1]
    for line in entries.splitlines():
        if line.startswith('Path = '):
            value = line[7:]
            path = PurePosixPath(value)
            if path.is_absolute() or '..' in path.parts or '\\' in value:
                raise ValueError('Unsafe builder archive entry')
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        work = Path(temporary)
        subprocess.run([str(seven), 'x', '-y', str(archive), '-o' + str(work)], check=True,
                       stdout=subprocess.DEVNULL)
        for path in work.rglob('*'):
            if path.is_symlink() and not path.resolve().is_relative_to(work):
                raise ValueError('Escaping builder archive link')
        contents = list(work.iterdir())
        extracted = contents[0] if len(contents) == 1 and contents[0].is_dir() else work
        shutil.copytree(extracted, target, symlinks=True)
    marker.write_text(resource['sha256'] + '\n')
    inventory_path.write_text(json.dumps({p.relative_to(target).as_posix(): sha256(p)
                                         for p in target.rglob('*') if p.is_file() and p != marker},
                                        indent=2, sort_keys=True) + '\n')
print(tools)
