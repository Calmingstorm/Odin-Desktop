import { mkdirSync, readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type ElectronApplication, type Page } from '@playwright/test'
import { assertIsolated, exitApp, launchApp, waitForCore } from './harness'

if (process.env.ODIN_APP_COMPOSER_GEOMETRY !== '1' || !process.env.ODIN_APP_COMPOSER_PLAN || !process.env.ODIN_APP_E2E_OUT) {
  throw new Error('Use scripts/composer-geometry.mjs; direct/nonisolated Composer geometry execution refused')
}
const output = process.env.ODIN_APP_E2E_OUT!
const plan = JSON.parse(readFileSync(process.env.ODIN_APP_COMPOSER_PLAN!, 'utf8')) as { command: string[] }
async function settled(page: Page): Promise<void> {
  await page.evaluate(async () => { await document.fonts.ready; await new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))) })
}
async function size(app: ElectronApplication, page: Page, width: number, height: number, zoom = 1): Promise<void> {
  await app.evaluate(({ BrowserWindow }, dimensions) => {
    const window = BrowserWindow.getAllWindows()[0]!
    window.setContentSize(dimensions.width, dimensions.height)
    window.webContents.setZoomFactor(dimensions.zoom)
  }, { width, height, zoom })
  await expect.poll(() => page.evaluate(() => ({ width: innerWidth, height: innerHeight }))).toEqual({ width: Math.round(width / zoom), height: Math.round(height / zoom) })
  await settled(page)
}
async function geometry(page: Page) {
  await settled(page)
  return page.evaluate(() => {
    const textarea = document.querySelector<HTMLTextAreaElement>('.composer-box textarea')!
    const box = document.querySelector<HTMLElement>('.composer-box')!
    const scroller = document.querySelector<HTMLElement>('.message-scroll')!
    const style = getComputedStyle(textarea)
    const rect = (element: Element) => {
      const b = element.getBoundingClientRect()
      return { x: b.x, y: b.y, width: b.width, height: b.height, right: b.right, bottom: b.bottom }
    }
    return { textarea: rect(textarea), box: rect(box), composerForm: rect(document.querySelector('.composer-form')!),
      help: rect(document.querySelector('#composer-help')!), statusbar: rect(document.querySelector('.statusbar')!),
      lineHeight: parseFloat(style.lineHeight),
      chrome: parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth),
      overflowY: style.overflowY, maxHeight: style.maxHeight, clientHeight: textarea.clientHeight, scrollHeight: textarea.scrollHeight,
      buttons: [...box.querySelectorAll('button')].map((button) => ({ name: button.getAttribute('aria-label'), ...rect(button) })),
      messageScroll: { top: scroller.scrollTop, client: scroller.clientHeight, height: scroller.scrollHeight, bounds: rect(scroller) },
      viewport: { width: innerWidth, height: innerHeight }, documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth, documentHeight: document.documentElement.clientHeight,
      documentScrollHeight: document.documentElement.scrollHeight }
  })
}
async function initial(page: Page): Promise<void> {
  await expect.poll(async () => (await geometry(page)).textarea.height).toBeCloseTo(38, 0)
}
async function alignment(page: Page): Promise<void> {
  const measured = await geometry(page)
  for (const button of measured.buttons) {
    expect(Math.abs(button.bottom - measured.textarea.bottom), `${button.name} bottom aligned with textarea`).toBeLessThanOrEqual(1)
    expect(button.height).toBeCloseTo(38, 0)
  }
}
async function proof(name: string, body: (app: ElectronApplication, page: Page, record: (label: string, evidence?: unknown) => Promise<void>) => Promise<void>): Promise<void> {
  assertIsolated()
  mkdirSync(output, { recursive: true, mode: 0o700 })
  const receipt: Record<string, unknown> = { name, outcome: 'running', measurements: [],
    provenance: { uid: process.getuid?.(), gid: process.getgid?.(), pidNamespace: readlinkSync('/proc/self/ns/pid'),
      outerPidNamespace: process.env.ODIN_REAL_CORE_OUTER_PID_NS, home: process.env.HOME,
      display: process.env.DISPLAY, privateDbus: Boolean(process.env.DBUS_SESSION_BUS_ADDRESS) },
    limitation: 'Real Composer renderer geometry; synthetic core, not engine or installed/native-platform qualification.' }
  let app: ElectronApplication | undefined
  let page: Page | undefined
  const record = async (label: string, evidence?: unknown): Promise<void> => {
    const path = join(output, `${name}-${label}.png`)
    const measured = await geometry(page!)
    await page!.screenshot({ path, animations: 'disabled', caret: 'hide' })
    ;(receipt.measurements as unknown[]).push({ label, ...measured, screenshot: path, ...(evidence ? { evidence } : {}) })
  }
  try {
    app = await launchApp({ profile: name, realCore: false, env: { ODIN_DESKTOP_CORE_CMD: JSON.stringify(plan.command) } })
    await waitForCore(app)
    page = await app.firstWindow()
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await size(app, page, 1180, 780)
    await page.getByRole('button', { name: 'Composer geometry history', exact: true }).click()
    await expect(page.locator('.message-scroll .msg').first()).toBeAttached()
    await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled()
    await initial(page)
    await body(app, page, record)
    receipt.outcome = 'passed'
  } catch (error) {
    receipt.outcome = 'failed'; receipt.error = String(error)
    if (page && !page.isClosed()) await record('failure').catch(() => undefined)
    throw error
  } finally {
    try {
      if (app) await exitApp(app).catch((error) => { receipt.cleanupError = String(error); receipt.outcome = 'failed'; throw error })
    } finally {
      writeFileSync(join(output, `${name}.json`), JSON.stringify(receipt, null, 2) + '\n', { mode: 0o600 })
    }
  }
}

test('real Composer: one-line38, Shift+Enter growth, eight-line clamp, shrink and native text paste', async () => {
  await proof('growth-paste', async (app, page, record) => {
    const textarea = page.getByRole('textbox', { name: 'Message', exact: true })
    await record('initial')
    await textarea.fill('First line')
    await textarea.press('End')
    await textarea.press('Shift+Enter')
    await textarea.press('KeyA')
    await expect.poll(async () => { const m = await geometry(page); return Math.abs(m.textarea.height - (2 * m.lineHeight + m.chrome)) }).toBeLessThanOrEqual(1)
    await alignment(page); await record('two-lines')
    await textarea.fill(Array.from({ length: 30 }, (_, i) => `Line ${i}`).join('\n'))
    await expect.poll(async () => { const m = await geometry(page); return Math.abs(m.textarea.height - (8 * m.lineHeight + m.chrome)) }).toBeLessThanOrEqual(1)
    const capped = await geometry(page)
    expect(capped.scrollHeight).toBeGreaterThan(capped.clientHeight)
    expect(['auto', 'scroll']).toContain(capped.overflowY)
    await alignment(page); await record('eight-line-clamp')
    await textarea.fill('Short'); await initial(page); await record('shrink')
    for (const lines of [7, 8, 9, 8]) {
      await textarea.fill(Array.from({ length: lines }, (_, i) => `Boundary line ${i}`).join('\n'))
      await expect.poll(async () => { const m = await geometry(page); return Math.abs(m.textarea.height - (Math.min(lines, 8) * m.lineHeight + m.chrome)) }).toBeLessThanOrEqual(1)
      const measured = await geometry(page)
      expect(measured.overflowY).toBe(lines > 8 ? 'auto' : 'hidden')
    }
    const frames = await page.evaluate(async () => {
      const element = document.querySelector<HTMLTextAreaElement>('.composer-box textarea')!
      const result: { height: number; width: number; overflow: string }[] = []
      for (let frame = 0; frame < 20; frame++) {
        await new Promise<void>((done) => requestAnimationFrame(() => done()))
        result.push({ height: element.getBoundingClientRect().height, width: element.clientWidth, overflow: getComputedStyle(element).overflowY })
      }
      return result
    })
    expect(new Set(frames.map((frame) => JSON.stringify(frame))).size, 'Eight-line boundary must settle without height/scrollbar oscillation').toBe(1)
    await record('eight-line-boundary-stable', { frames })
    const mirror = page.locator('.composer-measurement')
    await expect(mirror).toHaveAttribute('aria-hidden', 'true')
    await expect(mirror).toBeHidden()
    // Query Chromium's actual accessibility tree. DOM hiding alone is not AX proof.
    const cdp = await page.context().newCDPSession(page)
    try {
      const root = await cdp.send('DOM.getDocument')
      const node = await cdp.send('DOM.querySelector', { nodeId: root.root.nodeId, selector: '.composer-measurement' })
      expect(node.nodeId).toBeGreaterThan(0)
      const tree = await cdp.send('Accessibility.getPartialAXTree', { nodeId: node.nodeId, fetchRelatives: false })
      expect(tree.nodes.length).toBeGreaterThan(0)
      expect(tree.nodes.every((item: { ignored: boolean }) => item.ignored), 'Measurement mirror must not duplicate draft in accessibility tree').toBe(true)
      await record('mirror-excluded-from-ax', { nodes: tree.nodes })
    } finally { await cdp.detach() }
    const pasted = 'Clipboard line one\nClipboard line two\nClipboard line three'
    await app.evaluate(({ clipboard }, value) => clipboard.writeText(value), pasted)
    await textarea.fill(''); await textarea.focus(); await textarea.press('Control+V')
    await expect(textarea).toHaveValue(pasted)
    await expect.poll(async () => { const m = await geometry(page); return Math.abs(m.textarea.height - (3 * m.lineHeight + m.chrome)) }).toBeLessThanOrEqual(1)
    await record('native-paste')
  })
})

test('real Composer: successful send reset and per-conversation draft restoration across unmount', async () => {
  await proof('send-draft', async (_app, page, record) => {
    const textarea = page.getByRole('textbox', { name: 'Message', exact: true })
    const draft = 'Retained draft one\nRetained draft two\nRetained draft three'
    await textarea.fill(draft); await record('draft-before-switch')
    await page.getByRole('button', { name: 'New conversation', exact: true }).click()
    await expect(textarea).toHaveValue(''); await initial(page)
    await textarea.fill('Second conversation draft')
    await page.getByRole('button', { name: 'Composer geometry history', exact: true }).click()
    await expect(textarea).toHaveValue(draft)
    await expect.poll(async () => { const m = await geometry(page); return Math.abs(m.textarea.height - (3 * m.lineHeight + m.chrome)) }).toBeLessThanOrEqual(1)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await page.getByRole('button', { name: 'Back to chat' }).click()
    await expect(textarea).toHaveValue(draft)
    await expect.poll(async () => { const m = await geometry(page); return m.textarea.height }).toBeGreaterThan(38)
    await record('draft-after-remount')
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(textarea).toHaveValue(''); await initial(page)
    await expect(page.locator('.message-scroll')).toContainText('Echo: Retained draft one')
    await record('send-reset')
  })
})

test('real Composer: width and asynchronous FontFace remeasurement without input', async () => {
  await proof('width-font', async (app, page, record) => {
    const textarea = page.getByRole('textbox', { name: 'Message', exact: true })
    const text = 'Width changes must remeasure this unchanged draft. '.repeat(6)
    await textarea.fill(text)
    const wide = await geometry(page); await record('wide')
    await size(app, page, 720, 780)
    await expect(textarea).toHaveValue(text)
    await expect.poll(async () => (await geometry(page)).textarea.height).toBeGreaterThan(wide.textarea.height)
    await record('narrow-reflow')
    await size(app, page, 1180, 780)
    await expect.poll(async () => (await geometry(page)).textarea.height).toBeCloseTo(wide.textarea.height, 0)
    await textarea.fill('Font line one\nFont line two')
    const before = await geometry(page)
    const font = await page.evaluate(async () => {
      const element = document.querySelector<HTMLTextAreaElement>('.composer-box textarea')!
      const face = new FontFace('ComposerGeometryProof', 'local("DejaVu Sans Mono")')
      document.fonts.add(face)
      let events = 0
      const listener = (): void => { events++ }
      document.fonts.addEventListener('loadingdone', listener)
      element.style.fontFamily = 'ComposerGeometryProof, monospace'
      element.style.fontSize = '18px'; element.style.lineHeight = '28px'
      await document.fonts.load('18px ComposerGeometryProof')
      await document.fonts.ready
      await new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done())))
      document.fonts.removeEventListener('loadingdone', listener)
      return { status: face.status, events }
    })
    expect(font.status).toBe('loaded'); expect(font.events).toBeGreaterThan(0)
    await expect(textarea).toHaveValue('Font line one\nFont line two')
    await expect.poll(async () => { const m = await geometry(page); return Math.abs(m.textarea.height - (2 * m.lineHeight + m.chrome)) }).toBeLessThanOrEqual(1)
    expect((await geometry(page)).textarea.height).toBeGreaterThan(before.textarea.height)
    await alignment(page); await record('font-loaded-remeasurement', font)
  })
})

test('real Composer: history reading scroll does not jump while draft grows', async () => {
  await proof('scroll-stability', async (_app, page, record) => {
    const textarea = page.getByRole('textbox', { name: 'Message', exact: true })
    await page.locator('.message-scroll').evaluate((element) => { element.scrollTop = 300 })
    await settled(page)
    const before = await geometry(page)
    expect(before.messageScroll.height).toBeGreaterThan(before.messageScroll.client + 600)
    expect(before.messageScroll.top).toBeGreaterThan(100)
    await record('reading-before')
    await textarea.fill(Array.from({ length: 8 }, (_, i) => `Expanded draft line ${i}`).join('\n'))
    await expect.poll(async () => (await geometry(page)).textarea.height).toBeGreaterThan(38)
    expect(Math.abs((await geometry(page)).messageScroll.top - before.messageScroll.top)).toBeLessThanOrEqual(1)
    await record('reading-expanded')
    await textarea.fill('Short')
    await initial(page)
    expect(Math.abs((await geometry(page)).messageScroll.top - before.messageScroll.top)).toBeLessThanOrEqual(1)
    await record('reading-shrunk')
  })
})

test('real Composer: minimum and 200-percent bounds, bottom buttons and command keyboard behavior', async () => {
  await proof('bounds-commands', async (app, page, record) => {
    const textarea = page.getByRole('textbox', { name: 'Message', exact: true })
    for (const variant of [{ key: 'minimum', width: 720, height: 480, zoom: 1 }, { key: 'zoom200', width: 1180, height: 780, zoom: 2 }]) {
      await size(app, page, variant.width, variant.height, variant.zoom)
      for (const lines of [1, 8]) {
        await textarea.fill(Array.from({ length: lines }, (_, i) => `Line ${i}`).join('\n'))
        await alignment(page)
        const m = await geometry(page)
        expect(m.documentScrollWidth).toBeLessThanOrEqual(m.documentWidth + 1)
        expect(m.documentScrollHeight).toBeLessThanOrEqual(m.documentHeight + 1)
        expect(m.messageScroll.client, 'Eight-line composer must preserve a visible history region').toBeGreaterThanOrEqual(79)
        expect(m.composerForm.bottom, 'Composer form must not overlap the status footer').toBeLessThanOrEqual(m.statusbar.y - 1)
        expect(m.help.bottom, 'Composer help must remain above the status footer').toBeLessThanOrEqual(m.statusbar.y - 1)
        if (variant.zoom === 2 && lines === 8) {
          expect(m.textarea.height).toBeLessThan(8 * m.lineHeight + m.chrome)
          expect(m.scrollHeight, 'Draft must scroll internally rather than be clipped by the short viewport').toBeGreaterThan(m.clientHeight)
          expect(m.overflowY).toBe('auto')
        }
        for (const box of [m.box, m.textarea, m.composerForm, m.help, m.statusbar, m.messageScroll.bounds, ...m.buttons]) {
          expect(box.x).toBeGreaterThanOrEqual(-1); expect(box.right).toBeLessThanOrEqual(m.viewport.width + 1)
          expect(box.y).toBeGreaterThanOrEqual(-1); expect(box.bottom).toBeLessThanOrEqual(m.viewport.height + 1)
          expect(box.width).toBeGreaterThan(0); expect(box.height).toBeGreaterThan(0)
        }
        await record(`${variant.key}-${lines}-lines`)
      }
    }
    await size(app, page, 1180, 780)
    await textarea.fill('/'); await expect(page.getByRole('listbox', { name: 'Commands' })).toBeVisible()
    await textarea.press('End')
    const last = await textarea.getAttribute('aria-activedescendant')
    await textarea.press('Home')
    expect(await textarea.getAttribute('aria-activedescendant')).not.toBe(last)
    await textarea.press('ArrowDown'); await textarea.press('ArrowUp')
    await textarea.press('Escape'); await expect(page.getByRole('listbox', { name: 'Commands' })).toHaveCount(0)
    await textarea.fill('/sta'); await textarea.press('Tab'); await expect(textarea).toHaveValue('/status ')
    await initial(page); await textarea.press('Enter')
    await expect(page.getByRole('region', { name: 'Status', exact: true })).toBeVisible()
    await expect(textarea).toHaveValue(''); await initial(page)
    await page.getByRole('button', { name: 'Close command report', exact: true }).click()
    await expect(textarea).toBeFocused(); await record('command-preserved')
  })
})
