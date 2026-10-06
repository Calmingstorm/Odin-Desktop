import { existsSync, readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { execFileSync, spawn } from 'node:child_process'
import { join } from 'node:path'
import { expect, test, type ElectronApplication, type TestInfo } from '@playwright/test'
import { exitApp, isolatedEnv, launchApp, launchRaw, launchSecond, repository, request, snapshot, waitForCore } from './harness'
import { RealCoreHarness } from '../real-core-harness'
import { PrivateNotificationBus } from './private-notification-bus'

function identity(pid: number) {
  const stat = readFileSync(`/proc/${pid}/stat`, 'utf8')
  return { pid, startTicks: stat.slice(stat.lastIndexOf(')') + 2).split(' ')[19],
    namespace: readlinkSync(`/proc/${pid}/ns/pid`), command: readFileSync(`/proc/${pid}/cmdline`, 'utf8').split('\0') }
}
function alive(original: ReturnType<typeof identity>): boolean {
  try {
    const stat = readFileSync(`/proc/${original.pid}/stat`, 'utf8')
    return stat.slice(stat.lastIndexOf(')') + 2).split(' ')[0] !== 'Z'
      && identity(original.pid).startTicks === original.startTicks
  } catch { return false }
}
async function dispose(application: ElectronApplication): Promise<void> {
  try { await application.close() } catch (error) {
    if (!/closed|_object/.test(String(error))) throw error
  }
}
async function hook(application: ElectronApplication, name: 'close' | 'show' | 'rendererCrash') {
  await application.evaluate((_electron, name) => {
    (globalThis as unknown as { __odinE2E: Record<string, () => void> }).__odinE2E[name]!()
  }, name)
}
async function receipt(info: TestInfo, name: string, data: unknown) {
  await info.attach(name, { body: Buffer.from(JSON.stringify(data, null, 2)), contentType: 'application/json' })
}

test('direct real core graceful parent EOF releases its owned socket', async ({}, info) => {
  const core = new RealCoreHarness()
  try {
    await core.start()
    const owned = identity(core.child.pid!)
    const { broker } = await core.connect()
    expect((await broker.request('status.get')).ok).toBe(true)
    const result = await core.parentEOF()
    expect(result.code).toBe(0)
    expect(existsSync(core.paths.socketPath)).toBe(false)
    await receipt(info, 'direct-parent-eof', { owned, result, socketRemoved: true })
  } finally { await core.dispose() }
})

test('a regular file socket occupant is preserved and bounded startup never reports ready', async ({}, info) => {
  // Bound the complete two-launch fixture above its failure-observation wait; product restart timing stays unchanged.
  test.setTimeout(240_000)
  const profile = 'regular-occupant'
  const initial = await launchApp({ profile })
  await waitForCore(initial)
  const before = await snapshot(initial)
  await exitApp(initial)
  const content = 'Owned non-socket occupant. Never unlink this file.\n'
  writeFileSync(before.paths.socketPath, content, { mode: 0o600 })
  const application = await launchApp({ profile })
  try {
    // Observe four cold attempts plus unchanged 1s/3s/10s backoffs under load; no fixture retry or product change.
    await expect.poll(async () => (await snapshot(application)).coreState, { timeout: 60_000 }).toBe('failed')
    expect(readFileSync(before.paths.socketPath, 'utf8')).toBe(content)
    expect((await snapshot(application)).appState.link).toBe('core-failed')
    await receipt(info, 'regular-socket-occupant-preserved', {
      state: await snapshot(application), content,
      log: readFileSync(join(before.paths.dataDir, 'logs/core.log'), 'utf8')
    })
    await exitApp(application)
  } finally { await dispose(application) }
})

test('no-tray notice is accepted once and remains one-time across full app restarts', async ({}, info) => {
  const bus = new PrivateNotificationBus()
  await bus.start()
  let application: ElectronApplication | null = null
  try {
    for (let launch = 0; launch < 2; launch++) {
      application = await launchApp({ profile: 'no-tray-notice' })
      await waitForCore(application)
      await hook(application, 'close')
      await expect.poll(async () => (await bus.snapshot()).requests.length).toBe(1)
      const state = await snapshot(application)
      expect(state.visible).toBe(false)
      expect(state.noTrayNoticeShown).toBe(true)
      expect((await request(application, 'status.get')).ok).toBe(true)
      await launchSecond(application)
      await expect.poll(async () => (await snapshot(application!)).visible).toBe(true)
      await exitApp(application)
      application = null
    }
    const received = await bus.snapshot()
    expect(received.requests[0]?.summary).toBe('Odin is still running')
    expect(received.requests[0]?.body).toContain('Reopen Odin')
    await receipt(info, 'one-time-no-tray-notice', received)
  } finally {
    if (application) await dispose(application)
    await receipt(info, 'no-tray-private-bus-cleanup', await bus.stop())
  }
})

test('live owned socket is never replaced or signalled and startup budget ends', async ({}, info) => {
  test.setTimeout(40_000)
  const profile = 'live-owned'
  const initial = await launchApp({ profile })
  await waitForCore(initial)
  const before = await snapshot(initial)
  await exitApp(initial)
  const fixture = spawn(process.env.ODIN_DESKTOP_ENGINE_PYTHON!,
    [join(repository, 'tests/desktop_fixtures/lifecycle_owned_socket.py'), before.paths.socketPath, 'live'],
    { env: isolatedEnv(profile), stdio: ['pipe', 'pipe', 'pipe'] })
  let output = ''
  fixture.stdout.on('data', (chunk: Buffer) => { output += chunk.toString() })
  await expect.poll(() => output.length > 0).toBe(true)
  const owned = identity(fixture.pid!)
  const application = await launchApp({ profile })
  try {
    await expect.poll(async () => (await snapshot(application)).coreState, { timeout: 25_000 }).toBe('failed')
    expect(alive(owned)).toBe(true)
    expect(existsSync(before.paths.socketPath)).toBe(true)
    const log = readFileSync(join(before.paths.dataDir, 'logs/core.log'), 'utf8')
    expect((log.match(/\[supervisor\] core ended/g) ?? []).length).toBe(5)
    await receipt(info, 'live-socket-budget', { owned, fixture: JSON.parse(output), state: await snapshot(application), log })
    await exitApp(application)
  } finally {
    await dispose(application)
    const ended = new Promise<{code: number | null; signal: string | null}>((done) => fixture.once('exit', (code, signal) => done({ code, signal })))
    fixture.stdin.end()
    const result = await Promise.race([ended, new Promise<never>((_done, reject) => setTimeout(() => reject(new Error('Owned socket EOF teardown timed out')), 3_000))])
    await receipt(info, 'live-socket-fixture-release', { owned, result })
  }
})

test('real core ignores stale PID text and safely replaces owned dead socket', async ({}, info) => {
  const profile = 'stale-owned'
  const initial = await launchApp({ profile })
  await waitForCore(initial)
  const before = await snapshot(initial)
  await exitApp(initial)
  writeFileSync(join(before.paths.configDir, '.core.lock'), '2147483647\n', { mode: 0o600 })
  const fixture = spawn(process.env.ODIN_DESKTOP_ENGINE_PYTHON!,
    [join(repository, 'tests/desktop_fixtures/lifecycle_owned_socket.py'), before.paths.socketPath, 'stale'],
    { env: isolatedEnv(profile), stdio: ['pipe', 'pipe', 'pipe'] })
  let output = ''
  fixture.stdout.on('data', (chunk: Buffer) => { output += chunk.toString() })
  await new Promise<void>((done, reject) => {
    fixture.once('error', reject)
    fixture.once('exit', (code) => code === 0 ? done() : reject(new Error(`socket fixture failed ${code}`)))
  })
  const recovered = await launchApp({ profile })
  try {
    const core = await waitForCore(recovered)
    expect((await request(recovered, 'status.get')).ok).toBe(true)
    await receipt(info, 'stale-owned-socket-and-pid-text', { fixture: JSON.parse(output), core: identity(core.pid) })
    await exitApp(recovered)
  } finally { await dispose(recovered) }
})

test('abrupt app loss causes real-core EOF shutdown and persistent unknown cleanup', async ({}, info) => {
  const application = await launchApp({ profile: 'parent-loss' })
  const core = await waitForCore(application)
  const before = await snapshot(application)
  const owned = identity(core.pid)
  const parent = identity(before.pid)
  const closed = application.waitForEvent('close')
  application.process().kill('SIGKILL')
  await closed
  await expect.poll(() => alive(owned), { timeout: 12_000 }).toBe(false)
  const pending = JSON.parse(readFileSync(before.cleanupPath, 'utf8'))
  expect(pending.state).toBe('running')
  const recovered = await launchApp({ profile: 'parent-loss' })
  try {
    await waitForCore(recovered)
    expect((await snapshot(recovered)).cleanupUnknown?.state).toBe('unknown')
    await receipt(info, 'abrupt-app-loss', { parent, owned, pending, recovered: await snapshot(recovered),
      limitation: 'Core EOF/ownership evidence, not dispatched descendants or native input release.' })
    await exitApp(recovered)
    expect(JSON.parse(readFileSync(before.cleanupPath, 'utf8')).state).toBe('unknown')
  } finally { await dispose(recovered) }
})

test('SIGSTOP real core exercises bounded escalation without release claims', async ({}, info) => {
  test.setTimeout(45_000)
  const application = await launchApp({ profile: 'escalation' })
  try {
    const core = await waitForCore(application)
    const before = await snapshot(application)
    const owned = identity(core.pid)
    process.kill(core.pid, 'SIGSTOP')
    const start = Date.now()
    await exitApp(application)
    expect(Date.now() - start).toBeLessThan(30_000)
    await expect.poll(() => alive(owned)).toBe(false)
    const cleanup = JSON.parse(readFileSync(before.cleanupPath, 'utf8'))
    expect(cleanup).toMatchObject({ state: 'unknown', processOutcome: 'killed', shutdownAccepted: false })
    await receipt(info, 'sigstop-escalation', { owned, cleanup, durationMs: Date.now() - start })
  } finally { await dispose(application) }
})

test('menu and launcher Exit share accepted real-core shutdown', async ({}, info) => {
  for (const route of ['menu', 'launcher', 'keyboard'] as const) {
    const application = await launchApp({ profile: `route-${route}` })
    try {
      const core = await waitForCore(application)
      const before = await snapshot(application)
      const owned = identity(core.pid)
      const closed = application.waitForEvent('close')
      if (route === 'launcher') expect((await launchSecond(application, ['--exit'])).code).toBe(0)
      else if (route === 'keyboard') {
        await application.evaluate(({ BrowserWindow }) => {
          const window = BrowserWindow.getAllWindows()[0]!
          window.show()
          window.focus()
          window.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Q', modifiers: ['control'] })
          window.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Q', modifiers: ['control'] })
        })
      }
      else await application.evaluate(({ Menu }) => {
        const item = Menu.getApplicationMenu()!.items[0]!.submenu!.items.find((item) => item.label === 'Exit Odin')!
        if (item.accelerator !== 'Ctrl+Q') throw new Error('Exit accelerator missing')
        item.click()
      })
      await closed
      await expect.poll(() => alive(owned)).toBe(false)
      const cleanup = JSON.parse(readFileSync(before.cleanupPath, 'utf8'))
      expect(cleanup).toMatchObject({ state: 'process-exited', shutdownAccepted: true })
      await receipt(info, `exit-${route}`, { owned, cleanup })
    } finally { await dispose(application) }
  }
})

test('renderer loss preserves real core and relaunch recovers renderer', async ({}, info) => {
  const application = await launchApp({ profile: 'renderer-loss' })
  try {
    const core = await waitForCore(application)
    const owned = identity(core.pid)
    const renderer = (await snapshot(application)).rendererPid!
    const rendererIdentity = identity(renderer)
    let ancestor = renderer
    const mainPid = (await snapshot(application)).pid
    const ancestry: number[] = []
    while (ancestor !== mainPid && ancestor > 1 && ancestry.length < 8) {
      ancestry.push(ancestor)
      const status = readFileSync(`/proc/${ancestor}/status`, 'utf8')
      ancestor = Number(status.match(/^PPid:\s+(\d+)/m)?.[1])
    }
    expect(ancestor).toBe(mainPid)
    expect(identity(renderer).startTicks).toBe(rendererIdentity.startTicks)
    process.kill(renderer, 'SIGKILL')
    await expect.poll(async () => application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.webContents.isCrashed())).toBe(true)
    expect((await request(application, 'status.get')).ok).toBe(true)
    expect(alive(owned)).toBe(true)
    expect((await launchSecond(application)).code).toBe(0)
    await expect.poll(async () => application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.webContents.isCrashed())).toBe(false)
    expect((await waitForCore(application)).instanceId).toBe(core.instanceId)
    await receipt(info, 'renderer-loss', { owned, rendererIdentity, ancestry, state: await snapshot(application) })
    await exitApp(application)
  } finally { await dispose(application) }
})

test('unexpected ready core loss fences replacement with unknown cleanup', async ({}, info) => {
  const application = await launchApp({ profile: 'core-loss' })
  try {
    const core = await waitForCore(application)
    const owned = identity(core.pid)
    process.kill(core.pid, 'SIGKILL')
    await expect.poll(async () => (await snapshot(application)).coreState).toBe('failed')
    await new Promise((done) => setTimeout(done, 1_200))
    const after = await snapshot(application)
    expect(after.corePid).toBeUndefined()
    expect(after.cleanupUnknown?.state).toBe('unknown')
    expect(alive(owned)).toBe(false)
    await receipt(info, 'core-loss-replacement-fenced', { owned, after })
    await exitApp(application)
  } finally { await dispose(application) }
})

test('unknown cleanup is nonmodal even when hidden, acknowledgment archives it, and a later loss warns anew', async ({}, info) => {
  const profile = 'acknowledge-cleanup'
  let application: ElectronApplication | null = await launchApp({ profile })
  const core = await waitForCore(application)
  const before = await snapshot(application)
  const owned = identity(core.pid)
  const closed = application.waitForEvent('close')
  application.process().kill('SIGKILL')
  await closed
  application = null
  await expect.poll(() => alive(owned), { timeout: 12_000 }).toBe(false)
  try {
    application = await launchApp({ profile, args: ['--hidden'] })
    await waitForCore(application)
    const page = await application.firstWindow()
    const notice = page.getByRole('region', { name: 'Cleanup unknown' })
    await expect(notice).toBeVisible()
    await expect(notice).toContainText('without a shutdown receipt')
    // Inspect the private X server, not an Electron-only window inventory:
    // native message boxes would otherwise escape BrowserWindow accounting.
    expect(execFileSync('xwininfo', ['-root', '-tree'], { encoding: 'utf8' })).not.toContain('Odin cleanup unknown')
    expect((await snapshot(application)).visible).toBe(false)
    expect((await request(application, 'status.get')).ok).toBe(true)
    await launchSecond(application)
    await expect.poll(async () => (await snapshot(application!)).visible).toBe(true)
    // A real renderer button invokes the guarded bridge; no main-only
    // acknowledgment hook or injected modal dismissal substitutes for it.
    await notice.getByRole('button', { name: 'Acknowledge', exact: true }).click()
    await expect(notice).toHaveCount(0)
    const archived = JSON.parse(readFileSync(before.cleanupPath, 'utf8')).archived
    expect(archived.length).toBeGreaterThan(0)
    expect(archived[0].records[0]).toMatchObject({ state: 'unknown' })
    expect(Number.isFinite(Date.parse(archived[0].acknowledgedAt))).toBe(true)
    await exitApp(application)
    application = await launchApp({ profile })
    const quietCore = await waitForCore(application)
    await expect((await application.firstWindow()).getByRole('region', { name: 'Cleanup unknown' })).toHaveCount(0)
    expect((await snapshot(application)).cleanupUnknown).toBeNull()
    expect(JSON.parse(readFileSync(before.cleanupPath, 'utf8')).archived).toEqual(archived)
    const secondOwned = identity(quietCore.pid)
    const secondClosed = application.waitForEvent('close')
    application.process().kill('SIGKILL')
    await secondClosed
    application = null
    await expect.poll(() => alive(secondOwned), { timeout: 12_000 }).toBe(false)
    application = await launchApp({ profile })
    await waitForCore(application)
    await expect((await application.firstWindow()).getByRole('region', { name: 'Cleanup unknown' })).toBeVisible()
    expect((await snapshot(application)).cleanupUnknown?.state).toBe('unknown')
    expect(JSON.parse(readFileSync(before.cleanupPath, 'utf8')).archived).toEqual(archived)
    await receipt(info, 'nonmodal-cleanup-acknowledgment', { archived, renewed: await snapshot(application),
      journal: JSON.parse(readFileSync(before.cleanupPath, 'utf8')) })
    await exitApp(application)
    application = null
  } finally { if (application) await dispose(application) }
})

test('acknowledgment of a core resource warning stays quiet without clearing core reconciliation', async ({}, info) => {
  const profile = 'acknowledge-core-resource'
  let application: ElectronApplication | null = await launchApp({ profile })
  try {
    const core = await waitForCore(application)
    const before = await snapshot(application)
    process.kill(core.pid, 'SIGKILL')
    await expect.poll(async () => (await snapshot(application!)).coreState).toBe('failed')
    await exitApp(application)
    application = await launchApp({ profile })
    await waitForCore(application)
    const page = await application.firstWindow()
    const notice = page.getByRole('region', { name: 'Cleanup unknown' })
    await expect(notice).toContainText('native resources require reconciliation')
    const publicBefore = await request(application, 'status.get')
    expect((publicBefore.result as any).resource_cleanup.reconciliation_required).toBe(true)
    await notice.getByRole('button', { name: 'Acknowledge', exact: true }).click()
    await expect(notice).toHaveCount(0)
    const publicAfter = await request(application, 'status.get')
    expect((publicAfter.result as any).resource_cleanup).toEqual((publicBefore.result as any).resource_cleanup)
    const archived = JSON.parse(readFileSync(before.cleanupPath, 'utf8')).archived
    await exitApp(application)
    application = await launchApp({ profile })
    await waitForCore(application)
    const publicRestart = await request(application, 'status.get')
    expect((publicRestart.result as any).resource_cleanup.reconciliation_required).toBe(true)
    await expect((await application.firstWindow()).getByRole('region', { name: 'Cleanup unknown' })).toHaveCount(0)
    expect((await snapshot(application)).cleanupUnknown).toBeNull()
    expect(JSON.parse(readFileSync(before.cleanupPath, 'utf8')).archived).toEqual(archived)
    await receipt(info, 'acknowledgment-is-not-resource-reconciliation', { publicBefore, publicAfter, publicRestart, archived })
    await exitApp(application)
    application = null
  } finally { if (application) await dispose(application) }
})

test('exit-only with no app constructs neither core nor Odin profile', async () => {
  const env = isolatedEnv('exit-only')
  env.ODIN_DESKTOP_CORE_CMD = 'invalid: coreCommand must never be called'
  expect((await launchRaw(env, ['--exit'])).code).toBe(0)
  expect(existsSync(join(env.XDG_CONFIG_HOME!, 'odin-desktop'))).toBe(false)
  expect(existsSync(join(env.XDG_DATA_HOME!, 'odin-desktop'))).toBe(false)
})

test('close and simultaneous relaunch preserve app and ready real core with no tray', async ({}, info) => {
  const application = await launchApp({ profile: 'relaunch' })
  try {
    const core = await waitForCore(application)
    const before = await snapshot(application)
    const owned = identity(core.pid)
    expect(before.appState.noTray).toBe(true)
    await hook(application, 'close')
    expect((await snapshot(application)).visible).toBe(false)
    expect((await request(application, 'status.get')).ok).toBe(true)
    expect((await snapshot(application)).noTrayNoticeShown).toBe(true)
    expect((await Promise.all([launchSecond(application), launchSecond(application)])).map((result) => result.code)).toEqual([0, 0])
    await expect.poll(async () => (await snapshot(application)).visible).toBe(true)
    const after = await snapshot(application)
    expect(after.pid).toBe(before.pid)
    expect(after.corePid).toBe(core.pid)
    expect(after.appState.coreInstanceId).toBe(core.instanceId)
    expect(alive(owned)).toBe(true)
    await receipt(info, 'close-relaunch-owned-processes', { app: identity(before.pid), core: owned, before, after,
      limitation: 'Ready step-one core only, no turns/agents/schedules or native tray claim.' })
    await exitApp(application)
    await expect.poll(() => alive(owned)).toBe(false)
    const persisted = JSON.parse(readFileSync(before.cleanupPath, 'utf8'))
    expect(persisted.state).toBe('process-exited')
    await receipt(info, 'normal-shutdown', persisted)
  } finally { await dispose(application) }
})
