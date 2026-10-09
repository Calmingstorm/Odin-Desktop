import { createHash } from 'node:crypto'
import { readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { join, resolve, sep } from 'node:path'
import { expect, test, type ElectronApplication, type Page } from '@playwright/test'
import { assertIsolated, exitApp, launchApp, repository, request, waitForCore } from './harness'

if (process.env.ODIN_APP_UI_102 !== '1' || !process.env.ODIN_APP_UI_PLAN) throw new Error('Use test/ui-1.0.2-capture.mjs after parent declares tree stable')
const plan = JSON.parse(readFileSync(process.env.ODIN_APP_UI_PLAN, 'utf8')) as { epoch: string; command: string[] }
const hash = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex')
async function settled(page: Page) {
  await page.evaluate(async () => { await document.fonts.ready; await new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))) })
}
async function fixture<T>(app: ElectronApplication, action: string, params: Record<string, unknown> = {}): Promise<T> {
  const result = await request(app, 'ui_102.fixture', { action, ...params })
  expect(result.ok, JSON.stringify(result)).toBe(true)
  return result.result as T
}
type Binding = { conversation_id: string; request_id: string; title: string }

test('UI 1.0.2 actual fixture-core pixels, effects dismissal, clocks and document-never-scroll matrix', async () => {
  assertIsolated()
  expect(process.env.DISPLAY).not.toBe(':0')
  const output = resolve(process.env.ODIN_APP_E2E_OUT!)
  expect(output === repository || output.startsWith(repository + sep)).toBe(false)
  const receipt = { outcome: 'running', scope: 'Actual Electron Chromium browser layout and source renderer, synthetic private fixture backend. No mocked bridge.',
    provenance: { uid: process.getuid?.(), pidNamespace: readlinkSync('/proc/self/ns/pid'), display: process.env.DISPLAY, home: process.env.HOME },
    fixture: { path: plan.command.at(-1), sha256: hash(readFileSync(plan.command.at(-1)!)), realCore: false },
    screenshots: [] as { label: string; path: string; sha256: string; width: number; height: number }[],
    overflow: [] as unknown[], alignment: [] as unknown[], checks: [] as unknown[], error: '' }
  let app: ElectronApplication | undefined
  try {
    app = await launchApp({ profile: 'ui-102', realCore: false, env: { ODIN_DESKTOP_CORE_CMD: JSON.stringify(plan.command) } })
    await waitForCore(app)
    const page = await app.firstWindow()
    const cdp = await page.context().newCDPSession(page)
    await cdp.send('Emulation.setTimezoneOverride', { timezoneId: 'America/New_York' })
    await page.clock.setFixedTime(new Date(plan.epoch))
    await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
    const size = async (width: number, height: number) => {
      await app!.evaluate(({ BrowserWindow }, bounds) => BrowserWindow.getAllWindows()[0]!.setContentSize(bounds.width, bounds.height), { width, height })
      await expect.poll(() => page.evaluate(() => [innerWidth, innerHeight])).toEqual([width, height])
      await settled(page)
    }
    const screenshot = async (label: string) => {
      await settled(page)
      const dimensions = await page.evaluate(() => ({ width: innerWidth, height: innerHeight }))
      const path = join(output, `${dimensions.width}x${dimensions.height}-${label}.png`)
      await page.screenshot({ path, animations: 'disabled', fullPage: false, caret: 'hide', scale: 'css' })
      receipt.screenshots.push({ label, path, sha256: hash(readFileSync(path)), ...dimensions })
      console.log(`UI 1.0.2 screenshot: ${path}`)
    }
    // Real browser metrics and attempted scrolling, not a CSS-text or fake-DOM test.
    const neverScroll = async (label: string) => {
      await settled(page)
      const measurement = await page.evaluate(() => {
        window.scrollTo(99999, 99999)
        const roots = [document.documentElement, document.body, document.getElementById('app')!].map((node) => {
          const rect = node.getBoundingClientRect(), css = getComputedStyle(node)
          return { tag: node.id || node.tagName, width: rect.width, height: rect.height, scrollHeight: node.scrollHeight, clientHeight: node.clientHeight, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth, overflowX: css.overflowX, overflowY: css.overflowY }
        })
        const scroller = document.querySelector('.message-scroll')
        const shell = document.querySelector('.shell')!.getBoundingClientRect()
        const main = document.querySelector('main')!
        const mainBounds = main.getBoundingClientRect()
        const status = document.querySelector('.statusbar')!.getBoundingClientRect()
        const composer = main.querySelector('.composer')
        let composerReachable: { top: number; bottom: number; mainTop: number; mainBottom: number } | null = null
        if (composer) {
          const top = main.scrollTop
          main.scrollTop = main.scrollHeight
          const rect = composer.getBoundingClientRect()
          composerReachable = { top: rect.top, bottom: rect.bottom, mainTop: mainBounds.top, mainBottom: mainBounds.bottom }
          main.scrollTop = top
        }
        return { width: innerWidth, height: innerHeight, x: scrollX, y: scrollY, roots, shell: { bottom: shell.bottom, right: shell.right },
          main: { clientHeight: main.clientHeight, scrollHeight: main.scrollHeight, top: mainBounds.top, bottom: mainBounds.bottom, overflow: getComputedStyle(main).overflowY },
          status: { top: status.top, bottom: status.bottom }, composerReachable, historyOverscroll: scroller ? getComputedStyle(scroller).overscrollBehaviorY : null,
          overflowCandidates: [...document.querySelectorAll('*')].map((node) => { const rect = node.getBoundingClientRect(); const css = getComputedStyle(node); return { tag: node.tagName, class: node.className, top: rect.top + scrollY, bottom: rect.bottom + scrollY, position: css.position, overflow: css.overflowY } }).filter((row) => row.bottom > innerHeight + 1).slice(0, 60) }
      })
      receipt.overflow.push({ label, ...measurement })
      expect(measurement.x, label).toBe(0)
      expect(measurement.y, label).toBe(0)
      for (const root of measurement.roots) {
        expect(root.overflowY, `${label} ${root.tag}`).toBe('hidden')
        expect(root.scrollHeight, `${label} ${root.tag} vertical extent`).toBeLessThanOrEqual(root.clientHeight + 1)
        expect(root.scrollWidth, `${label} ${root.tag} horizontal extent`).toBeLessThanOrEqual(root.clientWidth + 1)
      }
      expect(measurement.shell.bottom).toBeLessThanOrEqual(measurement.height + 1)
      expect(measurement.shell.right).toBeLessThanOrEqual(measurement.width + 1)
      expect(measurement.status.bottom, `${label} status visible`).toBeLessThanOrEqual(measurement.height + 1)
      expect(measurement.main.clientHeight, `${label} nonzero main`).toBeGreaterThan(0)
      if (measurement.composerReachable) {
        expect(measurement.composerReachable.bottom, `${label} composer bottom locally reachable`).toBeLessThanOrEqual(measurement.composerReachable.mainBottom + 1)
        expect(measurement.composerReachable.top, `${label} composer top locally reachable`).toBeGreaterThanOrEqual(measurement.composerReachable.mainTop - 1)
      }
      if (measurement.historyOverscroll !== null) expect(measurement.historyOverscroll).toBe('contain')
    }
    const matrix = async (label: string, capture = false) => {
      for (const [width, height] of [[1180, 780], [720, 480], [1920, 1080]]) {
        await size(width!, height!)
        await neverScroll(label)
        if (await page.locator('.msg.assistant .body').count() && await page.locator('.msg.notice .body').count()) {
          await alignment(`${label}-${width}x${height}`, ['.msg.assistant .body', '.msg.notice .body'])
        }
        if (capture && width !== 1920) await screenshot(label)
      }
      await size(1180, 780)
    }
    const seed = async (mode: string): Promise<Binding> => {
      const result = await fixture<Binding>(app!, 'seed', { mode })
      await page.getByRole('navigation', { name: 'Conversations', exact: true }).getByRole('button', { name: new RegExp(`^${result.title}(,|$)`) }).click()
      await expect(page.locator('.topbar h1')).toHaveText(result.title)
      await settled(page)
      return result
    }
    const alignment = async (label: string, selectors: string[]) => {
      const rows = await page.evaluate((selectors) => selectors.map((selector) => {
        const node = document.querySelector(selector)!
        const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT)
        let text: Node | null = walker.nextNode()
        while (text && !text.textContent?.trim()) text = walker.nextNode()
        if (!text) throw new Error(`No text for ${selector}`)
        const range = document.createRange(); range.selectNodeContents(text)
        const box = node.getBoundingClientRect(), rect = range.getBoundingClientRect()
        return { selector, x: rect.x, right: box.right, width: box.width, text: node.textContent?.trim() }
      }), selectors)
      receipt.alignment.push({ label, rows })
      for (const row of rows.slice(1)) expect(Math.abs(row.x - rows[0]!.x), `${label}: ${row.selector}`).toBeLessThanOrEqual(1)
      if (selectors.includes('.msg.notice .body')) {
        const notice = rows.find((row) => row.selector === '.msg.notice .body')!
        expect(Math.abs(notice.width - rows[0]!.width), `${label}: shared body width`).toBeLessThanOrEqual(1)
        expect(Math.abs(notice.right - rows[0]!.right), `${label}: shared right edge`).toBeLessThanOrEqual(1)
      }
    }
    await size(1180, 780)
    await seed('empty')
    await expect(page.getByTestId('first-run-banner')).toBeVisible()
    await matrix('empty-chat', true)
    await seed('cancelled-no-reply')
    await expect(page.locator('.outcome').first()).toHaveText('The task was stopped.')
    await expect(page.locator('.control-receipts')).toHaveCount(0)
    await alignment('notice-outcome', ['.msg.assistant .body', '.msg.notice .body', '.outcome'])
    await matrix('notice-and-stopped-outcome', true)
    await seed('cancelled-reply')
    await expect(page.getByText('Task stopped by user. No further steps ran.', { exact: true })).toBeVisible()
    await expect(page.locator('.outcome')).toHaveCount(0)
    await expect(page.locator('.control-receipts')).toHaveCount(0)
    await screenshot('stopped-assistant-reply-no-duplicate')
    receipt.checks.push({ name: 'U2-U3-ended-controls-hidden-stopped-reply-not-duplicated', outcome: 'passed' })
    const stopping = await seed('stopping')
    await fixture(app, 'tool', stopping)
    await expect(page.locator('.tool-row')).toContainText('run_command')
    expect((await page.locator('.tool-row').innerText()).match(/run_command/g)).toHaveLength(1)
    await page.getByRole('button', { name: 'Stop the current task', exact: true }).click()
    await expect(page.locator('.working-line')).toContainText('Stopping… waiting for run_command to finish (1:10)')
    await expect(page.locator('.composer-stop')).toContainText('Stopping… waiting for run_command to finish (1:10)')
    await expect(page.locator('.control-receipts')).toBeVisible()
    await alignment('notice-steer-stop-receipts', ['.msg.assistant .body', '.msg.notice .body', '.steers .steer-text', '.control-receipts .steer-text'])
    await matrix('stopping-tool-and-receipts', true)
    await fixture(app, 'queue', stopping)
    await expect(page.locator('.working-line')).toContainText('1 follow-up queued')
    await matrix('stopping-with-queue-and-banner', true)
    await page.clock.setFixedTime(new Date(Date.parse(plan.epoch) + 1000))
    await expect(page.locator('.working-line')).toContainText('(1:11)')
    await expect(page.locator('.composer-stop')).toContainText('(1:11)')
    receipt.checks.push({ name: 'U4-event-start-clock-ticks-U6-name-deduplicated', outcome: 'passed' })
    await page.getByRole('textbox', { name: 'Message', exact: true }).fill(Array.from({ length: 15 }, (_, i) => `Long composer line ${i}: continued fixture text.`).join('\n'))
    await matrix('stopping-expanded-composer', true)
    await page.getByRole('textbox', { name: 'Message', exact: true }).fill('')
    await seed('stopping-plain')
    await page.getByRole('button', { name: 'Stop the current task', exact: true }).click()
    await expect(page.locator('.composer-stop')).toHaveText('Stopping…')
    await matrix('stopping-without-tool')
    await seed('unresolved')
    await expect(page.locator('.status')).toContainText('1 action with an unknown outcome')
    await expect(page.locator('.unresolved')).toContainText('It will not be repeated.')
    await alignment('unknown-outcome', ['.msg.assistant .body', '.unresolved'])
    await matrix('unknown-outcome-before-dismiss', true)
    await page.locator('.unresolved').getByRole('button', { name: 'Dismiss', exact: true }).click()
    await expect(page.locator('.unresolved')).toHaveCount(0)
    await expect(page.locator('.status')).not.toContainText('unknown outcome')
    const acks = await fixture<{ calls: Record<string, unknown>[] }>(app, 'acknowledgements')
    expect(acks.calls).toHaveLength(1)
    expect(acks.calls[0]!.control_command_id).toEqual(expect.any(String))
    receipt.checks.push({ name: 'U5-real-preload-IPC-effects-acknowledge-synthetic-event-dismiss-and-status', outcome: 'passed', calls: acks.calls })
    await screenshot('unknown-outcome-after-dismiss')
    await seed('history')
    await matrix('long-history', true)
    const history = page.locator('.message-scroll')
    await history.evaluate((node) => { node.scrollTop = node.scrollHeight })
    await history.hover(); await page.mouse.wheel(0, 3000); await neverScroll('history-wheel-bottom-boundary')
    await history.evaluate((node) => { node.scrollTop = 0 })
    await page.mouse.wheel(0, -3000); await neverScroll('history-wheel-top-boundary')
    await page.keyboard.press('Control+Shift+f')
    await expect(page.locator('#conversation-search')).toBeVisible()
    await matrix('search-banner', true)
    await page.keyboard.press('Control+Shift+f')
    await seed('work')
    await page.getByRole('button', { name: /^Work(?:,|$)/ }).click()
    await expect(page.locator('.work-column')).toBeVisible()
    await page.getByRole('button', { name: 'Refresh work', exact: true }).click()
    await expect(page.locator('.work-column')).toContainText('Inspect disks')
    await expect(page.locator('.work-column')).toContainText('Today')
    const cards = await page.locator('.work-column article').allTextContents()
    expect(cards.length).toBeGreaterThanOrEqual(3)
    expect(cards.join('\n')).not.toMatch(/hidden-|Revision|Not reported|2026-10-08T|resource_release|fixture_finished/)
    const endedSchedule = page.locator('.work-column article').filter({ hasText: 'Finished report' })
    await expect(endedSchedule).toContainText('Done')
    await expect(endedSchedule).toContainText('Last run')
    await expect(endedSchedule).not.toContainText('Next run')
    const chatCard = await page.locator('.work-column article').filter({ hasText: 'Inspect disks' }).innerText()
    receipt.checks.push({ name: 'U7-local-short-work-times-no-manager-internals', outcome: 'passed', cards, localTimezone: await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone) })
    await matrix('work-panel-local-times', true)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(page.getByRole('navigation', { name: 'Settings sections' })).toBeVisible()
    await matrix('settings-main', true)
    await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: 'Work', exact: true }).click()
    const settingsCard = page.getByRole('region', { name: 'Running work', exact: true }).locator('article').filter({ hasText: 'Inspect disks' })
    await expect(settingsCard).toBeVisible()
    expect(await settingsCard.innerText()).toBe(chatCard)
    await expect(settingsCard).not.toContainText('Settlement')
    receipt.checks.push({ name: 'R2-R3-shared-settings-chat-card-identical-ended-schedule-no-next-run', outcome: 'passed', chatCard, settingsCard: await settingsCard.innerText() })
    await settingsCard.scrollIntoViewIfNeeded()
    await screenshot('settings-work-shared-compact-card')
    await neverScroll('settings-work-shared-compact-card')
    await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: 'General', exact: true }).click()
    await page.getByRole('group', { name: 'Theme', exact: true }).getByRole('button', { name: 'Light', exact: true }).click()
    await screenshot('settings-light')
    await neverScroll('settings-light')
    await page.getByRole('button', { name: /Back to chat/ }).click()
    await screenshot('work-panel-local-times-light')
    await neverScroll('work-panel-light')
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.webContents.setZoomFactor(2))
    await settled(page)
    await neverScroll('work-panel-200-percent-zoom')
    await screenshot('work-panel-200-percent-zoom')
    receipt.outcome = 'passed'
  } catch (error) { receipt.outcome = 'failed'; receipt.error = String((error as Error).stack || error); throw error }
  finally {
    writeFileSync(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n')
    if (app) await exitApp(app).catch(() => app!.close())
  }
})
