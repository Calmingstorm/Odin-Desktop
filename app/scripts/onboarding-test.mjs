// No desktop/display/session credentials enter this gate. Build first, then run
// the actual Electron app and actual core inside the established isolation gate.
import { join } from 'node:path'
import { launchIsolated, repositoryRoot } from './real-core-isolation.mjs'

await launchIsolated('xvfb-run', ['-a', '-s', '-screen 0 1280x800x24',
  process.execPath, join(repositoryRoot, 'app/node_modules/vitest/vitest.mjs'),
  'run', '--config', 'vitest.onboarding.config.ts', ...process.argv.slice(2)], {
  // Bound all Electron launches under CI load without changing individual test deadlines or retrying.
  cwd: join(repositoryRoot, 'app'), timeoutMs: 600_000
})
