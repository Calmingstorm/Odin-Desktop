// Development-only assertions, invoked exclusively by the isolated smoke runner.
// Exercise the named preload bridge and rendered app, not a second mock client.
import { strict as assert } from 'node:assert'
import { writeFileSync } from 'node:fs'
import type { BrowserWindow } from 'electron'
import type { Broker } from './broker'

const pause = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

// Reviewed named management surface; never derive expected capabilities from welcome.
export const realCoreCapabilities = ['status.get', 'events.subscribe', 'runtime.shutdown', ...[
  'settings.schema', 'settings.set', 'secrets.set', 'secrets.clear', 'models.image.intent',
  'providers.codex.set', 'providers.auxiliary.set', 'providers.ollama.set', 'providers.compat.set',
  'codex.accounts.list', 'codex.accounts.activate', 'codex.accounts.remove', 'codex.accounts.label', 'codex.login.begin', 'codex.login.poll',
  'hosts.list', 'hosts.settings', 'hosts.prepare', 'hosts.test', 'hosts.commit', 'hosts.set_enabled', 'hosts.references', 'hosts.delete', 'hosts.public_key', 'hosts.force_revoke',
  'memory.list', 'memory.get', 'memory.set', 'memory.delete', 'memory.bulk_delete', 'lists.list', 'lists.get', 'lists.delete',
  'knowledge.list', 'knowledge.search', 'knowledge.ingest', 'knowledge.reingest', 'knowledge.delete', 'knowledge.versions', 'knowledge.restore', 'knowledge.import',
  'audit.query', 'audit.verify', 'health.get', 'logs.search', 'turn_state.list', 'usage.get', 'runtime.reload',
  'models.main.set', 'models.agents.get', 'models.agents.set', 'models.discover', 'personality.get', 'personality.set', 'personality.presets.save', 'personality.presets.delete',
  'tools.list', 'tools.set_enabled', 'tools.timeouts.get', 'tools.timeouts.set',
  'webhooks.outbound.list', 'webhooks.outbound.save', 'webhooks.outbound.delete', 'webhooks.outbound.test', 'integrations.email.get'
].sort()]
export type RealCoreStatus = { phase: string; version: string; core_instance_id: string; capabilities: string[];
  model: { main: string | null; effort: string | null; provider: string | null };
  providers: Array<{ name: string; health: string }>; limits: Record<string, number>; summary: string }

export function assertFreshManagementStatus(status: RealCoreStatus): void {
  assert.equal(status.phase, 'ready') // Transport lifetime, not provider readiness.
  assert.deepEqual(status.capabilities, realCoreCapabilities)
  // capture_serving_identity exposes the configured default even without a
  // client. Provider health, not this identity, proves actual readiness.
  assert.deepEqual(status.model, { main: 'gpt-6.1-sol', effort: null, provider: 'codex' })
  assert.deepEqual(status.providers, [
    { name: 'codex', health: 'unavailable' }, { name: 'ollama', health: 'disabled' }, { name: 'compat', health: 'disabled' }
  ])
  assert.deepEqual(status.limits, { chunk_bytes: 512 * 1024, attachment_bytes: 25 * 1024 * 1024, attachments_per_turn: 10 })
  assert.match(status.summary, /Codex: unavailable/)
}

export async function realCoreSmoke(win: BrowserWindow, broker: Broker, out: string): Promise<void> {
  const deadline = Date.now() + 30_000
  while (broker.linkState !== 'ready' || win.webContents.isLoading()) {
    assert(Date.now() < deadline, 'real-core smoke timed out waiting for the app and handshake')
    await pause(100)
  }
  const result = await broker.request('status.get')
  assert(result.ok, 'real status.get must succeed')
  const status = result.result as RealCoreStatus
  assertFreshManagementStatus(status)
  assert.equal(status.core_instance_id, broker.coreInstanceId)
  assert.equal(status.version, process.env.ODIN_SMOKE_EXPECT_VERSION ?? '0.1.0.dev1')

  // Later-slice reads are genuine core refusals, not empty successful lists.
  for (const method of ['conversations.list', 'conversations.create', 'submission.send', 'search.query', 'work.list', 'skills.list', 'mcp.list', 'schedules.list', 'computer.status']) {
    const refused = await broker.request(method)
    assert(!refused.ok && refused.error.code === 'capability_unavailable', `${method} must honestly refuse`)
  }

  const reads: Record<string, unknown> = {}
  for (const method of ['settings.schema', 'usage.get', 'personality.get', 'tools.list', 'tools.timeouts.get', 'hosts.list', 'memory.list', 'lists.list', 'knowledge.list', 'health.get', 'audit.query', 'logs.search', 'turn_state.list']) {
    const answer = await broker.request(method)
    assert(answer.ok, `${method} management read must succeed`)
    reads[method] = answer.result
  }
  const accounts = await broker.request('codex.accounts.list')
  assert(!accounts.ok && accounts.error.code === 'keyring_unavailable', 'isolated profile must honestly report missing system keyring, not invent accounts')
  reads['codex.accounts.list'] = accounts
  assert.deepEqual(reads['lists.list'], { items: [] })
  assert.deepEqual(reads['audit.query'], [])
  assert.deepEqual(reads['logs.search'], { entries: [], count: 0 })
  assert.equal((reads['turn_state.list'] as { availability: string }).availability, 'not_enabled')
  assert.deepEqual((reads['usage.get'] as { tokens: unknown }).tokens, { value: null, kind: 'unknown' })
  assert((reads['settings.schema'] as { fields: unknown[] }).fields.length > 0, 'real management schema must contain fields')

  const run = async <T = unknown>(script: string): Promise<T> => {
    try {
      return await win.webContents.executeJavaScript(script, true) as T
    } catch (error) {
      throw new Error(`UI assertion failed: ${script}: ${String(error)}`)
    }
  }
  const text = (selector: string): Promise<string> => run(`document.querySelector(${JSON.stringify(selector)})?.innerText ?? ''`)
  const click = async (selector: string): Promise<void> => {
    assert(await run(`Boolean(document.querySelector(${JSON.stringify(selector)}))`), `missing UI control ${selector}`)
    await run(`document.querySelector(${JSON.stringify(selector)}).click()`)
  }
  const until = async (predicate: () => Promise<boolean>, label: string): Promise<void> => {
    const end = Date.now() + 8_000
    while (!await predicate()) {
      if (Date.now() >= end) {
        writeFileSync(out, (await win.webContents.capturePage()).toPNG())
        throw new Error(`real-core smoke: UI did not settle for ${label}. Rendered page: ${await text('body')}`)
      }
      await pause(100)
    }
  }
  const screens: Array<{ screen: string; text: string }> = []
  const unavailable = /not (?:yet )?available|unavailable|not served|later (?:step|slice)/i
  const recordUnavailable = async (screen: string, selector: string): Promise<void> => {
    await until(async () => unavailable.test(await text(selector)), screen)
    const rendered = await text(selector)
    assert(!/Loading…|Searching…/.test(rendered), `${screen} is still loading`)
    assert(!/Service is not available yet/.test(rendered), `${screen} presents a generic core error instead of an unavailable state`)
    screens.push({ screen, text: rendered })
  }

  await until(async () => (await text('.status')).includes(status.version), 'real core status bar')
  screens.push({ screen: 'Status', text: await text('.status') })
  await recordUnavailable('Chat and conversations', '.main')
  await recordUnavailable('Conversation sidebar', 'nav[aria-label="Conversations"]')
  const sidebarInset = await run<number>(`(() => {
    const nav = document.querySelector('nav[aria-label="Conversations"]').getBoundingClientRect();
    return document.querySelector('.sidebar-notice').getBoundingClientRect().left - nav.left;
  })()`)
  assert(sidebarInset >= 12, 'conversation unavailable notice must retain the sidebar inset')
  assert.equal(await run('document.querySelectorAll(".conv-row").length'), 0, 'real session must never seed fixture conversations')
  assert(await run('document.querySelector(".composer button[type=submit]")?.disabled === true'), 'unavailable chat must not offer a sendable composer')
  assert(await run(`document.querySelector(${JSON.stringify('button[aria-label="Attach files"]')})?.disabled === true`), 'unavailable chat must not offer attachments')
  await click('button[aria-label="New conversation"]')
  await until(async () => unavailable.test(await text('.composer .notice:last-child')), 'new conversation refusal')
  assert.equal(await run('document.querySelectorAll(".conv-row").length'), 0, 'refused creation must not invent a conversation')

  // Slash commands remain useful without chat. Exercise the actual command
  // palette and bridge; served usage with missing history remains unknown.
  for (const command of ['/status', '/usage']) {
    await run(`(() => {
      const input = document.querySelector('.composer textarea');
      input.value = ${JSON.stringify(command)}; input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`)
    await pause(50)
    await run(`document.querySelector('.composer form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))`)
    if (command === '/status') {
      await until(async () => (await text('.composer .panel-text')).includes(status.version), '/status report')
      screens.push({ screen: '/status', text: await text('.composer .panel-text') })
      await click('.composer .panel button')
    } else {
      const summary = (reads['usage.get'] as { summary: string }).summary
      await until(async () => (await text('.composer .panel-text')).includes(summary), '/usage report')
      assert(!/Usage.*unavailable/i.test(await text('.status')), 'served usage must not present capability refusal')
      screens.push({ screen: '/usage', text: await text('.composer .panel-text') })
      await click('.composer .panel button')
    }
  }

  await click('button[title="Search all conversations (Ctrl+Shift+F)"]')
  await run(`(() => {
    const input = document.querySelector('.search-form input');
    input.value = 'smoke query'; input.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('.search-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  })()`)
  await recordUnavailable('Search', '.search-panel')
  assert.equal(await run('document.querySelectorAll(".search-hits li").length'), 0)
  await click('.work-toggle')
  await recordUnavailable('Work', '.work-panel')
  assert.equal(await run('document.querySelectorAll(".work-item").length'), 0)
  writeFileSync(out, (await win.webContents.capturePage()).toPNG())

  await click('button[title="Settings (Ctrl+,)"]')
  await until(async () => (await run<number>('document.querySelectorAll(".settings-group .schema-form").length')) > 0, 'served settings schema and navigation')
  const sections = await run<string[]>('Array.from(document.querySelectorAll(".settings-nav-item"), b => b.innerText)')
  assert.deepEqual(sections, ['General', 'Models and providers', 'Personality', 'Tools', 'Skills', 'MCP servers', 'Hosts and trust', 'Scheduled and running work', 'State', 'Records', 'Other'])
  // Check unserved owners separately from read-backed management panels.
  const servicePanels: Record<string, string[]> = {
    Skills: ['section[aria-label="Skills"]'],
    'MCP servers': ['section[aria-label="MCP servers"]'],
    'Scheduled and running work': ['section[aria-label="Schedules"]', 'section[aria-label="Running work"]'],
    Records: ['section[aria-label="Computer use"]']
  }
  const servedPanels: Record<string, Array<[string, RegExp]>> = {
    'Models and providers': [['.codex-accounts', /keyring.*(?:locked|unavailable)/i]],
    Personality: [['section[aria-label="Personality"]', /preset|personality/i]],
    Tools: [['section[aria-label="Built-in tools"]', /run_command/], ['section[aria-label="Tool timeouts"]', /Default|seconds/i]],
    'Hosts and trust': [['section[aria-label="Hosts"]', /localhost/]],
    State: [['section[aria-label="Memory"]', /0 entries/], ['section[aria-label="Named lists"]', /No lists\./], ['section[aria-label="Knowledge"]', /Knowledge/]],
    Records: [['section[aria-label="Health"]', /healthy.*degraded.*down.*not set up/s], ['section[aria-label="Usage"]', /not measured: Odin doesn't know this value/], ['section[aria-label="Audit"]', /Nothing recorded\./], ['section[aria-label="Logs"]', /No entries\./], ['section[aria-label="Turn state"]', /Turn state is off\./]]
  }
  for (let i = 0; i < sections.length; i++) {
    await click(`.settings-nav-item:nth-of-type(${i + 2})`)
    if (sections[i] === 'Models and providers') {
      await until(async () => (await text('.codex-accounts')).includes('Add account'), 'served account management')
      assert.equal(await run('document.querySelectorAll(".account").length'), 0, 'real session must not display fixture accounts')
    }
    for (const selector of servicePanels[sections[i]!] ?? []) {
      await recordUnavailable(`Settings / ${sections[i]} / ${selector}`, selector)
      assert.equal(await run(`document.querySelectorAll(${JSON.stringify(selector + ' .manage-row, ' + selector + ' .work-item')}).length`), 0, `${selector} must not display fixture rows`)
      assert(!/No schedules yet|No servers\.|Nothing is running\./.test(await text(selector)), 'refused reads must not claim successful empty results')
    }
    for (const [selector, expected] of servedPanels[sections[i]!] ?? []) {
      await until(async () => expected.test(await text(selector)), `served ${sections[i]} / ${selector}`)
      assert(!/Service is not available yet|Loading…|Searching…/.test(await text(selector)), `${selector} must settle its served read`)
      assert.equal(await run(`document.querySelectorAll(${JSON.stringify(selector + ' .capability-unavailable')}).length`), 0, `${selector} must not claim its served capability unavailable`)
      screens.push({ screen: `Settings / ${sections[i]} / ${selector}`, text: await text(selector) })
    }
    if (sections[i] === 'State') {
      // Context reload is deliberately on demand, not a screen-mount side effect.
      await click('section[aria-label="Context"] button')
      await until(async () => /Context reloaded.*context directory does not exist; nothing is loaded/s.test(await text('section[aria-label="Context"] .manage-json')), 'served context reload')
      assert.equal(await run('document.querySelectorAll("section[aria-label=Context] button").length'), 1, 'served context reload remains offered')
      screens.push({ screen: 'Settings / State / Context reload', text: await text('section[aria-label="Context"]') })
    }
    assert.equal(await run('document.querySelectorAll(".settings-body [role=alert]").length'), 0, `${sections[i]} must not present capability refusal as a fault`)
    assert.equal(await run('document.querySelectorAll(".settings-body .work-item, .settings-body .account").length'), 0, `${sections[i]} must not display fixture accounts/work`)
    const renderedPaths = await run<string[]>('Array.from(document.querySelectorAll(".settings-body .field-path"), e => e.textContent)')
    const fields = (reads['settings.schema'] as { fields: Array<{ path: string }> }).fields
    for (const path of renderedPaths) assert(fields.some((field) => field.path === path), `rendered field ${path} must belong to the served schema`)
    if (sections[i] === 'General') assert(renderedPaths.length > 0, 'General must render real schema fields')
    screens.push({ screen: `Settings / ${sections[i]}`, text: await text('.settings-body') })
    if (i === 0) {
      assert((await text('.settings-body')).includes('Start Odin when you log in'), 'app-local settings remain available')
    }
    writeFileSync(out.replace(/\.png$/i, '') + `-settings-${i + 1}.png`, (await win.webContents.capturePage()).toPNG())
  }
  writeFileSync(out.replace(/\.png$/i, '') + '-settings.png', (await win.webContents.capturePage()).toPNG())
  assert.equal(broker.linkState, 'ready')
  writeFileSync(out.replace(/\.png$/i, '') + '-evidence.json', JSON.stringify({ link: broker.linkState, status, reads, screens }, null, 2) + '\n')
  process.stdout.write(`real-core-smoke: evidence ${JSON.stringify({ link: broker.linkState, status, screens })}\n`)
  process.stdout.write(`real-core-smoke: ok link=ready version=${status.version} screens=${screens.length}\n`)
}
