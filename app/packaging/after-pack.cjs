// The same sealed unpacked tree feeds .deb and AppImage. This hook never publishes.
const { spawnSync } = require('node:child_process')
const { join } = require('node:path')
const { copyFileSync, renameSync, writeFileSync, chmodSync, lstatSync, readdirSync } = require('node:fs')

// Set construction permissions BEFORE sealing, not when verifying a candidate.
// Archive extractors apply the extracting user's umask to non-executable files.
// Canonical modes also agree with fpm's late profile write under build-linux's
// explicit 022 umask. Keep executable resources executable; never follow links.
function requireDirectory(root) {
  const rootInfo = lstatSync(root)
  if (!rootInfo.isDirectory() || rootInfo.isSymbolicLink()) {
    throw new Error(`Packaged tree root is not a directory: ${root}`)
  }
}

function normalizeTree(root, resources = false) {
  requireDirectory(root)
  // Include each traversal root, not just its children. Electron's unpacked
  // app root and resources root can both inherit 0775 from umask 0002.
  chmodSync(root, 0o755)
  for (const name of readdirSync(root)) {
    const path = join(root, name)
    const info = lstatSync(path)
    if (info.isSymbolicLink()) continue
    if (info.isDirectory()) {
      normalizeTree(path, resources || name === 'resources')
    } else if (info.isFile()) {
      if (resources) chmodSync(path, info.mode & 0o111 ? 0o755 : 0o644)
    } else {
      throw new Error(`Special packaged resource: ${path}`)
    }
  }
}

module.exports = async (context) => {
  requireDirectory(context.appOutDir)
  requireDirectory(join(context.appOutDir, 'resources'))
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
  normalizeTree(context.appOutDir)
  const result = spawnSync('python3', [join(__dirname, 'finalize-manifest.py'), join(context.appOutDir, 'resources')], {
    stdio: 'inherit', env: process.env
  })
  if (result.status !== 0) throw new Error('Packaged resource manifest failed')
}
