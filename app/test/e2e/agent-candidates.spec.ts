// Real Electron, real engine, disposable fresh profile: automatic agent candidates save from the Models page through
// the actual preload bridge. Electron refuses a live Vue proxy there, which a unit test's fake bridge can't show.
import { expect, test } from '@playwright/test'
import { assertIsolated, exitApp, launchApp, waitForCore } from './harness'

test('saves automatic agent candidates chosen on the Models page through the real bridge and engine', async () => {
  assertIsolated()
  const application = await launchApp({ profile: 'agent-candidates' })
  try {
    await waitForCore(application)
    const page = await application.firstWindow()
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: 'Models and providers', exact: true }).click()
    await page.getByLabel('Agent model', { exact: true }).selectOption('auto')
    // Odin's default: every model it uses with nothing chosen is ticked, each with Odin's own description.
    await expect(page.getByTestId('agent-candidates-state')).toContainText("Using Odin's default")
    const list = page.getByRole('list', { name: 'Models Odin can choose from' })
    const defaults = await list.locator('li[data-model]').evaluateAll((items) => items
      .filter((item) => (item.querySelector('input[type=checkbox]') as HTMLInputElement | null)?.checked)
      .map((item) => item.getAttribute('data-model')!))
    expect(defaults.length).toBeGreaterThan(1)
    // The ticked defaults are the engine's own, read through the app's bridge.
    const status = await page.evaluate(() => (window as unknown as { odin: { modelsStatus(params: object): Promise<{ ok: boolean; result?: { agent_default_candidates?: string[] } }> } }).odin.modelsStatus({}))
    expect(status.ok).toBe(true)
    expect(status.result?.agent_default_candidates).toEqual(defaults)
    await expect(page.getByTestId(`candidate-description-${defaults[0]}`)).not.toContainText('Odin has no description')
    // Untick one, move the last up, and save: the edited list crosses the bridge.
    await list.locator(`li[data-model="${defaults[1]}"] input[type=checkbox]`).uncheck()
    await page.getByRole('button', { name: `Move ${defaults.at(-1)} up`, exact: true }).click()
    await page.getByTestId('agent-model-actions').getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByText('Saved.', { exact: true })).toBeVisible()
    await expect(page.getByText('could not be confirmed')).toHaveCount(0)
    const expected = defaults.filter((model) => model !== defaults[1])
    ;[expected[expected.length - 2], expected[expected.length - 1]] = [expected.at(-1)!, expected.at(-2)!]
    // Read back as the app does: the core's saved settings.
    const schema = await page.evaluate(() => (window as unknown as { odin: { settingsSchema(): Promise<{ ok: boolean; result?: { fields: Array<{ path: string; desired: unknown }> } }> } }).odin.settingsSchema())
    expect(schema.ok).toBe(true)
    const saved = (path: string) => schema.result?.fields.find((field) => field.path === path)?.desired
    expect(saved('agents.model')).toBe('auto')
    expect(saved('agents.auto_model_allowlist')).toEqual(expected)
  } finally {
    await exitApp(application)
  }
})
