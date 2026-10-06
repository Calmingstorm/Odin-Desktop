// Source-build lifecycle acceptance. No workstation display, bus or profile is
// passed through; all Electron/core/fixture descendants live in the PID namespace.
import { existsSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { launchIsolated, repositoryRoot } from './real-core-isolation.mjs'

const appDir = resolve(import.meta.dirname, '..')
const output = process.env.ODIN_APP_E2E_OUT ? resolve(process.env.ODIN_APP_E2E_OUT) : ''
if (output) mkdirSync(output, { recursive: true, mode: 0o700 })
if (!existsSync(join(appDir, 'out/main/index.js'))) {
  throw new Error('Build the source app first with npm run build. No installed-package fallback.')
}
try {
  await launchIsolated('dbus-run-session', ['--config-file',
    join(repositoryRoot, 'tests/desktop_fixtures/private-session.conf'), '--', 'xvfb-run', '-a', '-s',
    '-screen 0 1280x800x24 -nolisten tcp', process.execPath,
    join(appDir, 'node_modules/@playwright/test/cli.js'), 'test',
    '--config', join(appDir, 'playwright.config.ts'), ...process.argv.slice(2)], {
    cwd: repositoryRoot,
    timeoutMs: 10 * 60_000,
    env: { ODIN_APP_E2E: '1', ...(output ? { ODIN_APP_E2E_OUT: output } : {}) }
  })
} catch (error) {
  console.error(`Source-build lifecycle qualification FAILED: ${error.message}`)
  process.exitCode = 1
}
