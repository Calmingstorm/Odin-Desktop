// Development-only driver: actual BrowserWindow/preload/Vue over the real
// framed transport. Determinism belongs only to the external test adapter.
import { strict as assert } from 'node:assert'
import { readFileSync, writeFileSync } from 'node:fs'
import type { BrowserWindow } from 'electron'
import type { Broker } from './broker'

const pause = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))
const forbidden = ['E2E-OAUTH-ACCESS-NEVER-RENDER', 'E2E-OAUTH-REFRESH-NEVER-RENDER', 'E2E-DEVICE-SECRET-NEVER-RENDER', 'E2E-WRITE-ONLY-NEVER-RENDER']
type FirstRun = { state: string; reason: string; keyring_unavailable: boolean }
type Meta = { revision: string; fields: Array<{ path: string; desired: unknown; effective: unknown }> }

export async function onboardingSmoke(win: BrowserWindow, broker: Broker, out: string): Promise<void> {
  const scenario = process.env.ODIN_SMOKE_ONBOARDING!
  const controlFile = process.env.ODIN_SMOKE_CONTROL!
  const states: string[] = []
  const checks: string[] = []
  const run = async <T = unknown>(script: string): Promise<T> => {
    try { return await win.webContents.executeJavaScript(script, true) as T }
    catch { throw new Error(`Onboarding renderer operation failed: ${script.replace(/E2E-[A-Z-]+NEVER-RENDER/g, '[synthetic-secret-redacted]')}`) }
  }
  const text = (selector: string): Promise<string> => run(`document.querySelector(${JSON.stringify(selector)})?.innerText ?? ''`)
  const count = (selector: string): Promise<number> => run(`document.querySelectorAll(${JSON.stringify(selector)}).length`)
  const until = async (predicate: () => Promise<boolean>, label: string, ms = 12_000): Promise<void> => {
    const end = Date.now() + ms
    while (!await predicate()) {
      assert(Date.now() < end, `onboarding ${scenario}: timed out at ${label}`)
      await pause(60)
    }
  }
  const request = async <T>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
    const result = await broker.request(method, params)
    assert(result.ok, `${method} must succeed (${result.ok ? '' : result.error.code})`)
    return result.result as T
  }
  const click = async (selector: string): Promise<void> => {
    assert.equal(await count(selector), 1, `exactly one ${selector} control`)
    await run(`document.querySelector(${JSON.stringify(selector)}).click()`)
    await pause(100)
  }
  const button = async (scope: string, label: string): Promise<void> => {
    await run(`(() => {
      const buttons = Array.from(document.querySelectorAll(${JSON.stringify(scope + ' button')})).filter(b => b.innerText.trim() === ${JSON.stringify(label)});
      if (buttons.length !== 1 || buttons[0].disabled) throw new Error('Expected one enabled button: ' + ${JSON.stringify(label)});
      buttons[0].click();
    })()`)
    await pause(100)
  }
  const control = (change: Record<string, unknown>): void => {
    const previous = JSON.parse(readFileSync(controlFile, 'utf8')) as Record<string, unknown>
    writeFileSync(controlFile, JSON.stringify({ ...previous, ...change }), { mode: 0o600 })
  }
  // Use the renderer's collision-free ID contract without importing renderer modules into main.
  const fieldId = (path: string): string => `[id=${JSON.stringify(`settings-${path === 'logging.level' ? 'curated' : 'field'}-${encodeURIComponent(path)}`)}]`
  const fieldText = (path: string): Promise<string> => run(`document.querySelector(${JSON.stringify(fieldId(path))})?.closest('.field, .setting-editor')?.innerText ?? ''`)
  const edit = async (path: string, value: string | boolean): Promise<void> => {
    const id = fieldId(path)
    assert.equal(await count(id), 1, `${path} single existing settings field`)
    await run(`(() => {
      const input = document.querySelector(${JSON.stringify(id)});
      if (input.type === 'checkbox') { input.checked = ${JSON.stringify(value)}; input.dispatchEvent(new Event('change', { bubbles: true })); }
      else if (input.tagName === 'SELECT') { input.value = ${JSON.stringify(value)}; input.dispatchEvent(new Event('change', { bubbles: true })); }
      else { input.value = ${JSON.stringify(value)}; input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); }
    })()`)
  }
  const schema = (): Promise<Meta> => request('settings.schema')
  const savedValue = async (path: string): Promise<unknown> => (await schema()).fields.find((field) => field.path === path)?.desired
  const section = async (label: string): Promise<void> => {
    await button('.settings-nav', label)
    await until(async () => await text('.settings-body h2') === label, `section ${label}`)
  }
  const openSettings = async (): Promise<void> => {
    if (!await count('.settings')) await click('button[title="Settings (Ctrl+,)"]')
    await until(async () => (await count('.settings-nav-item')) > 2, 'real settings')
  }
  const observeState = async (expected: string): Promise<FirstRun> => {
    let observed: FirstRun | undefined
    await until(async () => {
      observed = (await request<{ first_run: FirstRun }>('status.get')).first_run
      return observed.state === expected
    }, `authoritative ${expected}`)
    // Readiness is owned by chat, not Settings. Re-enter the previous settings
    // destination after checking the actual banner, without changing core state.
    const settingsOpen = await count('.settings') === 1
    if (settingsOpen) await click('.settings-nav .back')
    await until(async () => await run(`Boolean(document.querySelector('.first-run-banner[data-state=${JSON.stringify(expected)}]'))`), `rendered ${expected}`)
    if (settingsOpen) await openSettings()
    if (!states.includes(expected)) states.push(expected)
    return observed!
  }
  const noSecrets = async (): Promise<void> => {
    const renderer = await run<string>(`JSON.stringify({html:document.documentElement.outerHTML, values:Array.from(document.querySelectorAll('input,textarea'), e=>e.value), local:{...localStorage}, session:{...sessionStorage}})`)
    const projections = await run<string>(`(async () => JSON.stringify([await window.odin.settingsSchema(), await window.odin.codexAccounts()]))()`)
    for (const secret of forbidden) {
      assert(!renderer.includes(secret), 'secret absent rendered HTML, fields and browser storage')
      assert(!projections.includes(secret), 'secret absent preload readback')
    }
    assert.equal(await count('.msg'), 0, 'onboarding never creates a transcript message')
    checks.push('secret-readback-absent')
  }
  const login = async (): Promise<void> => {
    await button('.codex-accounts', 'Add account')
    await until(async () => (await text('.login-code')) === 'TEST-CODE', 'intended verification code')
    await noSecrets()
  }
  const finishLogin = async (): Promise<void> => {
    control({ auth: 'success' })
    await login()
    await until(async () => (await count('.account')) === 1, 'real persisted account')
  }
  const model = async (value: string): Promise<void> => {
    await edit('llm_provider.model', value)
    await until(async () => (await savedValue('llm_provider.model')) === value, 'saved main model')
  }
  const preferences = async (second: boolean): Promise<void> => {
    await section('General')
    await until(async () => (await count('#start-at-login, #notifications-enabled, #notification-previews')) === 3, 'general settings')
    const actual = await run<boolean[]>('Array.from(document.querySelectorAll("#start-at-login, #notifications-enabled, #notification-previews"), e => e.checked)')
    assert.equal(actual[0], second, 'autostart initially off, persisted opt-in only')
    assert.equal(actual[2], !second, 'previews initially on, persisted toggle respected')
    if (!second) {
      await run(`(() => { const input = document.querySelector('#start-at-login'); input.checked=true; input.dispatchEvent(new Event('change',{bubbles:true})); })()`)
      await run(`(() => { const input = document.querySelector('#notification-previews'); input.checked=false; input.dispatchEvent(new Event('change',{bubbles:true})); })()`)
      await until(async () => await run(`(async () => { const r=await window.odin.getSettings(); return r.ok && r.result.autostart && !r.result.notifications.previews; })()`), 'preferences saved')
    }
    checks.push(second ? 'preferences-persisted' : 'defaults-and-opt-in')
  }

  await until(async () => broker.linkState === 'ready' && !win.webContents.isLoading(), 'app/core handshake', 25_000)
  await openSettings()
  if (scenario === 'fresh' || scenario === 'fresh-second') {
    await observeState('fresh')
    await section('General')
    const defaults = await run<boolean[]>('Array.from(document.querySelectorAll("#start-at-login, #notifications-enabled, #notification-previews"), e => e.checked)')
    assert.equal(defaults[0], false)
    assert.equal(defaults[2], true)
    await click('.settings-nav .back')
    await button('.first-run-banner', 'Set up later')
    assert.equal(await count('.settings'), 0, 'setup later leaves chat navigable')
    await openSettings()
    for (let i = 0; i < 3; i++) {
      await section('Models and providers')
      assert.equal(await count('.codex-accounts'), 1, 'no duplicate account form')
      assert.equal(await count(fieldId('llm_provider.model')), 1, 'no duplicate model form')
      await section('General')
    }
    assert.equal((await request<{ first_run: FirstRun }>('status.get')).first_run.state, 'fresh', 'setup later never marks provider complete')
    checks.push('setup-later', 'section-reentry', 'defaults')
  } else if (scenario === 'ready-second') {
    await observeState('effective-ready')
    await preferences(true)
    checks.push('startup-provider-adopted')
  } else if (scenario === 'saved-second') {
    await observeState('saved')
    await preferences(true)
    await section('Models and providers')
    control({ startup_provider_unavailable: false })
    const previous = String(await savedValue('llm_provider.model'))
    await model(previous.endsWith('gpt-5.4') ? 'codex:gpt-5.3-codex' : 'codex:gpt-5.4')
    await observeState('effective-ready')
    checks.push('saved-not-effective')
  } else if (scenario === 'locked' || scenario === 'missing') {
    const degraded = await observeState('degraded')
    assert.equal(degraded.keyring_unavailable, true)
    await click('.settings-nav .back')
    await until(async () => /keyring/i.test(await text('.first-run-banner')), 'visible keyring failure')
    await openSettings()
    await section('Models and providers')
    await edit('openai_compatible.api_key', 'E2E-WRITE-ONLY-NEVER-RENDER')
    await until(async () => await run(`document.querySelector(${JSON.stringify(fieldId('openai_compatible.api_key'))}).value === ''`), 'failed secret clears')
    assert.equal((await request<{ first_run: FirstRun }>('status.get')).first_run.state, 'degraded')
    // A locked collection must be unlocked by the rendered owner Retry, not
    // secretly made healthy by the orchestrator before the click.
    if (scenario === 'missing') control({ keyring: 'healthy' })
    await click('.settings-nav .back')
    await button('.first-run-banner', 'Retry')
    await observeState('fresh')
    const keyringControl = JSON.parse(readFileSync(process.env.ODIN_SMOKE_CONTROL!, 'utf8')) as { unlock_calls?: number }
    assert.equal(keyringControl.unlock_calls ?? 0, scenario === 'locked' ? 1 : 0)
    checks.push('keyring-retry')
    await openSettings()
    await finishLogin()
    await model('codex:gpt-5.4')
    await observeState('effective-ready')
  } else {
    await observeState('fresh')
    await preferences(false)
    await section('Models and providers')
    // A durable partial configuration is incomplete, not wizard-complete.
    await edit('openai_codex.enabled', false)
    await until(async () => await savedValue('openai_codex.enabled') === false, 'partial configuration saved')
    await observeState('incomplete')
    await login()
    await button('.login', 'Stop waiting')
    control({ auth: 'success' })
    await pause(1300)
    assert.equal((await request<{ configured: boolean }>('codex.accounts.list')).configured, false, 'cancelled UI polling never invents authenticated account')
    checks.push('canceled-login')
    control({ auth: 'expired' })
    await login()
    await until(async () => /expired/i.test(await text('.login')), 'expired login')
    checks.push('expired-login')
    await finishLogin()
    await edit('openai_codex.enabled', true)
    await until(async () => await savedValue('openai_codex.enabled') === true, 'provider enabled after login')
    await model('codex:gpt-5.4')
    await observeState('effective-ready')

    await section('General')
    await button('.settings-body', 'Advanced settings')
    await until(async () => await text('.settings-body h2') === 'Advanced settings', 'secondary Advanced settings')
    const current = await schema()
    await request('settings.set', { expected_revision: current.revision, changes: [{ path: 'logging.level', value: 'DEBUG' }] })
    await edit('logging.level', 'WARNING')
    await until(async () => /changed elsewhere|reloaded/i.test(await fieldText('logging.level')), 'revision rejection')
    assert.equal(await savedValue('logging.level'), 'DEBUG')
    await edit('logging.level', 'WARNING')
    await until(async () => await savedValue('logging.level') === 'WARNING', 'revision retry')
    checks.push('revision-retry')
    // Cut the actual socket at submission admission, while the rendered form
    // still exists. Do not fabricate a failed Result or remove the real core.
    const actualRequest = broker.request.bind(broker)
    let cut = false
    broker.request = async (method, params = {}, id) => {
      if (!cut && method === 'settings.set') { cut = true; broker.close() }
      return actualRequest(method, params, id)
    }
    await edit('logging.level', 'ERROR')
    await until(async () => cut && (/connect|receipt|unavailable/i.test(await fieldText('logging.level')) || await count(fieldId('logging.level')) === 0), 'connection rejection')
    broker.request = actualRequest
    broker.connect()
    broker.startEvents()
    await until(async () => broker.linkState === 'ready', 'broker reconnect')
    assert.equal(await savedValue('logging.level'), 'WARNING', 'disconnected save did not commit')
    await until(async () => await count(fieldId('logging.level')) === 1, 'reconnected form')
    await edit('logging.level', 'ERROR')
    await until(async () => await savedValue('logging.level') === 'ERROR', 'connection retry')
    checks.push('connection-retry')
    await section('Models and providers')
    await edit('openai_compatible.api_key', 'E2E-WRITE-ONLY-NEVER-RENDER')
    await until(async () => await run(`document.querySelector(${JSON.stringify(fieldId('openai_compatible.api_key'))}).value === ''`), 'secret clears after submit')
    await until(async () => Boolean(await savedValue('openai_compatible.api_key')), 'write-only credential present')
    checks.push('secret-cleared')
    // Real qualification failure keeps durable settings and serving identity;
    // fixing the external service allows the same rendered control to retry.
    control({ probe_failure: true })
    await edit('openai_compatible.enabled', true)
    await until(async () => (await run<string>(`document.querySelector(${JSON.stringify(fieldId('openai_compatible.enabled'))})?.closest('.field')?.querySelector('.warn')?.innerText ?? ''`)).length > 0, 'qualification save failure')
    assert.equal(await savedValue('openai_compatible.enabled'), false, 'failed save restored durable provider configuration')
    await observeState('effective-ready')
    control({ probe_failure: false })
    await edit('openai_compatible.enabled', true)
    await until(async () => await savedValue('openai_compatible.enabled') === true, 'qualification retry')
    await model('compat:e2e-qualified')
    await observeState('effective-ready')
    checks.push('provider-save-retry')
    control({ guard_degraded: true })
    await model('codex:gpt-5.3-codex')
    assert.equal((await observeState('degraded')).reason, 'provider_health_degraded')
    control({ guard_degraded: false })
    await model('codex:gpt-5.4')
    await observeState('effective-ready')
    checks.push('degraded-health-recovery')
  }
  await noSecrets()
  writeFileSync(out, JSON.stringify({ scenario, passed: true, states, checks }), { mode: 0o600 })
}
