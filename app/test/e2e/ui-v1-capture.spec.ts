import { mkdirSync, readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join, resolve, sep } from 'node:path'
import { expect, test, type ElectronApplication, type Locator, type Page } from '@playwright/test'
import { exitApp, launchApp, repository, snapshot, waitForCore } from './harness'
import { buttonPattern, comparableButtonPattern } from '../helpers/ui-button-pattern'

type Variant = { key: string; width: number; height: number; theme: 'dark' | 'light' }
type BoundsVariant = { key: string; width: number; height: number; zoom: number }
if (process.env.ODIN_APP_UI_CAPTURE !== '1' || !process.env.ODIN_APP_UI_PLAN) {
  throw new Error('Use scripts/ui-v1-capture.mjs to supply an isolated capture plan')
}
const plan = JSON.parse(readFileSync(process.env.ODIN_APP_UI_PLAN, 'utf8')) as {
  epoch: string; navigation: string[]; variants: Variant[]; bounds: BoundsVariant[]; command: string[]
  requiredStates: string[]; advancedCategories: string[]; longAccountLabel: string
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
      documentHeight: document.documentElement.clientHeight, documentScrollHeight: document.documentElement.scrollHeight,
      documentScrollWidth: document.documentElement.scrollWidth, shell: rect(shell), settings: rect(settings),
      nav: rect(nav), body: rect(body), bodyClientWidth: body.clientWidth, bodyScrollWidth: body.scrollWidth,
      navClientWidth: nav.clientWidth, navScrollWidth: nav.scrollWidth, outOfBounds }
  })
  expect(measured.documentScrollWidth, 'Document must not scroll horizontally').toBeLessThanOrEqual(measured.documentWidth + 1)
  expect(measured.documentScrollHeight, 'Settings scroll inside their body, never the outer document').toBeLessThanOrEqual(measured.documentHeight + 1)
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

// Every top-level card is compared numerically to BOTH stable reference pages.
// Nested panels are not page cards. Their style metrics are retained separately.
async function geometry(page: Page) {
  return page.locator('.settings-content').evaluate((content) => {
    const box = (node: Element) => {
      const rect = node.getBoundingClientRect()
      return { left: rect.left, right: rect.right, width: rect.width }
    }
    const style = (node: Element) => {
      const css = getComputedStyle(node)
      return { fontSize: css.fontSize, lineHeight: css.lineHeight, color: css.color, background: css.backgroundColor,
        borderRadius: css.borderRadius, paddingLeft: css.paddingLeft, paddingRight: css.paddingRight,
        fontFamily: css.fontFamily, fontWeight: css.fontWeight,
        display: css.display, gridTemplateColumns: css.gridTemplateColumns,
        columnGap: css.columnGap, rowGap: css.rowGap, justifyContent: css.justifyContent }
    }
    const visible = (node: Element) => node.getClientRects().length > 0
    const cards = [...content.querySelectorAll('.settings-card, .panel, .settings-group')]
      .filter(visible).filter((node) => !node.parentElement?.closest('.settings-card, .panel, .settings-group'))
      .map((node) => ({ ...box(node), style: style(node), className: node.className }))
    const metrics = (selector: string) => [...content.querySelectorAll(selector)].filter(visible)
      .map((node) => ({ text: node.textContent?.trim().slice(0, 120), className: node.className,
        context: node.closest('.settings-segmented') ? 'segmented' : node.closest('.menu') ? 'menu'
          : node.closest('.settings-form-actions') ? 'form-actions' : node.closest('.settings-editor-actions') ? 'editor-actions'
            : node.closest('.settings-row-control') ? 'row-control' : '',
        ...box(node), style: style(node) }))
    const bodyStyle = getComputedStyle(content.closest('.settings-body')!)
    return { content: box(content), cards,
      layout: { viewport: innerWidth, document: document.documentElement.clientWidth,
        documentHeight: document.documentElement.scrollHeight,
        absoluteControls: [...content.querySelectorAll<HTMLElement>('.sr-only')].map((node) => ({ text: node.textContent,
          top: node.getBoundingClientRect().top, bottom: node.getBoundingClientRect().bottom, offsetParent: node.offsetParent?.className })),
        body: box(content.closest('.settings-body')!), bodyClient: content.closest('.settings-body')!.clientWidth,
        bodyOverflowY: bodyStyle.overflowY, bodyPaddingLeft: bodyStyle.paddingLeft, bodyPaddingRight: bodyStyle.paddingRight,
        bodyScroll: content.closest('.settings-body')!.scrollHeight, bodyHeight: content.closest('.settings-body')!.clientHeight },
      gutter: bodyStyle.scrollbarGutter, innerPadding: getComputedStyle(content).getPropertyValue('--settings-padding').trim(),
      padding: metrics('.settings-row, .settings-card > .manage-list > .manage-row, .panel'),
      help: metrics('.settings-help, .settings-row-copy p, .panel-hint'),
      buttons: metrics('button'), rows: metrics('.settings-row'),
      overflow: content.scrollWidth > content.clientWidth + 1 }
  })
}

async function dialogContainment(page: Page, dialog: Locator): Promise<void> {
  const controls = dialog.locator('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary')
  await controls.last().focus()
  await page.keyboard.press('Tab')
  expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true)
  await controls.first().focus()
  await page.keyboard.press('Shift+Tab')
  expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true)
}

test.beforeEach(() => {
  if (process.env.ODIN_APP_UI_CAPTURE !== '1') throw new Error('Use scripts/ui-v1-capture.mjs; this suite is not a platform qualification')
})

for (const variant of CAPTURE_VARIANTS as Variant[]) {
  test(`UI D ${variant.key}: complete settings and chat evidence matrix`, async ({}, info) => {
    test.setTimeout(300_000)
    const output = externalOutput(process.env.ODIN_APP_E2E_OUT)
    mkdirSync(output, { recursive: true, mode: 0o700 })
    const fixture = join(repository, 'app/fixture-core/fixture_core.py')
    const python = process.env.ODIN_DESKTOP_ENGINE_PYTHON!
    const command = plan.command
    expect(command[0]).toBe(python)
    expect(command.at(-1)).toBe(fixture)
    const outcome: Record<string, unknown> = {
      variant, outcome: 'running', screenshots: [], checks: [], pages: [], geometry: [],
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
      application = await launchApp({ profile: `ui-d-${variant.key}`, realCore: false,
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
      const draft = 'UI D retained draft. Never sent.'
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
      const screenshot = async (label: string, scroller: Locator = body, prefix = variant.key) => {
        await settled(page)
        const path = join(output, `${prefix}-${label}.png`)
        await page.screenshot({ path, fullPage: false, animations: 'disabled', caret: 'hide', scale: 'css' })
        const record = { path, sha256: sha256(readFileSync(path)), label,
          ...await scroller.evaluate((element) => ({ top: element.scrollTop, height: element.scrollHeight, client: element.clientHeight })) }
        screenshots.push(record)
        await info.attach(label, { path, contentType: 'image/png' })
        console.log(`UI D screenshot: ${path}`)
        return record
      }
      const destination = async (name: string): Promise<void> => {
        if (name === 'Advanced settings') {
          await destination('General')
          await page.getByRole('button', { name, exact: true }).click()
        } else {
          const selected = nav.getByRole('button', { name, exact: true })
          await selected.focus()
          await selected.press('Space')
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
      const references: { name: string; measured: Awaited<ReturnType<typeof geometry>> }[] = []
      for (const name of [...PRIMARY_NAV, 'Advanced settings']) {
        await destination(name)
        if (name === 'Models and providers') {
          await expect(page.locator('.accounts .account')).toHaveCount(2)
          await expect(page.getByRole('combobox', { name: 'Model', exact: true })).toContainText('Capture main model')
          await expect(page.getByRole('combobox', { name: 'Reasoning effort', exact: true })).toBeEnabled()
          await expect(page.getByRole('combobox', { name: 'Agent reasoning effort', exact: true })).toHaveValue('auto')
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
        const measured = await geometry(page)
        console.log(`UI D geometry ${variant.key} ${name}: ${JSON.stringify({ content: measured.content, layout: measured.layout })}`)
        // Preserve the failing page's actual metrics before assertions, not just
        // earlier successful pages. Native controls are visible issues to review,
        // never automatically declared equivalent to the shared design patterns.
        const record = { name, outcome: 'measured', references: references.map((reference) => reference.name), measured,
          buttonPatterns: measured.buttons.map((button) => ({ text: button.text, pattern: buttonPattern(button.className, button.context),
            sharedComparison: comparableButtonPattern(buttonPattern(button.className, button.context)) })) }
        ;(outcome.geometry as unknown[]).push(record)
        const nativeButtons = measured.buttons.filter((button) => buttonPattern(button.className, button.context) === 'native-unclassed')
        if (nativeButtons.length) {
          outcome.visibleReviewCandidates ??= []
          ;(outcome.visibleReviewCandidates as unknown[]).push({ name, kind: 'native-unclassed-buttons',
            issue: 'Native button appearance is not evidence of uniform shared-button styling; inspect final screenshots for C1.',
            buttons: nativeButtons.map((button) => ({ text: button.text, context: button.context, style: button.style })) })
        }
        if (name === 'General' || name === 'Models and providers') references.push({ name, measured })
        expect(measured.overflow, `${name}: no content overflow`).toBe(false)
        expect(measured.cards.length, `${name}: rendered page cards`).toBeGreaterThan(0)
        for (const reference of references) {
          for (const card of measured.cards) {
            for (const axis of ['left', 'right', 'width'] as const) {
              expect(Math.abs(card[axis] - reference.measured.content[axis]), `${name} ${card.className} ${axis} vs ${reference.name}`).toBeLessThanOrEqual(1)
            }
          }
        }
        const referenceRows = references[0]!.measured.rows
        for (const row of measured.rows) {
          expect(row.style.paddingLeft, `${name} shared row left padding`).toBe(referenceRows[0]!.style.paddingLeft)
          expect(row.style.paddingRight, `${name} shared row right padding`).toBe(referenceRows[0]!.style.paddingRight)
          for (const property of ['display', 'gridTemplateColumns', 'columnGap', 'rowGap'] as const) {
            expect(row.style[property], `${name} shared row ${property}`).toBe(referenceRows[0]!.style[property])
          }
        }
        const referenceHelp = references.flatMap((reference) => reference.measured.help)
        for (const help of measured.help) {
          const reference = referenceHelp.find((item) => item.className === help.className)
          if (reference) for (const property of ['fontSize', 'lineHeight', 'color'] as const) {
            expect(help.style[property], `${name} ${help.className} help ${property}`).toBe(reference.style[property])
          }
        }
        const referenceButtons = references.flatMap((reference) => reference.measured.buttons)
        for (const button of measured.buttons) {
          const pattern = buttonPattern(button.className, button.context)
          const reference = comparableButtonPattern(pattern) && referenceButtons.find((item) => buttonPattern(item.className, item.context) === pattern)
          if (reference) for (const property of ['fontFamily', 'fontSize', 'borderRadius', 'paddingLeft', 'paddingRight'] as const) {
            expect(button.style[property], `${name} ${button.className} button ${property}`).toBe(reference.style[property])
          }
        }
        record.outcome = 'passed'
        record.references = references.map((reference) => reference.name)
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
      for (const record of outcome.geometry as { name: string; references: string[]; measured: Awaited<ReturnType<typeof geometry>> }[]) {
        for (const reference of references) for (const card of record.measured.cards) {
          for (const axis of ['left', 'right', 'width'] as const) {
            expect(Math.abs(card[axis] - reference.measured.content[axis]), `${record.name} ${axis} vs ${reference.name}`).toBeLessThanOrEqual(1)
          }
        }
        for (const item of record.measured.padding) {
          expect(Number.parseFloat(item.style.paddingLeft), `${record.name} shared padding left`).toBe(18)
          expect(Number.parseFloat(item.style.paddingRight), `${record.name} shared padding right`).toBe(18)
        }
        expect(record.measured.gutter, `${record.name} stable scrollbar gutter`).toBe('stable')
        expect(record.measured.innerPadding, `${record.name} shared inner padding token`).toBe('18px')
        for (const reference of references) {
          for (const help of record.measured.help) {
            const baseline = reference.measured.help.find((item) => item.className === help.className)
            if (baseline) for (const property of ['fontSize', 'lineHeight', 'color'] as const) {
              expect(help.style[property], `${record.name} help ${property} vs ${reference.name}`).toBe(baseline.style[property])
            }
          }
          for (const button of record.measured.buttons) {
            const pattern = buttonPattern(button.className, button.context)
            const baseline = comparableButtonPattern(pattern) && reference.measured.buttons.find((item) => buttonPattern(item.className, item.context) === pattern)
            if (baseline) for (const property of ['fontFamily', 'fontSize', 'borderRadius', 'paddingLeft', 'paddingRight'] as const) {
              expect(button.style[property], `${record.name} button ${property} vs ${reference.name}`).toBe(baseline.style[property])
            }
          }
        }
        record.references = references.map((reference) => reference.name)
      }
      checks.push({ name: 'keyboard-every-settings-destination-and-numeric-General-Models-card-parity', outcome: 'passed' })

      await destination('Models and providers')
      const effort = page.getByRole('combobox', { name: 'Reasoning effort', exact: true })
      await effort.selectOption('high')
      const dirtyActions = page.getByTestId('main-model-actions')
      await expect(dirtyActions).toContainText('Unsaved changes')
      await expect(dirtyActions.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
      await dirtyActions.scrollIntoViewIfNeeded()
      const actionPlacement = await dirtyActions.evaluate((node) => {
        const card = node.closest('.settings-card')!.getBoundingClientRect()
        const action = node.getBoundingClientRect()
        const save = node.querySelector('button')!.getBoundingClientRect()
        return { cardBottom: card.bottom, actionBottom: action.bottom, cardRight: card.right,
          actionRight: action.right, saveLeft: save.left, actionLeft: action.left,
          justifyContent: getComputedStyle(node).justifyContent }
      })
      expect(actionPlacement.justifyContent).toBe('flex-end')
      expect(actionPlacement.cardBottom - actionPlacement.actionBottom).toBeLessThanOrEqual(25)
      expect(actionPlacement.cardRight - actionPlacement.actionRight).toBeLessThanOrEqual(25)
      expect(actionPlacement.saveLeft).toBeGreaterThan(actionPlacement.actionLeft)
      await screenshot('models-dirty-save')
      await dirtyActions.getByRole('button', { name: 'Cancel', exact: true }).click()
      await expect(effort).toHaveValue('medium')
      await expect(dirtyActions).toHaveCount(0)
      checks.push({ name: 'model-dirty-bottom-actions-and-cancel-no-save', outcome: 'passed', actionPlacement })
      await page.getByRole('button', { name: 'Rename Secondary', exact: true }).click()
      const rename = page.getByRole('dialog', { name: 'Label this account', exact: true })
      await expect(rename).toBeVisible()
      const labelField = rename.getByRole('textbox', { name: 'Label', exact: true })
      const maximum = Number(await labelField.getAttribute('maxlength'))
      expect(plan.longAccountLabel.length).toBeLessThanOrEqual(maximum)
      await labelField.fill(plan.longAccountLabel)
      await expect(labelField).toHaveValue(plan.longAccountLabel)
      await rename.getByRole('button', { name: 'Save', exact: true }).click()
      await expect(rename).toHaveCount(0)
      await expect(page.locator('.accounts')).toContainText(plan.longAccountLabel)
      await page.locator('.accounts').scrollIntoViewIfNeeded()
      await screenshot('models-long-names')
      checks.push({ name: 'long-account-name-no-overflow', outcome: 'passed', bounds: await bounds(page) })
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
      await dialogContainment(page, add)
      await add.locator('details > summary').click()
      await fullScroll('mcp-add', add)
      await add.getByLabel('Timeout, in seconds', { exact: true }).fill('0')
      await add.getByRole('button', { name: 'Add server (MCP)', exact: true }).click()
      await expect(add.getByRole('alert')).toBeVisible()
      await screenshot('mcp-validation-error', add)
      await add.getByRole('button', { name: 'Cancel MCP server changes', exact: true }).click()
      await expect(add).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Add server', exact: true })).toBeFocused()
      await page.getByRole('button', { name: 'Edit LMMS', exact: true }).click()
      const edit = page.getByRole('dialog', { name: 'Edit MCP server LMMS', exact: true })
      await expect(edit).toBeVisible()
      await dialogContainment(page, edit)
      await edit.locator('details > summary').click()
      await fullScroll('mcp-edit', edit)
      await edit.getByRole('button', { name: 'Cancel MCP server changes', exact: true }).click()
      await expect(edit).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Edit LMMS', exact: true })).toBeFocused()
      checks.push({ name: 'mcp-dialog-tab-containment-and-trigger-focus-return', outcome: 'passed' })

      await destination('Work')
      await page.getByRole('button', { name: 'Add outbound webhook', exact: true }).click()
      const outboundAdd = page.getByRole('dialog', { name: 'Add outbound target', exact: true })
      await expect(outboundAdd).toBeVisible()
      await dialogContainment(page, outboundAdd)
      await fullScroll('outbound-add', outboundAdd)
      await outboundAdd.getByRole('button', { name: 'Cancel outbound edit', exact: true }).click()
      await expect(outboundAdd).toHaveCount(0)
      await page.getByRole('button', { name: 'Edit outbound webhook Capture event target', exact: true }).click()
      const outboundEdit = page.getByRole('dialog', { name: 'Edit outbound target', exact: true })
      await expect(outboundEdit).toBeVisible()
      await dialogContainment(page, outboundEdit)
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
        if (variant.key === CAPTURE_VARIANTS[0]!.key) {
          await body.evaluate((element) => { element.scrollTop = 0 })
          await screenshot(check.key, body, 'bounds')
        }
        checks.push({ name: check.key, outcome: 'passed', screenshots: variant.key === CAPTURE_VARIANTS[0]!.key, upper, lower })
      }
      await size(application, page, variant.width, variant.height)
      const back = page.getByRole('button', { name: /Back to chat/, exact: false })
      await back.focus()
      await back.press('Space')
      await expect(composer).toHaveValue(draft)
      await composer.fill('')
      await expect(page.locator('.msg')).toHaveCount(0)
      await screenshot('chat-empty', page.locator('.message-scroll'))
      await composer.fill('Captured fixture conversation. No provider or external tools are contacted.\n\n```text\nsynthetic capture output\n```')
      await composer.press('Enter')
      await expect(page.locator('.msg.assistant')).toContainText('Echo:')
      await expect(page.locator('.msg.user')).toHaveCount(1)
      await screenshot('chat-populated', page.locator('.message-scroll'))
      await composer.fill(draft)
      await page.keyboard.press('Control+,')
      await expect(body).toBeVisible()
      await back.focus()
      await back.press('Space')
      await expect(composer).toHaveValue(draft)
      await expect(composer).toBeFocused()
      checks.push({ name: 'keyboard-back-draft-and-composer-focus-return', outcome: 'passed' })
      checks.push({ name: 'reduced-motion-preference', outcome: 'passed',
        measured: await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches) })
      expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true)
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
      console.log(`UI D receipt: ${path} (${outcome.outcome})`)
    }
  })
}
