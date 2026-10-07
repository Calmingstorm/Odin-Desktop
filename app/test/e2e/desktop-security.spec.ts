import { join } from 'node:path'
import { test, expect } from '@playwright/test'
import { exitApp, launchApp, repository, waitForCore } from './harness'

const { probe } = require(join(repository, 'scripts/qualification/desktop-probe.cjs')) as {
  probe: (app: unknown, page: unknown) => Promise<{ renderer: { names: string[] }; content: { execution: number } }>
}

test('production renderer enforcement on actual Electron, no unsafe fixture dispatch', async () => {
  const app = await launchApp()
  try {
    await waitForCore(app)
    const page = await app.firstWindow()
    const result = await probe(app, page)
    expect(result.renderer.names).toContain('reportPage')
    expect(result.content.execution).toBe(0)
  } finally { await exitApp(app) }
})

test('real DOM long replies, tables, inert Markdown, images and report paging', async () => {
  // Controlled fixture transport for content regressions only, never native
  // candidate/provider qualification. Uses production components and preload.
  const app = await launchApp({ realCore: false, profile: 'p36-content' })
  try {
    await waitForCore(app)
    const page = await app.firstWindow()
    await page.getByRole('button', { name: 'New conversation', exact: true }).click()
    const message = page.getByRole('textbox', { name: 'Message', exact: true })
    await message.fill('long image report\n\n| Column | Value |\n| --- | --- |\n| safe | data |\n\n<script>window.__p36Markdown = 1</script>')
    await message.press('Enter')
    const reply = page.locator('.msg.assistant')
    await expect(reply).toContainText('log line 5000')
    await expect(reply.locator('table')).toContainText('safe')
    expect(await page.evaluate(() => (window as unknown as { __p36Markdown?: number }).__p36Markdown)).toBeUndefined()
    await expect(reply.locator('img')).toBeVisible()
    expect(await reply.locator('img').evaluate(el => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
    const report = reply.locator('.report')
    await expect(report).toContainText('Page 1')
    await report.getByRole('button', { name: 'Next page of Health report', exact: true }).click()
    await expect(report).toContainText('Page 2')
    await report.getByRole('button', { name: 'Previous page of Health report', exact: true }).click()
    await expect(report).toContainText('Page 1')
  } finally { await exitApp(app) }
})
