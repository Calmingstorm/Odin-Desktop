import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchIsolated } from './real-core-isolation.mjs'
import { runRealCoreShards } from './real-core-shards.mjs'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..')
try {
  await runRealCoreShards({ launch: launchIsolated, command: process.execPath, cwd: app,
    config: resolve(app, 'vitest.real-core.config.ts'),
    args: [resolve(app, 'node_modules/vitest/vitest.mjs'), 'run'], extraArgs: process.argv.slice(2) })
} catch (error) {
  console.error(error.message)
  process.exitCode = 1
}
