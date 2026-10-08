import { mkdirSync, readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join, resolve, sep } from 'node:path'
import { expect, test, type ElectronApplication, type Page } from '@playwright/test'
import { exitApp, launchApp, repository, snapshot, waitForCore } from './harness'

type Variant = { key: string; width: number; height: number; theme: 'dark' | 'light' }
type BoundsVariant = { key: string; width: number; height: number; zoom: number }
if (process.env.ODIN_APP_UI_CAPTURE !== '1' || !process.env.ODIN_APP_UI_PLAN) {
  throw new Error('Use scripts/ui-v1-capture.mjs to supply an isolated capture plan')
}
const plan = JSON.parse(readFileSync(process.env.ODIN_APP_UI_PLAN, 'utf8')) as {
  epoch: string; navigation: string[]; variants: Variant[]; bounds: BoundsVariant[]; command: string[]
}
const { epoch: CAPTURE_EPOCH, navigation: PRIMARY_NAV, variants: CAPTURE_VARIANTS, bounds: BOUNDS_VARIANTS } = plan
function sha256(bytes: Buffer): string { return createHash('sha256').update(bytes).digest('hex') }
function externalOutput(value: string | undefined): string {
  if (!value) throw new Error('Missing external output directory')
  const output = resolve(value)
  if (output === repository || output.startsWith(repository + sep)) throw new Error('Evidence must remain outside repository')
  return output
}

async function size(application: ElectronApplication, page: Page, width: number, height: number, zoom = 1): Promise<void> {
  await application.evaluate(({ BrowserWindow }, dimensions) => {
    const window = BrowserWindow.getAllWindows()[0]!
    window.setContentSize(dimensions.width, dimensions.height)
    window.webContents.setZoomFactor(dimensions.zoom)
  }, { width, height, zoom })
  await expect.poll(() => page.evaluate(() => ({ width: innerWidth, height: innerHeight }))).toEqual({
    width: Math.round(width / zoom), height: Math.round(height / zoom)
  })
}

async function settled(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await document.fonts.ready
    await new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done())))
  })
}

async function bounds(page: Page): Promise<unknown> {
  await settled(page)
  const measured = await page.evaluate(() => {
    const documentWidth = document.documentElement.clientWidth
    const shell = document.querySelector<HTMLElement>('.shell')!
    const settings = document.querySelector<HTMLElement>('.settings')!
    const body = document.querySelector<HTMLElement>('.settings-body')!
    const nav = document.querySelector<HTMLElement>('.settings-nav')!
    const rect = (element: Element) => {
      const box = element.getBoundingClientRect()
      return { x: box.x, y: box.y, width: box.width, height: box.height, right: box.right, bottom: box.bottom }
    }
    // Vertical offscreen controls belong to a scrollable page. Horizontal spill does not.
    const outOfBounds = [...settings.querySelectorAll<HTMLElement>('button, input, select, textarea, [role="switch"]')]
      .filter((element) => element.getClientRects().length > 0)
      .map((element) => ({ name: element.getAttribute('aria-label') || element.textContent?.trim() || element.id,
        box: rect(element) }))
      .filter(({ box }) => box.x < -1 || box.right > documentWidth + 1)
    return { viewport: { width: innerWidth, height: innerHeight }, documentWidth,
      documentScrollWidth: document.documentElement.scrollWidth, shell: rect(shell), settings: rect(settings),
      nav: rect(nav), body: rect(body), bodyClientWidth: body.clientWidth, bodyScrollWidth: body.scrollWidth,
      navClientWidth: nav.clientWidth, navScrollWidth: nav.scrollWidth, outOfBounds }
  })
  expect(measured.documentScrollWidth, 'Document must not scroll horizontally').toBeLessThanOrEqual(measured.documentWidth + 1)
  expect(measured.bodyScrollWidth, 'General content must not overflow horizontally').toBeLessThanOrEqual(measured.bodyClientWidth + 1)
  expect(measured.navScrollWidth, 'Settings navigation must not overflow horizontally').toBeLessThanOrEqual(measured.navClientWidth + 1)
  expect(measured.outOfBounds, 'Settings controls must remain within horizontal viewport bounds').toEqual([])
  for (const box of [measured.shell, measured.settings, measured.nav, measured.body]) {
    expect(box.x).toBeGreaterThanOrEqual(-1)
    expect(box.right).toBeLessThanOrEqual(measured.viewport.width + 1)
    expect(box.y).toBeGreaterThanOrEqual(-1)
    expect(box.bottom).toBeLessThanOrEqual(measured.viewport.height + 1)
    expect(box.width).toBeGreaterThan(0)
    expect(box.height).toBeGreaterThan(0)
  }
  return measured
}

test.beforeEach(() => {
  if (process.env.ODIN_APP_UI_CAPTURE !== '1') throw new Error('Use scripts/ui-v1-capture.mjs; this suite is not a platform qualification')
})

for (const variant of CAPTURE_VARIANTS as Variant[]) {
  test(`UI B ${variant.key}: General, About and representative settings shell`, async ({}, info) => {
    test.setTimeout(180_000)
    const output = externalOutput(process.env.ODIN_APP_E2E_OUT)
    mkdirSync(output, { recursive: true, mode: 0o700 })
    const fixture = join(repository, 'app/fixture-core/fixture_core.py')
    const python = process.env.ODIN_DESKTOP_ENGINE_PYTHON!
    const command = plan.command
    expect(command[0]).toBe(python)
    expect(command.at(-1)).toBe(fixture)
    const outcome: Record<string, unknown> = {
      variant, outcome: 'running', screenshots: [], checks: [],
      fixture: { path: fixture, sha256: sha256(readFileSync(fixture)), command, realCore: false },
      provenance: { epoch: CAPTURE_EPOCH, uid: process.getuid?.(), gid: process.getgid?.(),
        pidNamespace: readlinkSync('/proc/self/ns/pid'), outerPidNamespace: process.env.ODIN_REAL_CORE_OUTER_PID_NS,
        home: process.env.HOME, display: process.env.DISPLAY, privateDbus: Boolean(process.env.DBUS_SESSION_BUS_ADDRESS) },
      limitation: 'Source-build fixture renderer evidence only. Other settings pages are staged, not converted or qualified.'
    }
    const checks = outcome.checks as unknown[]
    const screenshots = outcome.screenshots as unknown[]
    let application: ElectronApplication | undefined
    try {
      application = await launchApp({ profile: `ui-b-${variant.key}`, realCore: false,
        env: { ODIN_DESKTOP_CORE_CMD: JSON.stringify(command) } })
      await waitForCore(application)
      const page = await application.firstWindow()
      // Fixture reset/relative timestamps must not change between reruns. Real timeout clocks remain untouched.
      await page.clock.setFixedTime(new Date(CAPTURE_EPOCH))
      // Respect the app's style-src self policy. Reduced motion and screenshot
      // animation/caret options provide deterministic capture without injected CSS.
      await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'no-preference' })
      await size(application, page, variant.width, variant.height)
      await page.getByRole('button', { name: 'New conversation', exact: true }).click()
      const draft = 'UI B retained draft. Never sent.'
      const composer = page.getByRole('textbox', { name: 'Message', exact: true })
      await expect(composer).toBeVisible()
      await composer.fill(draft)
      await page.getByRole('button', { name: 'Settings', exact: true }).click()
      await expect(page.locator('.sidebar')).toBeHidden()
      await expect(page.getByRole('heading', { name: 'General', exact: true })).toBeVisible()
      const nav = page.getByRole('navigation', { name: 'Settings sections', exact: true })
      await expect(nav.locator('[data-testid^="settings-section-"]')).toHaveText(PRIMARY_NAV)
      await expect(nav.getByRole('button', { name: 'Advanced settings', exact: true })).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Advanced settings', exact: true })).toHaveCount(1)
      checks.push({ name: 'exact-nine-primary-navigation-and-secondary-advanced', outcome: 'passed', names: PRIMARY_NAV })

      const quiet = page.getByRole('switch', { name: 'Quiet hours', exact: true })
      await expect(quiet).toHaveCount(1)
      await expect(quiet).toHaveAttribute('type', 'checkbox')
      await expect(quiet).toHaveAccessibleName('Quiet hours')
      await quiet.focus()
      const initial = await quiet.isChecked()
      await quiet.press('Space')
      await expect(quiet).toBeChecked({ checked: !initial })
      await expect.poll(async () => page.evaluate(async () => {
        const response = await window.odin.getSettings()
        return response.ok ? response.result.notifications.quietHours.enabled : null
      })).toBe(!initial)
      await quiet.press('Space')
      await expect(quiet).toBeChecked({ checked: initial })
      await expect.poll(async () => page.evaluate(async () => {
        const response = await window.odin.getSettings()
        return response.ok ? response.result.notifications.quietHours.enabled : null
      })).toBe(initial)
      checks.push({ name: 'native-quiet-hours-switch-Space-and-persisted-local-setting', outcome: 'passed', initial })

      for (const name of ['Quiet hours start', 'Quiet hours end']) {
        await expect(page.getByLabel(name, { exact: true })).toHaveAccessibleName(name)
      }
      await expect(page.getByRole('radio', { name: 'Dark', exact: true })).toHaveAccessibleName('Dark')
      await expect(page.getByRole('radio', { name: 'Light', exact: true })).toHaveAccessibleName('Light')
      await page.getByRole('radio', { name: variant.theme === 'dark' ? 'Dark' : 'Light', exact: true }).check()
      await expect.poll(async () => page.evaluate(async () => {
        const response = await window.odin.getSettings()
        return response.ok ? response.result.appearance : null
      })).toBe(variant.theme)
      // Reset only the Playwright media override so Electron's nativeTheme
      // selection, rather than Playwright's default light emulation, owns color.
      await page.emulateMedia({ colorScheme: null, reducedMotion: 'reduce' })
      await expect.poll(() => page.evaluate(() => matchMedia('(prefers-color-scheme: dark)').matches)).toBe(variant.theme === 'dark')
      checks.push({ name: 'accessible-theme-and-quiet-hours-names', outcome: 'passed' })

      await page.getByRole('button', { name: /Back to chat/, exact: false }).click()
      await expect(page.locator('.sidebar')).toBeVisible()
      await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toHaveValue(draft)
      checks.push({ name: 'settings-sidebar-hidden-and-chat-draft-restored', outcome: 'passed' })
      await page.getByRole('button', { name: 'Settings', exact: true }).click()
      const body = page.locator('.settings-body')
      const screenshot = async (label: string) => {
        await settled(page)
        const path = join(output, `${variant.key}-${label}.png`)
        await page.screenshot({ path, fullPage: false, animations: 'disabled', caret: 'hide', scale: 'css' })
        screenshots.push({ path, sha256: sha256(readFileSync(path)), label,
          scroll: await body.evaluate((element) => ({ top: element.scrollTop, height: element.scrollHeight, client: element.clientHeight })) })
        await info.attach(label, { path, contentType: 'image/png' })
        console.log(`UI B screenshot: ${path}`)
      }
      await expect(page.getByRole('heading', { name: 'About', exact: true })).toHaveCount(1)
      await body.evaluate((element) => { element.scrollTop = 0 })
      await screenshot('general-upper')
      await page.getByRole('heading', { name: 'This app', exact: true }).evaluate((element) => element.scrollIntoView({ block: 'start' }))
      await expect(page.getByRole('switch', { name: 'Desktop notifications', exact: true })).toBeInViewport()
      await expect(page.getByLabel('Quiet hours end', { exact: true })).toBeInViewport()
      await screenshot('general-notifications')
      await body.evaluate((element) => { element.scrollTop = element.scrollHeight })
      await screenshot('general-lower')
      await page.getByRole('heading', { name: 'About', exact: true }).scrollIntoViewIfNeeded()
      await expect(page.getByRole('heading', { name: 'About', exact: true })).toBeVisible()
      await screenshot('general-about')
      await nav.getByRole('button', { name: 'Models and providers', exact: true }).click()
      await expect(page.getByRole('heading', { name: 'Models and providers', exact: true })).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Codex accounts', exact: true })).toBeVisible()
      await expect(page.locator('.accounts .account')).toHaveCount(2)
      await body.evaluate((element) => { element.scrollTop = 0 })
      await screenshot('models-and-providers-shell')

      await nav.getByRole('button', { name: 'General', exact: true }).click()
      for (const check of BOUNDS_VARIANTS as BoundsVariant[]) {
        await size(application, page, check.width, check.height, check.zoom)
        await body.evaluate((element) => { element.scrollTop = 0 })
        const upper = await bounds(page)
        await body.evaluate((element) => { element.scrollTop = element.scrollHeight })
        const lower = await bounds(page)
        checks.push({ name: check.key, outcome: 'passed', screenshots: false, upper, lower })
      }
      await size(application, page, variant.width, variant.height)
      outcome.mainSnapshot = await snapshot(application)
      await exitApp(application)
      application = undefined
      checks.push({ name: 'graceful-app-exit', outcome: 'passed' })
      outcome.outcome = 'passed'
    } catch (error) {
      outcome.outcome = 'failed'
      outcome.error = String(error instanceof Error ? error.stack : error)
      throw error
    } finally {
      if (application) {
        try { await application.close(); outcome.cleanup = 'application-close-completed' }
        catch (error) { outcome.cleanup = String(error) }
      }
      const path = join(output, `${variant.key}.json`)
      writeFileSync(path, JSON.stringify(outcome, null, 2) + '\n', { mode: 0o600 })
      console.log(`UI B receipt: ${path} (${outcome.outcome})`)
    }
  })
}
