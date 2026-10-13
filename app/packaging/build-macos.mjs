// Local, non-publishing Mac candidate build, on Apple silicon: the macOS runtime stage, the app, then
// electron-builder.macos.yml's .dmg. The build's Python is the repository's locked environment
// (`uv sync --locked --extra dev`), or ODIN_BUILD_PYTHON; it stages the runtime and seals the
// resources. ODIN_PACKAGING_RELEASE=1 asks for release provenance, which refuses an uncommitted tree.
// Nothing is signed here; phase 5's release build signs and notarizes.
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

if (process.platform !== 'darwin' || process.arch !== 'arm64') {
  process.stderr.write('Mac candidates are built on Apple silicon.\n')
  process.exit(1)
}
const app = resolve(import.meta.dirname, '..')
process.env.SOURCE_DATE_EPOCH = '1791158400'
// No signing identity is looked up for a candidate.
process.env.CSC_IDENTITY_AUTO_DISCOVERY = 'false'
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
  run(process.execPath, [resolve(app, 'node_modules/electron-builder/cli.js'), '--config',
    'electron-builder.macos.yml', '--mac', 'dmg', '--arm64', '--publish', 'never'])
} catch (error) {
  process.stderr.write(`${error.message}\n`)
  process.exit(error.code || 1)
}
