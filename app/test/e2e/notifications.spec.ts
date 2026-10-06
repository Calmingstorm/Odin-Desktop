// Native Electron -> private receiver. Fixture conversations/acks, NOT real-core delivery or human appearance.
import { test, expect, type ElectronApplication } from '@playwright/test'
import { resolve } from 'node:path'
import { readFileSync, readlinkSync } from 'node:fs'
import type { NotificationChange, OdinApi } from '../../src/shared/api'
import { launchApp, request, waitForCore } from './harness'
import { PrivateNotificationBus } from './private-notification-bus'
interface Ack { dedupeKey: string; outcome: string; settled: { ok: boolean } }
interface Hook { notification(intent: Record<string, unknown>, at: string): Promise<string>; notificationAcks: Ack[] }
async function notify(app: ElectronApplication, key: string, at = new Date().toISOString()): Promise<string> {
  return app.evaluate((_electron, data) => {
    return (globalThis as unknown as { __odinE2E: Hook }).__odinE2E.notification(data.intent, data.at)
  }, { intent: { conversation_id: 'notify-main', message_id: 'notify-main-3', category: 'reply', preview: 'Committed fixture preview', dedupe_key: key }, at })
}
async function acks(app: ElectronApplication): Promise<Ack[]> {
  return app.evaluate(() => (globalThis as unknown as { __odinE2E: Hook }).__odinE2E.notificationAcks)
}
test.describe('private native notifications (fixture conversation/ack service)', () => {
  let app: ElectronApplication | undefined
  let bus: PrivateNotificationBus
  test.beforeEach(async () => {
    bus = new PrivateNotificationBus()
    await bus.start()
    app = await launchApp({ realCore: false, env: { ODIN_DESKTOP_CORE_CMD: JSON.stringify([
      process.env.ODIN_DESKTOP_ENGINE_PYTHON, resolve('tests/desktop_fixtures/notification_core.py')]) } })
    await waitForCore(app!)
    await (await app!.firstWindow()).locator('.message-scroll').waitFor()
    await (await app!.firstWindow()).locator('.conv', { hasText: 'Other conversation' }).click()
    await expect((await app!.firstWindow()).locator('#m-notify-other-119')).toBeVisible()
    await app!.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.hide())
  })
  test.afterEach(async ({}, info) => {
    if (app) { await app.close(); app = undefined }
    if (bus) {
      const before = await bus.snapshot()
      const cleanup = await bus.stop()
      await info.attach('private-notification-receiver', { body: JSON.stringify({ before, cleanup }, null, 2), contentType: 'application/json' })
      expect(cleanup.code).toBe(0)
      expect(cleanup.socketRemoved).toBe(true)
      expect(cleanup.receipt).toContain('"bus_disconnected": true')
    }
  })
  test('native request/show/ack and ActionInvoked reaches the exact older message', async ({}, info) => {
    const running = app!
    const before = await request(running, 'notification.qualification') as { result: { reads: unknown[] } }
    expect(await notify(running, 'shown-old')).toBe('shown')
    const snapshot = await bus.snapshot()
    expect(snapshot.requests).toHaveLength(1)
    const native = snapshot.requests[0]!
    expect(native).toMatchObject({ summary: 'Odin · Notification target', body: 'Committed fixture preview', accepted: true })
    expect(native.actions).toContain('default')
    await expect.poll(async () => (await acks(running)).find((ack) => ack.dedupeKey === 'shown-old')?.settled.ok).toBe(true)
    const accepted = await request(running, 'notification.qualification')
    expect(accepted).toMatchObject({ ok: true, result: { acks: { 'shown-old': 'shown' }, reads: before.result.reads } })
    await bus.control({ action: 'click', id: native.id })
    const page = await running.firstWindow()
    await expect(page.locator('#m-notify-main-3')).toHaveClass(/highlight/)
    await expect(page.locator('.conv.active')).toContainText('Notification target')
    await expect(page.locator('#m-notify-main-3')).toBeInViewport()
    await expect(page.locator('.jump-banner')).toBeVisible()
    expect((await bus.snapshot()).actions).toEqual([{ id: native.id, key: 'default' }])
    const after = await request(running, 'notification.qualification')
    expect(after).toMatchObject({ ok: true, result: { fixture_only: true, reads: before.result.reads } })
    await info.attach('notification-ack-read-watermarks', {
      body: JSON.stringify({ before, accepted, after, ackReceipts: await acks(running),
        visibleMessage: await page.locator('.msg.highlight').getAttribute('id') }, null, 2),
      contentType: 'application/json'
    })
  })
  test('native rejection produces failed ack and dedupe never fabricates acceptance', async () => {
    const running = app!
    await bus.control({ action: 'reject', enabled: true })
    expect(await notify(running, 'failed')).toBe('failed')
    expect(await notify(running, 'failed')).toBe('duplicate')
    expect((await bus.snapshot()).requests).toHaveLength(1)
    expect((await bus.snapshot()).requests[0]?.accepted).toBe(false)
    await expect.poll(async () => (await acks(running)).find((ack) => ack.dedupeKey === 'failed')?.settled.ok).toBe(true)
    expect(await request(running, 'notification.qualification')).toMatchObject({ ok: true, result: { acks: { failed: 'failed' } } })
    await bus.control({ action: 'reject', enabled: false })
    expect(await notify(running, 'after-failure')).toBe('shown')
  })
  test('preview/focus/mute/quiet-hours/stale/dedupe preserve policy before native request', async () => {
    const running = app!
    const page = await running.firstWindow()
    const settings = (change: NotificationChange) => page.evaluate((value) => (window as unknown as { odin: OdinApi }).odin.setNotifications(value), change)
    await settings({ previews: false })
    expect(await notify(running, 'private-preview')).toBe('shown')
    expect((await bus.snapshot()).requests[0]?.body).toBe('New message from Odin')
    expect(await notify(running, 'private-preview')).toBe('duplicate')
    await settings({ previews: true })
    await page.evaluate(() => (window as unknown as { odin: OdinApi }).odin.setConversationMuted({ conversation_id: 'notify-main', muted: true }))
    expect(await notify(running, 'muted')).toBe('suppressed')
    await page.evaluate(() => (window as unknown as { odin: OdinApi }).odin.setConversationMuted({ conversation_id: 'notify-main', muted: false }))
    const now = new Date()
    const time = (at: Date) => `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`
    await settings({ quietHours: { enabled: true, start: time(now), end: time(new Date(now.getTime() + 120_000)) } })
    expect(await notify(running, 'quiet')).toBe('suppressed')
    await settings({ quietHours: { enabled: false } })
    expect(await notify(running, 'stale', new Date(Date.now() - 180_000).toISOString())).toBe('suppressed')
    await running.evaluate(({ BrowserWindow }) => { const win = BrowserWindow.getAllWindows()[0]!; win.show(); win.focus() })
    await expect.poll(() => running.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.isFocused())).toBe(true)
    expect(await notify(running, 'focused')).toBe('suppressed')
    expect((await bus.snapshot()).requests).toHaveLength(1)
    await expect.poll(async () => (await acks(running)).filter((ack) => ack.settled.ok).length).toBe(5)
  })

  test('notification daemon absence fails without autoactivation and cannot strand the window', async () => {
    const running = app!
    await bus.control({ action: 'release_name' })
    expect(await notify(running, 'daemon-absent')).toBe('failed')
    expect((await bus.snapshot()).requests).toHaveLength(0)
    await expect.poll(async () => (await acks(running)).find((ack) => ack.dedupeKey === 'daemon-absent')?.settled.ok).toBe(true)
    expect(await request(running, 'notification.qualification')).toMatchObject({ ok: true, result: { acks: { 'daemon-absent': 'failed' } } })
    await running.evaluate(({ BrowserWindow }) => { const win = BrowserWindow.getAllWindows()[0]!; win.show(); win.focus() })
    await expect((await running.firstWindow()).locator('.message-scroll')).toBeVisible()
  })

  test('native action survives renderer loss and waits for the new preload listener', async ({}, info) => {
    const running = app!
    expect(await notify(running, 'renderer-lost')).toBe('shown')
    const native = (await bus.snapshot()).requests[0]!
    const rendererPid = await running.evaluate(({ BrowserWindow }) => {
      const contents = BrowserWindow.getAllWindows()[0]!.webContents
      Object.assign(globalThis, { __notificationRendererGone: false })
      contents.once('render-process-gone', () => Object.assign(globalThis, { __notificationRendererGone: true }))
      return contents.getOSProcessId()
    })
    // Electron forcefullyCrashRenderer did not emit loss in this attached debugger build. Terminate only the
    // app-owned renderer PID, with native PID/UID/namespace evidence, inside the hard-isolated test namespace.
    const rendererIdentity = {
      pid: rendererPid,
      startTicks: readFileSync(`/proc/${rendererPid}/stat`, 'utf8').split(') ')[1]!.split(' ')[19],
      namespace: readlinkSync(`/proc/${rendererPid}/ns/pid`),
      uid: Number(/^Uid:\s+(\d+)/m.exec(readFileSync(`/proc/${rendererPid}/status`, 'utf8'))?.[1])
    }
    const mainPid = await running.evaluate(() => process.pid)
    // Chromium's sandbox can add a nested PID namespace. Trace native parentage in the runner's /proc,
    // rather than disabling that sandbox or assuming every descendant shares the runner namespace.
    const lineage: number[] = [rendererPid]
    let cursor = rendererPid
    for (let depth = 0; depth < 8 && cursor !== mainPid; depth++) {
      cursor = Number(/^PPid:\s+(\d+)/m.exec(readFileSync(`/proc/${cursor}/status`, 'utf8'))?.[1])
      if (!cursor) break
      lineage.push(cursor)
    }
    expect(lineage).toContain(mainPid)
    expect(rendererIdentity.namespace).not.toBe(process.env.ODIN_REAL_CORE_OUTER_PID_NS)
    expect(rendererIdentity.uid).toBe(process.getuid!())
    expect(rendererPid).not.toBe(process.pid)
    process.kill(rendererPid, 'SIGKILL')
    await expect.poll(() => running.evaluate(() => (globalThis as unknown as { __notificationRendererGone: boolean }).__notificationRendererGone)).toBe(true)
    await bus.control({ action: 'click', id: native.id })
    // A renderer SIGKILL invalidates Playwright's old CDP page session. Use the
    // surviving main process to inspect the newly created receiver, not a locator
    // whose transport belongs to the killed renderer. No direct navigation is
    // injected here; the native ActionInvoked still drives the application route.
    const recovered = () => running.evaluate(async ({ BrowserWindow }) => {
      const contents = BrowserWindow.getAllWindows()[0]!.webContents
      if (contents.isCrashed() || contents.isLoadingMainFrame()) return null
      return contents.executeJavaScript(`(() => {
        const message = document.querySelector('#m-notify-main-3');
        const rect = message?.getBoundingClientRect();
        const scroll = document.querySelector('.message-scroll')?.getBoundingClientRect();
        return { highlighted: message?.classList.contains('highlight') ?? false,
          active: document.querySelector('.conv.active')?.textContent ?? '',
          inViewport: Boolean(rect && scroll && rect.bottom > scroll.top && rect.top < scroll.bottom) };
      })()`)
    })
    try {
      await expect.poll(recovered, { timeout: 15_000 }).toMatchObject({
        highlighted: true, active: expect.stringContaining('Notification target'), inViewport: true
      })
    } catch (error) {
      const nativeState = await running.evaluate(async ({ BrowserWindow }) => {
        const contents = BrowserWindow.getAllWindows()[0]!.webContents
        return { crashed: contents.isCrashed(), loading: contents.isLoadingMainFrame(), url: contents.getURL(),
          text: contents.isCrashed() ? null : await contents.executeJavaScript('document.body.innerText') }
      })
      await info.attach('recovery-failure-diagnostics', { body: JSON.stringify({ nativeState, receiver: await bus.snapshot() }, null, 2), contentType: 'application/json' })
      throw error
    }
    await info.attach('recovered-notification-message', {
      body: JSON.stringify(await recovered()), contentType: 'application/json'
    })
    await expect.poll(async () => (await acks(running)).find((ack) => ack.dedupeKey === 'renderer-lost')?.settled.ok).toBe(true)
  })
})
