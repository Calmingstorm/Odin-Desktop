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
const seededOut = out.replace(/\.png$/i, '') + '-seeded-work-proof.png'
// Two independent namespaces and fresh profiles. The production pass never
// imports the workProof bootstrap; the second uses the same entry as the harness.
const phases = [
  { label: 'production entry / fresh real profile', entry: ['-m', 'src'], workProof: '0', out },
  { label: 'seeded work proof', entry: [join(repositoryRoot, 'app/test/services-b-core.py')], workProof: '1', out: seededOut }
]

try {
  for (const phase of phases) {
    console.log(`real-core smoke START: ${phase.label}`)
    await launchIsolated('xvfb-run', ['-a', '-s', '-screen 0 1280x800x24',
      join(appDir, 'node_modules/.bin/electron'), appDir, '--smoke-test'], {
      // Deliberately launch from app/: its TypeScript src/ must not shadow the installed engine.
      cwd: appDir,
      timeoutMs: 90_000,
      env: {
        ODIN_DESKTOP_ENGINE_PYTHON: python,
        ODIN_DESKTOP_CORE_CMD: JSON.stringify([python, '-B', '-P', ...phase.entry]),
        ODIN_SMOKE_REAL_CORE: '1',
        ODIN_SMOKE_WORK_PROOF: phase.workProof,
        ODIN_SMOKE_OUT: phase.out
      }
    })
    if (!existsSync(phase.out)) throw new Error(`${phase.label} did not create its checkpoint screenshot.`)
    console.log(`real-core smoke PASSED: ${phase.label}${process.env.ODIN_SMOKE_OUT ? ` screenshot: ${phase.out}` : ' (temporary screenshot verified)'}`)
  }
} catch (error) {
  console.error(`real-core smoke FAILED: ${error.message}`)
  process.exitCode = 1
} finally {
  rmSync(root, { recursive: true, force: true })
}
