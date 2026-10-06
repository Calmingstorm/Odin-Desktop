// The same sealed unpacked tree feeds .deb and AppImage. This hook never publishes.
const { spawnSync } = require('node:child_process')
const { join } = require('node:path')
const { copyFileSync, renameSync, writeFileSync, chmodSync } = require('node:fs')

module.exports = async (context) => {
  const executable = join(context.appOutDir, 'odin-desktop')
  renameSync(executable, `${executable}.bin`)
  copyFileSync(join(__dirname, 'ownership.py'), join(context.appOutDir, 'resources', 'ownership.py'))
  writeFileSync(executable, '#!/bin/sh\nset -eu\n' +
    'SELF=$(readlink -f -- "$0")\n' +
    'ROOT=$(CDPATH= cd -- "$(dirname -- "$SELF")" && pwd)\n' +
    'KIND=appimage\n[ "$ROOT" != /opt/Odin ] || KIND=deb\n' +
    'exec "$ROOT/resources/runtime/python/bin/python3" -I -B ' +
    '"$ROOT/resources/ownership.py" exec --kind "$KIND" -- "$ROOT/odin-desktop.bin" "$@"\n')
  chmodSync(executable, 0o755)
  const result = spawnSync('python3', [join(__dirname, 'finalize-manifest.py'), join(context.appOutDir, 'resources')], {
    stdio: 'inherit', env: process.env
  })
  if (result.status !== 0) throw new Error('Packaged resource manifest failed')
}
