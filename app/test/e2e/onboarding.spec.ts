// A real BrowserWindow, sandboxed preload and rendered Vue app over the real
// framed socket transport. Only the external keyring/auth/provider boundaries
// are deterministic. A missing namespace, display or engine is a failure.
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { assertIsolated } from '../real-core-harness'

const repository = resolve(__dirname, '../../..')
const appDir = join(repository, 'app')
const forbidden = ['E2E-OAUTH-ACCESS-NEVER-RENDER', 'E2E-OAUTH-REFRESH-NEVER-RENDER', 'E2E-DEVICE-SECRET-NEVER-RENDER', 'E2E-WRITE-ONLY-NEVER-RENDER']
let root: string
let currentProfile = ''
const checkpoints: Record<string, unknown> = {}

function scanPrivateFiles(directory: string): void {
  if (!existsSync(directory)) return
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const file = join(directory, entry.name)
    if (entry.isDirectory()) scanPrivateFiles(file)
    else if (entry.isFile()) {
      const bytes = readFileSync(file)
      for (const secret of forbidden) {
        // Existing trusted core login receipts retain raw device auth protocol
        // data for idempotency. It must never cross preload or reach app logs,
        // config, drafts or transcript. OAuth and user-entered secrets have no
        // such exception, including the private transport journal.
        if (secret === 'E2E-DEVICE-SECRET-NEVER-RENDER' && entry.name.startsWith('transport.sqlite3')) continue
        expect(bytes.includes(Buffer.from(secret)), `secret persisted to ${entry.name}`).toBe(false)
      }
    }
  }
}

async function launch(scenario: string, profile: string, initial: Record<string, unknown>): Promise<Record<string, unknown>> {
  // Production intentionally uses the default profile. Fresh scenario pairs
  // require fresh roots, not a public profile-selection test seam.
  if (profile !== currentProfile) {
    for (const key of ['XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR']) {
      const directory = process.env[key]!
      for (const name of readdirSync(directory)) rmSync(join(directory, name), { recursive: true, force: true })
    }
    currentProfile = profile
  }
  const control = join(root, `${scenario}-control.json`)
  const resultFile = join(root, `${scenario}-result.json`)
  writeFileSync(control, JSON.stringify(initial), { mode: 0o600 })
  const python = process.env.ODIN_DESKTOP_ENGINE_PYTHON!
  const env = { ...process.env,
    // Electron adds its own invalid D-Bus sentinel during startup. Drop only
    // that child environment value; adapter still rejects any inherited bus.
    ODIN_DESKTOP_CORE_CMD: JSON.stringify(['/usr/bin/env', '-u', 'DBUS_SESSION_BUS_ADDRESS', '-u', 'DBUS_SYSTEM_BUS_ADDRESS', python, '-B', join(repository, 'app/test/e2e/auth-core.py')]),
    ODIN_SMOKE_ONBOARDING: scenario, ODIN_SMOKE_CONTROL: control, ODIN_SMOKE_OUT: resultFile
  }
  let output = ''
  await new Promise<void>((accept, reject) => {
    const child = spawn(join(appDir, 'node_modules/.bin/electron'), [appDir, '--smoke-test'], {
      cwd: repository, env, stdio: ['ignore', 'pipe', 'pipe']
    })
    child.stdout.on('data', (chunk: Buffer) => { output += chunk.toString() })
    child.stderr.on('data', (chunk: Buffer) => { output += chunk.toString() })
    const timer = setTimeout(() => { child.kill('SIGTERM'); reject(new Error(`Onboarding ${scenario} timeout`)) }, 70_000)
    child.once('error', (error) => { clearTimeout(timer); reject(error) })
    child.once('exit', (code, signal) => {
      clearTimeout(timer)
      if (code === 0) accept()
      else {
        const log = join(process.env.XDG_DATA_HOME!, 'odin-desktop/default/logs/core.log')
        let diagnostic = existsSync(log) ? readFileSync(log, 'utf8') : '(no core log)'
        for (const secret of forbidden) diagnostic = diagnostic.replaceAll(secret, '[synthetic-secret-redacted]')
        reject(new Error(`Onboarding ${scenario} failed (${code}/${signal}): ${output}\n${diagnostic}`))
      }
    })
  })
  for (const secret of forbidden) expect(output.includes(secret), 'secret in Electron/core logs').toBe(false)
  expect(existsSync(resultFile), 'actual Electron driver must return measured checkpoints').toBe(true)
  const result = JSON.parse(readFileSync(resultFile, 'utf8')) as Record<string, unknown>
  expect(result.scenario).toBe(scenario)
  expect(result.passed).toBe(true)
  checkpoints[scenario] = result
  // SQLite journals, config, drafts and app logs must not hold plaintext auth
  // or a transient secret. The test control file contains modes/booleans only.
  scanPrivateFiles(process.env.XDG_CONFIG_HOME!)
  scanPrivateFiles(process.env.XDG_DATA_HOME!)
  scanPrivateFiles(process.env.XDG_CACHE_HOME!)
  return result
}

describe('real app/core first-run onboarding', () => {
  beforeAll(() => {
    assertIsolated()
    expect(process.env.DISPLAY).toMatch(/^:/)
    expect(process.env.DBUS_SESSION_BUS_ADDRESS).toBeUndefined()
    root = mkdtempSync(join(process.env.HOME!, 'onboarding-'))
    mkdirSync(join(root, 'reports'))
  })
  afterAll(() => { if (root) rmSync(root, { recursive: true, force: true }) })

  it('fresh launch supports setup later, section re-entry and a second launch without a local readiness flag', async () => {
    const fresh = await launch('fresh', 'onboarding-fresh', { keyring: 'healthy', auth: 'pending' })
    expect(fresh.states).toEqual(['fresh'])
    const second = await launch('fresh-second', 'onboarding-fresh', { keyring: 'healthy', auth: 'pending' })
    expect(second.states).toEqual(['fresh'])
  })

  it('real saves stay retryable after stale revision/disconnection, login cancellation/expiry and write-only credentials', async () => {
    const ready = await launch('ready', 'onboarding-ready', { keyring: 'healthy', auth: 'pending' })
    expect(ready.states).toContain('incomplete')
    expect(ready.states).toContain('effective-ready')
    expect(ready.checks).toEqual(expect.arrayContaining(['revision-retry', 'connection-retry', 'provider-save-retry', 'degraded-health-recovery', 'canceled-login', 'expired-login', 'secret-cleared', 'secret-readback-absent']))
  })

  it('saved model on second launch is not effective until the real provider owner adopts it; app defaults persist', async () => {
    const second = await launch('ready-second', 'onboarding-ready', { keyring: 'healthy', auth: 'success', authorized: true })
    expect(second.states).toContain('saved')
    expect(second.states).toContain('effective-ready')
    expect(second.checks).toContain('preferences-persisted')
  })

  for (const keyring of ['locked', 'missing']) {
    it(`${keyring} keyring never succeeds falsely and recovers through the rendered Retry`, async () => {
      const recovery = await launch(keyring, `onboarding-${keyring}`, { keyring, auth: 'success' })
      expect(recovery.states).toEqual(expect.arrayContaining(['degraded', 'fresh', 'effective-ready']))
      expect(recovery.checks).toContain('keyring-retry')
    })
  }
})
