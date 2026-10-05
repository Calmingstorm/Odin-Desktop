// The renderer/Chromium AX gate is not an Orca or AT-SPI qualification.
import { resolve } from 'node:path'
import { launchIsolated } from './real-core-isolation.mjs'

const appDir = resolve(import.meta.dirname, '..')
await launchIsolated('xvfb-run', ['-a', '-s', '-screen 0 1440x1000x24', 'dbus-run-session', '--',
  process.execPath, resolve(appDir, 'node_modules/@playwright/test/cli.js'), 'test', ...process.argv.slice(2)], {
  cwd: appDir,
  env: process.env.ODIN_APP_A11Y_REPORT ? { ODIN_APP_A11Y_REPORT: process.env.ODIN_APP_A11Y_REPORT } : {},
  timeoutMs: 900_000
})
