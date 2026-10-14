// Local, non-publishing Mac candidate build, on Apple silicon: the macOS runtime stage, the app, then
// electron-builder.macos.yml's .dmg. The build's Python is the repository's locked environment
// (`uv sync --locked --extra dev`), or ODIN_BUILD_PYTHON; it stages the runtime and seals the
// resources. ODIN_PACKAGING_RELEASE=1 asks for release provenance, which refuses an uncommitted tree.
//
// A plain build signs nothing, whatever the environment holds. --signed is macos-release.yml's build
// (phase 5): ODIN_MACOS_SIGN_IDENTITY names the Developer ID ("Developer ID Application: …") in a
// keychain on the search list (ODIN_MACOS_KEYCHAIN names it), and APPLE_API_KEY, APPLE_API_KEY_ID and
// APPLE_API_ISSUER the notary key. after-pack-macos.cjs signs Resources before sealing them;
// electron-builder.macos.signed.yml signs, notarizes and staples the app; notarize-macos-dmg.py then
// signs, notarizes, staples and assesses the .dmg.
import { spawnSync } from 'node:child_process'
import { existsSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

if (process.platform !== 'darwin' || process.arch !== 'arm64') {
  process.stderr.write('Mac candidates are built on Apple silicon.\n')
  process.exit(1)
}
const app = resolve(import.meta.dirname, '..')
process.env.SOURCE_DATE_EPOCH = '1791158400'
// No signing identity is ever looked up: a signed build names its own.
process.env.CSC_IDENTITY_AUTO_DISCOVERY = 'false'
const SIGNING = ['ODIN_MACOS_SIGN_IDENTITY', 'ODIN_MACOS_KEYCHAIN', 'APPLE_API_KEY', 'APPLE_API_KEY_ID',
  'APPLE_API_ISSUER']
const PREFIX = 'Developer ID Application: '
const signed = process.argv.includes('--signed')
if (signed) {
  const missing = SIGNING.filter((name) => name !== 'ODIN_MACOS_KEYCHAIN' && !process.env[name])
  if (missing.length || !process.env.ODIN_MACOS_SIGN_IDENTITY.startsWith(PREFIX)) {
    process.stderr.write(`A signed build needs a Developer ID Application identity and the notary key: ${missing.join(', ')}\n`)
    process.exit(1)
  }
} else {
  for (const name of SIGNING) delete process.env[name]
}
const python = process.env.ODIN_BUILD_PYTHON || resolve(app, '..', '.venv', 'bin', 'python')
if (!existsSync(python)) {
  process.stderr.write(`The build's Python is missing: ${python}. Run uv sync --locked --extra dev, `
    + 'or set ODIN_BUILD_PYTHON.\n')
  process.exit(1)
}
process.env.ODIN_BUILD_PYTHON = python
const release = process.env.ODIN_PACKAGING_RELEASE === '1'
const run = (command, args) => {
  const result = spawnSync(command, args, { cwd: app, stdio: 'inherit', env: process.env })
  if (result.status !== 0) throw Object.assign(new Error(`${command} exited ${result.status}`), { code: result.status })
}
try {
  run(python, ['-I', '-B', resolve(import.meta.dirname, 'build-runtime.py'), '--platform', 'darwin',
    '--provenance', release ? 'release' : 'worktree'])
  run(process.execPath, [resolve(app, 'node_modules/electron-vite/bin/electron-vite.js'), 'build'])
  const identity = process.env.ODIN_MACOS_SIGN_IDENTITY
  run(process.execPath, [resolve(app, 'node_modules/electron-builder/cli.js'), '--config',
    signed ? 'electron-builder.macos.signed.yml' : 'electron-builder.macos.yml',
    // electron-builder wants the name without its certificate type and picks the type itself.
    ...(signed ? [`-c.mac.identity=${identity.slice(PREFIX.length)}`] : []),
    '--mac', 'dmg', '--arm64', '--publish', 'never'])
  if (signed) {
    const output = resolve(app, '..', '.packaging-candidates')
    const images = readdirSync(output).filter((name) => name.endsWith('-arm64.dmg'))
    if (images.length !== 1) throw new Error(`Expected one disk image in ${output}: ${images.join(', ')}`)
    const dmg = join(output, images[0])
    const keychain = process.env.ODIN_MACOS_KEYCHAIN
    run(python, ['-I', '-B', resolve(import.meta.dirname, 'notarize-macos-dmg.py'), dmg,
      '--identity', identity, ...(keychain ? ['--keychain', keychain] : []),
      '--key', process.env.APPLE_API_KEY, '--key-id', process.env.APPLE_API_KEY_ID,
      '--issuer', process.env.APPLE_API_ISSUER, '--evidence', `${dmg}.notary.json`])
  }
} catch (error) {
  process.stderr.write(`${error.message}\n`)
  process.exit(error.code || 1)
}
