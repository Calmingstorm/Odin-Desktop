// The installed Mac app's construction hook (phase 4), selected by electron-builder.macos.yml.
// Electron's own executable stays the app: it holds its package lease itself, through
// ownership.py copied here, and runs the engine under the guardian that the runtime stage built.
// The menu bar's template images must be in the app archive. The resources are then sealed by the
// same finalizer as Linux, run by the build's locked Python, which packaging/build-macos.mjs names.
// A signed build (ODIN_MACOS_SIGN_IDENTITY, from packaging/build-macos.mjs --signed) first signs every
// Mach-O under Resources (sign-macos-resources.py), so the seal records the signed bytes;
// electron-builder signs the rest of the app and leaves Resources alone. This hook never publishes.
const { spawnSync } = require('node:child_process')
const { join } = require('node:path')
const { chmodSync, copyFileSync, lstatSync } = require('node:fs')

function requireDirectory(root) {
  const info = lstatSync(root)
  if (!info.isDirectory() || info.isSymbolicLink()) {
    throw new Error(`Packaged tree root is not a directory: ${root}`)
  }
}

module.exports = async (context) => {
  if (context.electronPlatformName !== 'darwin') {
    throw new Error('The Mac construction hook builds macOS only')
  }
  const python = process.env.ODIN_BUILD_PYTHON
  if (!python) throw new Error('Mac candidates are built by packaging/build-macos.mjs')
  const bundle = join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`)
  requireDirectory(bundle)
  const resources = join(bundle, 'Contents', 'Resources')
  requireDirectory(resources)
  const guardian = lstatSync(join(resources, 'runtime', 'odin-guardian'))
  if (!guardian.isFile() || guardian.isSymbolicLink() || !(guardian.mode & 0o111)) {
    throw new Error('The packaged runtime has no executable guardian')
  }
  const { listPackage } = require('@electron/asar')
  const archived = new Set(listPackage(join(resources, 'app.asar'), { isPack: false }))
  for (const name of ['/resources/trayTemplate.png', '/resources/trayTemplate@2x.png']) {
    if (!archived.has(name)) throw new Error(`The app archive is missing ${name}`)
  }
  copyFileSync(join(__dirname, 'ownership.py'), join(resources, 'ownership.py'))
  chmodSync(join(resources, 'ownership.py'), 0o644)
  const identity = process.env.ODIN_MACOS_SIGN_IDENTITY
  if (identity) {
    const keychain = process.env.ODIN_MACOS_KEYCHAIN
    const signed = spawnSync(python, ['-I', '-B', join(__dirname, 'sign-macos-resources.py'), resources,
      '--identity', identity, ...(keychain ? ['--keychain', keychain] : [])], { stdio: 'inherit', env: process.env })
    if (signed.status !== 0) throw new Error('Signing the packaged resources failed')
  }
  const result = spawnSync(python, ['-I', '-B', join(__dirname, 'finalize-manifest.py'), resources], {
    stdio: 'inherit', env: process.env
  })
  if (result.status !== 0) throw new Error('Packaged resource manifest failed')
}
