import { test, expect, type ElectronApplication } from '@playwright/test'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { createInterface } from 'node:readline'
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { assertIsolated, exitApp, isolatedEnv, launchApp, request, snapshot, waitForCore, repository } from './harness'

interface State { clients: string[][]; responses: Array<[boolean, string]> }
class SessionManager {
  private child!: ChildProcessWithoutNullStreams
  private pending: Array<(value: State) => void> = []
  async start(): Promise<void> {
    assertIsolated()
    this.child = spawn(process.env.ODIN_DESKTOP_ENGINE_PYTHON!, ['-m', 'tests.desktop_fixtures.private_session_manager'],
      { cwd: repository, env: process.env, stdio: 'pipe' })
    let errors = ''
    this.child.stderr.on('data', (data) => { errors += String(data) })
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`Session fixture startup: ${errors}`)), 5000)
      const lines = createInterface({ input: this.child.stdout })
      lines.on('line', (line) => {
        const value = JSON.parse(line)
        if (value.ready) { clearTimeout(timer); resolve() }
        else this.pending.shift()?.(value as State)
      })
      this.child.once('exit', (code) => { clearTimeout(timer); reject(new Error(`Session fixture exit ${code}: ${errors}`)) })
    })
  }
  call(action: string): Promise<State> {
    return new Promise((resolve) => { this.pending.push(resolve); this.child.stdin.write(`${JSON.stringify({ action })}\n`) })
  }
  async close(): Promise<void> {
    const closed = new Promise<void>((resolve) => this.child.once('exit', () => resolve()))
    this.child.stdin.end()
    await closed
  }
}

for (const actualEnd of ['end', 'stop']) {
  test(`GNOME/Cinnamon query cancellation keeps Odin running; ${actualEnd} writes clean Exit`, async ({}, info) => {
    const manager = new SessionManager()
    await manager.start()
    let application: ElectronApplication | null = null
    try {
      application = await launchApp({ profile: `session-${actualEnd}`, args: ['--hidden'] })
      await waitForCore(application)
      await expect.poll(async () => (await manager.call('snapshot')).clients.length).toBe(1)
      await manager.call('query')
      await expect.poll(async () => (await manager.call('snapshot')).responses.length).toBe(1)
      await manager.call('cancel')
      expect((await request(application, 'status.get')).ok).toBe(true)
      expect((await snapshot(application)).visible).toBe(false)
      const before = await snapshot(application)
      const closed = application.waitForEvent('close')
      await manager.call(actualEnd)
      await closed
      application = null
      await expect.poll(async () => (await manager.call('snapshot')).responses.length).toBe(2)
      const cleanup = JSON.parse(readFileSync(before.cleanupPath, 'utf8'))
      expect(cleanup.current.state).toBe('process-exited')
      expect(cleanup.current.shutdownAccepted).toBe(true)
      expect(cleanup.current.processOutcome).toBe('exited')
      expect(cleanup.warning).toBeNull()
      const core = JSON.parse(readFileSync(join(before.paths.dataDir, 'resource-cleanup.json'), 'utf8'))
      expect(core.state).toBe('complete')
      await info.attach('session-end', { body: JSON.stringify({ cleanup, core, manager: await manager.call('snapshot') }), contentType: 'application/json' })
    } finally {
      if (application) await exitApp(application)
      await manager.close()
    }
  })
}

test('Plasma post-cancellation hook waits for clean hidden-app Exit and removes itself', async ({}, info) => {
  const profile = 'kde-logout'
  const env = isolatedEnv(profile)
  let application: ElectronApplication | null = await launchApp({ profile, args: ['--hidden'], env: { XDG_CURRENT_DESKTOP: 'KDE' } })
  try {
    await waitForCore(application)
    const before = await snapshot(application)
    // Cancelled logout never reaches Plasma's runShutdownScripts.
    expect((await request(application, 'status.get')).ok).toBe(true)
    expect(before.visible).toBe(false)
    const path = join(env.XDG_CONFIG_HOME!, 'plasma-workspace', 'shutdown', 'odin-desktop.sh')
    expect(existsSync(path)).toBe(true)
    const closed = application.waitForEvent('close')
    const started = Date.now()
    const hook = spawn('/bin/sh', [path], { env, cwd: repository, stdio: 'pipe' })
    let stderr = ''
    hook.stderr.on('data', (data) => { stderr += String(data) })
    const result = new Promise((resolve) => hook.once('exit', (code) => resolve(code)))
    await closed
    application = null
    expect(await result).toBe(0)
    expect(Date.now() - started).toBeLessThan(10_000)
    const cleanup = JSON.parse(readFileSync(before.cleanupPath, 'utf8'))
    expect(cleanup.current.state).toBe('process-exited')
    expect(cleanup.current.shutdownAccepted).toBe(true)
    expect(cleanup.warning).toBeNull()
    const core = JSON.parse(readFileSync(join(before.paths.dataDir, 'resource-cleanup.json'), 'utf8'))
    expect(core.state).toBe('complete')
    expect(existsSync(path)).toBe(false)
    await info.attach('kde-hook', { body: JSON.stringify({ cleanup, core, stderr }), contentType: 'application/json' })
  } finally { if (application) await exitApp(application) }
})
