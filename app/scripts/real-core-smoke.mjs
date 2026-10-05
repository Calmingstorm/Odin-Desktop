// Provider, core and Electron start only inside the disposable PID namespace.
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { assertRealCoreIsolation, launchIsolated, repositoryRoot } from './real-core-isolation.mjs'

const appDir = resolve(import.meta.dirname, '..')
const python = resolve(process.env.ODIN_DESKTOP_ENGINE_PYTHON || join(repositoryRoot, '.venv/bin/python'))

async function inside() {
  assertRealCoreIsolation()
  const { startCannedProvider } = await import('../test/real-core-provider-fixture.mjs')
  const root = join(process.env.ODIN_REAL_CORE_ROOT, 'provider')
  mkdirSync(root, { mode: 0o700 })
  const provider = await startCannedProvider({ root })
  try {
    await new Promise((accept, reject) => {
      const child = spawn('xvfb-run', ['-a', '-s', '-screen 0 1280x800x24',
        join(appDir, 'node_modules/.bin/electron'), appDir, '--smoke-test'], {
        cwd: repositoryRoot, stdio: 'inherit', env: {
          ...process.env,
          ODIN_DESKTOP_CORE_CMD: JSON.stringify([python, '-B', join(appDir, 'test/real-core-provider-entry.py')]),
          ODIN_REAL_CORE_PROVIDER_CONFIG: provider.configPath,
          ODIN_SMOKE_PROVIDER_BASE_URL: provider.baseUrl,
          ODIN_SMOKE_REAL_CORE: '1'
        }
      })
      child.once('error', reject)
      child.once('exit', (code, signal) => code === 0 ? accept() : reject(new Error(`Electron smoke exited ${code}, signal ${signal ?? 'none'}`)))
    })
  } finally { await provider.close() }
}

async function outside() {
  const root = mkdtempSync(join(tmpdir(), 'odin-real-smoke-output-'))
  const out = process.env.ODIN_SMOKE_OUT ? resolve(process.env.ODIN_SMOKE_OUT) : join(root, 'real-core.png')
  try {
    await launchIsolated(process.execPath, [resolve(import.meta.filename), '--inside-smoke'], {
      cwd: repositoryRoot, timeoutMs: 180_000,
      env: { ODIN_DESKTOP_ENGINE_PYTHON: python, ODIN_SMOKE_OUT: out }
    })
    if (!existsSync(out) || !existsSync(out.replace(/\.png$/i, '') + '-evidence.json')) {
      throw new Error('Real-core smoke did not create screenshot and evidence JSON.')
    }
    console.log(`real-core smoke PASSED${process.env.ODIN_SMOKE_OUT ? ` screenshot: ${out}` : ' (temporary screenshot and evidence verified)'}`)
  } finally { rmSync(root, { recursive: true, force: true }) }
}

(process.argv.includes('--inside-smoke') ? inside() : outside()).catch((error) => {
  console.error(`real-core smoke FAILED: ${error.message}`)
  process.exitCode = 1
})
