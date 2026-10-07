#!/usr/bin/env python3
"""Stage the locked runtime once; both candidate formats consume these bytes."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FONTS = REPO / 'app/src/renderer/src/assets/fonts'


def stage_font_notices(legal: Path) -> list[str]:
    """The renderer bundles OFL fonts inside app.asar; each font's licence ships readable in legal/fonts."""
    target = legal / 'fonts'
    target.mkdir(exist_ok=True)
    names = sorted(path.name for path in FONTS.glob('OFL-*.txt'))
    for name in names:
        shutil.copyfile(FONTS / name, target / name)
    return names
sys.path.insert(0, str(HERE / 'python'))
from manifest import digest, inventory  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path, default=REPO / '.packaging-stage')
    parser.add_argument('--cache', type=Path, default=Path(os.environ.get(
        'ODIN_PACKAGING_CACHE', Path.home() / '.cache/odin-desktop-packaging')))
    parser.add_argument('--inventory-only', action='store_true')
    options = parser.parse_args()
    stage, cache = options.stage.resolve(), options.cache.resolve()
    stage.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    runtime = stage / 'runtime'
    inputs = []
    for lane in ['runtime', 'chromium', 'models', 'pdf', 'helpers']:
        metadata = stage / f'{lane}-metadata.json'
        if not options.inventory_only:
            module = importlib.import_module(lane)
            function = getattr(module, f'stage_{lane}')
            result = function(runtime, cache)
            metadata.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        inputs.append(json.loads(metadata.read_text()))
    legal = stage / 'legal'
    legal.mkdir(exist_ok=True)
    (legal / 'resource-provenance.json').write_text(json.dumps(inputs, indent=2, sort_keys=True) + '\n')
    shutil.copyfile(REPO / 'maintenance/UPSTREAM-LICENSE', legal / 'UPSTREAM-LICENSE')
    stage_font_notices(legal)
    app_inputs = json.loads((HERE / 'app-inputs.json').read_text())
    electron = REPO / 'app/node_modules/electron/dist'
    if digest(electron / 'electron') != app_inputs['electron']['executable_sha256']:
        raise ValueError('Pinned Electron executable digest mismatch; provision the reviewed version')
    for name in ['LICENSE', 'LICENSES.chromium.html']:
        shutil.copyfile(electron / name, legal / ('Electron-' + name))
    # Extraction may mask group/world write permissions. Normalize these early
    # inputs; after-pack canonicalizes builder-created resources before sealing.
    for directory in [runtime, legal]:
        for path in [directory, *directory.rglob('*')]:
            if path.is_symlink():
                continue
            if path.is_dir():
                path.chmod(0o755)
            elif path.is_file():
                path.chmod(0o755 if stat.S_IMODE(path.stat().st_mode) & 0o111 else 0o644)
    commit = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    manifest = {
        'schema': 1,
        'product': {'name': 'odin-desktop', 'version': json.loads((REPO / 'app/package.json').read_text())['version'],
                    'channel': 'unreleased-candidate'},
        'source': {'commit': commit, 'uv_lock_sha256': digest(REPO / 'uv.lock'),
                   'npm_lock_sha256': digest(REPO / 'app/package-lock.json')},
        'inputs': [app_inputs, *inputs],
        'files': sorted(inventory(runtime) + inventory(legal, prefix='legal'), key=lambda item: item['path']),
    }
    (stage / 'bundle-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'files': len(manifest['files']), 'bytes': sum(item['size'] for item in manifest['files']),
                      'manifest_sha256': digest(stage / 'bundle-manifest.json')}, indent=2))


if __name__ == '__main__':
    main()
