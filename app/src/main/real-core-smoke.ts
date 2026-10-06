// Development-only proof through the rendered app and named preload bridge.
import { strict as assert } from 'node:assert'
import { randomUUID } from 'node:crypto'
import { readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { dialog, type BrowserWindow } from 'electron'
import type { Broker } from './broker'
import type { ConversationSnapshot } from '../shared/api'

const pause = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))
interface SmokeMessage { id: string; role: string; text: string; request_id?: string; attachments?: unknown[]; artifacts?: unknown[] }

// Reviewed conversation/request and Step 6A management surface; never derive expectations from welcome.
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
  'webhooks.outbound.list', 'webhooks.outbound.save', 'webhooks.outbound.delete', 'webhooks.outbound.test', 'integrations.email.get',
  'skills.list', 'skills.get', 'skills.validate', 'skills.save', 'skills.delete',
  'skills.set_enabled', 'skills.config.get', 'skills.config.set',
  'mcp.list', 'mcp.status', 'mcp.tools', 'mcp.save', 'mcp.set_enabled', 'mcp.delete',
  'mcp.reconnect', 'mcp.refresh_tools', 'mcp.set_global_enabled', 'mcp.set_limits',
  'computer.status', 'computer.activation.set', 'computer.stop', 'computer.pause',
  'computer.cancel', 'computer.close', 'computer.reconcile', 'computer.operator_reconcile',
  'computer.release_owned_input', 'computer.acknowledge_legacy_recovery',
  'computer.reconcile_hyprland_owner'
].sort()]
export type RealCoreStatus = { phase: string; version: string; core_instance_id: string; capabilities: string[];
  model: { main: string | null; effort: string | null; provider: string | null };
  providers: Array<{ name: string; health: string }>; limits: Record<string, number>; summary: string;
  first_run: { state: string; reason: string; keyring_unavailable: boolean } }

export function assertFreshManagementStatus(status: RealCoreStatus, memoryKeyring = false): void {
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
  assert.deepEqual(status.first_run, memoryKeyring
    ? { state: 'fresh', reason: 'provider_not_configured', keyring_unavailable: false }
    : { state: 'degraded', reason: 'keyring_unavailable', keyring_unavailable: true })
}

// Substitute the peer and secret-storage boundary, never the settings owner.
export async function configureCannedProvider(broker: Broker, baseUrl: string): Promise<void> {
  const url = new URL(baseUrl)
  assert(url.protocol === 'http:' && url.hostname === '127.0.0.1' && url.port && !url.username && !url.password)
  const request = async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
    const answer = await broker.request(method, params)
    assert(answer.ok, `${method} failed: ${JSON.stringify(answer)}`)
    return answer.result as Record<string, unknown>
  }
  const save = async (method: string, changes: Array<{ path: string; value: unknown }>): Promise<void> => {
    const schema = await request('settings.schema')
    await request(method, { expected_revision: schema.revision, changes })
  }
  await save('providers.compat.set', [{ path: 'openai_compatible.enabled', value: false }])
  await save('providers.codex.set', [{ path: 'openai_codex.enabled', value: false }])
  await save('providers.auxiliary.set', [{ path: 'openai_codex.auxiliary.enabled', value: false }])
  await save('providers.compat.set', [
    { path: 'openai_compatible.base_url', value: baseUrl },
    { path: 'openai_compatible.model', value: 'canned-contract' },
    { path: 'openai_compatible.preset', value: 'custom' },
    { path: 'openai_compatible.reasoning_dialect', value: 'none' },
    { path: 'openai_compatible.reasoning_effort', value: 'none' },
    { path: 'openai_compatible.max_tokens', value: 4096 }
  ])
  await request('secrets.set', { path: 'openai_compatible.api_key', value: 'canned-local-test-only' })
  await save('providers.compat.set', [{ path: 'openai_compatible.enabled', value: true }])
  const schema = await request('settings.schema')
  await request('models.main.set', { model: 'compat:canned-contract', expected_revision: schema.revision })
  const status = await request('status.get')
  assert.deepEqual(status.model, { main: 'canned-contract', effort: null, provider: 'compat' })
  // Serving identity does not qualify a generation. The gates exercise that below.
}

export async function realCoreSmoke(win: BrowserWindow, broker: Broker, out: string): Promise<void> {
  const root = process.env.ODIN_REAL_CORE_ROOT
  assert(root && process.env.HOME === root && root.startsWith('/tmp/odrc-'), 'smoke requires disposable HOME')
  assert(process.getuid?.() !== 0, 'smoke must not run as root')
  assert(process.env.ODIN_REAL_CORE_OUTER_PID_NS && readlinkSync('/proc/self/ns/pid') !== process.env.ODIN_REAL_CORE_OUTER_PID_NS,
    'smoke requires the isolated PID namespace runner')
  assert(readFileSync('/proc/1/cmdline', 'utf8').split('\0').includes('--inside-run'), 'unexpected isolation owner')
  assert(process.env.ODIN_SMOKE_REAL_CORE === '1' && process.argv.includes('--smoke-test'), 'development smoke only')
  const handshakeDeadline = Date.now() + 30_000
  while (broker.linkState !== 'ready') {
    assert(Date.now() < handshakeDeadline, `real core handshake timed out: ${broker.linkState}`)
    await pause(100)
  }
  const events: Array<{ type: string; payload: Record<string, unknown> }> = []
  const observe = (event: { type: string; payload: Record<string, unknown> }): void => { events.push(event) }
  broker.on('event', observe)
  const screens: Array<{ screen: string; text: string }> = []
  const evidence: Record<string, unknown> = {
    isolation: { home: 'throwaway', pidNamespace: 'private', display: 'xvfb' },
    provider: 'canned loopback OpenAI-compatible, real provider client, no accounts',
    limitations: ['File/save chooser selections injected in main under isolation; native chooser UI not tested.',
      'No default-app launch or folder reveal. Resume without a durable checkpoint not claimed successful.']
  }
  const result = await broker.request('status.get')
  assert(result.ok, 'real status.get must succeed')
  const status = result.result as RealCoreStatus
  if (!process.env.ODIN_SMOKE_PROVIDER_BASE_URL) assertFreshManagementStatus(status)
  assert.equal(status.core_instance_id, broker.coreInstanceId)
  assert.equal(status.version, process.env.ODIN_SMOKE_EXPECT_VERSION ?? '0.1.0.dev1')
  for (const method of ['status.get', 'events.subscribe', 'runtime.shutdown', 'settings.schema', 'settings.set',
    'tools.list', 'tools.timeouts.get', 'personality.get', 'hosts.list', 'hosts.public_key',
    'memory.get', 'lists.list', 'knowledge.list', 'audit.query', 'logs.search', 'turn_state.list', 'usage.get',
    'skills.list', 'mcp.list', 'mcp.status', 'computer.status']) {
    assert(status.capabilities.includes(method), `${method} must be published by the real management core`)
  }

  // Part B dispatch, work and schedules remain genuine refusals. Step 6A
  // management being served does not grant skill execution or native input.
  for (const method of ['work.list', 'schedules.list', 'turns.create', 'skills.test',
    'loops.list', 'agents.list', 'shell.execute', 'computer_act']) {
    const refused = await broker.request(method)
    assert(!refused.ok && refused.error.code === 'capability_unavailable', `${method} must honestly refuse`)
  }

  const reads: Record<string, unknown> = {}
  for (const method of ['settings.schema', 'usage.get', 'personality.get', 'tools.list', 'tools.timeouts.get', 'hosts.list', 'memory.list', 'lists.list', 'knowledge.list', 'health.get', 'audit.query', 'logs.search', 'turn_state.list', 'skills.list', 'mcp.list', 'mcp.status', 'computer.status']) {
    const answer = await broker.request(method)
    assert(answer.ok, `${method} management read must succeed`)
    reads[method] = answer.result
  }
  const accounts = await broker.request('codex.accounts.list')
  if (!process.env.ODIN_SMOKE_PROVIDER_BASE_URL) assert(!accounts.ok && accounts.error.code === 'keyring_unavailable', 'fresh profile must report missing keyring')
  reads['codex.accounts.list'] = accounts
  assert.deepEqual(reads['lists.list'], { items: [] })
  assert.deepEqual(reads['skills.list'], [], 'fresh skills list is a served array, not an items wrapper')
  for (const method of ['mcp.list', 'mcp.status']) {
    const mcp = reads[method] as { servers: unknown[]; server_count: number; configured_servers: string[];
      configured_server_count: number; connected_count: number; published_tool_count: number; started: boolean; closed: boolean }
    assert.deepEqual(mcp.servers, [])
    assert.deepEqual(mcp.configured_servers, [])
    assert.equal(mcp.server_count, 0)
    assert.equal(mcp.configured_server_count, 0)
    assert.equal(mcp.connected_count, 0)
    assert.equal(mcp.published_tool_count, 0)
    assert.equal(mcp.started, true)
    assert.equal(mcp.closed, false)
  }
  const computer = reads['computer.status'] as { session: unknown; readiness: {
    management_available: boolean; foreground_available: boolean; native_qualified: boolean; input_supported: boolean; dispatch: string } }
  assert.equal(computer.session, null)
  assert.equal(computer.readiness.management_available, true)
  assert.equal(computer.readiness.foreground_available, false)
  assert.equal(computer.readiness.native_qualified, false)
  assert.equal(computer.readiness.input_supported, false)
  assert.equal(computer.readiness.dispatch, 'none')
  assert(!('input_dispatch' in computer), 'management status must not grant an input dispatch binding')
  if (!process.env.ODIN_SMOKE_PROVIDER_BASE_URL) {
    assert.deepEqual(reads['audit.query'], [])
    assert.deepEqual(reads['logs.search'], { entries: [], count: 0 })
    assert.equal((reads['turn_state.list'] as { availability: string }).availability, 'not_enabled')
    assert.deepEqual((reads['usage.get'] as { tokens: unknown }).tokens, { value: null, kind: 'unknown' })
  }
  assert((reads['settings.schema'] as { fields: unknown[] }).fields.length > 0, 'real management schema must contain fields')

  const run = async <T = unknown>(script: string): Promise<T> => {
    try { return await win.webContents.executeJavaScript(script, true) as T }
    catch (error) { throw new Error(`UI assertion failed: ${script}: ${String(error)}`) }
  }
  const text = (selector: string): Promise<string> => run(`document.querySelector(${JSON.stringify(selector)})?.innerText ?? ''`)
  const count = (selector: string): Promise<number> => run(`document.querySelectorAll(${JSON.stringify(selector)}).length`)
  const click = async (selector: string): Promise<void> => {
    assert(await run(`Boolean(document.querySelector(${JSON.stringify(selector)}))`), `missing UI control ${selector}`)
    await run(`document.querySelector(${JSON.stringify(selector)}).click()`)
  }
  const until = async (predicate: () => Promise<boolean>, label: string, timeout = 15_000): Promise<void> => {
    const end = Date.now() + timeout
    while (!await predicate()) {
      if (Date.now() >= end) throw new Error(`UI did not settle for ${label}. Rendered page: ${await text('body')}`)
      await pause(100)
    }
  }
  const record = async (screen: string, selector: string): Promise<void> => { screens.push({ screen, text: await text(selector) }) }
  const bridge = <T = unknown>(method: string, params?: unknown): Promise<T> =>
    run(`window.odin[${JSON.stringify(method)}](${params === undefined ? '' : JSON.stringify(params)})`)
  let activeCid = ''
  const setInput = async (selector: string, value: string): Promise<void> => {
    await run(`(() => { const input = document.querySelector(${JSON.stringify(selector)}); input.value = ${JSON.stringify(value)}; input.dispatchEvent(new Event('input', { bubbles: true })); })()`)
    await pause(50)
  }
  const unavailable = /not (?:yet )?available|unavailable|not served|later (?:step|slice)/i
  const recordUnavailable = async (screen: string, selector: string): Promise<void> => {
    await until(async () => unavailable.test(await text(selector)), screen)
    const rendered = await text(selector)
    assert(!/Loading…|Searching…/.test(rendered), `${screen} is still loading`)
    assert(!/Service is not available yet/.test(rendered), `${screen} presents a generic core error instead of an unavailable state`)
    screens.push({ screen, text: rendered })
  }

  let conversationId = ''
  if (!process.env.ODIN_SMOKE_PROVIDER_BASE_URL) {
  await until(async () => (await text('.status')).includes(status.version), 'real core status bar')
  screens.push({ screen: 'Status', text: await text('.status') })
  // The renderer creates Chat only after a successful empty list, then loads
  // an authoritative snapshot. A missing provider does not unserve chat.
  await until(async () => (await count('.conv-row')) === 1 && (await text('.message-scroll')).includes('Ask Odin anything.') &&
    await run<boolean>('document.querySelector(".composer textarea")?.disabled === false'), 'real first conversation and snapshot')
  assert.equal(await text('.conv.active .conv-title'), 'Chat')
  assert.equal(await count('.sidebar-notice'), 0, 'served conversations must not show an unavailable notice')
  assert.equal(await count('.msg'), 0, 'fresh real conversation must not seed fixture messages')
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
  conversationId = createdItems.find((item) => item.title === 'New chat')!.id
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
  }
  const send = async (value: string): Promise<void> => {
    await setInput('.composer textarea', value)
    await until(() => run('document.querySelector(".composer button[type=submit]")?.disabled === false'), 'sendable composer')
    await run('document.querySelector(".composer form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))')
    await until(() => run('document.querySelector(".composer textarea").value === ""'), 'submit admission/receipt')
  }
  const idle = (): Promise<void> => until(async () => {
    const snapshot = await bridge<{ ok: boolean; result: { running: unknown; queued: unknown[]; recent: Array<{ request_id: string }>; messages: { items: SmokeMessage[] } } }>('snapshotConversation', { conversation_id: activeCid })
    if (!snapshot.ok || snapshot.result.running || snapshot.result.queued.length) return false
    const last = snapshot.result.messages.items.filter((m) => m.role === 'user').at(-1)
    return Boolean(last && snapshot.result.recent.some((r) => r.request_id === last.request_id)) && await run<boolean>('!document.querySelector(".composer button.danger")')
  }, 'settled real request')
  const originalOpen = dialog.showOpenDialog
  const originalSave = dialog.showSaveDialog
  try {
    await until(async () => broker.linkState === 'ready' && !win.webContents.isLoading() && await run<boolean>('Boolean(window.odin)'), 'app handshake', 30_000)
    if (!process.env.ODIN_SMOKE_PROVIDER_BASE_URL) {
      await qualifyFreshManagement()
      Object.assign(evidence, { link: broker.linkState, screens, events })
      writeFileSync(out.replace(/\.png$/i, '') + '-evidence.json', JSON.stringify(evidence, null, 2) + '\n')
      process.stdout.write(`real-core-smoke: management ok link=ready screens=${screens.length}\n`)
      return
    }
    const response = await bridge<{ ok: boolean; result: { phase: string; version: string; capabilities: string[] } }>('status')
    assert(response.ok)
    const status = response.result
    assert.equal(status.phase, 'ready')
    // Assert advertised method names as well as their actual bridge results.
    for (const method of ['submission.send', 'control.stop', 'control.steer', 'conversations.reset_context',
      'attachments.begin', 'attachments.commit', 'tool.detail', 'tool.output', 'search.query']) {
      assert(status.capabilities.includes(method), `real core capability missing: ${method}`)
    }
    evidence.status = status
    await configureCannedProvider(broker, process.env.ODIN_SMOKE_PROVIDER_BASE_URL!)
    // The seeded lifetime has a genuine retained cleanup notice. Initial status
    // refresh can be invalidated by recovery; Retry uses the shipped read path.
    if (await run('Boolean(document.querySelector(".first-run button"))')) {
      await run('Array.from(document.querySelectorAll(".first-run button")).find(b => b.textContent.trim() === "Retry")?.click()')
    }
    await until(async () => (await text('.status')).includes('Connected'), 'real ready status bar')
    // The renderer legitimately creates its first conversation on an empty
    // served core. Never confuse that successful command with fixture seeding.
    if (await run<number>('document.querySelectorAll(".conv-row").length') === 0) await click('button[title="New conversation"]')
    await until(() => run('document.querySelectorAll(".conv-row").length === 1 && !document.querySelector(".composer textarea")?.disabled'), 'real conversation creation')
    await until(async () => !(await text('.composer')).includes('Loading this conversation'), 'snapshot catch-up')
    const conversations = await bridge<{ ok: boolean; result: { items: Array<{ id: string }> } }>('listConversations')
    assert(conversations.ok)
    const cid = conversations.result.items[0]!.id
    activeCid = cid
    evidence.conversationId = cid
    const snapshot = async (): Promise<{ messages: SmokeMessage[] }> => {
      const result = await bridge<{ ok: boolean; result: { messages: { items: SmokeMessage[] } } }>('snapshotConversation', { conversation_id: cid })
      assert(result.ok, 'actual snapshot bridge succeeds')
      return { messages: result.result.messages.items }
    }

    const seed = JSON.parse(readFileSync(join(root, 'resume-seed.json'), 'utf8')) as { request_id: string; message_id: string }
    await until(() => run('Boolean(document.querySelector(".resume-banner"))'), 'preserved real checkpoint banner')
    const beforeResume = (await snapshot()).messages.filter((m) => m.role === 'user')
    assert.deepEqual(beforeResume.map((m) => m.id), [seed.message_id])
    await send('continue')
    await idle()
    await until(async () => events.some((event) => event.type === 'request.started' && event.payload.request_id === seed.request_id && event.payload.generation === 2), 'typed resume same request generation 2')
    const typedResume = await bridge<{ ok: boolean; result: ConversationSnapshot }>('snapshotConversation', { conversation_id: cid })
    assert(typedResume.ok)
    assert(typedResume.result.recent.some((r) => r.request_id === seed.request_id && r.generation === 2 && r.outcome === 'completed'))
    assert.deepEqual(typedResume.result.messages.items.filter((m) => m.role === 'user').map((m) => m.id), [seed.message_id])
    assert(!await run('Array.from(document.querySelectorAll(".msg.user"), m => m.innerText).includes("continue")'), 'no optimistic continue bubble remains')
    evidence.typedResume = { request_id: seed.request_id, generation: 2, userMessages: 1 }
    await record('Typed continue resumes original request', '.message-scroll')
    // No preserved work remains: now the same trigger is an ordinary user message.
    await send('continue')
    await idle()
    const ordinaryContinue = (await snapshot()).messages.find((m) => m.role === 'user' && m.text === 'continue')
    assert(ordinaryContinue && ordinaryContinue.request_id !== seed.request_id, 'continue without checkpoint is an ordinary fresh send')
    evidence.ordinaryContinue = ordinaryContinue
    await send('[reply] smoke-search-needle')
    await idle()
    const replyRequest = (await snapshot()).messages.find((m) => m.role === 'user' && m.text === '[reply] smoke-search-needle')?.request_id
    assert(replyRequest, 'reply request is admitted under a real user message')
    await until(async () => (await snapshot()).messages.some((m) => m.role === 'assistant' && m.request_id === replyRequest), 'D9 committed reply')
    const replied = (await snapshot()).messages.find((m) => m.role === 'assistant' && m.request_id === replyRequest)!
    assert(replied.text, 'reply is a real committed request-bound assistant message')
    await until(() => run(`document.getElementById(${JSON.stringify(`m-${replied.id}`)})?.innerText.includes('Canned provider reply:') ?? false`), 'exact committed reply rendered')
    evidence.guardedReply = replied
    await record('Guarded reply', '.message-scroll')

    await send('[paged-tool]')
    await until(() => run('document.querySelectorAll(".tools-toggle").length > 0'), 'real tool card')
    await idle()
    await click('.tools-toggle')
    await until(() => run('Boolean(document.querySelector(".tool-row"))'), 'tool row')
    await click('.tool-row')
    await until(async () => (await text('.tool-detail')).includes('preview') || await run<boolean>('Boolean(document.querySelector(".tool-output button"))'), 'real tool details')
    let pages = 0
    if (await run('Boolean(document.querySelector(".tool-output button"))')) {
      await click('.tool-output button')
      await until(() => run('Boolean(document.querySelector(".tool-output pre"))'), 'retained first page')
      pages = 1
    }
    while (await run('Boolean(document.querySelector(".tool-output button:not([aria-disabled=true])"))')) {
      assert(pages < 20, 'paging must reach EOF')
      const old = await run<number>('document.querySelector(".tool-output pre").innerText.length')
      await click('.tool-output button')
      await until(() => run(`document.querySelector('.tool-output button')?.textContent.includes('All output loaded') || document.querySelector('.tool-output pre').innerText.length > ${old}`), 'retained next page')
      pages++
    }
    evidence.outputPaging = { pages, finalLength: await run<number>('document.querySelector(".tool-output pre")?.innerText.length ?? 0'),
      ...(pages === 0 ? { limitation: 'Real core tool.detail supplied preview only, no retained output cursor; rendered paging unavailable.' } : {}) }
    assert(pages > 1, 'canned retained output must exercise multiple real pages')
    const fullOutput = await text('.tool-output pre')
    assert(fullOutput.includes('Evidence line 0000:') && fullOutput.includes('Evidence line 0899:'), 'paging reaches both ends of real retained evidence')
    assert.equal(fullOutput.match(/Evidence line 0000:/g)?.length, 1, 'paging never appends the first page twice')
    await record('Tool details and retained output', '.tool-detail')
    await click('.tools-toggle')

    const attachment = join(root, 'smoke-upload.txt')
    writeFileSync(attachment, 'Real adapter chunked upload smoke.\n'.repeat(20_000))
    assert(status.capabilities.includes('attachments.chunk'))
    evidence.attachmentTransfer = { bytes: 700_000, chunkBytes: (response.result as typeof status & { limits: { chunk_bytes: number } }).limits.chunk_bytes,
      selection: 'main-injected disposable file picker; actual Attach UI and app adapter' }
    assert((evidence.attachmentTransfer as { chunkBytes: number }).chunkBytes < 700_000, 'attachment requires multiple protocol chunks')
    // Main-only selection. Stage/begin/chunk/commit/request claim remain real.
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [attachment] })) as typeof dialog.showOpenDialog
    await click('button[aria-label="Attach files"]')
    await until(() => run('Boolean(document.querySelector(".attachment.ready"))'), 'actual chunked attachment commit')
    await record('Attachment committed through app adapter', '.attachments')
    dialog.showOpenDialog = originalOpen
    await send('[reply] attachment receipt')
    await until(async () => (await text('.msg-attachments')).includes('smoke-upload.txt'), 'posted attachment')
    await idle()
    const attached = (await snapshot()).messages.find((m) => m.attachments?.length)
    assert(attached?.attachments?.length === 1, 'durable message claims committed attachment')
    evidence.attachment = attached

    await send('[artifact]')
    await until(() => run('Boolean(document.querySelector(".msg .file-card"))'), 'real posted file')
    await idle()
    const saved = join(root, 'saved-artifact.txt')
    dialog.showSaveDialog = (async () => ({ canceled: false, filePath: saved })) as typeof dialog.showSaveDialog
    await click('.msg .file-card .file-actions button:nth-child(2)')
    await until(async () => (await text('.msg .file-card')).includes('Saved contract.txt.'), 'actual artifact save bridge')
    assert(readFileSync(saved).length > 0, 'artifact downloaded into disposable path')
    dialog.showSaveDialog = originalSave
    await record('Posted file and download', '.msg .file-card')
    await until(() => run('Boolean(document.querySelector(".artifact-image img"))'), 'posted image through actual artifact adapter')
    evidence.postedImage = await run('document.querySelector(".artifact-image img")?.complete && document.querySelector(".artifact-image img")?.naturalWidth > 0')
    assert(evidence.postedImage, 'posted image really decodes')

    await send('[fail]')
    await until(async () => (await snapshot()).messages.some((m) => m.text === '[fail]'), 'failure request admitted')
    await idle()
    const failedMessages = (await snapshot()).messages
    const failedRequest = failedMessages.filter((m) => m.role === 'user' && m.text === '[fail]').at(-1)?.request_id
    const failureState = await bridge<{ ok: boolean; result: { recent: Array<{ request_id: string; outcome: string }> } }>('snapshotConversation', { conversation_id: cid })
    assert(failureState.ok && failureState.result.recent.some((r) => r.request_id === failedRequest && r.outcome === 'failed'), 'provider failure is a real terminal failure')
    evidence.providerFailureRendered = failedMessages.filter((m) => m.request_id === failedRequest)
    await until(async () => (await snapshot()).messages.some((m) => m.role === 'assistant' && m.request_id === failedRequest), 'guarded provider error committed')
    const failure = (await snapshot()).messages.find((m) => m.role === 'assistant' && m.request_id === failedRequest && /fail|error|couldn't|unable/i.test(m.text))
    assert(failure, 'HTTP provider failure must commit its actual guarded error reply')
    await until(() => run(`(() => { const body = document.getElementById(${JSON.stringify(`m-${failure.id}`)})?.innerText ?? ''; return body.includes('LLM API error') && body.includes('canned_failure'); })()`), 'exact committed provider error rendered')
    evidence.guardedProviderError = failure
    // The fresh management lane separately asserts the missing-provider notice.
    // Do not relabel this engine-owned guarded reply as a notice.
    await record('Provider failure outcome', '.message-scroll')
    const beforeDisable = await broker.request('settings.schema')
    assert(beforeDisable.ok)
    const disable = await broker.request('providers.compat.set', { expected_revision: (beforeDisable.result as { revision: string }).revision,
      changes: [{ path: 'openai_compatible.enabled', value: false }] })
    assert(disable.ok)
    await send('smoke missing selected provider')
    await idle()
    const noProviderUser = (await snapshot()).messages.find((m) => m.role === 'user' && m.text === 'smoke missing selected provider')!
    await until(async () => (await snapshot()).messages.some((m) => m.role === 'notice' && m.request_id === noProviderUser.request_id), 'provider failure notice committed')
    const noProviderNotice = (await snapshot()).messages.find((m) => m.role === 'notice' && m.request_id === noProviderUser.request_id)
    assert.equal(noProviderNotice?.text, 'No LLM provider available. Please try again later.')
    await until(async () => (await text('.message-scroll')).includes(noProviderNotice!.text), 'actual committed provider failure notice rendered')
    evidence.failureNotice = noProviderNotice
    await configureCannedProvider(broker, process.env.ODIN_SMOKE_PROVIDER_BASE_URL!)
    await send('[hold-stop]')
    await until(() => run('Boolean(document.querySelector(".composer button.danger"))'), 'running Stop control')
    const stopTarget = await bridge<{ ok: boolean; result: { running: { request_id: string; generation: number } | null } }>('snapshotConversation', { conversation_id: cid })
    assert(stopTarget.ok && stopTarget.result.running, 'Stop bound to real running request')
    const stopId = stopTarget.result.running.request_id
    await click('.composer button.danger')
    await idle()
    await record('Stop receipt and outcome', '.message-scroll')
    await until(async () => events.some((e) => /request\.(?:cancelled|interrupted|suspended)/.test(e.type) && e.payload.request_id === stopId), 'Stop terminal event for exact request')
    evidence.stoppedRequest = stopTarget.result.running
    const stoppedSnapshot = await bridge<{ ok: boolean; result: { recent: Array<{ request_id: string; generation: number }> } }>('snapshotConversation', { conversation_id: cid })
    assert(stoppedSnapshot.ok)
    const stopped = stoppedSnapshot.result.recent.at(-1)!
    const resume = await bridge<{ ok: boolean; result?: { disposition: string; reason?: string }; error?: unknown }>('resumeRequest', {
      control_command_id: randomUUID(), conversation_id: cid, request_id: stopped.request_id, generation: stopped.generation
    })
    evidence.resumeWithoutCheckpoint = resume
    assert(resume.ok && resume.result?.disposition === 'rejected' && resume.result.reason === 'not_resumable', `Resume must honestly deny a terminal cancelled task: ${JSON.stringify(resume)}`)

    await send('[hold-steer]')
    await until(() => run('Boolean(document.querySelector(".composer button.danger"))'), 'running Steer control')
    const steerTarget = await bridge<{ ok: boolean; result: { running: { request_id: string; generation: number } | null } }>('snapshotConversation', { conversation_id: cid })
    assert(steerTarget.ok && steerTarget.result.running)
    const queueStart = events.length
    await click('.composer input[value="queue"]')
    await send('[reply] queued smoke follow-up')
    await until(async () => events.slice(queueStart).some((e) => e.type === 'request.queued' && e.payload.conversation_id === cid), 'real queued follow-up')
    await click('.composer input[value="steer"]')
    await send('smoke steering instruction')
    await until(async () => /waiting for Odin|Odin has read|not used/.test(await text('.message-scroll')), 'Steer receipt')
    await record('Steer receipt before release', '.message-scroll')
    assert(process.env.ODIN_SMOKE_PROVIDER_BASE_URL?.startsWith('http://127.0.0.1:'), 'loopback only')
    const released = await fetch(new URL('/release', process.env.ODIN_SMOKE_PROVIDER_BASE_URL), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: '[hold-steer]' })
    })
    assert(released.ok, 'held response release')
    await idle()
    await until(async () => events.some((e) => e.type === 'control.receipt' && e.payload.disposition === 'consumed' && e.payload.request_id === steerTarget.result.running!.request_id), 'Steer consumed for exact request')
    evidence.steeredRequest = steerTarget.result.running
    evidence.queuedFollowup = (await snapshot()).messages.find((m) => m.text === '[reply] queued smoke follow-up')

    await click('button[title="Search all conversations (Ctrl+Shift+F)"]')
    await setInput('.search-form input', 'smoke-search-needle')
    await run('document.querySelector(".search-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))')
    await until(() => run('document.querySelectorAll(".search-hits .hit").length > 0'), 'real search')
    await record('Real search', '.search-panel')
    await click('.search-hits .hit')
    await until(() => run('Boolean(document.querySelector(".msg.highlight"))'), 'jump to real message')
    await click('button[aria-label="Close search"]')
    if (await run('Boolean(document.querySelector(".jump-banner button"))')) await click('.jump-banner button')
    await click('.conv-row .conv-more')
    await click('.menu button:nth-child(5)')
    await until(() => run('Boolean(document.querySelector(".dialog"))'), 'existing reset confirmation')
    await click('.dialog button[type=submit]')
    await until(() => run('document.querySelector(".message-scroll")?.textContent.includes("Model context reset.") ?? false'), 'context reset boundary')
    evidence.resetNotice = (await snapshot()).messages.find((m) => m.text === 'Model context reset.')
    assert(evidence.resetNotice, 'reset boundary persists')
    await record('Context reset retaining history', '.message-scroll')
    await click('.conv-row .conv-more')
    await click('.menu button:first-child')
    await until(() => run('Boolean(document.querySelector(".dialog input"))'), 'rename dialog')
    await setInput('.dialog input', 'Real smoke conversation')
    await click('.dialog button[type=submit]')
    await until(async () => (await text('.conv-title')).includes('Real smoke conversation'), 'real rename')
    const child = await bridge<{ ok: boolean; result: { conversation: { id: string; rev: number; parent_id: string; inherited_from: unknown } } }>('createConversation', {
      command_id: randomUUID(), title: 'Disposable smoke child', parent_id: cid, from_message_id: replied.id
    })
    assert(child.ok && child.result.conversation.parent_id === cid && child.result.conversation.inherited_from, `real child inheritance: ${JSON.stringify(child)}`)
    const archived = await bridge<{ ok: boolean; result: { conversation: { rev: number; archived: boolean } } }>('updateConversation', {
      command_id: randomUUID(), id: child.result.conversation.id, expected_rev: child.result.conversation.rev, archived: true
    })
    assert(archived.ok && archived.result.conversation.archived, 'real archive')
    const unarchived = await bridge<{ ok: boolean; result: { conversation: { rev: number; archived: boolean } } }>('updateConversation', {
      command_id: randomUUID(), id: child.result.conversation.id, expected_rev: archived.result.conversation.rev, archived: false
    })
    assert(unarchived.ok && !unarchived.result.conversation.archived, 'real unarchive')
    const deleted = await bridge<{ ok: boolean }>('deleteConversation', {
      command_id: randomUUID(), id: child.result.conversation.id, expected_rev: unarchived.result.conversation.rev
    })
    assert(deleted.ok, 'real child deletion')
    evidence.conversationLifecycle = { rename: 'rendered dialog', child: child.result.conversation, archived: true, unarchived: true, deleted: true }
    writeFileSync(out, (await win.webContents.capturePage()).toPNG())

    await click('.work-toggle')
    await until(async () => unavailable.test(await text('.work-panel')), 'honest unserved Work')
    assert.equal(await run('document.querySelectorAll(".work-item").length'), 0)
    await record('Unserved Work', '.work-panel')
    assert.equal(broker.linkState, 'ready')
    Object.assign(evidence, { link: broker.linkState, screens, events })
    writeFileSync(out.replace(/\.png$/i, '') + '-evidence.json', JSON.stringify(evidence, null, 2) + '\n')
    process.stdout.write(`real-core-smoke: ok link=ready version=${status.version} screens=${screens.length} output-pages=${pages}\n`)
  } catch (error) {
    Object.assign(evidence, { error: String(error), screens, events, renderedPage: await text('body').catch(() => '') })
    writeFileSync(out, (await win.webContents.capturePage()).toPNG())
    writeFileSync(out.replace(/\.png$/i, '') + '-evidence.json', JSON.stringify(evidence, null, 2) + '\n')
    throw error
  } finally {
    dialog.showOpenDialog = originalOpen
    dialog.showSaveDialog = originalSave
    broker.off('event', observe)
  }
  // Preserve main's fresh-profile management, unavailable provider and search gates
  // before the provider-backed workflow adds real logs, messages and usage.
  async function qualifyFreshManagement(): Promise<void> {
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
  await recordUnavailable('Work', '.work-panel')
  assert.equal(await run('document.querySelectorAll(".work-item").length'), 0)
  writeFileSync(out, (await win.webContents.capturePage()).toPNG())

  await click('button[title="Settings (Ctrl+,)"]')
  await until(async () => (await run<number>('document.querySelectorAll(".settings-nav-item").length')) > 1, 'settings navigation')
  await until(async () => (await count('.settings-group .schema-form')) > 0, 'real settings schema before enumerating all sections')
  const sections = await run<string[]>('Array.from(document.querySelectorAll(".settings-nav-item"), b => b.innerText)')
  assert.deepEqual(sections, ['General', 'Models and providers', 'Personality', 'Tools', 'Skills', 'MCP servers', 'Hosts and trust', 'Scheduled and running work', 'State', 'Records', 'Other'])
  // Check unserved work owners separately from the wired Step 6A read panels.
  const servicePanels: Record<string, string[]> = {
    'Scheduled and running work': ['section[aria-label="Schedules"]', 'section[aria-label="Running work"]']
  }
  const servedPanels: Record<string, Array<[string, RegExp]>> = {
    'Models and providers': [['.codex-accounts', /keyring.*(?:locked|unavailable)/i]],
    Personality: [['section[aria-label="Personality"]', /preset|personality/i]],
    Tools: [['section[aria-label="Built-in tools"]', /run_command/], ['section[aria-label="Tool timeouts"]', /Default|seconds/i]],
    Skills: [['section[aria-label="Skills"]', /New skill/]],
    'MCP servers': [['section[aria-label="MCP"]', /0 of 0 servers connected.*0 tools offered/s], ['section[aria-label="MCP servers"]', /Add server/]],
    'Hosts and trust': [['section[aria-label="Hosts"]', /localhost/]],
    State: [['section[aria-label="Memory"]', /0 entries/], ['section[aria-label="Named lists"]', /No lists\./], ['section[aria-label="Knowledge"]', /Knowledge/]],
    Records: [['section[aria-label="Health"]', /healthy.*degraded.*down.*not set up/s], ['section[aria-label="Usage"]', /not measured: Odin doesn't know this value/], ['section[aria-label="Audit"]', /Nothing recorded\./], ['section[aria-label="Logs"]', /No entries\./], ['section[aria-label="Turn state"]', /Turn state is off\./], ['section[aria-label="Computer use"]', /Refresh/]]
  }
  const observations = await run<Record<string, { ok: boolean; result?: unknown; error?: { code: string; message: string } }>>(`(async () => ({
    settings: await window.odin.settingsSchema(), hosts: await window.odin.hostsList({}),
    key: await window.odin.hostsPublicKey({}), tools: await window.odin.toolsList({}),
    timeouts: await window.odin.toolsTimeoutsGet({}), personality: await window.odin.personalityGet({}),
    memory: await window.odin.memoryList({}), lists: await window.odin.listsList({}),
    knowledge: await window.odin.knowledgeList({}), audit: await window.odin.auditQuery({}),
    logs: await window.odin.logsSearch({ level: 'all' }), turns: await window.odin.turnStateList({}),
    usage: await window.odin.usage('7d'), accounts: await window.odin.codexAccounts(),
    skills: await window.odin.skillsList({}), mcp: await window.odin.mcpStatus({}),
    computer: await window.odin.computerStatus({})
  }))()`)
  for (const [name, answer] of Object.entries(observations)) {
    if (name === 'accounts') {
      assert(answer.ok || answer.error?.code === 'keyring_unavailable', 'accounts must report empty accounts or distinct keyring failure')
    } else assert(answer.ok, `named bridge ${name} failed: ${JSON.stringify(answer.error)}`)
  }
  const hostData = observations.hosts!.result as { hosts: Array<{ alias: string; trust_state: string }>; default_host: string }
  assert.equal(hostData.hosts.length, 1, 'fresh core must have only its actual local host')
  assert.equal(hostData.hosts[0]!.alias, 'localhost')
  assert.equal(hostData.hosts[0]!.trust_state, 'local')
  assert.equal(hostData.default_host, 'localhost')
  assert.deepEqual(observations.audit!.result, [], 'fresh audit must have no invented tool records')
  assert.deepEqual(observations.skills!.result, reads['skills.list'])
  assert.deepEqual(observations.mcp!.result, reads['mcp.status'])
  assert.deepEqual(observations.computer!.result, reads['computer.status'])
  assert.deepEqual((observations.logs!.result as { entries: unknown[] }).entries, [])
  assert.equal((observations.turns!.result as { availability: string }).availability, 'not_enabled')
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
      assert((await text('section[aria-label="Health"]')).includes('host(s) configured'), 'real health must observe profile hosts')
      // The legacy Records renderer still expects a flat session shape. Prove
      // the served read/refresh and absence of session controls, not a usable
      // native surface or an invented enabled/state projection.
      assert.equal(await count('section[aria-label="Computer use"] .manage-name, section[aria-label="Computer use"] .manage-actions'), 0, 'fresh computer management must not invent a session or recovery action')
    }
    if (sections[i] === 'Skills' || sections[i] === 'MCP servers') {
      assert.equal(await count('.settings-body .manage-row'), 0, 'fresh Step 6A management must not display fixture skills or servers')
      assert.equal(await count('.settings-body .warn'), 0, 'served Step 6A reads must not present a renderer fault')
    }
    assert.equal(await run('document.querySelectorAll(".settings-body [role=alert]").length'), 0, `${sections[i]} must not present capability refusal as a fault`)
    assert.equal(await run('document.querySelectorAll(".settings-body .work-item, .settings-body .account").length'), 0, `${sections[i]} must not display fixture accounts/work`)
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
  // Keep provider failure after the fresh management/empty-log checkpoints:
  // executing a real request legitimately records its failure in core logs.
  await click('.settings-nav .back')
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
  Object.assign(evidence, { freshStatus: status, reads, observations })
  }
}
