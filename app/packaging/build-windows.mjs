// Local, non-publishing Windows candidate build, on Windows: the Windows runtime stage, the app,
// then electron-builder.windows.yml's per-user installer. The build's Python is the repository's
// locked environment (`uv sync --locked --extra dev`), or ODIN_BUILD_PYTHON; it stages the runtime
// and seals the resources. ODIN_PACKAGING_RELEASE=1 asks for release provenance, which refuses an
// uncommitted tree.
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

if (process.platform !== 'win32') {
  process.stderr.write('Windows candidates are built on Windows.\n')
  process.exit(1)
}
const app = resolve(import.meta.dirname, '..')
process.env.SOURCE_DATE_EPOCH = '1791158400'
const python = process.env.ODIN_BUILD_PYTHON || resolve(app, '..', '.venv', 'Scripts', 'python.exe')
if (!existsSync(python)) {
  process.stderr.write(`The build's Python is missing: ${python}. Run uv sync --locked --extra dev, `
    + 'or set ODIN_BUILD_PYTHON.\n')
  process.exit(1)
}
process.env.ODIN_BUILD_PYTHON = python
const release = process.env.ODIN_PACKAGING_RELEASE === '1'
// Node runs the JavaScript entry points itself: Windows refuses to spawn .cmd shims without a shell.
const run = (command, args) => {
  const result = spawnSync(command, args, { cwd: app, stdio: 'inherit', env: process.env })
  if (result.status !== 0) process.exit(result.status || 1)
}
run(python, ['-I', '-B', resolve(import.meta.dirname, 'build-runtime.py'), '--platform', 'win32',
  '--provenance', release ? 'release' : 'worktree'])
run(process.execPath, [resolve(app, 'node_modules/electron-vite/bin/electron-vite.js'), 'build'])
run(process.execPath, [resolve(app, 'node_modules/electron-builder/cli.js'), '--config', 'electron-builder.windows.yml',
  '--win', 'nsis', '--x64', '--publish', 'never'])
