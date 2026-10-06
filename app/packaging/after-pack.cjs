// The same sealed unpacked tree feeds .deb and AppImage. This hook never publishes.
const { spawnSync } = require('node:child_process')
const { join } = require('node:path')
const { copyFileSync, renameSync, writeFileSync, chmodSync, lstatSync, readdirSync } = require('node:fs')

// Set construction permissions BEFORE sealing, not when verifying a candidate.
// Archive extractors apply the extracting user's umask to non-executable files.
// Canonical modes also agree with fpm's late profile write under build-linux's
// explicit 022 umask. Keep executable resources executable; never follow links.
function normalizeResources(root) {
  for (const name of readdirSync(root)) {
    const path = join(root, name)
    const info = lstatSync(path)
    if (info.isSymbolicLink()) continue
    if (info.isDirectory()) {
      chmodSync(path, 0o755)
      normalizeResources(path)
    } else if (info.isFile()) {
      chmodSync(path, info.mode & 0o111 ? 0o755 : 0o644)
    } else {
      throw new Error(`Special packaged resource: ${path}`)
    }
  }
}

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
  normalizeResources(join(context.appOutDir, 'resources'))
  const result = spawnSync('python3', [join(__dirname, 'finalize-manifest.py'), join(context.appOutDir, 'resources')], {
    stdio: 'inherit', env: process.env
  })
  if (result.status !== 0) throw new Error('Packaged resource manifest failed')
}
