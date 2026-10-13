// Real Electron, real engine, disposable fresh profile: automatic agent candidates save from the Models page through
// the actual preload bridge. Electron refuses a live Vue proxy there, which a unit test's fake bridge can't show.
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { assertIsolated, exitApp, launchApp, repository, waitForCore } from './harness'
import { isolatedServicesBootstrap } from '../isolated-services-bootstrap'

// The isolated runner has no keyring daemon, and the model choices report whether a provider key is stored: the core
// starts with the in-memory keyring double, as the R4 cases do.
function memoryKeyringCore(): Record<string, string> {
  const python = process.env.ODIN_DESKTOP_ENGINE_PYTHON ?? join(repository, '.venv/bin/python')
  const script = join(process.env.ODIN_REAL_CORE_ROOT!, 'agent-candidates-memory-keyring-core.py')
  writeFileSync(script, isolatedServicesBootstrap, { mode: 0o600 })
  return { ODIN_DESKTOP_CORE_CMD: JSON.stringify([python, '-B', script, 'memory', '-', '-', 'stage']) }
}

test('saves automatic agent candidates chosen on the Models page through the real bridge and engine', async () => {
  assertIsolated()
  const application = await launchApp({ profile: 'agent-candidates', env: memoryKeyringCore() })
  try {
    await waitForCore(application)
    const page = await application.firstWindow()
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: 'Models and providers', exact: true }).click()
    await page.getByLabel('Agent model', { exact: true }).selectOption('auto')
    // Odin's default: every model it uses with nothing chosen is ticked, each with Odin's own description.
    // Wait for the model choices: the default's count shows once they are read.
    await expect(page.getByTestId('agent-candidates-state')).toContainText(/Using Odin's default: \d+ models/)
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
    // Untick one, move the last up, give the first its own effort and description, and save: the edited list
    // crosses the bridge, and the engine must accept a candidate's own effort and a model's description.
    await list.locator(`li[data-model="${defaults[1]}"] input[type=checkbox]`).uncheck()
    await page.getByRole('button', { name: `Move ${defaults.at(-1)} up`, exact: true }).click()
    await page.getByLabel(`Reasoning effort for ${defaults[0]}`, { exact: true }).selectOption('high')
    await page.getByRole('button', { name: `Details for ${defaults[0]}`, exact: true }).click()
    await page.getByRole('button', { name: `Edit the description of ${defaults[0]}`, exact: true }).click()
    await page.getByLabel(`Description for ${defaults[0]}`, { exact: true }).fill('Release check description')
    // A picture of the list for review; not an assertion.
    await page.getByTestId('agent-candidates').screenshot({ path: test.info().outputPath('agent-candidates.png') })
    await page.getByTestId('agent-model-actions').getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByText('Saved.', { exact: true })).toBeVisible()
    await expect(page.getByText('could not be confirmed')).toHaveCount(0)
    await expect(page.getByText('changed through')).toHaveCount(0)
    const expected = defaults.filter((model) => model !== defaults[1])
    ;[expected[expected.length - 2], expected[expected.length - 1]] = [expected.at(-1)!, expected.at(-2)!]
    // Read back as the app does: the core's saved settings.
    const schema = await page.evaluate(() => (window as unknown as { odin: { settingsSchema(): Promise<{ ok: boolean; result?: { fields: Array<{ path: string; desired: unknown }> } }> } }).odin.settingsSchema())
    expect(schema.ok).toBe(true)
    const saved = (path: string) => schema.result?.fields.find((field) => field.path === path)?.desired
    expect(saved('agents.model')).toBe('auto')
    const savedList = saved('agents.auto_model_allowlist') as Array<string | { model: string; reasoning_effort?: string }>
    expect(savedList.map((entry) => typeof entry === 'string' ? entry : entry.model)).toEqual(expected)
    expect(savedList[0]).toMatchObject({ model: defaults[0], reasoning_effort: 'high' })
    expect(saved('agents.model_selection_hints')).toEqual({ [defaults[0]!]: 'Release check description' })
  } finally {
    await exitApp(application)
  }
})
