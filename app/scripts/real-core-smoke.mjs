// Electron and the real core run together in a disposable PID namespace and
// xvfb display. The runner verifies unprivileged ownership and private XDG/HOME.
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { launchIsolated, repositoryRoot } from './real-core-isolation.mjs'

const appDir = resolve(import.meta.dirname, '..')
const python = resolve(process.env.ODIN_DESKTOP_ENGINE_PYTHON || join(repositoryRoot, '.venv/bin/python'))
const root = mkdtempSync(join(tmpdir(), 'odin-real-smoke-output-'))
const out = process.env.ODIN_SMOKE_OUT ? resolve(process.env.ODIN_SMOKE_OUT) : join(root, 'real-core.png')

try {
  await launchIsolated('dbus-run-session', ['--config-file',
    join(repositoryRoot, 'tests/desktop_fixtures/private-session.conf'), '--',
    'xvfb-run', '-a', '-s', '-screen 0 1280x800x24 -nolisten tcp',
    join(appDir, 'node_modules/.bin/electron'), appDir, '--smoke-test'], {
    // Deliberately launch from app/: its TypeScript src/ must not shadow the installed engine.
    cwd: appDir,
    // Bound the full multi-screen smoke under CI load; checkpoint deadlines and single-run behavior stay unchanged.
    timeoutMs: 600_000,
    env: {
      ODIN_DESKTOP_ENGINE_PYTHON: python,
      ODIN_DESKTOP_CORE_CMD: JSON.stringify([python, '-B', '-P', '-m', 'src']),
      ODIN_SMOKE_REAL_CORE: '1',
      ODIN_SMOKE_OUT: out
    }
  })
  if (!existsSync(out)) throw new Error('Real-core smoke did not create its checkpoint screenshot.')
  console.log(`real-core smoke PASSED${process.env.ODIN_SMOKE_OUT ? ` screenshot: ${out}` : ' (temporary screenshot verified)'}`)
} catch (error) {
  console.error(`real-core smoke FAILED: ${error.message}`)
  process.exitCode = 1
} finally {
  rmSync(root, { recursive: true, force: true })
}
