// Electron and the real core run together in a disposable PID namespace and
// xvfb display. The runner verifies unprivileged ownership and private XDG/HOME.
// Three labelled passes, each in its own namespace and fresh profile: the
// production entry, the seeded work proof and the provider-backed chat lane.
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'
import { launchIsolated, repositoryRoot } from './real-core-isolation.mjs'

const appDir = resolve(import.meta.dirname, '..')
const python = resolve(process.env.ODIN_DESKTOP_ENGINE_PYTHON || join(repositoryRoot, '.venv/bin/python'))

async function electron(env) {
  await new Promise((accept, reject) => {
    const child = spawn('dbus-run-session', ['--config-file',
      join(repositoryRoot, 'tests/desktop_fixtures/private-session.conf'), '--',
      'xvfb-run', '-a', '-s', '-screen 0 1280x800x24 -nolisten tcp',
      join(appDir, 'node_modules/.bin/electron'), appDir, '--smoke-test'], {
      cwd: appDir, stdio: 'inherit', env: { ...process.env, ...env, ODIN_SMOKE_REAL_CORE: '1' }
    })
    child.once('error', reject)
    child.once('exit', (code, signal) => code === 0 ? accept() : reject(new Error(`Electron smoke exited ${code}, signal ${signal ?? 'none'}`)))
  })
}

async function inside() {
  // #25 keeps the exact isolation runner at PID 1; this script is its child.
  // Use the real harness's descendant guard, never relax the runner's PID-1 assertion.
  const { build } = await import('esbuild')
  const bundle = join(appDir, 'out', 'real-core-seed.cjs')
  await build({ entryPoints: [join(appDir, 'test/real-core-smoke-seed.ts')], outfile: bundle,
    bundle: true, platform: 'node', format: 'cjs', external: ['electron'],
    define: { __dirname: JSON.stringify(join(appDir, 'test')) } })
  const require = createRequire(join(appDir, 'package.json'))
  const { assertIsolated, seed } = require(bundle)
  assertIsolated()
  const { startCannedProvider } = await import('../test/real-core-provider-fixture.mjs')
  const provider = await startCannedProvider({ root: join(process.env.ODIN_REAL_CORE_ROOT, 'provider') })
  try {
    await seed(provider.baseUrl, async () => {
      const deadline = Date.now() + 8000
      while (!provider.requests.some((entry) => entry.token === '[hold-resume]')) {
        if (Date.now() > deadline) throw new Error('Seed generation did not reach the real provider client')
        await new Promise((accept) => setTimeout(accept, 20))
      }
    })
    provider.release('[hold-resume]')
    await electron({
      ODIN_DESKTOP_CORE_CMD: JSON.stringify([python, '-B', '-P', join(appDir, 'test/real-core-keyring-entry.py')]),
      ODIN_SMOKE_PROVIDER_BASE_URL: provider.baseUrl
    })
  } finally { await provider.close() }
}

async function outside() {
  const root = mkdtempSync(join(tmpdir(), 'odin-real-smoke-output-'))
  const out = process.env.ODIN_SMOKE_OUT ? resolve(process.env.ODIN_SMOKE_OUT) : join(root, 'real-core.png')
  mkdirSync(resolve(out, '..'), { recursive: true })
  const stem = out.replace(/\.png$/i, '')
  // The production pass never imports the workProof bootstrap; the seeded pass
  // uses the same entry as the harness.
  const phases = [
    { label: 'production entry / fresh real profile', entry: ['-m', 'src'], workProof: '0', out },
    { label: 'seeded work proof', entry: [join(repositoryRoot, 'app/test/services-b-core.py')], workProof: '1', out: `${stem}-seeded-work-proof.png` }
  ]
  const verified = (label, path) => {
    if (!existsSync(path) || !existsSync(path.replace(/\.png$/i, '') + '-evidence.json')) {
      throw new Error(`${label} did not create both its checkpoint screenshot and evidence JSON.`)
    }
    console.log(`real-core smoke PASSED: ${label}${process.env.ODIN_SMOKE_OUT ? ` screenshot: ${path}` : ' (temporary screenshot and evidence verified)'}`)
  }
  try {
    for (const phase of phases) {
      console.log(`real-core smoke START: ${phase.label}`)
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
          ODIN_SMOKE_SKILL_FIXTURE: join(appDir, 'test/harmless-skill.py'),
          ODIN_SMOKE_MCP_FIXTURE: join(appDir, 'test/harmless-mcp-stdio.py'),
          ODIN_DESKTOP_CORE_CMD: JSON.stringify([python, '-B', '-P', ...phase.entry]),
          ODIN_SMOKE_REAL_CORE: '1',
          ODIN_SMOKE_WORK_PROOF: phase.workProof,
          ODIN_SMOKE_OUT: phase.out
        }
      })
      verified(phase.label, phase.out)
    }
    const chat = { label: 'provider-backed chat', out: `${stem}-provider-chat.png` }
    console.log(`real-core smoke START: ${chat.label}`)
    await launchIsolated(process.execPath, [resolve(import.meta.filename), '--inside-smoke'], {
      cwd: appDir, timeoutMs: 600_000,
      env: { ODIN_DESKTOP_ENGINE_PYTHON: python, ODIN_SMOKE_OUT: chat.out }
    })
    verified(chat.label, chat.out)
  } finally { rmSync(root, { recursive: true, force: true }) }
}

(process.argv.includes('--inside-smoke') ? inside() : outside()).catch((error) => {
  console.error(`real-core smoke FAILED: ${error.message}`)
  process.exitCode = 1
})
