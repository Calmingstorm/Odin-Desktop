// Real Electron/X11 lifecycle, exclusively through lifecycle-e2e's isolated
// nonroot PID namespace, private Xvfb, D-Bus and disposable HOME. No host WM.
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, readFileSync, renameSync, rmdirSync, writeFileSync } from 'node:fs'
import { expect, test, type ElectronApplication, type TestInfo } from '@playwright/test'
import { assertIsolated, exitApp, launchApp, snapshot, waitForCore } from './harness'
import type { Bounds, WindowState, WindowBackend } from '../../src/main/window-state'
type WindowSnapshot = { backend: WindowBackend; resolvedOzonePlatform: string; bounds: Bounds; normalBounds: Bounds;
  maximized: boolean; minimized: boolean; fullscreen: boolean; persisted: WindowState }
interface Hooks { windowSnapshot(): WindowSnapshot; windowBounds(bounds: Bounds): void; windowMode(mode: string): void; close(): void; show(): void }
const hooks = (application: ElectronApplication) => ({
  snapshot: () => application.evaluate(() => (globalThis as unknown as { __odinE2E: Hooks }).__odinE2E.windowSnapshot()),
  bounds: (bounds: Bounds) => application.evaluate((_electron, bounds) => (globalThis as unknown as { __odinE2E: Hooks }).__odinE2E.windowBounds(bounds), bounds),
  mode: (mode: string) => application.evaluate((_electron, mode) => (globalThis as unknown as { __odinE2E: Hooks }).__odinE2E.windowMode(mode), mode),
  close: () => application.evaluate(() => (globalThis as unknown as { __odinE2E: Hooks }).__odinE2E.close()),
  show: () => application.evaluate(() => (globalThis as unknown as { __odinE2E: Hooks }).__odinE2E.show())
})
async function dispose(application: ElectronApplication | null) { if (application) try { await application.close() } catch (error) { if (!/closed|_object/.test(String(error))) throw error } }
async function evidence(info: TestInfo, name: string, data: unknown) {
  await info.attach(name, { body: Buffer.from(JSON.stringify(data, null, 2)), contentType: 'application/json' })
}
let wm: ChildProcess
test.beforeAll(async () => {
  assertIsolated()
  // A WM is necessary to test actual maximize/unmaximize, not a fake boolean.
  // This process can see only the runner's private X server/session bus.
  wm = spawn('/usr/bin/openbox', ['--sm-disable'], { env: process.env, stdio: ['ignore', 'pipe', 'pipe'] })
  await new Promise<void>((resolve, reject) => { wm.once('spawn', resolve); wm.once('error', reject) })
  await expect.poll(async () => {
    const { execFile } = await import('node:child_process')
    return await new Promise<string>((resolve) => execFile('/usr/bin/xprop', ['-root', '_NET_SUPPORTING_WM_CHECK'], { env: process.env }, (_error, stdout) => resolve(stdout)))
  }).toMatch(/window id # 0x[1-9a-f]/)
})
test.afterAll(async () => {
  if (wm && wm.exitCode === null && wm.signalCode === null) {
    const ended = new Promise<void>((resolve) => wm.once('exit', () => resolve()))
    wm.kill('SIGTERM'); await ended
  }
})

test('normal restart and close-to-tray preserve latest geometry, appearance, notifications and dismissal', async ({}, info) => {
  test.setTimeout(150_000)
  let application: ElectronApplication | null = await launchApp({ profile: 'window-normal', env: { WAYLAND_DISPLAY: 'not-a-real-wayland-socket' } })
  try {
    await waitForCore(application)
    const page = await application.firstWindow(); await page.waitForFunction(() => Boolean(window.odin))
    const before = await hooks(application).snapshot()
    expect(before.backend).toBe('x11'); expect(before.resolvedOzonePlatform).toBe('x11')
    const bounds = { x: 100, y: 100, width: 900, height: 600 }
    await hooks(application).bounds(bounds)
    await expect.poll(async () => (await hooks(application!).snapshot()).normalBounds).toEqual(bounds)
    const receipts = await page.evaluate(async () => [await window.odin.setSetupReminderHidden(true),
      await window.odin.setAppearance('light'), await window.odin.setNotifications({ previews: false })])
    expect(receipts.every((receipt) => receipt.ok)).toBe(true)
    await hooks(application).close()
    const state = await snapshot(application)
    const saved = JSON.parse(readFileSync(state.paths.appStatePath, 'utf8'))
    expect(saved).toMatchObject({ setupReminderHidden: true, appearance: 'light', notifications: { previews: false },
      windowState: { normalBounds: bounds, maximized: false } })
    await exitApp(application); application = null
    application = await launchApp({ profile: 'window-normal' }); await waitForCore(application)
    await expect.poll(async () => (await hooks(application!).snapshot()).normalBounds).toEqual(bounds)
    const reopened = await application.firstWindow()
    const prefs = await reopened.evaluate(async () => ({ reminder: await window.odin.getSetupReminderHidden(), settings: await window.odin.getSettings() }))
    expect(prefs).toMatchObject({ reminder: { ok: true, result: { hidden: true } }, settings: { ok: true, result: { appearance: 'light', notifications: { previews: false } } } })
    await evidence(info, 'window-normal-restart', { before, saved, after: await hooks(application).snapshot(), prefs,
      qualification: 'Real Electron 44 on private Xvfb/Openbox X11; not native Wayland or multi-monitor hardware qualification.' })
    await exitApp(application); application = null
  } finally { await dispose(application) }
})

test('maximized restart retains normal bounds, minimize/fullscreen do not overwrite them', async ({}, info) => {
  test.setTimeout(150_000)
  let application: ElectronApplication | null = await launchApp({ profile: 'window-maximized' })
  try {
    await waitForCore(application)
    const bounds = { x: 90, y: 110, width: 920, height: 610 }
    await hooks(application).bounds(bounds)
    await expect.poll(async () => (await hooks(application!).snapshot()).normalBounds).toEqual(bounds)
    await hooks(application).mode('maximize')
    await expect.poll(async () => (await hooks(application!).snapshot()).maximized).toBe(true)
    await hooks(application).mode('minimize')
    await expect.poll(async () => (await hooks(application!).snapshot()).minimized).toBe(true)
    await hooks(application).close()
    const before = await snapshot(application)
    const minimizedDisk = JSON.parse(readFileSync(before.paths.appStatePath, 'utf8')).windowState
    expect(minimizedDisk).toMatchObject({ normalBounds: bounds, maximized: true })
    await hooks(application).show()
    await expect.poll(async () => (await hooks(application!).snapshot()).minimized).toBe(false)
    await exitApp(application); application = null
    application = await launchApp({ profile: 'window-maximized' }); await waitForCore(application)
    await expect.poll(async () => (await hooks(application!).snapshot()).maximized).toBe(true)
    const restoredMax = await hooks(application).snapshot()
    // Native getNormalBounds may transiently report the maximized rectangle on
    // hidden X11 startup. The retained state and real unmaximize must restore it.
    expect(restoredMax.persisted.normalBounds).toEqual(bounds)
    await hooks(application).mode('unmaximize')
    await expect.poll(async () => (await hooks(application!).snapshot()).normalBounds).toEqual(bounds)
    await hooks(application).mode('fullscreen')
    await expect.poll(async () => (await hooks(application!).snapshot()).fullscreen).toBe(true)
    await hooks(application).close()
    const fullscreenDisk = JSON.parse(readFileSync(before.paths.appStatePath, 'utf8')).windowState
    expect(fullscreenDisk).toMatchObject({ normalBounds: bounds, maximized: false })
    await hooks(application).mode('normal')
    await hooks(application).show()
    await evidence(info, 'window-maximize-minimize-fullscreen', { minimizedDisk, restoredMax, fullscreenDisk })
    await exitApp(application); application = null
  } finally { await dispose(application) }
})

test('damaged/null app-owned state cannot prevent real Electron startup', async ({}, info) => {
  test.setTimeout(240_000)
  let application: ElectronApplication | null = await launchApp({ profile: 'window-damaged' })
  try {
    await waitForCore(application); const before = await snapshot(application)
    await exitApp(application); application = null
    const reports = []
    for (const value of ['null', '[]', '{broken', JSON.stringify({ windowState: { version: 1, normalBounds: { x: 1e15, y: 0, width: -1, height: 0 }, maximized: true } })]) {
      writeFileSync(before.paths.appStatePath, value, { mode: 0o600 })
      application = await launchApp({ profile: 'window-damaged' }); await waitForCore(application)
      const state = await hooks(application).snapshot()
      expect(state.normalBounds.width).toBeGreaterThanOrEqual(720); expect(state.normalBounds.height).toBeGreaterThanOrEqual(480)
      expect(state.maximized).toBe(false); reports.push({ value, state })
      await exitApp(application); application = null
    }
    await evidence(info, 'window-damaged-startup', reports)
  } finally { await dispose(application) }
})

test('UI state write failure does not make orderly Exit cleanup unknown', async ({}, info) => {
  let application: ElectronApplication | null = await launchApp({ profile: 'window-write-failure' })
  let blockedPath = ''
  try {
    await waitForCore(application); const before = await snapshot(application)
    // Block only this disposable app-owned state file, not drafts/core/cleanup receipts.
    blockedPath = before.paths.appStatePath
    await hooks(application).close()
    renameSync(blockedPath, `${blockedPath}.preserved`); mkdirSync(blockedPath, { mode: 0o700 })
    await hooks(application).bounds({ x: 80, y: 90, width: 900, height: 600 })
    await exitApp(application); application = null
    const cleanup = JSON.parse(readFileSync(before.cleanupPath, 'utf8'))
    expect(cleanup).toMatchObject({ state: 'process-exited', unsaved: false, shutdownAccepted: true })
    await evidence(info, 'window-best-effort-ui-exit', { cleanup, blockedPath })
  } finally { await dispose(application); if (blockedPath) rmdirSync(blockedPath) }
})
