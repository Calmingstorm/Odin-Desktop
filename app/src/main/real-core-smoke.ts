// Development-only proof through the rendered app and named preload bridge.
import { strict as assert } from 'node:assert'
import { randomUUID } from 'node:crypto'
import { existsSync, readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { app, dialog, type BrowserWindow } from 'electron'
import type { Broker } from './broker'
import type { ConversationSnapshot, ScheduleRow, WebhookIngressStatus } from '../shared/api'
import type { ConfigField } from '../shared/api'
import { reportPlainText } from '../shared/report-text'
import { assertAdvancedInventory, advancedPresentation } from './advanced-capture-contract'

const pause = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))
interface SmokeMessage { id: string; role: string; text: string; request_id?: string; attachments?: unknown[]; artifacts?: unknown[] }

// Structured members edit their enclosing schema record, not invented scalar leaves.
export function renderedSettingPath(id: string, ownerId: string | null): string {
  const prefix = 'settings-curated-'
  const recordPrefix = `${prefix}record-`
  assert(id.startsWith(prefix), 'expected a curated settings control')
  if (!id.startsWith(recordPrefix)) return decodeURIComponent(id.slice(prefix.length))
  assert(ownerId && ownerId.startsWith(prefix) && !ownerId.startsWith(recordPrefix), 'structured control must have an authoritative parent')
  const parent = decodeURIComponent(ownerId.slice(prefix.length))
  const child = decodeURIComponent(id.slice(recordPrefix.length))
  assert(child.startsWith(`${parent}.`), 'structured control must retain its parent ownership')
  return parent
}

// Reviewed conversation/request, management and background surface; never derive expectations from welcome.
export const realCoreCapabilities = ['status.get', 'events.subscribe', 'runtime.shutdown', 'submission.send', 'notifications.ack', ...[
  'attachments.begin', 'attachments.chunk', 'attachments.commit', 'attachments.cancel',
  'artifacts.read', 'tool.detail', 'tool.output',
  'conversations.list', 'conversations.create', 'conversations.update', 'conversations.delete',
  'conversations.reset_context', 'conversations.mark_read', 'messages.list',
  'conversation.snapshot', 'search.query', 'messages.around',
  'settings.schema', 'settings.set', 'secrets.set', 'secrets.clear', 'secrets.unlock', 'models.image.intent',
  'providers.codex.set', 'providers.auxiliary.set', 'providers.ollama.set', 'providers.compat.set',
  'codex.accounts.list', 'codex.accounts.activate', 'codex.accounts.remove', 'codex.accounts.label', 'codex.accounts.refresh', 'codex.login.begin', 'codex.login.poll',
  'hosts.list', 'hosts.settings', 'hosts.prepare', 'hosts.test', 'hosts.commit', 'hosts.set_enabled', 'hosts.references', 'hosts.delete', 'hosts.public_key', 'hosts.force_revoke', 'hosts.import_legacy',
  'memory.list', 'memory.get', 'memory.set', 'memory.delete', 'memory.bulk_delete', 'lists.list', 'lists.get', 'lists.delete',
  'knowledge.list', 'knowledge.search', 'knowledge.ingest', 'knowledge.reingest', 'knowledge.delete', 'knowledge.versions', 'knowledge.restore', 'knowledge.import',
  'knowledge.chunks', 'knowledge.duplicates', 'knowledge.merge', 'knowledge.version', 'knowledge.diff',
  'learned.list', 'learned.update', 'learned.delete',
  'audit.query', 'audit.verify', 'health.get', 'logs.search', 'turn_state.list', 'usage.get', 'runtime.reload',
  'audit.diffs', 'audit.failures', 'audit.tail', 'logs.stats', 'logs.tail',
  'trajectories.list', 'trajectories.read', 'trajectories.search', 'trajectories.message',
  'observability.stats', 'observability.tools', 'observability.risk', 'observability.risk_recent',
  'observability.governor', 'observability.audit_risk', 'observability.freshness',
  'observability.freshness_recent', 'observability.bulkheads', 'observability.compression',
  'observability.validation', 'observability.affordances', 'observability.context',
  'observability.usage', 'observability.usage_totals', 'observability.subsystems',
  'recovery.stats', 'recovery.recent', 'capacity.snapshot', 'turn_state.snapshot',
  'pools.ssh', 'pools.http', 'pools.close',
  'openrouter.catalogue', 'openrouter.endpoints', 'openrouter.select',
  'providers.compat.diagnostic', 'models.status', 'models.provider.get', 'models.provider.set',
  'models.main.set', 'models.agents.get', 'models.agents.set', 'models.discover', 'personality.get', 'personality.set', 'personality.presets.save', 'personality.presets.delete',
  'tools.list', 'tools.set_enabled', 'tools.timeouts.get', 'tools.timeouts.set',
  'control.stop', 'control.steer', 'control.resume', 'effects.acknowledge',
  'work.list', 'work.control', 'reports.page',
  'schedules.list', 'schedules.save', 'schedules.delete', 'schedules.run',
  'schedules.reset_failures', 'schedules.history', 'schedules.validate_cron',
  'webhooks.outbound.list', 'webhooks.outbound.save', 'webhooks.outbound.delete', 'webhooks.outbound.test', 'integrations.email.get',
  'skills.list', 'skills.get', 'skills.validate', 'skills.save', 'skills.delete', 'skills.test',
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
  first_run: { state: string; reason: string; keyring_unavailable: boolean }; webhook_ingress: WebhookIngressStatus }

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
  // Inbound ingress is opt-in (D10): a fresh profile never listens.
  assert.deepEqual(status.webhook_ingress, { reason: 'disabled', address: null, eligible_schedules: 0, unknown_deliveries: 0 })
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
  const seededWorkProof = process.env.ODIN_SMOKE_WORK_PROOF === '1'
  const phase = seededWorkProof ? 'seeded work proof' : 'production entry / fresh real profile'
  const deadline = Date.now() + 30_000
  while (broker.linkState !== 'ready' || win.webContents.isLoading()) {
    assert(Date.now() < deadline, 'real-core smoke timed out waiting for the app and handshake')
    await pause(100)
  }
  const events: Array<{ type: string; payload: Record<string, unknown> }> = []
  const observe = (event: { type: string; payload: Record<string, unknown> }): void => { events.push(event) }
  broker.on('event', observe)
  const screens: Array<{ screen: string; text: string }> = []
  const evidence: Record<string, unknown> = {
    isolation: { home: 'throwaway', pidNamespace: 'private', display: 'xvfb' },
    ...(process.env.ODIN_SMOKE_PROVIDER_BASE_URL ? {
      provider: 'canned loopback OpenAI-compatible, real provider client, no accounts',
      limitations: ['File/save chooser selections injected in main under isolation; native chooser UI not tested.',
        'No default-app launch or folder reveal. Resume without a durable checkpoint not claimed successful.']
    } : {})
  }
  const proofPath = join(process.env.HOME!, 'work-proof.json')
  if (seededWorkProof) {
    while (!existsSync(proofPath)) {
      assert(Date.now() < deadline, 'seeded work proof bootstrap did not settle')
      await pause(100)
    }
  } else {
    assert(!existsSync(proofPath), 'production entry must not import the seeded work proof')
  }
  const proof = seededWorkProof ? JSON.parse(readFileSync(proofPath, 'utf8')) as { conversation_id: string; report_id: string; recovery_id: string } : undefined
  const counts = (): unknown => Object.fromEntries(['background', 'report'].map(name =>
    [name, readFileSync(join(process.env.HOME!, `${name}-effects`), 'utf8').trim().split('\n').length]))
  const beforePaging = seededWorkProof ? counts() : undefined
  const result = await broker.request('status.get')
  assert(result.ok, 'real status.get must succeed')
  const status = result.result as RealCoreStatus
  if (!process.env.ODIN_SMOKE_PROVIDER_BASE_URL) assertFreshManagementStatus(status, seededWorkProof)
  assert.equal(status.core_instance_id, broker.coreInstanceId)
  // One version number: the engine reports the release it shipped in.
  assert.equal(status.version, process.env.ODIN_SMOKE_EXPECT_VERSION ?? app.getVersion())
  for (const method of ['status.get', 'events.subscribe', 'runtime.shutdown', 'settings.schema', 'settings.set',
    'conversations.list', 'conversations.create', 'messages.list', 'conversation.snapshot', 'search.query',
    'submission.send', 'control.stop', 'control.steer', 'control.resume',
    'tools.list', 'tools.timeouts.get', 'personality.get', 'hosts.list', 'hosts.public_key',
    'memory.get', 'lists.list', 'knowledge.list', 'audit.query', 'logs.search', 'turn_state.list', 'usage.get',
    'conversations.list', 'conversations.create', 'conversation.snapshot', 'search.query', 'submission.send',
    'control.stop', 'control.steer', 'control.resume', 'attachments.begin', 'attachments.chunk',
    'attachments.commit', 'attachments.cancel', 'audit.diffs', 'audit.failures', 'audit.tail', 'logs.stats',
    'logs.tail', 'knowledge.chunks', 'knowledge.duplicates', 'knowledge.version', 'knowledge.diff',
    'learned.list', 'observability.stats', 'observability.risk', 'openrouter.catalogue', 'trajectories.list',
    'skills.list', 'skills.save', 'skills.validate', 'skills.test', 'mcp.status', 'mcp.save', 'mcp.tools', 'computer.status', 'computer.reconcile',
    'work.list', 'work.control', 'reports.page', 'schedules.list', 'schedules.run', 'schedules.history']) {
    assert(status.capabilities.includes(method), `${method} must be published by the real management core`)
  }

  // Raw dispatch aliases and foreground input remain genuine refusals. Served
  // work management does not grant arbitrary RPC execution or native input.
  for (const method of ['turns.create',
    'loops.list', 'agents.list', 'shell.execute', 'computer_act']) {
    assert(!status.capabilities.includes(method), `${method} must not be advertised as served`)
    const refused = await broker.request(method)
    assert(!refused.ok && refused.error.code === 'capability_unavailable', `${method} must honestly refuse`)
  }

  // Odin starts its usage backfill at boot. Settle it once, so every read and
  // panel below sees one coverage state instead of racing the first pass.
  const settleBy = Date.now() + 15_000
  for (;;) {
    const usage = await broker.request('observability.usage')
    assert(usage.ok, 'observability.usage management read must succeed')
    if ((usage.result as { coverage?: { backfill_complete?: unknown } }).coverage?.backfill_complete === true) break
    assert(Date.now() < settleBy, 'usage backfill must complete within 15 s of startup')
    await pause(100)
  }
  const reads: Record<string, unknown> = {}
  for (const method of ['settings.schema', 'usage.get', 'personality.get', 'tools.list', 'tools.timeouts.get', 'hosts.list', 'memory.list', 'lists.list', 'knowledge.list', 'health.get', 'audit.query', 'logs.search', 'turn_state.list', 'skills.list', 'mcp.list', 'mcp.status', 'computer.status', 'work.list', 'schedules.list', 'schedules.history']) {
    const answer = await broker.request(method)
    assert(answer.ok, `${method} management read must succeed`)
    reads[method] = answer.result
  }
  const accounts = await broker.request('codex.accounts.list')
  if (!process.env.ODIN_SMOKE_PROVIDER_BASE_URL) {
    if (seededWorkProof) {
      // The seeded bootstrap's ephemeral keyring serves the actual empty account store.
      assert(accounts.ok, 'ephemeral keyring must serve the actual empty account store')
      assert.deepEqual(accounts.result, { configured: false, accounts: [] })
    } else assert(!accounts.ok && accounts.error.code === 'keyring_unavailable', 'fresh profile must report missing keyring')
  }
  reads['codex.accounts.list'] = accounts
  assert.deepEqual(reads['lists.list'], { items: [] })
  if (!seededWorkProof) assert.deepEqual(reads['work.list'], { items: [] })
  if (!seededWorkProof) {
    // The seeded pass deliberately holds D12 schedules and their history.
    assert.deepEqual(reads['schedules.list'], [])
    assert.deepEqual(reads['schedules.history'], [])
  }
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
    if (!seededWorkProof) {
      assert.deepEqual(reads['audit.query'], [])
      assert.deepEqual(reads['logs.search'], { entries: [], count: 0 })
    }
    assert.equal((reads['turn_state.list'] as { availability: string }).availability, 'available')
    assert.deepEqual((reads['usage.get'] as { tokens: unknown }).tokens, { value: 0, kind: 'measured' })
  }
  assert((reads['settings.schema'] as { fields: unknown[] }).fields.length > 0, 'real management schema must contain fields')

  const run = async <T = unknown>(script: string): Promise<T> => {
    try { return await win.webContents.executeJavaScript(script, true) as T }
    catch (error) { throw new Error(`UI assertion failed: ${script}: ${String(error)}`) }
  }
  const text = (selector: string): Promise<string> => run(`document.querySelector(${JSON.stringify(selector)})?.innerText ?? ''`)
  const count = (selector: string): Promise<number> => run(`document.querySelectorAll(${JSON.stringify(selector)}).length`)
  // Message bodies are committed DOM content. Off-screen messages use content-visibility,
  // which innerText omits until rendered, so message checks read textContent.
  const content = (selector: string): Promise<string> => run(`(document.querySelector(${JSON.stringify(selector)})?.textContent ?? '').replace(/\\s+/g, ' ').trim()`)
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
  if (seededWorkProof) {
    // Every captured screen carries its provenance, not just the console log.
    await run(`(() => {
      const label = document.createElement('div');
      label.textContent = 'seeded work proof | agent/process rows: metadata seeds, not execution qualification';
      label.style.cssText = 'position:fixed;bottom:0;left:0;right:0;z-index:2147483647;background:#221b00;color:#fff;padding:4px;font-size:12px;pointer-events:none';
      document.body.append(label);
    })()`)
  }
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
      description: 'Real ephemeral webhook reminder', action: 'reminder', channel_id: proof!.conversation_id,
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
    const transcript = await broker.request('conversation.snapshot', { conversation_id: proof!.conversation_id })
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

  let conversationId = ''
  if (!process.env.ODIN_SMOKE_PROVIDER_BASE_URL) {
  await until(async () => (await text('.status')).includes('Connected') &&
    await run<boolean>(`['Status', 'Usage'].every(label => Array.from(document.querySelectorAll('.status button')).some(e => e.textContent.trim() === label && !e.disabled))`), 'connected status bar and report actions')
  const compactStatus = await text('.status')
  assert(!compactStatus.includes(status.version), 'engine version belongs in General About, not the compact status bar')
  for (const provider of status.providers) {
    if (['degraded', 'unavailable', 'error', 'failed'].includes(provider.health)) {
      assert(compactStatus.includes(`${provider.name} ${provider.health}`), 'status bar must retain actionable provider failures')
    } else assert(!compactStatus.includes(`${provider.name} ${provider.health}`), 'status bar must omit routine provider badges')
  }
  screens.push({ screen: 'Status', text: await text('.status') })
  // The renderer creates Chat only after a successful empty list, then loads
  // an authoritative snapshot. A missing provider does not unserve chat.
  await until(async () => (await count('.conv-row')) === 1 && (await content('.message-scroll')).includes(seededWorkProof ? 'Harmless catch-up notice' : 'Ask Odin anything.') &&
    await run<boolean>('document.querySelector(".composer textarea")?.disabled === false'), 'real first conversation and snapshot')
  assert.equal(await text('.conv.active .conv-title'), 'Chat')
  assert.equal(await count('.sidebar-notice'), 0, 'served conversations must not claim unavailable')
  if (seededWorkProof) {
    assert((await count('.msg')) > 0, 'real background publication must appear in the transcript')
    assert(/Due:.*late by.*Omitted slots:/s.test(await content('.message-scroll')), 'real D12 reminder must show catch-up provenance')
    await until(async () => (await text('.report-body')).includes('produced once'), 'stored real report first page')
    await click('.report-nav button:nth-of-type(2)')
    await until(async () => (await text('.report-body')).includes('no rerun'), 'stored real report second page')
    assert.deepEqual(counts(), beforePaging, 'report paging must not execute the external tool again')
    screens.push({ screen: 'Stored report paging and D12 catch-up notice', text: await content('.message-scroll') })
    writeFileSync(out.replace(/\.png$/i, '') + '-report.png', (await win.webContents.capturePage()).toPNG())
  } else {
    assert.equal(await count('.msg'), 0, 'fresh real conversation must not seed fixture messages')
  }
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
  const emptyMessages = await broker.request('messages.list', { conversation_id: conversationId, limit: 100 })
  assert(emptyMessages.ok, 'real empty transcript must succeed')
  assert.deepEqual((emptyMessages.result as { items: unknown[] }).items, [])
  screens.push({ screen: 'Conversation sidebar', text: await text('nav[aria-label="Conversations"]') })

  // Both status-bar actions and slash commands remain useful without a provider.
  // Click the real retained buttons, not merely their labels.
  for (const report of ['Status', 'Usage']) {
    await run(`(() => { const button = Array.from(document.querySelectorAll('.status button')).find(b => b.textContent.trim() === ${JSON.stringify(report)}); if (!button || button.disabled) throw new Error('Missing enabled status report action'); button.click(); })()`)
    // The panel shows the core's report with its Markdown rendered.
    const expected = report === 'Status' ? status.version : reportPlainText((reads['usage.get'] as { summary: string }).summary)
    await until(async () => (await text('.composer .panel-text')).includes(expected), `status bar ${report} report`)
    screens.push({ screen: `Status bar / ${report}`, text: await text('.composer .panel-text') })
    await click('.composer .panel button')
  }
  // Exercise the actual command
  // palette and bridge; /status and /usage use real step-five observations,
  // with served usage measured once the boot backfill has settled.
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
      await until(async () => (await text('.composer .panel-text')).includes(reportPlainText(summary)), '/usage report')
      assert(await run<boolean>(`!Array.from(document.querySelectorAll('.status [role="status"]')).some(e => /Usage.*unavailable/i.test(e.textContent))`), 'served usage must not present capability refusal')
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
    await until(async () => (await text('.rail-link')).includes('Connected'), 'real ready connection indicator')
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
    // Compare message bodies: each user article also renders "You" and its submission state.
    assert(!await run('Array.from(document.querySelectorAll(".msg.user .body"), m => m.textContent.trim()).includes("continue")'), 'no optimistic continue bubble remains')
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
    await until(async () => (await text('.work-panel')).includes('No work'), 'served empty Work')
    assert.equal(await run('document.querySelectorAll(".work-item").length'), 0)
    await record('Empty Work', '.work-panel')
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
  assert.equal(await run('document.querySelectorAll(".search-hits li").length'), 0)
  const searched = await broker.request('search.query', { query: 'smoke query' })
  assert(searched.ok, 'real search must succeed')
  assert.deepEqual((searched.result as { hits: unknown[] }).hits, [])
  assert.equal((searched.result as { next_cursor: string | null }).next_cursor, null)
  screens.push({ screen: 'Search', text: await text('.search-panel') })
  await click('.work-toggle')
  let receipt: unknown
  if (seededWorkProof) {
    await until(async () => (await text('.work-panel')).includes('Harmless completed task') &&
      (await text('.work-panel')).includes('The outcome is not confirmed.'), 'real Work detail and honest unconfirmed outcome')
    const work = await broker.request('work.list')
    assert(work.ok)
    const workItems = (work.result as { items: Array<Record<string, unknown>> }).items
    assert.deepEqual(new Set(workItems.map(i => i.kind)), new Set(['agent', 'task', 'workflow', 'loop', 'process', 'schedule']))
    const cancellable = workItems.find(i => i.title === 'Harmless cancellable task')!
    const controlParams = Object.fromEntries(['kind', 'id', 'manager_generation', 'run_id', 'generation', 'conversation_id'].map(k => [k, cancellable[k]]))
    Object.assign(controlParams, { action: 'cancel', control_command_id: randomUUID() })
    const controlReceipt = await run<{ ok: boolean; result?: { disposition: string } }>(`window.odin.workControl(${JSON.stringify(controlParams)})`)
    receipt = controlReceipt
    assert(controlReceipt.ok)
    assert.equal(controlReceipt.result!.disposition, 'done')
    assert.deepEqual(await run(`window.odin.workControl(${JSON.stringify(controlParams)})`), controlReceipt, 'named bridge must return journaled receipt without repeating cancellation')
    await click('button[aria-label="Refresh work"]')
    // The cancelled task's own card: other seeded work may already read Stopped.
    const cancelledState = `.work-panel .work-state.cancelled[id$=${JSON.stringify(`-${encodeURIComponent(`${cancellable.kind}:${cancellable.id}`)}-state`)}]`
    await until(async () => (await text(cancelledState)) === 'Stopped', 'settled actual task after journaled cancellation')
    screens.push({ screen: 'Work all kinds (agent/process metadata seeds), settled task and journaled receipt', text: await text('.work-panel') })
  } else {
    const work = await broker.request('work.list')
    assert(work.ok, 'fresh work list must be served')
    assert.deepEqual((work.result as { items: unknown[] }).items, [], 'fresh profile must not invent work rows')
    await until(async () => (await text('.work-panel')).includes('No work'), 'fresh empty Work')
    assert.equal(await count('.work-item'), 0)
    screens.push({ screen: 'Fresh empty Work', text: await text('.work-panel') })
  }
  writeFileSync(out, (await win.webContents.capturePage()).toPNG())

  await click('button[title="Settings (Ctrl+,)"]')
  await until(async () => (await run<number>('document.querySelectorAll(".settings-nav-item").length')) > 1, 'settings navigation')
  await until(async () => (await count('[id="settings-curated-timezone"]')) === 1, 'real curated time zone before enumerating all sections')
  const sections = await run<string[]>('Array.from(document.querySelectorAll(".settings-nav-item"), b => b.innerText)')
  assert.deepEqual(sections, ['General', 'Models and providers', 'Personality', 'Tools', 'Skills', 'MCP servers', 'Hosts and access', 'Work', 'Data and privacy'])
  // Data and privacy owns both previous state/records surfaces. Advanced is
  // secondary access from General, never a tenth primary destination.
  const destinations = [...sections, 'Usage, logs and audit', 'Advanced settings']
  // Check unserved work owners separately from the wired Step 6A read panels.
  const servicePanels: Record<string, string[]> = {
  }
  const servedPanels: Record<string, Array<[string, RegExp]>> = {
    'Models and providers': [['.codex-accounts', seededWorkProof ? /No accounts\. Add an account to use Codex\./ : /keyring.*(?:locked|unavailable)/i]],
    Personality: [['section[aria-label="Personality"]', /preset|personality/i]],
    Tools: [['section[aria-label="Built-in tools"]', /run_command/], ['section[aria-label="Tool timeouts"]', /Default|seconds/i]],
    Skills: [['section[aria-label="Skills"]', /New skill/]],
    'MCP servers': [['section[aria-label="MCP"]', /1 of 1 servers connected.*1 tools available/s], ['section[aria-label="MCP servers"]', /Add server/]],
    'Hosts and access': [['section[aria-label="Hosts"]', /localhost/]],
    'Data and privacy': [['section[aria-label="Memory"]', /0 entries/], ['section[aria-label="Named lists"]', /No lists\./], ['section[aria-label="Knowledge"]', /Knowledge/]],
    'Usage, logs and audit': [['section[aria-label="Health"]', /healthy.*degraded.*down.*not set up/s], ['section[aria-label="Usage"]', /tokens in .*\(measured\)/], ['section[aria-label="Computer use"]', /Refresh/]]
  }
  const observations = await run<Record<string, { ok: boolean; result?: unknown; error?: { code: string; message: string } }>>(`(async () => ({
    settings: await window.odin.settingsSchema(), hosts: await window.odin.hostsList({}),
    key: await window.odin.hostsPublicKey({}), tools: await window.odin.toolsList({}),
    timeouts: await window.odin.toolsTimeoutsGet({}), personality: await window.odin.personalityGet({}),
    memory: await window.odin.memoryList({}), lists: await window.odin.listsList({}),
    knowledge: await window.odin.knowledgeList({}), audit: await window.odin.auditQuery({}),
    logs: await window.odin.logsSearch({ level: 'all' }), turns: await window.odin.turnStateList({}),
    usage: await window.odin.usage('7d'), accounts: await window.odin.codexAccounts(),
    conversations: await window.odin.listConversations(), search: await window.odin.search({ query: 'smoke query' }),
    snapshot: await window.odin.snapshotConversation({ conversation_id: ${JSON.stringify(conversationId)} }),
    diffs: await window.odin.auditDiffs({}), failures: await window.odin.auditFailures({}),
    logStats: await window.odin.logsStats({}), auditTail: await window.odin.auditTail({ lines: 20 }),
    logTail: await window.odin.logsTail({ lines: 20 }), duplicates: await window.odin.knowledgeDuplicates({}),
    learned: await window.odin.learnedList({}), stats: await window.odin.observabilityStats({}),
    risk: await window.odin.observabilityRisk({}), trajectories: await window.odin.trajectoriesList({}),
    openrouter: await window.odin.openrouterCatalogue({}),
    skills: await window.odin.skillsList({}), mcp: await window.odin.mcpStatus({}),
    computer: await window.odin.computerStatus({})
  }))()`)
  for (const [name, answer] of Object.entries(observations)) {
    if (name === 'accounts') {
      assert(answer.ok || answer.error?.code === 'keyring_unavailable', 'accounts must report empty accounts or distinct keyring failure')
      if (seededWorkProof) {
        assert(accounts.ok, 'ephemeral keyring must serve the actual empty account store')
        assert.deepEqual(answer.result, accounts.result, 'named bridge must read the same ephemeral account store')
      }
    } else if (name === 'openrouter') {
      assert(!answer.ok && answer.error?.code === 'not_found' && /not recognized/i.test(answer.error.message), 'fresh unconfigured OpenRouter must report not-recognized, not fake catalogue data')
    } else assert(answer.ok, `named bridge ${name} failed: ${JSON.stringify(answer.error)}`)
  }
  const hostData = observations.hosts!.result as { hosts: Array<{ alias: string; trust_state: string }>; default_host: string }
  assert.equal(hostData.hosts.length, 1, 'fresh core must have only its actual local host')
  assert.equal(hostData.hosts[0]!.alias, 'localhost')
  assert.equal(hostData.hosts[0]!.trust_state, 'local')
  assert.equal(hostData.default_host, 'localhost')
  if (seededWorkProof) {
    assert(Array.isArray(observations.audit!.result), 'audit must report actual local schedule/task records')
    assert(Array.isArray((observations.logs!.result as { entries: unknown[] }).entries), 'logs must read actual engine records')
  } else {
    assert.deepEqual(observations.audit!.result, [], 'fresh audit must have no invented tool records')
    assert.deepEqual((observations.logs!.result as { entries: unknown[] }).entries, [], 'fresh logs must have no invented entries')
  }
  assert.deepEqual(observations.skills!.result, reads['skills.list'])
  assert.deepEqual(observations.mcp!.result, reads['mcp.status'])
  assert.deepEqual(observations.computer!.result, reads['computer.status'])
  assert.equal((observations.turns!.result as { availability: string }).availability, 'available')
  if (!seededWorkProof) {
    assert.deepEqual(observations.duplicates!.result, { exact: [], near: [] }, 'fresh knowledge must have no invented duplicates')
    assert.deepEqual((observations.learned!.result as { entries: unknown[] }).entries, [])
    assert.deepEqual((observations.diffs!.result as { entries: unknown[] }).entries, [])
    assert.deepEqual((observations.trajectories!.result as { files: string[] }).files, [])
    assert.deepEqual((observations.search!.result as { hits: unknown[] }).hits, [])
    assert.equal((observations.conversations!.result as { items: unknown[] }).items.length, 2, 'only first Chat and explicitly created New chat may exist')
    for (const key of ['auditTail', 'logTail']) {
      const tail = observations[key]!.result as { lines: unknown[]; cursor: string; availability: string }
      assert.deepEqual(tail.lines, [], 'fresh records tails must not invent activity')
      assert.equal(typeof tail.cursor, 'string')
      assert(['available', 'missing'].includes(tail.availability), 'tail must distinguish an empty source from a missing file')
    }
    const noSubmission = observations.snapshot!.result as { messages: { items: unknown[] }; running: unknown; queued: unknown[]; recent: unknown[]; unresolved: unknown[] }
    assert.deepEqual(noSubmission.messages.items, [], 'local slash reports must not submit provider messages')
    assert.equal(noSubmission.running, null)
    assert.deepEqual(noSubmission.queued, [])
    assert.deepEqual(noSubmission.recent, [])
    assert.deepEqual(noSubmission.unresolved, [])
  }
  // All operations cross the named preload bridge. The fixture is local stdio,
  // implements initialize/tools-list, and has no account or network listener.
  const invoke = <T = unknown>(name: string, params: unknown = {}): Promise<T> =>
    run(`window.odin[${JSON.stringify(name)}](${JSON.stringify(params)})`)
  type Answer = { ok: boolean; result?: unknown; error?: { code: string; message: string } }
  const observedService = async (name: string, params: unknown = {}): Promise<unknown> => {
    const answer = await invoke<Answer>(name, params)
    assert(answer.ok, `${name}: ${JSON.stringify(answer.error)}`)
    observations[name] = answer
    return answer.result
  }
  const skillCode = readFileSync(process.env.ODIN_SMOKE_SKILL_FIXTURE!, 'utf8')
  const validation = await observedService('skillsValidate', { code: skillCode }) as { valid: boolean }
  assert(validation.valid, 'harmless constant must validate')
  await observedService('skillsSave', { name: 'slice4_constant', code: skillCode, create: true })
  const skill = await observedService('skillsGet', { name: 'slice4_constant' }) as { code: string }
  assert.equal(skill.code, skillCode)
  type SkillRow = { name: string; total_executions: number }
  const initialSkills = await observedService('skillsList') as SkillRow[]
  assert.equal(initialSkills.find((row) => row.name === 'slice4_constant')?.total_executions, 0)
  const tested = await observedService('skillsTest', { name: 'slice4_constant' }) as { result: string; is_error: boolean }
  assert.deepEqual(tested, { result: 'harmless constant', is_error: false }, 'named bridge must execute the harmless skill with empty input')
  const testedSkills = await observedService('skillsList') as SkillRow[]
  assert.equal(testedSkills.find((row) => row.name === 'slice4_constant')?.total_executions, 1, 'bridge Test must count a genuine execution')
  type McpStatus = { revision: string; server_count: number; servers: Array<{ name: string; state: string; published_count: number }> }
  const mcpMutation = async (name: string, params: Record<string, unknown>): Promise<void> => {
    const before = await observedService('mcpStatus') as McpStatus
    await observedService(name, { ...params, expected_revision: before.revision })
  }
  await mcpMutation('mcpSave', { name: 'slice4_local', transport: 'stdio', command: process.env.ODIN_DESKTOP_ENGINE_PYTHON, args: ['-B', process.env.ODIN_SMOKE_MCP_FIXTURE] })
  await mcpMutation('mcpSetGlobalEnabled', { enabled: true })
  await until(async () => (await observedService('mcpStatus') as McpStatus).servers.some((row) => row.name === 'slice4_local' && row.state === 'connected'), 'real stdio MCP handshake')
  const tools = await observedService('mcpTools', { name: 'slice4_local' }) as { tools: unknown[] }
  assert.equal(tools.tools.length, 1, 'real discovery must publish the constant tool')
  assert(JSON.stringify(tools.tools).includes('constant'))
  await mcpMutation('mcpRefreshTools', { name: 'slice4_local' })
  // Saving a server adds exact server-local settings fields. Compare rendered
  // paths with a fresh authoritative schema, never the pre-mutation snapshot.
  reads['settings.schema'] = await observedService('settingsSchema')
  const sliceComputer = await observedService('computerStatus') as { session: unknown; readiness: { input_supported: boolean; native_qualified: boolean } }
  assert.equal(sliceComputer.session, null)
  assert.equal(sliceComputer.readiness.input_supported, false)
  assert.equal(sliceComputer.readiness.native_qualified, false)
  const health = await observedService('healthGet') as { browser: { state: string; ready: boolean; retry_available: boolean } }
  // D17 fresh settings enable the browser; no bundle is qualified in this
  // source-tree profile. Preserve the unavailable retry seam, not native success.
  assert.deepEqual({ state: health.browser.state, ready: health.browser.ready, retry_available: health.browser.retry_available }, { state: 'unavailable', ready: false, retry_available: true })
  for (let i = 0; i < destinations.length; i++) {
    const destination = destinations[i]!
    if (i < sections.length) await click(`.settings-nav-item:nth-of-type(${i + 2})`)
    else if (destination === 'Usage, logs and audit') await click('.settings-subnav button:nth-of-type(3)')
    else {
      await click('.settings-nav-item:nth-of-type(2)')
      await run(`(() => { const buttons = Array.from(document.querySelectorAll('.settings-body button')).filter(b => b.textContent.trim() === 'Advanced settings'); if (buttons.length !== 1 || buttons[0].disabled) throw new Error('Expected one enabled Advanced settings button'); buttons[0].click(); })()`)
      await until(async () => (await count('[id="settings-curated-logging.level"]')) === 1, 'real secondary Advanced log detail')
    }
    if (destination === 'Models and providers') {
      await until(async () => (await count('[data-testid="codex-add-account"]')) === 1 &&
        await run<boolean>('document.querySelector("[data-testid=codex-add-account]")?.disabled === false'), 'served account management')
      await until(async () => !(await text('.codex-accounts')).includes('Loading'), 'real account observation')
      assert(!/not (?:yet )?available|not served/i.test(await text('.codex-accounts')), 'served account management must not remain capability-unavailable')
      assert.equal(await run('document.querySelectorAll(".account").length'), 0, 'real session must not display fixture accounts')
      await until(async () => (await count('[data-testid="configure-compat"]')) === 1, 'real curated provider configuration')
      await click('[data-testid="configure-compat"]')
      await until(async () => (await count('#provider-compat-setup')) === 1, 'expanded compatible-provider setup')
      await until(async () => /OpenRouter endpoint not recognized/i.test(await text('section[aria-label="OpenRouter models"]')), 'honest unconfigured OpenRouter panel')
      assert.equal(await count('section[aria-label="OpenRouter models"] li'), 0, 'unconfigured OpenRouter must not invent models')
    }
    if (destination === 'Personality') {
      await until(async () => await run<boolean>('Boolean(document.querySelector("section[aria-label=Personality] select"))'), 'real personality settings')
    }
    if (destination === 'Tools') {
      await until(async () => (await count('section[aria-label="Built-in tools"] .manage-row')) > 0, 'real built-in tools')
      await run(`(() => { const timeout = document.querySelector('section[aria-label="Tool timeouts"]'); const details = timeout?.closest('details'); if (!details) throw new Error('Timeouts must remain reachable under More options'); details.open = true; })()`)
      assert((await text('section[aria-label="Tool timeouts"]')).includes('Timeouts'))
      const tools = (observations.tools!.result as { tools: Array<{ name: string; cost?: string | null; risk?: string | null }> }).tools
      const rows = await run<Array<{ name: string; facts: string }>>('Array.from(document.querySelectorAll("section[aria-label=\\"Built-in tools\\"] .manage-row"), row => ({ name: row.querySelector(".manage-name")?.textContent.trim() ?? "", facts: row.querySelector(".panel-hint")?.textContent.trim() ?? "" }))')
      for (const tool of tools) {
        assert(rows.some((row) => row.name === tool.name &&
          (tool.cost ? row.facts.includes(`Cost: ${tool.cost}.`) : !row.facts.includes('Cost:')) &&
          (tool.risk ? row.facts.includes(`Risk: ${tool.risk}.`) : !row.facts.includes('Risk:'))), `${tool.name} must render its reported cost and risk without invented measurements`)
      }
      await until(async () => /unavailable/i.test(await text('section[aria-label="Browser runtime"]')), 'real unqualified browser state')
    }
    if (destination === 'Skills') {
      await until(async () => (await text('section[aria-label="Skills"]')).includes('slice4_constant'), 'real skill card')
      assert(!(await text('section[aria-label="Skills"]')).includes('Test is unavailable in this core.'), 'a capable core must not show Test unavailable')
      assert((await text('section[aria-label="Skills"] .manage-count')).includes('1 runs'), 'the card must show the bridge execution')
      await click('button[aria-label="Open slice4_constant"]')
      await until(async () => await run<boolean>('Boolean(document.querySelector(".skill-editor"))'), 'real skill editor')
      const testButton = '.skill-editor button[aria-label="Test slice4_constant"]'
      assert.equal(await run(`document.querySelector(${JSON.stringify(testButton)}).disabled`), false)
      await click(testButton)
      await until(async () => (await text('.skill-editor .manage-json')) === 'harmless constant', 'real rendered Test result')
      await until(async () => (await text('section[aria-label="Skills"] .manage-count')).includes('2 runs'), 'rendered execution count after UI Test')
      const afterUiTest = await observedService('skillsList') as SkillRow[]
      const runs = afterUiTest.find((row) => row.name === 'slice4_constant')?.total_executions
      assert.equal(runs, 2, 'one named-bridge Test and one UI Test must produce exactly two executions')
      assert.equal(await run('document.querySelector(".skill-editor .manage-json").classList.contains("warn")'), false)
      process.stdout.write(`real-core-smoke: skills.test result=${JSON.stringify(tested.result)} is_error=${tested.is_error} rendered=${JSON.stringify(await text('.skill-editor .manage-json'))} runs=${runs}\n`)
    }
    if (destination === 'MCP servers') {
      await until(async () => (await text('section[aria-label="MCP servers"]')).includes('slice4_local'), 'real MCP row')
      assert((await text('section[aria-label="MCP servers"]')).includes('connected'), 'MCP UI must show real handshake state')
      await click('button[aria-label="Tools for slice4_local"]')
      await until(async () => (await text('.mcp-tools')).includes('constant'), 'rendered real MCP tools disclosure')
    }
    if (destination === 'Work') {
      if (seededWorkProof) {
        await until(async () => (await text('section[aria-label="Schedules"]')).includes('D12 manual recovery check') &&
          (await text('section[aria-label="Schedules"]')).includes('Recovery required'), 'real D12 recovery-required schedule')
        assert((await text('section[aria-label="Schedules"]')).includes('No effects were replayed'), 'D12 must render actual recovery reason')
        await webhookSmoke()
      } else {
        const schedules = await broker.request('schedules.list')
        assert(schedules.ok, 'fresh schedules list must be served')
        assert.deepEqual(schedules.result, [], 'fresh profile must not invent schedules')
        await until(async () => (await text('section[aria-label="Schedules"]')).includes('No schedules yet.'), 'real empty schedules')
        await until(async () => (await text('section[aria-label="Running work"]')).includes('Nothing is running.'), 'real empty running work')
        assert.equal(await count('section[aria-label="Running work"] .work-item'), 0)
      }
    }
    if (destination === 'Hosts and access') {
      await until(async () => (await text('section[aria-label=Hosts]')).includes('localhost'), 'real localhost row')
      assert.equal(await run('document.querySelector("section[aria-label=Hosts] select").value'), 'localhost')
      await until(async () => (await text('section[aria-label="Odin\'s key"]')).includes('ssh-ed25519'), 'fresh provisioned SSH public key')
    }
    for (const selector of servicePanels[destination] ?? []) {
      await recordUnavailable(`Settings / ${destination} / ${selector}`, selector)
      assert.equal(await run(`document.querySelectorAll(${JSON.stringify(selector + ' .manage-row, ' + selector + ' .work-item')}).length`), 0, `${selector} must not display fixture rows`)
      assert(!/No schedules yet|No servers\.|Nothing is running\./.test(await text(selector)), 'refused reads must not claim successful empty results')
    }
    for (const [selector, expected] of servedPanels[destination] ?? []) {
      await until(async () => expected.test(await text(selector)), `served ${destination} / ${selector}`)
      assert(!/Service is not available yet|Loading…|Searching…/.test(await text(selector)), `${selector} must settle its served read`)
      if (selector === 'section[aria-label="Computer use"]') {
        // Served management and unqualified native input are separate claims.
        await until(async () => (await count(selector + ' .capability-unavailable')) === 1, 'computer use foreground refusal')
        assert.match(await text(selector + ' .capability-unavailable'), /Desktop input is unavailable\..*Input route: none\./s)
        assert.equal(await run(`document.querySelector(${JSON.stringify('button[aria-label="Refresh computer use"]')})?.disabled`), false)
      } else {
        assert.equal(await count(selector + ' .capability-unavailable'), 0, `${selector} must not claim its served capability unavailable`)
      }
      screens.push({ screen: `Settings / ${destination} / ${selector}`, text: await text(selector) })
    }
    if (destination === 'Data and privacy') {
      // Context reload is deliberately on demand, not a screen-mount side effect.
      await click('section[aria-label="Context"] button')
      await until(async () => /Context reloaded.*context directory does not exist; nothing is loaded/s.test(await text('section[aria-label="Context"] .manage-json')), 'served context reload')
      assert.equal(await run('document.querySelectorAll("section[aria-label=Context] button").length'), 1, 'served context reload remains offered')
      screens.push({ screen: 'Settings / Data and privacy / Memory and knowledge / Context reload', text: await text('section[aria-label="Context"]') })
      assert(!(await text('.settings-body')).includes('Loading'))
      assert((await text('section[aria-label="Named lists"]')).includes('No lists.'))
      // Learned context lists the entries the core returns; a fresh profile has none.
      await until(async () => (await text('ul[aria-label="Learned entries"]')).includes('Nothing learned yet.'), 'real learned context read')
      assert.equal(await count('ul[aria-label="Learned entries"] button[aria-label^="Edit learned entry"]'),
        (observations.learned!.result as { entries: unknown[] }).entries.length, 'learned context must list exactly the core entries')
      // Knowledge details reads saved documents, so a fresh profile offers no reads. Save one as a
      // person would, through Add a document, then read duplicates through the UI.
      assert((await text('section[aria-label="Knowledge details"]')).includes('No documents saved yet.'), 'no reads without documents')
      await setInput('#knowledge-source', 'smoke-note.md')
      await setInput('#knowledge-content', 'A short note the smoke saves before reading knowledge details.')
      await click('section[aria-label="Add a document"] .panel-actions button')
      await until(async () => /Stored as \d+ chunks?\./.test(await text('section[aria-label="Add a document"]')), 'real knowledge ingest through the UI')
      await until(async () => (await count('form[aria-label="Find knowledge duplicates"]')) === 1, 'knowledge details offers reads for a saved document')
      await click('form[aria-label="Find knowledge duplicates"] button')
      await until(async () => (await count('pre[aria-label="Knowledge duplicates JSON"]')) === 1, 'real knowledge duplicates read')
      // The complete record sits in a closed disclosure: compare its text, not what is rendered.
      const duplicates = await run<{ ok: boolean; result?: unknown }>('window.odin.knowledgeDuplicates({})')
      assert(duplicates.ok, 'knowledge duplicates core read must succeed')
      assert.deepEqual(JSON.parse(await run<string>(`document.querySelector('pre[aria-label="Knowledge duplicates JSON"]').textContent`)), duplicates.result)
    }
    if (destination === 'Usage, logs and audit') {
      if (seededWorkProof) {
        await until(async () => !(await text('section[aria-label=Audit]')).includes('Loading'), 'seeded work proof audit')
        await until(async () => !(await text('section[aria-label=Logs]')).includes('Loading'), 'seeded work proof logs')
      } else {
        await until(async () => (await text('section[aria-label=Audit]')).includes('Nothing recorded.'), 'real empty audit')
        await until(async () => (await text('section[aria-label=Logs]')).includes('No entries.'), 'real empty logs')
      }
      await until(async () => (await text('section[aria-label="Turn state"]')).includes('Preserved work') &&
        !(await text('section[aria-label="Turn state"]')).includes('Loading'), 'real turn-state availability')
      assert((await text('section[aria-label="Health"]')).includes('host(s) configured'), 'real health must observe profile hosts')
      for (const [label, method] of [['Audit diffs', 'auditDiffs'], ['Audit failures', 'auditFailures'], ['Log statistics', 'logsStats']] as const) {
        const selector = `section[aria-label="${label}"]`
        await click(`${selector} button`)
        await until(async () => (await text(selector)).includes('Last successful read shown below.'), `real ${label} panel read`)
        // Compare with a fresh core read: the seeded webhook deliveries legitimately add
        // records after the first observations, and nothing runs between these two reads.
        const current = await run<{ ok: boolean; result?: unknown }>(`window.odin.${method}({})`)
        assert(current.ok, `${label} core read must succeed`)
        assert.deepEqual(JSON.parse(await text(`${selector} pre`)), current.result, `${label} must render the actual core record`)
      }
      await click('section[aria-label="Runtime statistics"] button')
      await until(async () => (await count('section[aria-label="Runtime statistics"] pre')) > 0, 'real runtime statistics panel read')
      const stats = JSON.parse(await text('section[aria-label="Runtime statistics"] pre')) as { risk: unknown }
      assert.deepEqual(stats.risk, observations.risk!.result, 'runtime statistics must render the actual risk summary')
      await until(async () => /no .*session|no .*task/i.test(await text('section[aria-label="Computer use"]')), 'real absent computer session')
      assert(/Desktop input is unavailable\..*Input route: none/is.test(await text('section[aria-label="Computer use"]')), 'computer input must be explicitly unavailable while computer use is off')
      // Slice 4 reads the real envelope. No absent-session recovery/input action
      // may be invented while the retained management Refresh remains offered.
      assert.equal(await count('section[aria-label="Computer use"] .manage-name, section[aria-label="Computer use"] .manage-actions'), 0, 'fresh computer management must not invent a session or recovery action')
    }
    if (destination === 'Skills' || destination === 'MCP servers') {
      assert.equal(await count('.settings-body .manage-row'), 1, 'Step 6A management must show exactly its saved real-core fixture, not renderer-seeded rows')
      assert.equal(await count('.settings-body .warn'), 0, 'served Step 6A reads must not present a renderer fault')
    }
    assert.equal(await run('document.querySelectorAll(".settings-body [role=alert]").length'), 0, `${destination} must not present capability refusal as a fault`)
    // Seeded Work is real 6B work in its own section; accounts are never served in this isolated profile.
    const fixtureRows = seededWorkProof && destination === 'Work'
      ? '.settings-body .account' : '.settings-body .work-item, .settings-body .account'
    assert.equal(await run(`document.querySelectorAll(${JSON.stringify(fixtureRows)}).length`), 0, `${destination} must not display fixture accounts/work`)
    const renderedControls = await run<Array<{ id: string; ownerId: string | null }>>(`Array.from(document.querySelectorAll('.settings-body :is(input, select, textarea, output)[id^="settings-curated-"]'), e => ({ id: e.id, ownerId: e.parentElement?.closest('[id^="settings-curated-"]:not([id^="settings-curated-record-"])')?.id ?? null }))`)
    const renderedPaths = renderedControls.map(({ id, ownerId }) => renderedSettingPath(id, ownerId))
    const fields = (reads['settings.schema'] as { fields: Array<{ path: string }> }).fields
    for (const path of renderedPaths) assert(fields.some((field) => field.path === path), `rendered field ${path} must belong to the served schema`)
    assert.equal(await count('.settings-body .schema-form'), 0, 'ordinary settings must not render automatic schema groups')
    if (destination === 'Models and providers') {
      assert(fields.some((field) => field.path === 'llm_provider.model'), 'main-model control must have a served configuration field')
      assert.equal(await count('[id="settings-curated-llm_provider.model"]'), 1, 'Models must render its dedicated main-model control')
    }
    if (destination === 'General') {
      assert(renderedPaths.includes('timezone'), 'General must render the real curated time zone schema field')
      const about = await run<Array<{ label: string; value: string }>>(`(() => {
        const section = Array.from(document.querySelectorAll('.settings-body .settings-section')).find(e => e.querySelector('h3')?.textContent.trim() === 'About');
        return Array.from(section?.querySelectorAll('.settings-row') ?? [], row => ({ label: row.querySelector('.settings-row-label')?.textContent.trim() ?? '', value: row.querySelector('.settings-row-control')?.textContent.trim() ?? '' }));
      })()`)
      assert.equal(about.find(row => row.label === 'Engine build')?.value, status.version, 'General About must show the actual engine build separately from Desktop release')
      assert(about.some(row => row.label === 'Desktop release' && row.value && row.value !== 'Unavailable'), 'General About must retain the separate Desktop release fact')
    }
    if (destination === 'Advanced settings') {
      const owners = await run<string[]>(`Array.from(document.querySelectorAll('.settings-body :is(input, select, textarea, output, div)[id^="settings-curated-"]:not([id^="settings-curated-record-"])'), e => decodeURIComponent(e.id.slice('settings-curated-'.length)))`)
      const categories = await run<string[]>(`Array.from(document.querySelectorAll('.settings-body .settings-section-header > h3'), e => e.textContent.trim())`)
      assertAdvancedInventory(fields as ConfigField[], owners, categories, advancedPresentation)
    }
    assert(!(await text('.settings-body')).includes('Service is not available yet'), `${destination} must not leak a generic capability refusal`)
    screens.push({ screen: `Settings / ${destination}`, text: await text('.settings-body') })
    if (i === 0) {
      assert((await text('.settings-body')).includes('Start Odin when you log in'), 'app-local settings remain available')
    }
    writeFileSync(out.replace(/\.png$/i, '') + `-settings-${i + 1}.png`, (await win.webContents.capturePage()).toPNG())
  }
  writeFileSync(out.replace(/\.png$/i, '') + '-settings.png', (await win.webContents.capturePage()).toPNG())
  await observedService('skillsDelete', { name: 'slice4_constant' })
  await mcpMutation('mcpSetGlobalEnabled', { enabled: false })
  await mcpMutation('mcpDelete', { name: 'slice4_local' })
  // Served controls fence a missing request without invoking desktop input or a provider.
  for (const method of ['control.stop', 'control.steer', 'control.resume']) {
    const controlled = await broker.request(method, {
      control_command_id: `smoke-${method}`, conversation_id: conversationId,
      request_id: 'r_missing_smoke', generation: 1,
      ...(method === 'control.steer' ? { text: 'smoke steering' } : {})
    })
    assert.deepEqual(controlled, { ok: true, result: method === 'control.resume'
      ? { disposition: 'rejected', reason: 'stale_binding' } : { disposition: 'stale_binding' } },
    `${method} must serve its concrete request-binding disposition`)
  }
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
  await until(async () => (await content('.message-scroll .msg.notice .body')).includes('No LLM provider available. Please try again later.') &&
    (await content('.message-scroll .outcome')).includes('The task failed.') && (await count('.working, .msg.pending')) === 0, 'actual unavailable-provider task outcome')
  assert.equal(await count('.message-scroll .msg.user'), 1, 'submission must commit exactly one user message')
  await until(async () => (await content('.message-scroll .msg.user .body')) === submissionText, 'committed user message text')
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
  assert.match(failedSnapshot.recent[0]!.request_id, /^r_[a-f0-9]+$/)
  assert.match(failedSnapshot.messages.items[0]!.id, /^m_[a-f0-9]+$/)
  assert.equal(failedSnapshot.messages.items[0]!.request_id, failedSnapshot.recent[0]!.request_id,
    'the committed user message must belong to the actual admitted request')
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
  await until(async () => (await content('.message-scroll .msg.highlight .body')) === submissionText, 'real search hit navigation')
  screens.push({ screen: 'Search / committed transcript', text: await text('.search-panel') })
  writeFileSync(out.replace(/\.png$/i, '') + '-chat.png', (await win.webContents.capturePage()).toPNG())
  assert.equal(broker.linkState, 'ready')
  if (seededWorkProof) assert.deepEqual(counts(), beforePaging, 'all report reads and UI navigation must not rerun a check')
  const labelledScreens = screens.map(screen => ({ ...screen, screen: `${phase} / ${screen.screen}` }))
  Object.assign(evidence, { phase, qualification: seededWorkProof ? 'agent/process rows are metadata seeds, not execution qualification' : 'unmodified production entry on a fresh real profile', link: broker.linkState, status, reads, observations, proof, receipt, webhookProof: seededWorkProof ? webhookProof : undefined, toolCounts: seededWorkProof ? counts() : undefined, screens: labelledScreens, events })
  writeFileSync(out.replace(/\.png$/i, '') + '-evidence.json', JSON.stringify(evidence, null, 2) + '\n')
  process.stdout.write(`real-core-smoke: evidence ${JSON.stringify({ phase, link: broker.linkState, status, screens: labelledScreens.map(({ screen }) => screen), observations: Object.fromEntries(Object.entries(observations).map(([name, answer]) => [name, answer.ok ? 'observed' : answer.error?.code])) })}\n`)
  process.stdout.write(`real-core-smoke: ok phase=${phase} link=ready version=${status.version} screens=${screens.length}\n`)
  }
}
