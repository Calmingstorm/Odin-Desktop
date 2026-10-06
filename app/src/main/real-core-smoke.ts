// Development-only assertions, invoked exclusively by the isolated smoke runner.
// Exercise the named preload bridge and rendered app, not a second mock client.
import { strict as assert } from 'node:assert'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'
import type { BrowserWindow } from 'electron'
import type { Broker } from './broker'
import type { ConversationSnapshot, WebhookIngressStatus, ScheduleRow } from '../shared/api'

const pause = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

// Reviewed conversation/request and management surface; never derive expectations from welcome.
export const realCoreCapabilities = ['status.get', 'events.subscribe', 'runtime.shutdown', 'submission.send', 'notifications.ack', ...[
  'attachments.begin', 'attachments.chunk', 'attachments.commit', 'attachments.cancel',
  'artifacts.read', 'tool.detail', 'tool.output',
  'conversations.list', 'conversations.create', 'conversations.update', 'conversations.delete',
  'conversations.reset_context', 'conversations.mark_read', 'messages.list',
  'conversation.snapshot', 'search.query', 'messages.around',
  'settings.schema', 'settings.set', 'secrets.set', 'secrets.clear', 'secrets.unlock', 'models.image.intent',
  'providers.codex.set', 'providers.auxiliary.set', 'providers.ollama.set', 'providers.compat.set',
  'codex.accounts.list', 'codex.accounts.activate', 'codex.accounts.remove', 'codex.accounts.label', 'codex.login.begin', 'codex.login.poll',
  'hosts.list', 'hosts.settings', 'hosts.prepare', 'hosts.test', 'hosts.commit', 'hosts.set_enabled', 'hosts.references', 'hosts.delete', 'hosts.public_key', 'hosts.force_revoke',
  'memory.list', 'memory.get', 'memory.set', 'memory.delete', 'memory.bulk_delete', 'lists.list', 'lists.get', 'lists.delete',
  'knowledge.list', 'knowledge.search', 'knowledge.ingest', 'knowledge.reingest', 'knowledge.delete', 'knowledge.versions', 'knowledge.restore', 'knowledge.import',
  'audit.query', 'audit.verify', 'health.get', 'logs.search', 'turn_state.list', 'usage.get', 'runtime.reload',
  'models.main.set', 'models.agents.get', 'models.agents.set', 'models.discover', 'personality.get', 'personality.set', 'personality.presets.save', 'personality.presets.delete',
  'tools.list', 'tools.set_enabled', 'tools.timeouts.get', 'tools.timeouts.set',
  'control.stop', 'control.steer', 'control.resume',
  'work.list', 'work.control', 'reports.page', 'schedules.list', 'schedules.save', 'schedules.delete',
  'schedules.run', 'schedules.reset_failures', 'schedules.history', 'schedules.validate_cron',
  'webhooks.outbound.list', 'webhooks.outbound.save', 'webhooks.outbound.delete', 'webhooks.outbound.test', 'integrations.email.get'
].sort()]
export type RealCoreStatus = { phase: string; version: string; core_instance_id: string; capabilities: string[];
  model: { main: string | null; effort: string | null; provider: string | null };
  providers: Array<{ name: string; health: string }>; limits: Record<string, number>; summary: string;
  first_run: { state: string; reason: string; keyring_unavailable: boolean }; webhook_ingress: WebhookIngressStatus }

export function assertFreshManagementStatus(status: RealCoreStatus, keyring: 'unavailable' | 'ephemeral' = 'unavailable'): void {
  assert.equal(status.phase, 'ready') // Transport lifetime, not provider readiness.
  assert.deepEqual(status.capabilities, realCoreCapabilities)
  // capture_serving_identity exposes the configured default even without a
  // client. Provider health, not this identity, proves actual readiness.
  assert.deepEqual(status.model, { main: 'gpt-6.1-sol', effort: null, provider: 'codex' })
  assert.deepEqual(status.providers, [
    { name: 'codex', health: 'unavailable' }, { name: 'ollama', health: 'disabled' }, { name: 'compat', health: 'disabled' }
  ])
  assert.deepEqual(status.limits, { chunk_bytes: 512 * 1024, attachment_bytes: 50 * 1024 * 1024, attachments_per_turn: 10 })
  assert.match(status.summary, /Codex: unavailable/)
  assert.deepEqual(status.first_run, keyring === 'unavailable'
    ? { state: 'degraded', reason: 'keyring_unavailable', keyring_unavailable: true }
    : { state: 'fresh', reason: 'provider_not_configured', keyring_unavailable: false })
  assert.deepEqual(status.webhook_ingress, { reason: 'disabled', address: null, eligible_schedules: 0, unknown_deliveries: 0 })
}

export async function realCoreSmoke(win: BrowserWindow, broker: Broker, out: string): Promise<void> {
  const deadline = Date.now() + 30_000
  while (broker.linkState !== 'ready' || win.webContents.isLoading()) {
    assert(Date.now() < deadline, 'real-core smoke timed out waiting for the app and handshake')
    await pause(100)
  }
  const proofPath = join(process.env.HOME!, 'work-proof.json')
  while (!existsSync(proofPath)) {
    assert(Date.now() < deadline, 'real work proof bootstrap did not settle')
    await pause(100)
  }
  const proof = JSON.parse(readFileSync(proofPath, 'utf8')) as { conversation_id: string; report_id: string; recovery_id: string }
  const counts = (): unknown => Object.fromEntries(['background', 'report'].map(name =>
    [name, readFileSync(join(process.env.HOME!, `${name}-effects`), 'utf8').trim().split('\n').length]))
  const beforePaging = counts()
  const result = await broker.request('status.get')
  assert(result.ok, 'real status.get must succeed')
  const status = result.result as RealCoreStatus
  assertFreshManagementStatus(status, 'ephemeral')
  assert.equal(status.core_instance_id, broker.coreInstanceId)
  assert.equal(status.version, process.env.ODIN_SMOKE_EXPECT_VERSION ?? '0.1.0.dev1')
  for (const method of ['status.get', 'events.subscribe', 'runtime.shutdown', 'settings.schema', 'settings.set',
    'tools.list', 'tools.timeouts.get', 'personality.get', 'hosts.list', 'hosts.public_key',
    'memory.get', 'lists.list', 'knowledge.list', 'audit.query', 'logs.search', 'turn_state.list', 'usage.get',
    'work.list', 'work.control', 'reports.page', 'schedules.list', 'schedules.run', 'schedules.history']) {
    assert(status.capabilities.includes(method), `${method} must be published by the real management core`)
  }

  // Later-slice reads are genuine core refusals, not empty successful lists.
  for (const method of ['skills.list', 'mcp.list', 'mcp.status', 'computer.status']) {
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
  assert(accounts.ok, 'ephemeral keyring must serve the actual empty account store')
  assert.deepEqual(accounts.result, { configured: false, accounts: [] })
  reads['codex.accounts.list'] = accounts
  assert.deepEqual(reads['lists.list'], { items: [] })
  assert(Array.isArray(reads['audit.query']) && (reads['audit.query'] as unknown[]).length > 0, 'real task/check activity must populate audit')
  const logRead = reads['logs.search'] as { entries: unknown[]; count: number }
  assert(Array.isArray(logRead.entries) && logRead.entries.length > 0 && logRead.count > 0, 'real task/check activity must populate logs')
  assert.equal((reads['turn_state.list'] as { availability: string }).availability, 'available')
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
  const count = (selector: string): Promise<number> => run(`document.querySelectorAll(${JSON.stringify(selector)}).length`)
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
  const webhookProof: Record<string, unknown> = {}
  const webhookSmoke = async (): Promise<void> => {
    const panel = '[data-testid="webhook-ingress"]'
    const measured = async (): Promise<WebhookIngressStatus> => {
      const answer = await broker.request('status.get')
      assert(answer.ok)
      const ingress = (answer.result as RealCoreStatus).webhook_ingress
      assert(ingress, 'status.get must include the actual ingress owner projection')
      assert(Number.isInteger(ingress.eligible_schedules) && ingress.eligible_schedules >= 0)
      assert.equal(ingress.unknown_deliveries, 0, 'completed deliveries must not invent unknown handoffs')
      return ingress
    }
    const refresh = async (): Promise<void> => {
      await until(async () => await run<boolean>(`document.querySelector(${JSON.stringify(panel)})?.getAttribute('aria-busy') === 'false'`), 'idle webhook inspector')
      await click('button[aria-label="Refresh webhook ingress"]')
      await until(async () => await run<boolean>(`document.querySelector(${JSON.stringify(panel)})?.getAttribute('aria-busy') === 'false'`), 'refreshed webhook inspector')
    }
    const field = async (testid: string, value: string, event = 'input'): Promise<void> => {
      await run(`(() => { const input = document.querySelector('[data-testid=${testid}]');
        input.value = ${JSON.stringify(value)}; input.dispatchEvent(new Event(${JSON.stringify(event)}, { bubbles: true })); })()`)
    }
    const button = async (label: string): Promise<void> => {
      await pause(50) // Vue must commit the previous grounded field change.
      await run(`(() => { const button = Array.from(document.querySelectorAll(${JSON.stringify(panel + ' button')})).find(b => b.textContent.trim() === ${JSON.stringify(label)});
        if (!button || button.disabled) throw new Error('Missing or disabled webhook action'); button.click(); })()`)
    }
    await refresh()
    assert.deepEqual(await measured(), { reason: 'disabled', address: null, eligible_schedules: 0, unknown_deliveries: 0 })
    assert((await text('[data-testid="webhook-ingress-status"]')).startsWith('Disabled'))
    assert.equal(await run('document.querySelector("[data-testid=webhook-ingress-enabled]").checked'), false, 'inbound ingress must start opt-in')
    await field('webhook-ingress-bind', '127.0.0.1')
    await field('webhook-ingress-port', '0')
    await click('[data-testid="webhook-ingress-enabled"]')
    await button('Save listener setup')
    await until(async () => (await measured()).reason === 'no_eligible_schedule', 'opt-in without eligible trigger stays off')
    await refresh()
    assert.deepEqual(await measured(), { reason: 'no_eligible_schedule', address: null, eligible_schedules: 0, unknown_deliveries: 0 })
    assert((await text('[data-testid="webhook-ingress-status"]')).includes('Off: no eligible schedule'))
    // Named preload creation enters the actual scheduler, not a seeded row.
    const created = await run<{ ok: boolean; result: ScheduleRow }>(`window.odin.schedulesSave(${JSON.stringify({
      description: 'Real ephemeral webhook reminder', action: 'reminder', channel_id: proof.conversation_id,
      trigger: { source: 'generic', event: 'smoke-delivery' }, message: 'Real webhook schedule ran.'
    })})`)
    assert(created.ok, 'named trigger schedule creation must succeed')
    const row = created.result
    webhookProof.schedule = row
    await click('button[aria-label="Refresh schedules"]')
    await until(async () => (await text('section[aria-label="Schedules"]')).includes(row.description), 'actual created trigger in Settings schedule list')
    await refresh()
    await field('webhook-ingress-schedule', row.id, 'change')
    await until(async () => (await count('[data-testid="webhook-ingress-secret"]')) === 1, 'selected saved trigger inspector')
    assert.equal(await run('document.querySelector("[data-testid=webhook-ingress-secret]").value'), '', 'stored secret must never prefill')
    assert.equal((await measured()).eligible_schedules, 0, 'saved schedule alone cannot authenticate a delivery')
    await field('webhook-ingress-source', 'generic', 'change')
    const secret = randomUUID() // Ephemeral fixture credential, excluded from evidence.
    await field('webhook-ingress-secret', secret)
    await button('Save trigger source and secret')
    await until(async () => (await measured()).reason === 'accepting', 'actual loopback ingress bind')
    await refresh()
    const accepting = await measured()
    assert.equal(accepting.eligible_schedules, 1)
    assert.equal(accepting.address?.[0], '127.0.0.1')
    assert(Number.isInteger(accepting.address?.[1]) && accepting.address![1] > 0, 'port0 must report its actual ephemeral port')
    assert.equal(await run('document.querySelector("[data-testid=webhook-ingress-secret]").value'), '', 'submission clears secret draft')
    const url = `http://127.0.0.1:${accepting.address![1]}/webhook/generic/${encodeURIComponent(row.id)}`
    assert((await text('[data-testid="webhook-ingress-endpoint"]')).includes(url), 'UI must show actual socket endpoint, not configured port0')
    const schema = await run<{ ok: boolean; result: unknown }>('window.odin.settingsSchema()')
    assert(schema.ok && !JSON.stringify(schema.result).includes(secret), 'write-only schema must not reveal fixture credential')
    assert(!(await text(panel)).includes(secret), 'inspector must not render stored credential')
    screens.push({ screen: 'Webhook ingress / actual accepting loopback endpoint', text: await text(panel) })
    writeFileSync(out.replace(/\.png$/i, '') + '-webhook.png', (await win.webContents.capturePage()).toPNG())
    const history = async (): Promise<unknown[]> => {
      const answer = await run<{ ok: boolean; result: unknown[] }>(`window.odin.schedulesHistory({ id: ${JSON.stringify(row.id)} })`)
      assert(answer.ok)
      return answer.result
    }
    const deliver = async (credential: string, event: string, title: string): Promise<Response> => {
      try {
        return await fetch(url, {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Webhook-Secret': credential },
          body: JSON.stringify({ event, title, message: 'Harmless isolated delivery.' }), signal: AbortSignal.timeout(5_000)
        })
      } catch (error) {
        throw new Error(`Isolated webhook delivery ${title} failed: ${String(error)}`)
      }
    }
    assert.deepEqual(await history(), [])
    const denied = await deliver('not-the-trigger-secret', 'smoke-delivery', 'Rejected webhook')
    assert.equal(denied.status, 403)
    assert.deepEqual(await history(), [], 'unauthenticated delivery must not invoke the scheduler')
    const filtered = await deliver(secret, 'different-event', 'Filtered webhook notice')
    assert.equal(filtered.status, 200)
    assert.deepEqual(await filtered.json(), { status: 'delivered' })
    assert.deepEqual(await history(), [], 'authenticated nonmatching event publishes notice without running trigger')
    for (const title of ['Actual webhook delivery one', 'Actual webhook delivery two']) {
      const response = await deliver(secret, 'smoke-delivery', title)
      assert.equal(response.status, 200)
      assert.deepEqual(await response.json(), { status: 'delivered' })
    }
    const runs = await history()
    assert.equal(runs.length, 2, 'each HTTP delivery must run once through the actual scheduler')
    assert(runs.every(run => (run as { status: string }).status === 'success'))
    const transcript = await broker.request('conversation.snapshot', { conversation_id: proof.conversation_id })
    assert(transcript.ok)
    const messages = (transcript.result as ConversationSnapshot).messages.items
    assert.equal(messages.filter(item => item.text.includes('Real webhook schedule ran.')).length, 2)
    for (const title of ['Filtered webhook notice', 'Actual webhook delivery one', 'Actual webhook delivery two']) {
      assert.equal(messages.filter(item => item.text.includes(title)).length, 1, 'delivery notice must publish once')
    }
    assert(!JSON.stringify(transcript.result).includes(secret), 'delivery transcript must not reveal authentication secret')
    assert.deepEqual(counts(), beforePaging, 'webhook reminder delivery must not rerun existing task/report commands')
    webhookProof.accepting = accepting
    webhookProof.history = runs
    webhookProof.deliveryStatus = { rejected: denied.status, filtered: filtered.status, accepted: 2 }
    await button('Clear per-trigger secret')
    await until(async () => (await measured()).reason === 'no_eligible_schedule' && (await measured()).address === null, 'cleared secret closes actual listener')
    await refresh()
    assert.deepEqual(await measured(), { reason: 'no_eligible_schedule', address: null, eligible_schedules: 0, unknown_deliveries: 0 })
    assert.equal(await count('[data-testid="webhook-ingress-endpoint"]'), 0, 'inactive inspector must not advertise accepting endpoint')
    await assert.rejects(deliver(secret, 'smoke-delivery', 'After secret clear'), 'closed listener must reject connections')
    assert.deepEqual(await history(), runs, 'clearing secret must not replay or run any delivery')
    webhookProof.cleared = await measured()
    screens.push({ screen: 'Webhook ingress / secret cleared and listener off', text: await text(panel) })
  }
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
  // This retained Chat contains genuine task/report/reminder publications. The
  // new conversation below separately proves an authoritative empty snapshot.
  await until(async () => (await count('.conv-row')) === 1 && (await text('.conv.active .conv-title')) === 'Chat' &&
    await run<boolean>('document.querySelector(".composer textarea")?.disabled === false'), 'real first conversation and snapshot')
  assert.equal(await text('.conv.active .conv-title'), 'Chat')
  assert.equal(await count('.sidebar-notice'), 0, 'served conversations must not claim unavailable')
  assert((await count('.msg')) > 0, 'real background publication must appear in the transcript')
  const retained = await broker.request('conversation.snapshot', { conversation_id: proof.conversation_id })
  assert(retained.ok, 'retained Chat snapshot must be served')
  const retainedMessages = (retained.result as ConversationSnapshot).messages.items
  const reminders = retainedMessages.filter(message => message.text.includes('Harmless catch-up notice'))
  assert.equal(reminders.length, 1, 'real D12 reminder must publish exactly once')
  assert(/Due:.*late by.*Omitted slots:/s.test(reminders[0]!.text), 'durable D12 reminder must retain catch-up provenance')
  // Chromium skips offscreen content-visibility bodies in ancestor innerText.
  // Bring the exact authoritative message into view, then prove visible text.
  const reminderSelector = `#m-${reminders[0]!.id}`
  await run(`document.querySelector(${JSON.stringify(reminderSelector)}).scrollIntoView({ block: 'center' })`)
  await until(async () => (await text(reminderSelector)).includes('Harmless catch-up notice') &&
    /Due:.*late by.*Omitted slots:/s.test(await text(reminderSelector)), 'visible real D12 catch-up notice and provenance')
  screens.push({ screen: 'Visible durable D12 catch-up notice', text: await text(reminderSelector) })
  writeFileSync(out.replace(/\.png$/i, '') + '-reminder.png', (await win.webContents.capturePage()).toPNG())
  await run(`document.querySelector('.report-body').scrollIntoView({ block: 'center' })`)
  await until(async () => (await text('.report-body')).includes('produced once'), 'stored real report first page')
  await click('.report-nav button:nth-of-type(2)')
  await until(async () => (await text('.report-body')).includes('no rerun'), 'stored real report second page')
  assert.deepEqual(counts(), beforePaging, 'report paging must not execute the external tool again')
  screens.push({ screen: 'Stored report paging and D12 catch-up notice', text: await text('.message-scroll') })
  writeFileSync(out.replace(/\.png$/i, '') + '-report.png', (await win.webContents.capturePage()).toPNG())
  assert(await run('document.querySelector(".composer button[type=submit]")?.disabled === true'), 'empty composer must not send')
  assert(await run(`document.querySelector(${JSON.stringify('button[aria-label="Attach files"]')})?.disabled === false`), 'served chat must offer attachments')
  const initial = await broker.request('conversations.list')
  assert(initial.ok, 'real conversation list must succeed')
  const initialItems = (initial.result as { items: Array<{ id: string; title: string }> }).items
  assert.equal(initialItems.length, 1, 'first Chat must be persisted by the core, not a fixture row')
  assert.equal(initialItems[0]!.title, 'Chat')
  screens.push({ screen: 'Chat and conversations', text: await text('.main') })
  await click('button[aria-label="New conversation"]')
  await until(async () => (await count('.conv-row')) === 2 && (await text('.conv.active .conv-title')) === 'New chat' &&
    (await text('.message-scroll')).includes('Ask Odin anything.') &&
    await run<boolean>('document.querySelector(".composer textarea")?.disabled === false'), 'real new conversation and snapshot')
  const created = await broker.request('conversations.list')
  assert(created.ok, 'created conversations must be readable from the real core')
  const createdItems = (created.result as { items: Array<{ id: string; title: string }> }).items
  assert.equal(createdItems.length, 2)
  const conversationId = createdItems.find((item) => item.title === 'New chat')!.id
  assert.notEqual(conversationId, initialItems[0]!.id)
  const emptySnapshot = await broker.request('conversation.snapshot', { conversation_id: conversationId })
  assert(emptySnapshot.ok, 'new conversation snapshot must be served')
  assert.deepEqual((emptySnapshot.result as { messages: { items: unknown[] } }).messages.items, [])
  screens.push({ screen: 'Conversation sidebar', text: await text('nav[aria-label="Conversations"]') })

  // Slash commands remain useful without a provider. Exercise the actual command
  // palette and bridge; /status and /usage use real step-five observations,
  // with served usage remaining unknown when history is missing.
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
  await until(async () => (await text('.search-panel .search-note')).includes('No matches.'), 'served empty conversation search')
  assert.equal(await count('#conversation-search-error'), 0, 'served search must not claim capability refusal')
  screens.push({ screen: 'Search', text: await text('.search-panel') })
  assert.equal(await run('document.querySelectorAll(".search-hits li").length'), 0)
  await click('.work-toggle')
  await until(async () => (await text('.work-panel')).includes('Harmless completed task') &&
    (await text('.work-panel')).includes('Resource release is not confirmed'), 'real Work detail and honest unknown release')
  const work = await broker.request('work.list')
  assert(work.ok)
  const workItems = (work.result as { items: Array<Record<string, unknown>> }).items
  assert.deepEqual(new Set(workItems.map(i => i.kind)), new Set(['agent', 'task', 'workflow', 'loop', 'process', 'schedule']))
  const cancellable = workItems.find(i => i.title === 'Harmless cancellable task')!
  const controlParams = Object.fromEntries(['kind', 'id', 'manager_generation', 'run_id', 'generation', 'conversation_id'].map(k => [k, cancellable[k]]))
  Object.assign(controlParams, { action: 'cancel', control_command_id: randomUUID() })
  const receipt = await run<{ ok: boolean; result?: { disposition: string } }>(`window.odin.workControl(${JSON.stringify(controlParams)})`)
  assert(receipt.ok)
  assert.equal(receipt.result!.disposition, 'done')
  assert.deepEqual(await run(`window.odin.workControl(${JSON.stringify(controlParams)})`), receipt, 'named bridge must return journaled receipt without repeating cancellation')
  await click('button[aria-label="Refresh work"]')
  await until(async () => (await text('.work-panel')).includes('cancelled'), 'settled actual task after journaled cancellation')
  screens.push({ screen: 'Real Work all kinds, settled task and journaled receipt', text: await text('.work-panel') })
  writeFileSync(out, (await win.webContents.capturePage()).toPNG())

  await click('button[title="Settings (Ctrl+,)"]')
  await until(async () => (await run<number>('document.querySelectorAll(".settings-nav-item").length')) > 1, 'settings navigation')
  await until(async () => (await count('.settings-group .schema-form')) > 0, 'real settings schema before enumerating all sections')
  const sections = await run<string[]>('Array.from(document.querySelectorAll(".settings-nav-item"), b => b.innerText)')
  assert.deepEqual(sections, ['General', 'Models and providers', 'Personality', 'Tools', 'Skills', 'MCP servers', 'Hosts and trust', 'Scheduled and running work', 'State', 'Records', 'Other'])
  // Check unserved owners separately from read-backed management panels.
  const servicePanels: Record<string, string[]> = {
    Skills: ['section[aria-label="Skills"]'],
    'MCP servers': ['section[aria-label="MCP servers"]'],
    Records: ['section[aria-label="Computer use"]']
  }
  const servedPanels: Record<string, Array<[string, RegExp]>> = {
    'Models and providers': [['.codex-accounts', /Codex isn't configured\./]],
    Personality: [['section[aria-label="Personality"]', /preset|personality/i]],
    Tools: [['section[aria-label="Built-in tools"]', /run_command/], ['section[aria-label="Tool timeouts"]', /Default|seconds/i]],
    'Hosts and trust': [['section[aria-label="Hosts"]', /localhost/]],
    State: [['section[aria-label="Memory"]', /0 entries/], ['section[aria-label="Named lists"]', /No lists\./], ['section[aria-label="Knowledge"]', /Knowledge/]],
    Records: [['section[aria-label="Health"]', /healthy.*degraded.*down.*not set up/s], ['section[aria-label="Usage"]', /not measured: Odin doesn't know this value/], ['section[aria-label="Audit"]', /run_command/], ['section[aria-label="Logs"]', /run_command|schedule|task/i], ['section[aria-label="Turn state"]', /Preserved work/]]
  }
  const observations = await run<Record<string, { ok: boolean; result?: unknown; error?: { code: string; message: string } }>>(`(async () => ({
    settings: await window.odin.settingsSchema(), hosts: await window.odin.hostsList({}),
    key: await window.odin.hostsPublicKey({}), tools: await window.odin.toolsList({}),
    timeouts: await window.odin.toolsTimeoutsGet({}), personality: await window.odin.personalityGet({}),
    memory: await window.odin.memoryList({}), lists: await window.odin.listsList({}),
    knowledge: await window.odin.knowledgeList({}), audit: await window.odin.auditQuery({}),
    logs: await window.odin.logsSearch({ level: 'all' }), turns: await window.odin.turnStateList({}),
    usage: await window.odin.usage('7d'), accounts: await window.odin.codexAccounts()
  }))()`)
  for (const [name, answer] of Object.entries(observations)) {
    if (name === 'accounts') {
      assert(answer.ok, 'ephemeral account store read must succeed without inventing credentials')
      assert.deepEqual(answer.result, accounts.result)
    } else assert(answer.ok, `named bridge ${name} failed: ${JSON.stringify(answer.error)}`)
  }
  const hostData = observations.hosts!.result as { hosts: Array<{ alias: string; trust_state: string }>; default_host: string }
  assert.equal(hostData.hosts.length, 1, 'fresh core must have only its actual local host')
  assert.equal(hostData.hosts[0]!.alias, 'localhost')
  assert.equal(hostData.hosts[0]!.trust_state, 'local')
  assert.equal(hostData.default_host, 'localhost')
  assert(Array.isArray(observations.audit!.result), 'audit must report actual local schedule/task records')
  assert(Array.isArray((observations.logs!.result as { entries: unknown[] }).entries), 'logs must read actual engine records')
  assert.equal((observations.turns!.result as { availability: string }).availability, 'available')
  for (let i = 0; i < sections.length; i++) {
    await click(`.settings-nav-item:nth-of-type(${i + 2})`)
    if (sections[i] === 'Models and providers') {
      await until(async () => (await text('.codex-accounts')).includes('Add account'), 'served account management')
      await until(async () => !(await text('.codex-accounts')).includes('Loading'), 'real account observation')
      assert(!/not (?:yet )?available|not served/i.test(await text('.codex-accounts')), 'served account management must not remain capability-unavailable')
      assert.equal(await run('document.querySelectorAll(".account").length'), 0, 'real session must not display fixture accounts')
      await until(async () => (await run<number>('document.querySelectorAll(".schema-form").length')) > 0, 'real provider settings')
    }
    if (sections[i] === 'Personality') {
      await until(async () => await run<boolean>('Boolean(document.querySelector("section[aria-label=Personality] select"))'), 'real personality settings')
    }
    if (sections[i] === 'Tools') {
      await until(async () => (await count('section[aria-label="Built-in tools"] .manage-row')) > 0, 'real built-in tools')
      assert((await text('section[aria-label="Tool timeouts"]')).includes('Timeouts'))
    }
    if (sections[i] === 'Scheduled and running work') {
      await until(async () => (await text('section[aria-label="Schedules"]')).includes('D12 manual recovery check') &&
        (await text('section[aria-label="Schedules"]')).includes('Recovery required'), 'real D12 recovery-required schedule')
      assert((await text('section[aria-label="Schedules"]')).includes('No effects were replayed'), 'D12 must render actual recovery reason')
      await webhookSmoke()
    }
    if (sections[i] === 'Hosts and trust') {
      await until(async () => (await text('section[aria-label=Hosts]')).includes('localhost'), 'real localhost row')
      assert.equal(await run('document.querySelector("section[aria-label=Hosts] select").value'), 'localhost')
      await until(async () => (await text('section[aria-label="Odin\'s key"]')).includes('ssh-ed25519'), 'fresh provisioned SSH public key')
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
      assert(!(await text('.settings-body')).includes('Loading'))
      assert((await text('section[aria-label="Named lists"]')).includes('No lists.'))
    }
    if (sections[i] === 'Records') {
      await until(async () => !(await text('section[aria-label=Audit]')).includes('Loading'), 'real populated audit')
      await until(async () => !(await text('section[aria-label=Logs]')).includes('Loading'), 'real engine logs')
      await until(async () => (await text('section[aria-label="Turn state"]')).includes('Preserved work') &&
        !(await text('section[aria-label="Turn state"]')).includes('Loading'), 'real turn-state availability')
      assert((await text('section[aria-label="Health"]')).includes('host(s) configured'), 'real health must observe profile hosts')
    }
    assert.equal(await run('document.querySelectorAll(".settings-body [role=alert]").length'), 0, `${sections[i]} must not present capability refusal as a fault`)
    assert.equal(await count('.settings-body .account'), 0, `${sections[i]} must not display fixture accounts`)
    if (sections[i] === 'Scheduled and running work') {
      const titles = await run<string[]>('Array.from(document.querySelectorAll(".settings-body .work-title"), row => row.textContent.trim())')
      assert(titles.length > 0, 'Settings must retain actual seeded running work')
      for (const title of titles) assert(workItems.some(item => item.title === title), 'every Settings Work row must come from the actual work.list observation')
    } else assert.equal(await count('.settings-body .work-item'), 0, `${sections[i]} must not invent work rows`)
    const renderedPaths = await run<string[]>('Array.from(document.querySelectorAll(".settings-body .field-path"), e => e.textContent)')
    const fields = (reads['settings.schema'] as { fields: Array<{ path: string }> }).fields
    for (const path of renderedPaths) assert(fields.some((field) => field.path === path), `rendered field ${path} must belong to the served schema`)
    if (sections[i] === 'General') assert(renderedPaths.length > 0, 'General must render real schema fields')
    assert(!(await text('.settings-body')).includes('Service is not available yet'), `${sections[i]} must not leak a generic capability refusal`)
    screens.push({ screen: `Settings / ${sections[i]}`, text: await text('.settings-body') })
    if (i === 0) {
      assert((await text('.settings-body')).includes('Start Odin when you log in'), 'app-local settings remain available')
    }
    writeFileSync(out.replace(/\.png$/i, '') + `-settings-${i + 1}.png`, (await win.webContents.capturePage()).toPNG())
  }
  writeFileSync(out.replace(/\.png$/i, '') + '-settings.png', (await win.webContents.capturePage()).toPNG())
  // Keep provider failure after the management/task-log checkpoints:
  // executing a real request legitimately records its failure in core logs.
  await click('.settings-nav .back')
  // The retained Work inspector can consume the transcript viewport. Close it
  // through its real control before inspecting visible message bodies.
  await click('button[aria-label="Close work"]')
  await until(async () => (await count('.work-panel')) === 0, 'chat viewport after closing Work inspector')
  const submissionText = 'real-core smoke unavailable provider check'
  await run(`(() => {
    const input = document.querySelector('.composer textarea');
    input.value = ${JSON.stringify(submissionText)}; input.dispatchEvent(new Event('input', { bubbles: true }));
  })()`)
  await until(async () => await run<boolean>('document.querySelector(".composer button[type=submit]")?.disabled === false'), 'served composer ready to submit')
  await click('.composer button[type=submit]')
  await until(async () => (await text('.message-scroll .msg.notice .body')).includes('No LLM provider available. Please try again later.') &&
    (await text('.message-scroll .outcome')).includes('The task failed.') && (await count('.working, .msg.pending')) === 0, 'actual unavailable-provider task outcome')
  assert.equal(await count('.message-scroll .msg.user'), 1, 'submission must commit exactly one user message')
  await run(`document.querySelector('.message-scroll .msg.user').scrollIntoView({ block: 'center' })`)
  await until(async () => (await text('.message-scroll .msg.user .body')) === submissionText, 'visible committed user submission')
  assert.equal(await text('.message-scroll .msg.user .body'), submissionText)
  assert.equal(await count('.message-scroll .msg.assistant'), 0, 'missing provider must not invent an assistant reply')
  assert(await run('document.querySelector(".composer textarea").value === ""'), 'accepted submission clears its draft')
  const failed = await broker.request('conversation.snapshot', { conversation_id: conversationId })
  assert(failed.ok, 'failed request remains readable through its real snapshot')
  const failedSnapshot = failed.result as ConversationSnapshot
  assert.equal(failedSnapshot.running, null)
  assert.deepEqual(failedSnapshot.queued, [])
  assert.deepEqual(failedSnapshot.messages.items.map(({ role, text }) => ({ role, text })), [
    { role: 'user', text: submissionText },
    { role: 'notice', text: 'No LLM provider available. Please try again later.' }
  ])
  assert.equal(failedSnapshot.recent.length, 1)
  assert.equal(failedSnapshot.recent[0]!.outcome, 'failed')
  assert.equal(failedSnapshot.recent[0]!.unknown_effects, 0)
  assert.deepEqual(failedSnapshot.unresolved, [])
  reads['conversation.snapshot'] = failedSnapshot
  screens.push({ screen: 'Chat / unavailable provider', text: await text('.main') })

  // Search is backed by the committed transcript, including navigation to a hit.
  assert(await run('Boolean(document.querySelector(".search-panel"))'), 'search panel remains open across settings')
  await run(`(() => {
    const input = document.querySelector('.search-form input');
    input.value = ${JSON.stringify(submissionText)}; input.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('.search-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  })()`)
  await until(async () => (await text('.search-panel .search-note')).includes('1 results.') && (await count('.search-hits li')) === 1, 'real committed transcript search hit')
  assert.equal(await count('#conversation-search-error'), 0)
  assert((await text('.search-hits .hit-snippet')).includes(submissionText))
  await click('.search-hits .hit')
  await until(async () => (await text('.message-scroll .msg.highlight .body')) === submissionText, 'real search hit navigation')
  screens.push({ screen: 'Search / committed transcript', text: await text('.search-panel') })
  writeFileSync(out.replace(/\.png$/i, '') + '-chat.png', (await win.webContents.capturePage()).toPNG())
  assert.equal(broker.linkState, 'ready')
  assert.deepEqual(counts(), beforePaging, 'all report reads and UI navigation must not rerun a check')
  writeFileSync(out.replace(/\.png$/i, '') + '-evidence.json', JSON.stringify({ link: broker.linkState, status, reads, observations, proof, receipt, webhookProof, toolCounts: counts(), screens }, null, 2) + '\n')
  process.stdout.write(`real-core-smoke: evidence ${JSON.stringify({ link: broker.linkState, status, screens: screens.map(({ screen }) => screen), observations: Object.fromEntries(Object.entries(observations).map(([name, answer]) => [name, answer.ok ? 'observed' : answer.error?.code])) })}\n`)
  process.stdout.write(`real-core-smoke: ok link=ready version=${status.version} screens=${screens.length}\n`)
}
