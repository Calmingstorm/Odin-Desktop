// Real Electron, real engine, disposable fresh profile: automatic agent candidates save from the Models page through
// the actual preload bridge. Electron refuses a live Vue proxy there, which a unit test's fake bridge can't show.
import { expect, test } from '@playwright/test'
import { assertIsolated, exitApp, launchApp, request, waitForCore } from './harness'

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
    const status = await request(application, 'models.status')
    const defaults = (status.result as { agent_default_candidates: string[] }).agent_default_candidates
    expect(defaults.length).toBeGreaterThan(1)
    await expect(page.getByTestId('agent-candidates-state')).toContainText("Using Odin's default")
    const list = page.getByRole('list', { name: 'Models Odin can choose from' })
    for (const model of defaults) await expect(list.locator(`li[data-model="${model}"] input[type=checkbox]`)).toBeChecked()
    await expect(page.getByTestId(`candidate-description-${defaults[0]}`)).not.toContainText('Odin has no description')
    // Untick one, move the last up, and save: the edited list crosses the bridge.
    await list.locator(`li[data-model="${defaults[1]}"] input[type=checkbox]`).uncheck()
    await page.getByRole('button', { name: `Move ${defaults.at(-1)} up`, exact: true }).click()
    await page.getByTestId('agent-model-actions').getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByText('Saved.', { exact: true })).toBeVisible()
    await expect(page.getByText('could not be confirmed')).toHaveCount(0)
    const expected = defaults.filter((model) => model !== defaults[1])
    ;[expected[expected.length - 2], expected[expected.length - 1]] = [expected.at(-1)!, expected.at(-2)!]
    const agents = await request(application, 'models.agents.get')
    expect(agents.ok).toBe(true)
    expect(agents.result).toMatchObject({ model: 'auto', auto_model_allowlist: expected })
  } finally {
    await exitApp(application)
  }
})
