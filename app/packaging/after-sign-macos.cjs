// The signed Mac app's notarization (phase 5). electron-builder runs this after it signs the app
// and before it builds the .dmg, so the .dmg holds the stapled app. electron-builder's own
// notarization keeps no record of Apple's submission; this one keeps the submission ID and the
// verdict beside the .dmg (app.notary.json) for the receipt. Only a signed build does anything here.
const { spawnSync } = require('node:child_process')
const { join } = require('node:path')

module.exports = async (context) => {
  if (context.electronPlatformName !== 'darwin' || !process.env.ODIN_MACOS_SIGN_IDENTITY) return
  const python = process.env.ODIN_BUILD_PYTHON
  if (!python) throw new Error('Mac candidates are built by packaging/build-macos.mjs')
  const app = join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`)
  const result = spawnSync(python, ['-I', '-B', join(__dirname, 'notarize-macos-app.py'), app,
    '--key', process.env.APPLE_API_KEY, '--key-id', process.env.APPLE_API_KEY_ID,
    '--issuer', process.env.APPLE_API_ISSUER, '--evidence', join(context.outDir, 'app.notary.json')],
  { stdio: 'inherit', env: process.env })
  if (result.status !== 0) throw new Error('Notarizing the signed app failed')
}
