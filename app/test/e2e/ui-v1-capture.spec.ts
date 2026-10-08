import { mkdirSync, readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join, resolve, sep } from 'node:path'
import { expect, test, type ElectronApplication, type Locator, type Page } from '@playwright/test'
import { exitApp, launchApp, repository, snapshot, waitForCore } from './harness'

type Variant = { key: string; width: number; height: number; theme: 'dark' | 'light' }
type BoundsVariant = { key: string; width: number; height: number; zoom: number }
if (process.env.ODIN_APP_UI_CAPTURE !== '1' || !process.env.ODIN_APP_UI_PLAN) {
  throw new Error('Use scripts/ui-v1-capture.mjs to supply an isolated capture plan')
}
const plan = JSON.parse(readFileSync(process.env.ODIN_APP_UI_PLAN, 'utf8')) as {
  epoch: string; navigation: string[]; variants: Variant[]; bounds: BoundsVariant[]; command: string[]
  requiredStates: string[]; advancedCategories: string[]
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
  expect(measured.bodyScrollWidth, 'Settings content must not overflow horizontally').toBeLessThanOrEqual(measured.bodyClientWidth + 1)
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
  test(`UI C ${variant.key}: every settings page, full scroll coverage and expanded workflows`, async ({}, info) => {
    test.setTimeout(180_000)
    const output = externalOutput(process.env.ODIN_APP_E2E_OUT)
    mkdirSync(output, { recursive: true, mode: 0o700 })
    const fixture = join(repository, 'app/fixture-core/fixture_core.py')
    const python = process.env.ODIN_DESKTOP_ENGINE_PYTHON!
    const command = plan.command
    expect(command[0]).toBe(python)
    expect(command.at(-1)).toBe(fixture)
    const outcome: Record<string, unknown> = {
      variant, outcome: 'running', screenshots: [], checks: [], pages: [],
      fixture: { path: fixture, sha256: sha256(readFileSync(fixture)), command, realCore: false },
      provenance: { epoch: CAPTURE_EPOCH, uid: process.getuid?.(), gid: process.getgid?.(),
        pidNamespace: readlinkSync('/proc/self/ns/pid'), outerPidNamespace: process.env.ODIN_REAL_CORE_OUTER_PID_NS,
        home: process.env.HOME, display: process.env.DISPLAY, privateDbus: Boolean(process.env.DBUS_SESSION_BUS_ADDRESS) },
      limitation: 'Source-build synthetic fixture renderer evidence only, not engine adoption or platform qualification.'
    }
    const checks = outcome.checks as unknown[]
    const screenshots = outcome.screenshots as unknown[]
    let application: ElectronApplication | undefined
    try {
      application = await launchApp({ profile: `ui-c-${variant.key}`, realCore: false,
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
      const draft = 'UI C retained draft. Never sent.'
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
      const theme = page.getByRole('group', { name: 'Theme', exact: true })
      await expect(theme.getByRole('button', { name: 'Dark', exact: true })).toHaveAccessibleName('Dark')
      await expect(theme.getByRole('button', { name: 'Light', exact: true })).toHaveAccessibleName('Light')
      const choice = theme.getByRole('button', { name: variant.theme === 'dark' ? 'Dark' : 'Light', exact: true })
      await choice.focus()
      await choice.press('Space')
      await expect(choice).toHaveAttribute('aria-pressed', 'true')
      await expect(choice).toBeFocused()
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
      const screenshot = async (label: string, scroller: Locator = body) => {
        await settled(page)
        const path = join(output, `${variant.key}-${label}.png`)
        await page.screenshot({ path, fullPage: false, animations: 'disabled', caret: 'hide', scale: 'css' })
        const record = { path, sha256: sha256(readFileSync(path)), label,
          ...await scroller.evaluate((element) => ({ top: element.scrollTop, height: element.scrollHeight, client: element.clientHeight })) }
        screenshots.push(record)
        await info.attach(label, { path, contentType: 'image/png' })
        console.log(`UI C screenshot: ${path}`)
        return record
      }
      const destination = async (name: string): Promise<void> => {
        if (name === 'Advanced settings') {
          await destination('General')
          await page.getByRole('button', { name, exact: true }).click()
        } else {
          const selected = nav.getByRole('button', { name, exact: true })
          await selected.click()
          await expect(selected).toHaveAttribute('aria-current', 'page')
        }
        await expect(page.locator('#settings-section-title')).toHaveText(name)
        await expect(body.locator('[role="status"]', { hasText: /^Loading / })).toHaveCount(0)
        await settled(page)
      }
      const fullScroll = async (label: string, scroller: Locator = body) => {
        const frames: Awaited<ReturnType<typeof screenshot>>[] = []
        await scroller.evaluate((element) => { element.scrollTop = 0 })
        for (let index = 0; index < 40; index++) {
          const frame = await screenshot(`${label}-scroll-${String(index + 1).padStart(2, '0')}`, scroller)
          frames.push(frame)
          if (frame.top + frame.client >= frame.height - 1) return frames
          const target = Math.min(frame.height - frame.client, frame.top + Math.floor(frame.client * 0.8))
          await scroller.evaluate((element, top) => { element.scrollTop = top }, target)
          await expect.poll(() => scroller.evaluate((element) => element.scrollTop)).toBeCloseTo(target, 0)
        }
        throw new Error(`Scroll capture exceeded bounded 40 frames: ${label}`)
      }
      const pages = outcome.pages as unknown[]
      for (const name of [...PRIMARY_NAV, 'Advanced settings']) {
        await destination(name)
        if (name === 'Models and providers') {
          await expect(page.locator('.accounts .account')).toHaveCount(2)
          await expect(page.getByRole('combobox', { name: 'Model', exact: true })).toContainText('Capture main model')
          await expect(page.getByRole('combobox', { name: 'Reasoning effort', exact: true })).toBeEnabled()
        }
        if (name === 'Advanced settings') {
          const categories = await body.locator('.settings-section-header > h3').allTextContents()
          expect(categories).toEqual(plan.advancedCategories)
          outcome.advancedCategories = categories
        }
        if (name === 'Work') {
          await expect(page.getByRole('region', { name: 'Outgoing webhooks', exact: true })).toContainText('Capture event target')
        }
        const label = name === 'Models and providers' ? 'models' : name.toLowerCase().replace(/[^a-z0-9]+/g, '-')
        const frames = await fullScroll(label)
        if (name !== 'Models and providers') {
          const disclosures = body.locator('details > summary').filter({ hasText: 'More options' })
          for (const disclosure of await disclosures.all()) await disclosure.click()
          if (await disclosures.count()) {
            frames.push(...await fullScroll(`${label}-more-options`))
            for (const disclosure of await disclosures.all()) await disclosure.click()
          }
        }
        pages.push({ name, frames })
        checks.push({ name: `full-scroll-${name}`, outcome: 'passed', bounds: await bounds(page) })
      }

      await destination('Models and providers')
      const modelsMore = body.locator('details.settings-more-options')
      await modelsMore.locator('summary').click()
      await expect(modelsMore).toHaveAttribute('open', '')
      await fullScroll('models-more-options')
      await modelsMore.locator('summary').click()
      for (const provider of ['codex', 'ollama', 'compat']) {
        const configure = page.getByTestId(`configure-${provider}`)
        await configure.click()
        await expect(configure).toHaveAttribute('aria-expanded', 'true')
        await fullScroll(`provider-${provider}-configure`)
        await configure.click()
      }

      await destination('MCP servers')
      const more = page.getByRole('button', { name: 'More actions for LMMS', exact: true })
      const menu = page.getByRole('menu', { name: 'More actions for LMMS', exact: true })
      await more.focus()
      await more.press('ArrowDown')
      await expect(menu).toBeVisible()
      await expect(menu.getByRole('menuitem', { name: 'Reconnect LMMS', exact: true })).toBeFocused()
      await page.keyboard.press('End')
      await expect(menu.getByRole('menuitem', { name: 'Remove LMMS…', exact: true })).toBeFocused()
      await page.keyboard.press('Home')
      await expect(menu.getByRole('menuitem', { name: 'Reconnect LMMS', exact: true })).toBeFocused()
      await page.keyboard.press('Escape')
      await expect(menu).not.toBeVisible()
      await expect(more).toBeFocused()
      await more.press('ArrowUp')
      await expect(menu.getByRole('menuitem', { name: 'Remove LMMS…', exact: true })).toBeFocused()
      await page.keyboard.press('Tab')
      await expect(menu).not.toBeVisible()
      await expect(more).not.toBeFocused()
      await more.click()
      await body.getByRole('heading', { name: 'MCP servers', exact: true }).click()
      await expect(menu).not.toBeVisible()
      await expect(more).toHaveAttribute('aria-expanded', 'false')
      checks.push({ name: 'mcp-more-keyboard-navigation-escape-tab-outside', outcome: 'passed' })
      await page.getByRole('button', { name: 'Add server', exact: true }).click()
      const add = page.getByRole('dialog', { name: 'Add MCP server', exact: true })
      await expect(add).toBeVisible()
      await expect(add.locator('.settings-card')).toHaveCount(0)
      await expect(add.locator('.settings-form-actions button')).toHaveText(['Cancel', 'Add server'])
      await add.locator('details > summary').click()
      await fullScroll('mcp-add', add)
      await add.getByRole('button', { name: 'Cancel MCP server changes', exact: true }).click()
      await expect(add).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Add server', exact: true })).toBeFocused()
      await page.getByRole('button', { name: 'Edit LMMS', exact: true }).click()
      const edit = page.getByRole('dialog', { name: 'Edit MCP server LMMS', exact: true })
      await expect(edit).toBeVisible()
      await edit.locator('details > summary').click()
      await fullScroll('mcp-edit', edit)
      await edit.getByRole('button', { name: 'Cancel MCP server changes', exact: true }).click()
      await expect(edit).toHaveCount(0)

      await destination('Work')
      await page.getByRole('button', { name: 'Add outbound webhook', exact: true }).click()
      const outboundAdd = page.getByRole('dialog', { name: 'Add outbound target', exact: true })
      await expect(outboundAdd).toBeVisible()
      await fullScroll('outbound-add', outboundAdd)
      await outboundAdd.getByRole('button', { name: 'Cancel outbound edit', exact: true }).click()
      await expect(outboundAdd).toHaveCount(0)
      await page.getByRole('button', { name: 'Edit outbound webhook Capture event target', exact: true }).click()
      const outboundEdit = page.getByRole('dialog', { name: 'Edit outbound target', exact: true })
      await expect(outboundEdit).toBeVisible()
      await fullScroll('outbound-edit', outboundEdit)
      await outboundEdit.getByRole('button', { name: 'Cancel outbound edit', exact: true }).click()
      await expect(outboundEdit).toHaveCount(0)

      await destination('Data and privacy')
      const dataNav = page.getByRole('navigation', { name: 'Data and privacy subsections', exact: true })
      for (const [name, label] of [['Memory and knowledge', 'data-memory'], ['Conversations', 'data-conversations'], ['Usage, logs and audit', 'data-records']] as const) {
        const tab = dataNav.getByRole('button', { name, exact: true })
        await tab.click()
        await expect(tab).toHaveAttribute('aria-current', 'page')
        await expect(tab).toHaveAttribute('aria-pressed', 'true')
        await fullScroll(label)
      }

      await destination('Advanced settings')
      const search = page.getByRole('searchbox', { name: 'Search Advanced settings', exact: true })
      await search.fill('Command shell')
      await expect(body.getByRole('heading', { level: 3 })).toHaveText(['Tool execution'])
      await body.evaluate((element) => { element.scrollTop = 0 })
      await screenshot('advanced-search')
      await search.fill('zzzz-no-matching-setting')
      await expect(body.getByRole('status')).toContainText('No matching Advanced settings. Clear the search to browse all categories.')
      await screenshot('advanced-no-results')
      await search.fill('Attachment retention')
      const retention = page.getByLabel('Attachment retention', { exact: true })
      await retention.fill('48')
      await retention.press('Enter')
      const restart = page.getByRole('complementary', { name: 'Changes requiring restart', exact: true })
      await expect(restart).toContainText('Some changes need Odin to restart. Exit Odin, then open it again.')
      await expect(restart.getByRole('button', { name: 'Attachment retention', exact: true })).toBeVisible()
      await body.evaluate((element) => { element.scrollTop = 0 })
      await screenshot('pending-restart')
      await restart.getByRole('button', { name: 'Attachment retention', exact: true }).click()
      await expect(search).toHaveValue('')
      await expect(retention).toBeFocused()
      checks.push({ name: 'pending-restart-field-and-Advanced-search-clearing-link', outcome: 'passed', field: 'attachments.retention_hours' })

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
      console.log(`UI C receipt: ${path} (${outcome.outcome})`)
    }
  })
}
