// The installed Windows app's construction hook (phase 4, P7 and P8), selected by
// electron-builder.windows.yml. Electron's own executable stays the app: it holds its package lease
// itself, through the bundled guardian copied here, so there's no launcher to write. The resources
// are then sealed by the same finalizer as Linux, run by the build's locked Python, which
// packaging/build-windows.mjs names. This hook never publishes.
const { spawnSync } = require('node:child_process')
const { join } = require('node:path')
const { copyFileSync, lstatSync } = require('node:fs')

function requireDirectory(root) {
  const info = lstatSync(root)
  if (!info.isDirectory() || info.isSymbolicLink()) {
    throw new Error(`Packaged tree root is not a directory: ${root}`)
  }
}

module.exports = async (context) => {
  if (context.electronPlatformName !== 'win32') {
    throw new Error('The Windows construction hook builds Windows only')
  }
  const python = process.env.ODIN_BUILD_PYTHON
  if (!python) throw new Error('Windows candidates are built by packaging/build-windows.mjs')
  requireDirectory(context.appOutDir)
  const resources = join(context.appOutDir, 'resources')
  requireDirectory(resources)
  // electron-builder names Windows' executable after the product (Odin.exe).
  const executable = join(context.appOutDir, `${context.packager.appInfo.productFilename}.exe`)
  const info = lstatSync(executable)
  if (!info.isFile() || info.isSymbolicLink()) throw new Error(`Packaged executable is not a file: ${executable}`)
  copyFileSync(join(__dirname, 'ownership.py'), join(resources, 'ownership.py'))
  const result = spawnSync(python, ['-I', '-B', join(__dirname, 'finalize-manifest.py'), resources], {
    stdio: 'inherit', env: process.env
  })
  if (result.status !== 0) throw new Error('Packaged resource manifest failed')
}
