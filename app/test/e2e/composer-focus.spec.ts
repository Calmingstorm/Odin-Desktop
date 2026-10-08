import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { assertIsolated, exitApp, launchApp, repository, waitForCore } from './harness'

async function appearance(page: Page) {
  return page.locator('.composer-box').evaluate((box) => {
    const field = box.querySelector('textarea')!
    const css = getComputedStyle(field), frame = getComputedStyle(box)
    return { outline: css.outlineStyle, shadow: css.boxShadow, border: frame.borderTopColor,
      width: frame.borderTopWidth, focused: box.matches(':focus-within') }
  })
}

test('composer focus belongs to the outer frame, including steer and queue', async () => {
  assertIsolated()
  const output = process.env.ODIN_APP_E2E_OUT!
  const app = await launchApp({ profile: 'composer-focus', realCore: false,
    env: { ODIN_DESKTOP_CORE_CMD: JSON.stringify([join(repository, '.venv/bin/python'), '-B', '-P', join(repository, 'app/fixture-core/fixture_core.py')]) } })
  const screenshots: { label: string; path: string; sha256: string }[] = []
  const measurements: unknown[] = []
  let passed = false
  try {
    await waitForCore(app)
    const page = await app.firstWindow()
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.setContentSize(1180, 780))
    await page.getByRole('button', { name: 'New conversation', exact: true }).click()
    const field = page.getByRole('textbox', { name: 'Message', exact: true })
    const attach = page.getByRole('button', { name: 'Attach files', exact: true })
    const capture = async (label: string) => {
      await page.evaluate(async () => { await document.fonts.ready; await new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))) })
      expect(await page.evaluate(() => [innerWidth, innerHeight])).toEqual([1180, 780])
      const path = join(output, `1180x780-composer-${label}.png`)
      await page.screenshot({ path, animations: 'disabled', caret: 'hide' })
      screenshots.push({ label, path, sha256: createHash('sha256').update(readFileSync(path)).digest('hex') })
    }
    for (const theme of ['dark', 'light'] as const) {
      await page.emulateMedia({ colorScheme: theme, reducedMotion: 'reduce' })
      await attach.focus()
      // Tab is real keyboard navigation into the field; no injected CSS or DOM.
      await page.keyboard.press('Tab')
      await expect(field).toBeFocused()
      const focused = await appearance(page)
      expect(focused.outline).toBe('none')
      expect(focused.shadow).toBe('none')
      expect(focused.focused).toBe(true)
      if (theme === 'dark') await capture('focused')
      await page.getByRole('button', { name: 'New conversation', exact: true }).focus()
      const idle = await appearance(page)
      expect(idle.focused).toBe(false)
      expect(focused.border).not.toBe(idle.border)
      expect(focused.width).toBe(idle.width)
      if (theme === 'dark') await capture('idle')
      await attach.focus()
      expect(await attach.evaluate((node) => getComputedStyle(node).outlineStyle)).toBe('solid')
      measurements.push({ theme, focused, idle })
    }
    await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
    await field.fill('slow focus regression')
    await field.press('Enter')
    await expect(page.getByRole('button', { name: 'Stop the current task', exact: true })).toBeVisible()
    for (const mode of ['steer', 'queue'] as const) {
      await page.locator(`input[name="composer-mode"][value="${mode}"]`).check()
      await field.fill(mode === 'steer' ? 'Keep checking the hardware.' : 'Check the second host next.')
      const focused = await appearance(page)
      expect(focused.outline).toBe('none')
      expect(focused.shadow).toBe('none')
      expect(focused.focused).toBe(true)
      await expect(page.locator('.composer-send')).toHaveText(mode === 'steer' ? 'Steer' : 'Queue')
      measurements.push({ mode, focused })
      await capture(mode === 'steer' ? 'steering' : 'queue')
    }
    await page.getByRole('button', { name: 'Stop the current task', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Stop the current task', exact: true })).toBeHidden()
    passed = true
  } finally {
    await exitApp(app)
    writeFileSync(join(output, 'composer-focus-receipt.json'), JSON.stringify({ outcome: passed ? 'passed' : 'failed',
      measurements, screenshots, limitation: 'Source-built Electron with synthetic core in private PID/HOME/Xvfb/D-Bus isolation; not installed/native-platform qualification.' }, null, 2) + '\n')
  }
})
