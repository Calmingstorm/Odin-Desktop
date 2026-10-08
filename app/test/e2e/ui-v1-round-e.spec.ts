import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { join, resolve, sep } from 'node:path'
import { expect, test, type ElectronApplication, type Locator, type Page } from '@playwright/test'
import { assertIsolated, exitApp, launchApp, repository, request, snapshot, waitForCore } from './harness'

if (process.env.ODIN_APP_ROUND_E !== '1' || !process.env.ODIN_APP_ROUND_E_PLAN) throw new Error('Use scripts/ui-v1-round-e.mjs with stable-tree authorization')
const plan = JSON.parse(readFileSync(process.env.ODIN_APP_ROUND_E_PLAN, 'utf8')) as { epoch: string; command: string[]; requiredScreenshots: string[] }
type State = { calls: Record<string, unknown>[]; pending_reads: number; values: Record<string, unknown> }
const hash = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex')
async function settled(page: Page) {
  await page.evaluate(async () => { await document.fonts.ready; await new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))) })
}
async function measure(scroll: Locator) {
  return scroll.evaluate((node) => ({ top: node.scrollTop, height: node.scrollHeight, client: node.clientHeight, gap: node.scrollHeight - node.clientHeight - node.scrollTop }))
}
async function control<T>(app: ElectronApplication, action: string, params: Record<string, unknown> = {}): Promise<T> {
  const result = await request(app, 'round_e.fixture', { action, ...params })
  expect(result.ok, JSON.stringify(result)).toBe(true)
  return result.result as T
}
async function state(app: ElectronApplication): Promise<State> { return control(app, 'status') }
async function destination(page: Page, name: string) {
  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name, exact: true }).click()
  await expect(page.locator('#settings-section-title')).toHaveText(name)
  await settled(page)
}
async function theme(page: Page, name: 'Dark' | 'Light') {
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await destination(page, 'General')
  const button = page.getByRole('group', { name: 'Theme', exact: true }).getByRole('button', { name, exact: true })
  await button.click()
  await expect(button).toHaveAttribute('aria-pressed', 'true')
  await page.emulateMedia({ colorScheme: null, reducedMotion: 'reduce' })
  await expect.poll(() => page.evaluate(() => matchMedia('(prefers-color-scheme: dark)').matches)).toBe(name === 'Dark')
  await page.getByRole('button', { name: /Back to chat/ }).click()
}
async function options(select: Locator) {
  return select.locator('option').evaluateAll((nodes) => nodes.map((node) => ({ value: (node as HTMLOptionElement).value, text: node.textContent?.trim(), disabled: (node as HTMLOptionElement).disabled })))
}

test('Round E focused screenshots and actual keyboard/image behavior', async ({}, info) => {
  test.setTimeout(240_000)
  assertIsolated()
  expect(process.env.DISPLAY).not.toBe(':0')
  const output = resolve(process.env.ODIN_APP_E2E_OUT!)
  expect(output === repository || output.startsWith(repository + sep)).toBe(false)
  const receipt: Record<string, unknown> = { outcome: 'running', viewport: { width: 1180, height: 780 }, screenshots: [], checks: [],
    fixture: { path: plan.command.at(-1), sha256: hash(readFileSync(plan.command.at(-1)!)), realCore: false },
    provenance: { uid: process.getuid?.(), pidNamespace: readlinkSync('/proc/self/ns/pid'), display: process.env.DISPLAY, home: process.env.HOME },
    limitations: ['Synthetic backend, no provider or quota qualification.', 'Real app restart with synthetic persisted pair, not real-provider boot adoption.', 'Native popup captured from private Xvfb, never a recreated DOM menu.'] }
  const checks = receipt.checks as unknown[], screenshots = receipt.screenshots as { label: string; path: string; sha256: string }[]
  let app: ElectronApplication | undefined
  try {
    const boot = async () => {
      const application = await launchApp({ profile: 'round-e', realCore: false, env: { ODIN_DESKTOP_CORE_CMD: JSON.stringify(plan.command) } })
      await waitForCore(application)
      const page = await application.firstWindow()
      await page.clock.setFixedTime(new Date(plan.epoch))
      await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: null })
      await application.evaluate(({ BrowserWindow }) => { const window = BrowserWindow.getAllWindows()[0]!; window.setContentSize(1180, 780); window.setPosition(100, 80) })
      await expect.poll(() => page.evaluate(() => [innerWidth, innerHeight])).toEqual([1180, 780])
      return { application, page }
    }
    let current = await boot()
    app = current.application
    let page = current.page
    const screenshot = async (label: string, nativePopup = false) => {
      await settled(page)
      const path = join(output, `1180x780-${label}.png`)
      if (nativePopup) {
        assertIsolated()
        expect(process.env.DISPLAY).not.toBe(':0')
        const box = await app!.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.getContentBounds())
        execFileSync('import', ['-window', 'root', '-crop', `${box.width}x${box.height}+${box.x}+${box.y}`, '+repage', path], { timeout: 10_000 })
      } else await page.screenshot({ path, fullPage: false, animations: 'disabled', caret: 'hide', scale: 'css' })
      screenshots.push({ label, path, sha256: hash(readFileSync(path)) })
      await info.attach(label, { path, contentType: 'image/png' })
      console.log(`Round E screenshot: ${path}`)
    }
    await page.getByRole('button', { name: 'New conversation', exact: true }).click()
    await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeVisible()
    await theme(page, 'Dark')
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await destination(page, 'Models and providers')
    const picker = page.getByRole('combobox', { name: 'Model', exact: true })
    const choices = await options(picker)
    expect(choices).toEqual([{ value: 'gpt-6.1-sol', text: 'gpt-6.1-sol', disabled: false }, { value: 'gpt-6-luna', text: 'gpt-6-luna', disabled: false }])
    await picker.focus()
    await page.keyboard.press('Alt+ArrowDown')
    await screenshot('main-model-picker-open', true)
    await page.keyboard.press('Escape')
    checks.push({ name: 'enabled-only-main-picker-single-labels', outcome: 'passed', options: choices })
    await destination(page, 'Data and privacy')
    await page.getByRole('button', { name: 'Memory and knowledge', exact: true }).click()
    const knowledge = page.getByRole('region', { name: 'Knowledge', exact: true }), details = page.getByRole('region', { name: 'Knowledge details', exact: true })
    const geometry = await details.locator('.settings-row').evaluateAll((rows) => rows.map((row) => { const css = getComputedStyle(row); return { text: row.textContent?.trim().slice(0, 100), paddingLeft: parseFloat(css.paddingLeft), paddingRight: parseFloat(css.paddingRight) } }))
    expect(geometry.length).toBeGreaterThanOrEqual(8)
    for (const row of geometry) { expect(row.paddingLeft).toBeGreaterThanOrEqual(14); expect(row.paddingRight).toBeGreaterThanOrEqual(14) }
    await expect(page.locator('#knowledge-chunk-source')).toHaveAccessibleName('Chunk source')
    await expect(page.getByLabel('Load a text file', { exact: true })).toHaveAttribute('type', 'file')
    await knowledge.getByRole('heading', { name: 'Add a document', exact: true }).evaluate((node) => node.scrollIntoView({ block: 'start' }))
    await screenshot('knowledge-add-document')
    await details.evaluate((node) => node.scrollIntoView({ block: 'start' }))
    await screenshot('knowledge-details')
    await details.locator('#knowledge-diff-to').scrollIntoViewIfNeeded()
    await screenshot('knowledge-details-bottom')
    checks.push({ name: 'knowledge-shared-padding-file-control', outcome: 'passed', geometry })
    await page.getByRole('button', { name: /Back to chat/ }).click()
    const trigger = page.getByRole('button', { name: /^Change main model and reasoning effort/ }), dialog = page.getByRole('dialog', { name: 'Main model and reasoning effort', exact: true })
    await trigger.focus()
    await page.keyboard.press('Enter')
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('#header-model')).toBeFocused()
    expect(await options(dialog.locator('#header-model'))).toEqual(choices)
    await screenshot('header-switcher-open')
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(trigger).toBeFocused()
    await trigger.press('Space')
    await expect(dialog).toBeVisible()
    await page.getByRole('textbox', { name: 'Message', exact: true }).click()
    await expect(dialog).toBeHidden()
    expect((await state(app)).calls).toHaveLength(0)
    checks.push({ name: 'keyboard-open-Escape-outside-close-no-write', outcome: 'passed' })
    await trigger.click()
    await dialog.locator('#header-model').focus()
    await page.keyboard.press('ArrowDown')
    await expect(dialog.locator('#header-model')).toHaveValue('gpt-6-luna')
    const effortOptions = await options(dialog.locator('#header-effort'))
    expect(effortOptions.filter((item) => !item.disabled).map((item) => item.value)).toEqual(['low', 'medium'])
    expect(effortOptions.find((item) => item.value === 'high')?.disabled).toBe(true)
    await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
    await dialog.locator('#header-effort').selectOption('medium')
    await dialog.getByRole('button', { name: 'Save', exact: true }).focus()
    await page.keyboard.press('Enter')
    await expect(dialog).toBeHidden()
    const saved = await state(app)
    expect(saved.calls).toHaveLength(1)
    expect(saved.calls[0]).toMatchObject({ model: 'gpt-6-luna', reasoning_effort: 'medium' })
    expect(typeof saved.calls[0]!.expected_revision).toBe('string')
    expect(saved.values['llm_provider.model']).toBe('gpt-6-luna')
    expect(saved.values['openai_codex.reasoning_effort']).toBe('medium')
    checks.push({ name: 'valid-efforts-one-atomic-model-pair-write', outcome: 'passed', call: saved.calls[0] })
    await control(app, 'fail_next_save')
    await trigger.click()
    await dialog.locator('#header-effort').selectOption('low')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toContainText('Round E fixture save rejected. No values changed.')
    await screenshot('header-switcher-inline-error')
    expect((await state(app)).values['openai_codex.reasoning_effort']).toBe('medium')
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    checks.push({ name: 'inline-save-error-preserves-pair-Cancel-closes', outcome: 'passed' })
    const beforeRestart = await snapshot(app)
    await exitApp(app)
    app = undefined
    current = await boot()
    app = current.application
    page = current.page
    const afterRestart = await snapshot(app)
    expect(afterRestart.pid).not.toBe(beforeRestart.pid)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await destination(page, 'Models and providers')
    await expect(page.getByRole('combobox', { name: 'Model', exact: true })).toHaveValue('gpt-6-luna')
    await expect(page.getByRole('combobox', { name: 'Reasoning effort', exact: true })).toHaveValue('medium')
    await expect(page.getByText('The running value is not known.', { exact: true })).toHaveCount(0)
    await screenshot('models-after-restart')
    checks.push({ name: 'Electron-restart-synthetic-pair-no-warning', outcome: 'passed', beforePid: beforeRestart.pid, afterPid: afterRestart.pid, realProviderBoot: false })
    await page.getByRole('button', { name: /Back to chat/ }).click()
    await page.getByRole('button', { name: 'New conversation', exact: true }).click()
    const listed = await request(app, 'conversations.list')
    expect(listed.ok).toBe(true)
    const cid = (listed.result as { items: { id: string }[] }).items.at(-1)!.id
    await control(app, 'seed_history', { conversation_id: cid })
    const scroll = page.locator('.message-scroll')
    await expect(page.locator('#m-e-history-13')).toBeAttached()
    await scroll.focus()
    await page.keyboard.press('Control+End')
    await expect.poll(async () => (await measure(scroll)).gap).toBeLessThanOrEqual(3)
    await control(app, 'late_image', { conversation_id: cid, key: 'pinned' })
    await expect(page.locator('#m-e-delivery-pinned .image-loading')).toBeVisible()
    await expect.poll(async () => (await state(app!)).pending_reads).toBe(1)
    await expect.poll(async () => (await measure(scroll)).gap).toBeLessThanOrEqual(3)
    await settled(page)
    const beforePinned = await measure(scroll)
    checks.push({ name: 'before-pinned-image-release', measured: beforePinned })
    await control(app, 'release_image')
    await expect.poll(() => page.locator('#m-e-delivery-pinned .artifact-image img').evaluate((node) => (node as HTMLImageElement).complete && (node as HTMLImageElement).naturalWidth === 900)).toBe(true)
    checks.push({ name: 'decoded-pinned-image', measured: await measure(scroll) })
    await screenshot('image-decoded-before-pin-assertion')
    await expect.poll(async () => (await measure(scroll)).gap).toBeLessThanOrEqual(3)
    const afterPinned = await measure(scroll)
    expect(afterPinned.height).toBeGreaterThan(beforePinned.height + 100)
    await expect(page.locator('#m-e-reply-pinned')).toBeInViewport()
    await expect(page.locator('#m-e-delivery-pinned')).toHaveClass(/assistant/)
    await expect(page.locator('#m-e-delivery-pinned .who')).toHaveText('Odin')
    await screenshot('image-late-bottom-pinned')
    checks.push({ name: 'late-decode-growth-pins-bottom-and-reply', outcome: 'passed', before: beforePinned, after: afterPinned })
    await control(app, 'late_image', { conversation_id: cid, key: 'up' })
    await expect.poll(async () => (await state(app!)).pending_reads).toBe(1)
    await expect.poll(async () => (await measure(scroll)).gap).toBeLessThanOrEqual(3)
    await scroll.hover()
    await page.mouse.wheel(0, -520)
    await expect.poll(async () => (await measure(scroll)).gap).toBeGreaterThan(200)
    await settled(page)
    const beforeUp = await measure(scroll)
    await control(app, 'release_image')
    await expect.poll(() => page.locator('#m-e-delivery-up .artifact-image img').evaluate((node) => (node as HTMLImageElement).complete && (node as HTMLImageElement).naturalWidth === 900)).toBe(true)
    await settled(page)
    const afterUp = await measure(scroll)
    expect(afterUp.height).toBeGreaterThan(beforeUp.height + 100)
    expect(Math.abs(afterUp.top - beforeUp.top)).toBeLessThanOrEqual(3)
    expect(afterUp.gap).toBeGreaterThan(200)
    await screenshot('image-late-user-scrolled-up')
    checks.push({ name: 'wheel-up-before-release-preserves-scroll', outcome: 'passed', before: beforeUp, after: afterUp })
    await control(app, 'genuine_notice', { conversation_id: cid })
    await expect(page.locator('#m-e-system-notice')).toHaveClass(/notice/)
    await expect(page.locator('#m-e-system-notice .who')).toHaveText('Notice')
    await scroll.focus()
    await page.keyboard.press('Control+End')
    await expect.poll(async () => (await measure(scroll)).gap).toBeLessThanOrEqual(3)
    for (const selector of ['.msg.assistant > .avatar img.app-icon', '.rail-mark img.app-icon']) {
      const icons = page.locator(selector)
      expect(await icons.count()).toBeGreaterThan(0)
      const metrics = await icons.evaluateAll((nodes) => nodes.map((node) => { const image = node as HTMLImageElement, rect = image.getBoundingClientRect(); return { complete: image.complete, naturalWidth: image.naturalWidth, width: rect.width, height: rect.height, source: image.src } }))
      for (const metric of metrics) { expect(metric.complete).toBe(true); expect(metric.naturalWidth).toBeGreaterThan(0); expect(metric.width).toBeGreaterThanOrEqual(14) }
      checks.push({ name: `small-app-icon ${selector}`, outcome: 'passed', metrics })
    }
    await screenshot('avatar-and-rail-dark')
    await theme(page, 'Light')
    await screenshot('avatar-and-rail-light')
    for (const label of plan.requiredScreenshots) expect(screenshots.some((image) => image.label === label), label).toBe(true)
    receipt.outcome = 'passed'
  } catch (error) { receipt.outcome = 'failed'; receipt.error = String(error instanceof Error ? error.stack : error); throw error }
  finally {
    if (app) await exitApp(app).catch((error) => { receipt.cleanupError = String(error); receipt.outcome = 'failed' })
    writeFileSync(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n', { mode: 0o600 })
  }
})
