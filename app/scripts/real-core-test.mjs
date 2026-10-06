import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchIsolated } from './real-core-isolation.mjs'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..')
try {
  // Bound the whole suite under CI load; individual test deadlines and single-run behavior stay unchanged.
  await launchIsolated(process.execPath, [resolve(app, 'node_modules/vitest/vitest.mjs'), 'run', '--config',
    resolve(app, 'vitest.real-core.config.ts'), ...process.argv.slice(2)], { cwd: app, timeoutMs: 600_000 })
} catch (error) {
  console.error(error.message)
  process.exitCode = 1
}
