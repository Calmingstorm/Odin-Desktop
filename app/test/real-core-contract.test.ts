import { createHash, randomUUID } from 'node:crypto'
import { readFileSync, readlinkSync, statSync, writeFileSync } from 'node:fs'
import { createServer, type Server } from 'node:http'
import { join, resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, test } from 'vitest'
import type { ConversationSnapshot, CoreEvent } from '../src/shared/api'
import { PROTOCOL, type Settled, type Welcome } from '../src/main/broker'
import { FILE_CONTENT, IMAGE_BYTES, PAGED_TEXT, REPLY, TOOL_REPLY } from './real-core-provider-fixture.mjs'
import { AttachmentManager } from '../src/main/attachments'
import { assertIsolated, onceEvent, RealCoreHarness, usageSettled, waitFor, SERVED_CAPABILITIES } from './real-core-harness'
import { assertFreshManagementStatus, realCoreCapabilities, type RealCoreStatus } from '../src/main/real-core-smoke'
import { assertRealCoreIsolation } from '../scripts/real-core-isolation.mjs'
import { assertIsolated as assertSmokeIsolated } from './real-core-smoke-seed'

// Intentional module-level hard failure if someone invokes this file with the normal/unisolated Vitest gate.
assertIsolated()

const capabilities = SERVED_CAPABILITIES
function successful<T>(answer: Settled): T {
  expect(answer.ok, JSON.stringify(answer)).toBe(true)
  if (!answer.ok) throw new Error(`Expected a real-core receipt, got ${answer.error.code}`)
  return answer.result as T
}
function refused(answer: Settled, code: string, disposition = 'rejected'): void {
  expect(answer).toMatchObject({ ok: false, error: { code, disposition } })
}
type Status = RealCoreStatus
type Subscription = { event_high: string; reset_required: boolean }

test('chat smoke accepts a runner descendant while the exact PID-1 guard still refuses it', () => {
  expect(process.pid).not.toBe(1)
  const namespace = readlinkSync('/proc/self/ns/pid')
  expect(namespace).not.toBe(process.env.ODIN_REAL_CORE_OUTER_PID_NS)
  expect(readlinkSync('/proc/1/ns/pid')).toBe(namespace)
  const repository = resolve(__dirname, '../..')
  expect(readFileSync('/proc/1/cmdline', 'utf8').split('\0').slice(0, 3)).toEqual([
    process.execPath, join(repository, 'app/scripts/real-core-isolation.mjs'), '--inside-run'
  ])
  expect(String(process.getuid!())).toBe(process.env.ODIN_REAL_CORE_UID)
  expect(String(process.getgid!())).toBe(process.env.ODIN_REAL_CORE_GID)
  expect(assertSmokeIsolated).toBe(assertIsolated)
  expect(() => assertSmokeIsolated()).not.toThrow()
  expect(() => assertRealCoreIsolation()).toThrow('PID 1 and a separate PID namespace with private /proc')
})

describe('actual app Broker ↔ repository real core', () => {
  let core: RealCoreHarness
  let provider: Server | undefined
  beforeEach(async () => {
    core = new RealCoreHarness()
    await core.start()
  })
  afterEach(async () => {
    await core?.dispose()
    if (provider) await new Promise<void>((resolve, reject) => provider!.close((error) => error ? reject(error) : resolve()))
    provider = undefined
  })

  test('authenticates the handshake, reads real status and replays events after a cursor', async () => {
    expect(realCoreCapabilities).toEqual(SERVED_CAPABILITIES)
    expect(realCoreCapabilities).toHaveLength(180)
    expect(new Set(realCoreCapabilities).size).toBe(realCoreCapabilities.length)
    const { broker, welcome } = await core.connect()
    expect(welcome).toMatchObject({
      protocol: { major: PROTOCOL.major }, profile_id: 'default', capabilities, features: [],
      core: { version: '0.1.0.dev1' }
    })
    expect(welcome.core.instance_id).toMatch(/^[a-f0-9-]{36}$/)
    expect(welcome.max_frame).toBe(4 * 1024 * 1024)
    expect(statSync(core.paths.socketPath).mode & 0o777).toBe(0o600)
    expect(statSync(core.paths.tokenPath).mode & 0o777).toBe(0o600)
    const status = successful<Status>(await broker.request('status.get'))
    assertFreshManagementStatus(status)
    expect(status).toMatchObject({ phase: 'ready', core_instance_id: welcome.core.instance_id,
      version: welcome.core.version, capabilities,
      limits: { attachment_bytes: 50 * 1024 * 1024, attachments_per_turn: 10, chunk_bytes: 512 * 1024 },
      diagnostics: { turn_durability: { state: 'on', reason: null },
        compatible_provider: { state: 'off', reason: null } } })
    // A configured model label is not provider readiness. No client is available on a fresh profile.
    expect(status).toMatchObject({ model: { main: expect.any(String), provider: 'codex' },
      providers: expect.arrayContaining([{ name: 'codex', health: 'unavailable' }]) })
    expect(status.summary).toContain('Agents active: 0')
    expect(status.summary).toContain('Loops active: 0')

    const events: CoreEvent[] = []
    broker.on('event', (event: CoreEvent) => events.push(event))
    const subscribed = successful<Subscription>(await broker.request('events.subscribe', { after: '0' }))
    expect(subscribed).toEqual({ event_high: welcome.event_high, reset_required: false })
    await waitFor(() => events.length === 1, 'startup event replay')
    // The durable startup observation precedes the current read. Uptime in
    // the human summary is expected to advance; every stable field still
    // matches, and the next connection must replay the exact stored event.
    const { summary: currentSummary, ...stableStatus } = status as Status & { summary: string }
    expect(events[0]).toMatchObject({ t: 'evt', seq: 1, cursor: '1', type: 'runtime.status',
      entity: { kind: 'runtime', id: welcome.core.instance_id }, payload: stableStatus })
    const startupSummary = (events[0]!.payload as { summary: string }).summary
    const withoutUptime = (value: string): string => value.replace(/· up \d+s/, '· up <seconds>')
    expect(withoutUptime(startupSummary)).toBe(withoutUptime(currentSummary))
    expect(events[0]!.at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/)
    expect(Date.parse(events[0]!.at)).not.toBeNaN()
    expect(broker.cursor).toBe('1')
    // A newly connected Broker can replay the same persisted interval, not a fixture projection.
    const second = await core.connect()
    const replay = onceEvent<CoreEvent>(second.broker, 'event')
    successful(await second.broker.request('events.subscribe', { after: '0' }))
    expect(await replay).toEqual(events[0])
  })

  test('runtime.shutdown returns acceptance and shuts down gracefully; original receipt survives restart without another shutdown', async () => {
    const { broker } = await core.connect()
    const id = randomUUID()
    const params = { reason: 'real-core contract shutdown' }
    const accepted = await broker.request('runtime.shutdown', params, id)
    expect(accepted).toEqual({ ok: true, result: { disposition: 'accepted' } })
    expect(await core.waitExit()).toEqual({ code: 0, signal: null })
    broker.close()
    await core.start()
    const restarted = await core.connect()
    expect(await restarted.broker.request('runtime.shutdown', params, id)).toEqual(accepted)
    expect(successful<Status>(await restarted.broker.request('status.get')).phase).toBe('ready')
    expect(core.running).toBe(true)
    refused(await restarted.broker.request('runtime.shutdown', { reason: 'different reason' }, id), 'id_conflict')
    refused(await restarted.broker.request('status.get', {}, id), 'id_conflict')
    expect(successful<Status>(await restarted.broker.request('status.get')).phase).toBe('ready')
  })

  test('validation refusals are durable original receipts; canonical params agree and changed params conflict', async () => {
    const { broker } = await core.connect()
    const id = randomUUID()
    const original = await broker.request('runtime.shutdown', { reason: 42, extra: true }, id)
    refused(original, 'bad_request')
    expect(await broker.request('runtime.shutdown', { extra: true, reason: 42 }, id)).toEqual(original)
    refused(await broker.request('runtime.shutdown', { reason: 'now valid', extra: true }, id), 'id_conflict')
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    broker.close()
    await core.start()
    const restarted = await core.connect()
    expect(await restarted.broker.request('runtime.shutdown', { extra: true, reason: 42 }, id)).toEqual(original)
    expect(successful<Status>(await restarted.broker.request('status.get')).phase).toBe('ready')
  })

  test('the real startup pruner expires a receipt body but never re-admits its retained identity', async () => {
    const { broker } = await core.connect()
    const id = randomUUID()
    const params = { reason: 'expire real receipt' }
    expect(await broker.request('runtime.shutdown', params, id)).toEqual({ ok: true, result: { disposition: 'accepted' } })
    expect(await core.waitExit()).toEqual({ code: 0, signal: null })
    broker.close()
    // Only age finished_at offline. No handmade response/tombstone and no patched engine retention.
    core.ageReceipt(id)
    await core.start()
    const restarted = await core.connect()
    refused(await restarted.broker.request('runtime.shutdown', params, id), 'receipt_expired', 'outcome_unknown')
    refused(await restarted.broker.request('runtime.shutdown', { reason: 'changed expired binding' }, id), 'id_conflict')
    expect(successful<Status>(await restarted.broker.request('status.get')).phase).toBe('ready')
    expect(core.running).toBe(true)
  })

  test('fresh work/report/schedule reads do not reserve IDs; real schedule execution and report reads never replay effects', async () => {
    const { broker, welcome } = await core.connect()
    const id = randomUUID()
    expect(successful<Status>(await broker.request('status.get', {}, id)).core_instance_id).toBe(welcome.core.instance_id)
    expect(successful<Subscription>(await broker.request('events.subscribe', { after: '0' }, id)).reset_required).toBe(false)
    expect(successful<Subscription>(await broker.request('events.subscribe', { after: '999999' }, id)).reset_required).toBe(true)
    expect(successful<{ items: unknown[] }>(await broker.request('conversations.list', {}, id)).items).toEqual([])
    expect(successful<unknown[]>(await broker.request('skills.list', {}, id))).toEqual([])
    for (const method of ['mcp.list', 'mcp.status']) {
      expect(successful(await broker.request(method, {}, id))).toMatchObject({
        servers: [], server_count: 0, configured_servers: [], configured_server_count: 0,
        connected_count: 0, published_tool_count: 0, started: true, closed: false
      })
    }
    const computer = successful(await broker.request('computer.status', {}, id))
    expect(computer).toMatchObject({ session: null, readiness: {
      management_available: true, foreground_available: false, native_qualified: false,
      input_supported: false, dispatch: 'none'
    } })
    expect(computer).not.toHaveProperty('input_dispatch')
    expect(successful(await broker.request('work.list', {}, id))).toEqual({ items: [] })
    expect(successful(await broker.request('schedules.list', {}, id))).toEqual([])
    expect(successful(await broker.request('schedules.history', {}, id))).toEqual([])
    expect(successful(await broker.request('schedules.validate_cron', { expression: 'invalid' }, id)))
      .toEqual({ valid: false, next_runs: [] })
    const cron = successful<{ valid: boolean; next_runs: string[] }>(await broker.request('schedules.validate_cron', { expression: '0 0 1 1 *' }, id))
    expect(cron.valid).toBe(true)
    expect(cron.next_runs).toHaveLength(5)
    expect(cron.next_runs.every((instant) => Date.parse(instant) > Date.now())).toBe(true)
    refused(await broker.request('reports.page', { report_id: 'absent-report', page: 1 }, id), 'not_found')
    for (const method of ['turns.create',
      'loops.list', 'agents.list', 'shell.execute', 'computer_act']) {
      expect(capabilities).not.toContain(method)
      refused(await broker.request(method, {}, id), 'capability_unavailable')
    }
    expect(successful<{ fields: unknown[] }>(await broker.request('settings.schema', {}, id)).fields.length).toBeGreaterThan(0)
    refused(await broker.request('codex.accounts.list', {}, id), 'keyring_unavailable')
    await usageSettled(broker)
    expect(successful<{ tokens: unknown }>(await broker.request('usage.get', {}, id)).tokens).toEqual({ value: 0, kind: 'measured' })
    // Execute only a disposable namespace-local printf, with no provider, network,
    // real credentials, graphical input or changes to workstation services.
    const { conversation } = successful<{ conversation: { id: string } }>(await broker.request('conversations.create', { title: 'Isolated scheduled report' }))
    const output = JSON.stringify({ format: 'paginated_embed_v1', pages: [
      { title: 'Retained first page', description: 'Only one execution' },
      { title: 'Retained second page', description: 'Reading is not execution' }
    ] })
    const saved = successful<{ id: string }>(await broker.request('schedules.save', {
      description: 'Disposable report check', action: 'check', channel_id: conversation.id,
      cron: '0 0 1 1 *', cron_timezone: 'UTC', tool_name: 'run_command',
      tool_input: { command: `printf '%s' '${output}'`, host: 'localhost' }, report_format: 'paginated_embed_v1'
    }))
    type Work = { id: string; kind: string; conversation_id: string; actions: string[]; detail: { revision: number } }
    const work = successful<{ items: Work[] }>(await broker.request('work.list', { kind: 'schedule' }, id)).items
    expect(work).toHaveLength(1)
    expect(work[0]).toMatchObject({ kind: 'schedule', conversation_id: conversation.id, state: 'scheduled',
      actions: expect.arrayContaining(['pause', 'cancel', 'run_now']) })
    const control = { control_command_id: randomUUID(), kind: 'schedule', id: work[0]!.id, action: 'run_now', revision: work[0]!.detail.revision }
    expect(successful(await broker.request('work.control', { ...control, control_command_id: randomUUID(), revision: -1 })))
      .toMatchObject({ disposition: 'not_available' })
    expect(successful(await broker.request('schedules.history', { id: saved.id }, id))).toEqual([])
    const ran = await broker.request('work.control', control)
    expect(successful(ran)).toMatchObject({ disposition: 'done', schedule: { status: 'success', schedule_id: saved.id } })
    expect(await broker.request('work.control', control)).toEqual(ran)
    refused(await broker.request('work.control', { ...control, action: 'cancel' }), 'id_conflict')
    const history = successful<Array<{ status: string }>>(await broker.request('schedules.history', { id: saved.id }, id))
    expect(history).toHaveLength(1)
    expect(history[0]).toMatchObject({ status: 'success' })
    const snapshot = successful<ConversationSnapshot>(await broker.request('conversation.snapshot', { conversation_id: conversation.id }, id))
    const reports = snapshot.messages.items.flatMap((message) => message.artifacts ?? []).filter((artifact) => artifact.kind === 'report')
    expect(reports).toHaveLength(1)
    const pageParams = { report_id: reports[0]!.ref, page: 2 }
    const page = successful(await broker.request('reports.page', pageParams, id))
    expect(page).toMatchObject({ page: 2, pages: 2, text: expect.stringContaining('Retained second page') })
    expect(successful(await broker.request('reports.page', pageParams, id))).toEqual(page)
    refused(await broker.request('reports.page', { ...pageParams, page: 3 }, id), 'bad_request')
    expect(successful(await broker.request('schedules.history', { id: saved.id }, id))).toEqual(history)
    expect(successful(await broker.request('schedules.list', {}, id))).toEqual([
      expect.objectContaining({ id: saved.id, channel_id: conversation.id, action: 'check' })
    ])
    successful(await broker.request('schedules.delete', { id: saved.id }))
    expect(successful(await broker.request('schedules.list', {}, id))).toEqual([])
    // Reports remain readable after definition deletion; no schedule can run again.
    expect(successful(await broker.request('reports.page', pageParams, id))).toEqual(page)
    expect(await broker.request('runtime.shutdown', { reason: 'read ID is still available' }, id)).toEqual({
      ok: true, result: { disposition: 'accepted' }
    })
    expect(await core.waitExit()).toEqual({ code: 0, signal: null })
  })

  test('reads identical public transcript payloads through paging, snapshot and search navigation', async () => {
    const { broker } = await core.connect()
    type Conversation = { id: string; rev: number }
    const created = successful<{ conversation: Conversation }>(await broker.request(
      'conversations.create', { title: 'real conversation navigation' }, randomUUID()))
    const reset = successful<{ conversation: Conversation }>(await broker.request(
      'conversations.reset_context', { id: created.conversation.id, expected_rev: created.conversation.rev }, randomUUID()))
    const cid = reset.conversation.id
    const page = successful<{ items: { id: string; text: string }[] }>(await broker.request(
      'messages.list', { conversation_id: cid, limit: 100 }))
    const snapshot = successful<{ messages: { items: unknown[] } }>(await broker.request(
      'conversation.snapshot', { conversation_id: cid }))
    expect(page.items).toHaveLength(1)
    expect(page.items[0]!.text).toBe('Model context reset.')
    const around = successful<{ items: unknown[] }>(await broker.request('messages.around', {
      conversation_id: cid, message_id: page.items[0]!.id, before: 0, after: 0
    }))
    expect(around.items).toEqual(page.items)
    expect(around.items).toEqual(snapshot.messages.items)
    refused(await broker.request('messages.list', { conversation_id: cid, before: 'm_missing', limit: 100 }), 'not_found')
    const found = successful<{ hits: { message_id: string }[] }>(await broker.request(
      'search.query', { query: 'context RESET', conversation_id: cid }))
    expect(found.hits.map((hit) => hit.message_id)).toEqual([page.items[0]!.id])
  })

  test('served conversations admit a real submission without a provider, publish an honest failure and never repeat it', async () => {
    const { broker } = await core.connect()
    expect(successful<{ items: unknown[] }>(await broker.request('conversations.list')).items).toEqual([])
    const created = successful<{ conversation: { id: string; title: string } }>(await broker.request(
      'conversations.create', { title: 'unavailable provider conversation' }, randomUUID()))
    const cid = created.conversation.id
    expect(created.conversation.title).toBe('unavailable provider conversation')
    expect(successful<ConversationSnapshot>(await broker.request(
      'conversation.snapshot', { conversation_id: cid })).messages.items).toEqual([])
    const events: CoreEvent[] = []
    broker.on('event', (event: CoreEvent) => events.push(event))
    successful(await broker.subscribe())
    const commandId = randomUUID()
    const params = { client_submission_id: randomUUID(), conversation_id: cid,
      text: 'real submission with no provider' }
    const accepted = await broker.request('submission.send', params, commandId)
    const receipt = successful<{ disposition: string; request_id: string; message_id: string }>(accepted)
    expect(receipt).toMatchObject({ disposition: 'accepted', request_id: expect.stringMatching(/^r_/),
      message_id: expect.stringMatching(/^m_/) })
    await waitFor(() => events.some((event) => event.type === 'request.failed' && event.payload.request_id === receipt.request_id) &&
      events.some((event) => event.type === 'message.committed' &&
        (event.payload.message as { role?: string; request_id?: string }).role === 'notice' &&
        (event.payload.message as { request_id?: string }).request_id === receipt.request_id), 'real provider failure and transcript notice')
    const snapshot = successful<ConversationSnapshot>(await broker.request('conversation.snapshot', { conversation_id: cid }))
    expect(snapshot).toMatchObject({ running: null, queued: [], unresolved: [],
      recent: [{ request_id: receipt.request_id, generation: 1, outcome: 'failed', unknown_effects: 0 }] })
    expect(snapshot.messages.items.map(({ role, text, request_id }) => ({ role, text, request_id }))).toEqual([
      { role: 'user', text: params.text, request_id: receipt.request_id },
      { role: 'notice', text: 'No LLM provider available. Please try again later.', request_id: receipt.request_id }
    ])
    expect(snapshot.messages.items[0]).toMatchObject({ id: receipt.message_id, client_submission_id: params.client_submission_id })
    expect(events.filter((event) => event.type === 'request.started')).toHaveLength(1)
    expect(events.filter((event) => event.type === 'request.failed')).toHaveLength(1)
    // Both the command identity and domain submission identity return the same
    // acceptance, not a fresh execution or a fabricated successful model reply.
    expect(await broker.request('submission.send', params, commandId)).toEqual(accepted)
    expect(await broker.request('submission.send', params, randomUUID())).toEqual(accepted)
    refused(await broker.request('submission.send', { ...params, text: 'changed text' }, randomUUID()), 'id_conflict')
    expect(successful<ConversationSnapshot>(await broker.request('conversation.snapshot', { conversation_id: cid })).messages.items)
      .toEqual(snapshot.messages.items)
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    broker.close()
    await core.start()
    const restarted = (await core.connect()).broker
    expect(await restarted.request('submission.send', params, commandId)).toEqual(accepted)
    expect(await restarted.request('submission.send', params, randomUUID())).toEqual(accepted)
    const restored = successful<ConversationSnapshot>(await restarted.request('conversation.snapshot', { conversation_id: cid }))
    expect(restored.messages).toEqual(snapshot.messages)
    expect(restored.recent).toEqual(snapshot.recent)
    expect(restored.running).toBeNull()
    expect(restored.queued).toEqual([])
    expect(successful<Status>(await restarted.request('status.get')).providers)
      .toContainEqual({ name: 'codex', health: 'unavailable' })
  })

  test('real uploaded attachment with add_to_knowledge commits an assistant reply and completes the request', async () => {
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    core = new RealCoreHarness({ memoryKeyring: true })
    await core.start()

    // Only the external model boundary is synthetic. This remains the actual repository core,
    // with the app Broker and AttachmentManager performing the real upload and submission.
    const modelInputs: string[] = []
    provider = createServer(async (request, response) => {
      if (request.method !== 'POST' || request.url !== '/api/chat') {
        response.statusCode = 404
        response.end()
        return
      }
      const chunks: Buffer[] = []
      for await (const chunk of request) chunks.push(Buffer.from(chunk))
      const payload = JSON.parse(Buffer.concat(chunks).toString('utf8')) as {
        tools?: unknown[]; messages: { role: string; content: string }[] }
      if (payload.tools) modelInputs.push(payload.messages.filter((message) => message.role === 'user')
        .map((message) => message.content).join('\n'))
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ model: 'contract-model', done: true, done_reason: 'stop',
        message: { role: 'assistant', content: payload.tools ? 'I reviewed the uploaded note.' : 'COMPLETE' },
        prompt_eval_count: 12, eval_count: 10 }))
    })
    await new Promise<void>((resolve) => provider!.listen(0, '127.0.0.1', resolve))
    const address = provider.address()
    if (!address || typeof address === 'string') throw new Error('Missing deterministic provider port')

    const { broker } = await core.connect()
    const schema = successful<{ revision: string }>(await broker.request('settings.schema'))
    successful(await broker.request('providers.ollama.set', { expected_revision: schema.revision,
      changes: [{ path: 'ollama.model', value: 'contract-model' },
        { path: 'ollama.base_url', value: `http://127.0.0.1:${address.port}` },
        { path: 'ollama.enabled', value: true }] }))
    const configured = successful<{ revision: string }>(await broker.request('settings.schema'))
    successful(await broker.request('models.main.set', { model: 'ollama:contract-model',
      expected_revision: configured.revision }))

    const created = successful<{ conversation: { id: string } }>(await broker.request(
      'conversations.create', { title: 'uploaded attachment knowledge contract' }, randomUUID()))
    const file = join(core.root, 'real-upload.txt')
    writeFileSync(file, 'A deterministic note uploaded through the real attachment manager.\n')
    const manager = new AttachmentManager(broker, () => ({ attachment_bytes: 50 * 1024 * 1024, chunk_bytes: 512 * 1024 }))
    const staged = await manager.stagePath(file)
    expect(staged.ok).toBe(true)
    if (!staged.ok) throw new Error(`Could not stage attachment: ${staged.error.code}`)
    const uploaded = await manager.upload(staged.result.id, created.conversation.id)
    expect(uploaded.ok).toBe(true)
    if (!uploaded.ok) throw new Error(`Could not upload attachment: ${uploaded.error.code}`)

    const events: CoreEvent[] = []
    broker.on('event', (event: CoreEvent) => events.push(event))
    successful(await broker.subscribe())
    const submission = { client_submission_id: randomUUID(), conversation_id: created.conversation.id,
      text: 'Review this note.', attachments: [{ ref: uploaded.result.ref, add_to_knowledge: true }] }
    const accepted = successful<{ disposition: string; request_id: string; message_id: string }>(await broker.request(
      'submission.send', submission, randomUUID()))
    expect(accepted).toMatchObject({ disposition: 'accepted', request_id: expect.stringMatching(/^r_/),
      message_id: expect.stringMatching(/^m_/) })
    await waitFor(() => events.some((event) => event.type === 'request.completed' &&
      event.payload.request_id === accepted.request_id), 'real attachment request completion')

    const snapshot = successful<ConversationSnapshot>(await broker.request('conversation.snapshot', {
      conversation_id: created.conversation.id }))
    expect(snapshot).toMatchObject({ running: null, queued: [], unresolved: [], recent: [
      { request_id: accepted.request_id, generation: 1, outcome: 'completed', unknown_effects: 0 }
    ] })
    expect(snapshot.messages.items.map(({ role, text, request_id }) => ({ role, text, request_id }))).toEqual([
      { role: 'user', text: submission.text, request_id: accepted.request_id },
      { role: 'assistant', text: 'I reviewed the uploaded note.', request_id: accepted.request_id }
    ])
    expect(snapshot.messages.items[0]).toMatchObject({ id: accepted.message_id,
      attachments: [{ ref: uploaded.result.ref, name: 'real-upload.txt', mime: 'text/plain' }] })
    expect(events.some((event) => event.type === 'request.failed' && event.payload.request_id === accepted.request_id)).toBe(false)
    expect(modelInputs).toContainEqual(expect.stringContaining(
      '**Attached file: real-upload.txt**\n```\nA deterministic note uploaded through the real attachment manager.\n\n```\n[File read for current task. User requested knowledge ingestion; use ingest_document if appropriate.]'))
  })

  test('closing the parent stdin pipe exits orderly and releases the profile for a successor', async () => {
    const { broker, welcome } = await core.connect()
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    broker.close()
    expect(core.running).toBe(false)
    await core.start()
    const restarted = await core.connect()
    expect(restarted.welcome.core.instance_id).not.toBe(welcome.core.instance_id)
    expect(successful<Status>(await restarted.broker.request('status.get')).phase).toBe('ready')
  })

  test('a wrong token is unauthorized, never reaches ready, and cannot stop the real core', async () => {
    const broker = core.broker(true)
    const welcomes: Welcome[] = []
    broker.on('welcome', (welcome: Welcome) => welcomes.push(welcome))
    const rejected = onceEvent<string>(broker, 'bye')
    broker.connect()
    expect(await rejected).toBe('unauthorized')
    broker.close()
    expect(welcomes).toEqual([])
    expect(broker.linkState).not.toBe('ready')
    refused(await broker.request('runtime.shutdown', { reason: 'must not execute' }), 'not_connected', 'not_dispatched')
    const valid = await core.connect()
    expect(successful<Status>(await valid.broker.request('status.get')).phase).toBe('ready')
  })

  test('restart preserves the event sequence and the same Broker catches up with no reset or duplicate', async () => {
    const { broker, welcome } = await core.connect()
    const events: CoreEvent[] = []
    const resets: unknown[] = []
    broker.on('event', (event: CoreEvent) => events.push(event))
    broker.on('reset', (reset: unknown) => resets.push(reset))
    // A normal app subscription starts live at null; only future status events flow.
    successful(await broker.subscribe())
    expect(events).toEqual([])
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    await waitFor(() => events.length === 1, 'old incarnation quiescing event')
    expect(broker.cursor).toBe('2')
    // Observe the 25s cold-start harness plus the unchanged 5s handshake under load; never repeat startup.
    const changed = onceEvent<string>(broker, 'core-changed', 35_000)
    await core.start()
    const newInstance = await changed
    expect(newInstance).not.toBe(welcome.core.instance_id)
    await waitFor(() => events.some((event) => event.payload.core_instance_id === newInstance), 'new incarnation event after reconnect')
    expect(events.map((event) => event.seq)).toEqual([2, 3])
    expect(events.map((event) => event.cursor)).toEqual(['2', '3'])
    expect(events.map((event) => event.payload.phase)).toEqual(['quiescing', 'ready'])
    expect(events[1]!.entity.id).toBe(newInstance)
    expect(broker.cursor).toBe('3')
    expect(resets).toEqual([])
    expect(successful<Status>(await broker.request('status.get')).core_instance_id).toBe(newInstance)
    const replayBroker = (await core.connect()).broker
    const replayed: CoreEvent[] = []
    replayBroker.on('event', (event: CoreEvent) => replayed.push(event))
    expect(successful<Subscription>(await replayBroker.request('events.subscribe', { after: '0' }))).toEqual({
      reset_required: false, event_high: '3'
    })
    await waitFor(() => replayed.length === 3, 'entire persisted interval after restart')
    expect(replayed.map((event) => event.seq)).toEqual([1, 2, 3])
    expect(replayed[0]!.entity.id).toBe(welcome.core.instance_id)
    expect(replayed.slice(1)).toEqual(events)
    replayBroker.close()
    // The exact same read ID returns the successor's fresh status, never the old runtime's status.
    const id = randomUUID()
    successful(await broker.request('status.get', {}, id))
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    // This event wait starts before cold startup too; bound observation above its startup/handshake budgets.
    const next = onceEvent<string>(broker, 'core-changed', 35_000)
    await core.start()
    const nextInstance = await next
    expect(successful<Status>(await broker.request('status.get', {}, id)).core_instance_id).toBe(nextInstance)
  })
})

type Conversation = { id: string; rev: number; title: string; archived: boolean; parent_id: string | null }
type Message = { id: string; role: string; text: string; request_id?: string;
  artifacts?: { ref: string; name: string; mime: string }[]; attachments?: { ref: string }[] }
type Snapshot = { conversation: Conversation; watermark: string; messages: { items: Message[] };
  running: { request_id: string; generation: number } | null; queued: { request_id: string }[];
    recent: { request_id: string; outcome: string; unknown_effects: number }[];
    tools: Record<string, { invocation_id: string; tool: string }[]>; controls: unknown[] }
type Submission = { disposition: string; request_id: string; message_id: string }

describe('provider-backed steps 2-4 through the real Broker and real OpenAICompatibleClient', () => {
  let core: RealCoreHarness
  beforeEach(async () => {
    core = new RealCoreHarness()
    await core.configureProvider()
    await core.start()
  })
  afterEach(async () => { await core?.dispose() })

  async function setup() {
    const { broker } = await core.connect()
    const events: CoreEvent[] = []
    broker.on('event', (event: CoreEvent) => events.push(event))
    successful(await broker.subscribe())
    const conversation = successful<{ conversation: Conversation }>(await broker.request(
      'conversations.create', { title: 'Provider contract' }, randomUUID())).conversation
    const snapshot = async () => successful<Snapshot>(await broker.request('conversation.snapshot', { conversation_id: conversation.id }))
    const send = async (text: string, extra = {}) => successful<Submission>(await broker.request('submission.send', {
      conversation_id: conversation.id, client_submission_id: randomUUID(), text, ...extra
    }, randomUUID()))
    const settled = async (request: Submission, outcome = 'completed') => {
      await waitFor(() => events.some((event) => event.type === `request.${outcome}` && event.payload.request_id === request.request_id),
        `${request.request_id} ${outcome}`, 12_000)
      return snapshot()
    }
    const replied = async (text = REPLY) => waitFor(() => events.some((event) =>
      event.type === 'message.committed' && (event.payload.message as Message | undefined)?.text === text), 'committed guarded reply')
    return { broker, events, conversation, snapshot, send, settled, replied }
  }

  test('reply and immutable send receipt; CRUD/child/reset/search/jump and watermark catch-up', async () => {
    const { broker, events, conversation, snapshot, settled, replied } = await setup()
    const params = { conversation_id: conversation.id, client_submission_id: randomUUID(), text: '[reply] navigation contract' }
    const sent = successful<Submission>(await broker.request('submission.send', params, randomUUID()))
    await settled(sent)
    await replied()
    expect(successful(await broker.request('submission.send', params, randomUUID()))).toEqual(sent)
    refused(await broker.request('submission.send', { ...params, text: '[reply] changed' }, randomUUID()), 'id_conflict')
    let snap = await snapshot()
    const reply = snap.messages.items.find((message) => message.role === 'assistant')!
    expect(reply.text).toBe(REPLY)
    expect(reply.request_id).toBe(sent.request_id)
    expect(events.filter((event) => event.type === 'message.committed' && (event.payload.message as Message | undefined)?.role === 'assistant')).toHaveLength(1)
    expect(core.provider!.requests.filter((entry) => entry.body.max_tokens !== 1)).toHaveLength(1)
    expect(core.provider!.requests.find((entry) => entry.body.max_tokens !== 1)!.body).toMatchObject({ stream: true, model: 'canned-contract' })
    const child = successful<{ conversation: Conversation }>(await broker.request('conversations.create', {
      title: 'Child snapshot', parent_id: conversation.id, from_message_id: reply.id
    }, randomUUID())).conversation
    expect(child.parent_id).toBe(conversation.id)
    const childSent = successful<Submission>(await broker.request('submission.send', {
      conversation_id: child.id, client_submission_id: randomUUID(), text: '[reply] child context'
    }, randomUUID()))
    await waitFor(() => events.some((event) => event.type === 'request.completed' && event.payload.request_id === childSent.request_id), 'child real generation')
    expect(JSON.stringify(core.provider!.requests.find((entry) => JSON.stringify(entry.body.messages).includes('child context'))?.body.messages)).toContain('navigation contract')
    let current = successful<{ conversation: Conversation }>(await broker.request('conversations.update', {
      id: conversation.id, expected_rev: snap.conversation.rev, title: 'Renamed provider contract', archived: true
    }, randomUUID())).conversation
    expect(current).toMatchObject({ title: 'Renamed provider contract', archived: true })
    refused(await broker.request('conversations.update', { id: current.id, expected_rev: 1, title: 'stale' }, randomUUID()), 'stale_binding', 'stale_binding')
    const found = successful<{ hits: { message_id: string }[] }>(await broker.request('search.query', { query: 'real core contract', conversation_id: current.id }))
    expect(found.hits.some((hit) => hit.message_id === reply.id)).toBe(true)
    expect(successful<{ items: Message[] }>(await broker.request('messages.around', {
      conversation_id: current.id, message_id: reply.id, before: 0, after: 0
    })).items).toEqual([reply])
    const watermark = (await snapshot()).watermark
    current = successful<{ conversation: Conversation }>(await broker.request('conversations.reset_context', {
      id: current.id, expected_rev: current.rev
    }, randomUUID())).conversation
    snap = await snapshot()
    expect(snap.messages.items.at(-1)?.text).toBe('Model context reset.')
    expect(snap.messages.items).toContainEqual(reply)
    const reconnected = (await core.connect()).broker
    const replay: CoreEvent[] = []
    reconnected.on('event', (event: CoreEvent) => replay.push(event))
    successful(await reconnected.request('events.subscribe', { after: watermark }))
    await waitFor(() => replay.some((event) => event.cursor === snap.watermark), 'snapshot watermark catch-up')
    expect(replay.every((event) => BigInt(event.cursor) > BigInt(watermark))).toBe(true)
    expect(new Set(replay.map((event) => event.cursor)).size).toBe(replay.length)
    const afterReset = successful<Submission>(await broker.request('submission.send', {
      conversation_id: current.id, client_submission_id: randomUUID(), text: '[reply] after reset'
    }, randomUUID()))
    await settled(afterReset)
    const resetInput = core.provider!.requests.find((entry) => JSON.stringify(entry.body.messages).includes('after reset'))!
    expect(JSON.stringify(resetInput.body.messages)).not.toContain('navigation contract')
    expect(JSON.stringify(resetInput.body.messages)).not.toContain('child context')
    current = (await snapshot()).conversation
    const childCurrent = successful<Snapshot>(await broker.request('conversation.snapshot', { conversation_id: child.id })).conversation
    successful(await broker.request('conversations.delete', { id: child.id, expected_rev: childCurrent.rev }, randomUUID()))
    successful(await broker.request('conversations.delete', { id: current.id, expected_rev: current.rev }, randomUUID()))
    expect(successful<{ items: Conversation[] }>(await broker.request('conversations.list')).items).toEqual([])
    refused(await broker.request('conversation.snapshot', { conversation_id: current.id }), 'not_found')
  })

  test('harmless real tool produces activity and scoped detail rather than fixture cards', async () => {
    const { broker, snapshot, send, settled, replied } = await setup()
    const sent = await send('[tool] parse a harmless time')
    await settled(sent)
    await replied(TOOL_REPLY)
    const snap = await snapshot()
    const tool = snap.tools[sent.request_id]![0]!
    expect(tool).toBeDefined()
    const detail = successful<Record<string, unknown>>(await broker.request('tool.detail', { request_id: sent.request_id, invocation_id: tool.invocation_id }))
    expect(JSON.stringify(detail)).toContain('parse_time')
    expect(JSON.stringify(detail)).toContain('in 2 hours')
    // The real completion classifier may request another generation. Require
    // actual tool feedback, not a brittle exact count of model invocations.
    expect(core.provider!.requests.length).toBeGreaterThanOrEqual(2)
    expect(core.provider!.requests.some((entry) => entry.body.messages.some((message) => message.role === 'tool'))).toBe(true)
    refused(await broker.request('tool.detail', { request_id: 'r_missing', invocation_id: tool.invocation_id }), 'not_found')
  })

  test('real retained tool output pages through the original source without duplicate tails', async () => {
    const { broker, snapshot, send, settled, replied } = await setup()
    const sent = await send('[paged-tool] read canned retained evidence')
    await settled(sent)
    await replied(TOOL_REPLY)
    const tool = (await snapshot()).tools[sent.request_id]![0]!
    const detail = successful<{ output: { cursor: string } }>(await broker.request('tool.detail', { request_id: sent.request_id, invocation_id: tool.invocation_id }))
    expect(detail.output.cursor, JSON.stringify(detail)).toBeTruthy()
    let cursor: string | undefined = detail.output.cursor
    let text = ''
    let pages = 0
    while (cursor) {
      const page: { text: string; next_cursor?: string; eof: boolean } = successful(await broker.request('tool.output', { cursor, limit: 8000 }))
      text += page.text
      pages++
      expect(pages).toBeLessThan(40)
      cursor = page.next_cursor
      if (!cursor) expect(page.eof).toBe(true)
    }
    expect(pages).toBeGreaterThan(1)
    expect(text).toContain('Evidence line 0000')
    expect(text).toContain('Evidence line 0899')
    expect(text.match(/Evidence line 0000/g)).toHaveLength(1)
    expect(text.match(/Evidence line 0899/g)).toHaveLength(1)
    expect(PAGED_TEXT.length).toBeGreaterThan(32_000)
  })

  test('posted file and decoded image carry real artifact bytes and scoped reads', async () => {
    const { broker, events, snapshot, send, settled } = await setup()
    const sent = await send('[artifact] post a canned text file and image')
    await settled(sent)
    await waitFor(() => events.filter((event) => event.type === 'artifact.published').length === 2, 'posted file/image events')
    const artifacts = (await snapshot()).messages.items.flatMap((message) => message.artifacts ?? [])
    expect(artifacts).toHaveLength(2)
    const text = artifacts.find((artifact) => artifact.name === 'contract.txt')!
    const image = artifacts.find((artifact) => artifact.mime === 'image/png')!
    expect(image).toBeDefined()
    for (const [artifact, expected] of [[text, Buffer.from(FILE_CONTENT)], [image, IMAGE_BYTES]] as const) {
      const result = successful<{ data_b64: string }>(await broker.request('artifacts.read', { ref: artifact.ref, offset: 0, length: 4096 }))
      expect(Buffer.from(result.data_b64, 'base64')).toEqual(expected)
    }
    refused(await broker.request('artifacts.read', { ref: 'a_missing', offset: 0, length: 4096 }), 'not_found')
  })

  test('chunked attachment commit/adoption/cancel runs processing into provider input', async () => {
    const { broker, conversation, send, settled, snapshot, replied } = await setup()
    const bytes = Buffer.from('CANNED_ATTACHMENT_TEXT_CONTENT\n')
    const begin = async () => successful<{ upload_id: string }>(await broker.request('attachments.begin', {
      client_attachment_id: randomUUID(), conversation_id: conversation.id, name: 'input.txt', mime: 'text/plain', size: bytes.length
    })).upload_id
    const upload = await begin()
    for (const [offset, chunk] of [[0, bytes.subarray(0, 7)], [7, bytes.subarray(7)]] as const) {
      successful(await broker.request('attachments.chunk', { upload_id: upload, offset, data_b64: chunk.toString('base64') }))
    }
    const committed = successful<{ attachment: { ref: string } }>(await broker.request('attachments.commit', {
      upload_id: upload, sha256: createHash('sha256').update(bytes).digest('hex')
    }))
    const sent = await send('[reply] read my attachment', { attachments: [committed.attachment] })
    await settled(sent)
    await replied()
    expect(JSON.stringify(core.provider!.requests.find((entry) => entry.body.max_tokens !== 1)!.body.messages)).toContain('CANNED_ATTACHMENT_TEXT_CONTENT')
    expect((await snapshot()).messages.items.find((message) => message.id === sent.message_id)?.attachments).toHaveLength(1)
    const abandoned = await begin()
    successful(await broker.request('attachments.cancel', { upload_id: abandoned }))
    refused(await broker.request('attachments.chunk', { upload_id: abandoned, offset: 0, data_b64: bytes.toString('base64') }), 'expired')
  })

  test('provider failure is terminal failed, never successful, and the next send runs', async () => {
    const { events, send, settled, replied } = await setup()
    const failed = await send('[fail] fail on demand')
    const snap = await settled(failed, 'failed')
    expect(snap.recent).toContainEqual(expect.objectContaining({ request_id: failed.request_id, outcome: 'failed', unknown_effects: 0 }))
    expect(events.some((event) => event.type === 'request.completed' && event.payload.request_id === failed.request_id)).toBe(false)
    expect(snap.messages.items.filter((message) => message.role === 'assistant').every((message) => message.text !== REPLY)).toBe(true)
    await waitFor(() => events.some((event) => event.type === 'message.committed' &&
      (event.payload.message as Message | undefined)?.request_id === failed.request_id &&
      (event.payload.message as Message | undefined)?.role === 'assistant'), 'committed guarded provider error reply')
    await settled(await send('[reply] recovery after failure'))
    await replied()
  })

  test('held generation queues follow-up and consumes an accepted steer once at safe boundary', async () => {
    const { broker, events, conversation, snapshot, send, settled } = await setup()
    const active = await send('[hold-steer] hold for steering')
    await waitFor(() => core.provider!.requests.some((entry) => entry.token === '[hold-steer]'), 'held provider generation')
    // D9: provider generation is not transcript publication. Only the final
    // guarded delivery can create a public assistant message.
    expect((await snapshot()).messages.items.filter((message) => message.role === 'assistant')).toEqual([])
    const queued = await send('[reply] queued follow-up')
    expect((await snapshot()).queued.map((item) => item.request_id)).toContain(queued.request_id)
    const params = { control_command_id: randomUUID(), conversation_id: conversation.id, request_id: active.request_id, generation: 1, text: 'STEERING_DIRECTIVE_CONTRACT' }
    const receipt = await broker.request('control.steer', params, randomUUID())
    expect(successful(receipt)).toMatchObject({ disposition: 'queued', sequence: 1 })
    expect(await broker.request('control.steer', params, randomUUID())).toEqual(receipt)
    core.provider!.release('[hold-steer]')
    await settled(active)
    await settled(queued)
    await waitFor(() => events.some((event) => event.type === 'control.receipt' && event.payload.disposition === 'consumed'), 'steer consumed receipt')
    expect(JSON.stringify(core.provider!.requests.map((entry) => entry.body.messages))).toContain('STEERING_DIRECTIVE_CONTRACT')
    expect((await snapshot()).queued).toEqual([])
  })

  test('request-bound stop and stale controls never retarget a successor; resume answers honestly', async () => {
    const { broker, events, conversation, send, settled } = await setup()
    const active = await send('[hold-stop] wait for stop')
    await waitFor(() => core.provider!.requests.some((entry) => entry.token === '[hold-stop]'), 'held stop generation')
    const params = { control_command_id: randomUUID(), conversation_id: conversation.id, request_id: active.request_id, generation: 1 }
    const stopped = await broker.request('control.stop', params, randomUUID())
    expect(successful(stopped)).toMatchObject({ disposition: 'requested' })
    expect(await broker.request('control.stop', params, randomUUID())).toEqual(stopped)
    await waitFor(() => events.some((event) => ['request.cancelled', 'request.suspended'].includes(event.type) && event.payload.request_id === active.request_id), 'stopped generation settled')
    expect(events.some((event) => event.type === 'control.receipt' && event.payload.control_command_id === params.control_command_id)).toBe(true)
    expect(successful(await broker.request('control.stop', { ...params, control_command_id: randomUUID(), generation: 99 }, randomUUID()))).toMatchObject({ disposition: 'stale_binding' })
    const resumed = await broker.request('control.resume', { ...params, control_command_id: randomUUID() }, randomUUID())
    expect(successful(resumed)).toMatchObject({ disposition: 'rejected', reason: 'not_resumable' })
    await settled(await send('[reply] successor after stop'))
  })

  test.each(['control', 'continue'])('restart interrupted checkpoint resumes the same request on generation 2 via %s, not a new submission', async (path) => {
    const { broker, conversation, send, snapshot } = await setup()
    const active = await send('[hold-stop] preserve resumable checkpoint')
    await waitFor(() => core.provider!.requests.some((entry) => entry.token === '[hold-stop]'), 'checkpoint generation HTTP request')
    expect((await snapshot()).messages.items.filter((message) => message.role === 'assistant')).toEqual([])
    // The isolated core loses its process-local worker while retaining the real
    // durable generation checkpoint. No test-made ledger rows or fake decoder.
    core.child.kill('SIGKILL')
    await core.waitExit()
    broker.close()
    core.provider!.release('[hold-stop]')
    await core.start()
    const restarted = (await core.connect()).broker
    const events: CoreEvent[] = []
    restarted.on('event', (event: CoreEvent) => events.push(event))
    successful(await restarted.subscribe())
    const params = { control_command_id: randomUUID(), conversation_id: conversation.id,
      request_id: active.request_id, generation: 1 }
    const method = path === 'control' ? 'control.resume' : 'submission.send'
    const submitted = path === 'control' ? params : { conversation_id: conversation.id, client_submission_id: randomUUID(), text: 'continue' }
    const admitted = await restarted.request(method, submitted, randomUUID())
    expect(successful(admitted)).toMatchObject(path === 'control' ? { disposition: 'admitted' }
      : { disposition: 'accepted', request_id: active.request_id, message_id: active.message_id })
    expect(await restarted.request(method, submitted, randomUUID())).toEqual(admitted)
    await waitFor(() => events.some((event) => event.type === 'request.completed' && event.payload.request_id === active.request_id), 'resumed completion')
    const snap = successful<Snapshot>(await restarted.request('conversation.snapshot', { conversation_id: conversation.id }))
    expect(snap.recent).toContainEqual(expect.objectContaining({ request_id: active.request_id, generation: 2, outcome: 'completed' }))
    expect(snap.messages.items.filter((message) => message.role === 'user').map((message) => message.id)).toEqual([active.message_id])
    await waitFor(() => events.some((event) => event.type === 'message.committed' && (event.payload.message as Message | undefined)?.text === REPLY), 'resumed guarded reply')
  })

  test('continue with no resumable request commits an ordinary message', async () => {
    const { send, settled } = await setup()
    const sent = await send('continue')
    const snap = await settled(sent)
    expect(snap.messages.items.filter((message) => message.role === 'user')).toEqual([
      expect.objectContaining({ id: sent.message_id, request_id: sent.request_id, text: 'continue' })
    ])
  })

  test('typed resume of unreadable real checkpoint commits one failure notice, no new user message or execution', async () => {
    const { broker, conversation, send } = await setup()
    const preserved = await send('[hold-stop] preserve busy resume contract')
    await waitFor(() => core.provider!.requests.some((entry) => entry.token === '[hold-stop]'), 'real checkpoint before interruption')
    core.child.kill('SIGKILL')
    await core.waitExit()
    broker.close()
    core.corruptCheckpoint(preserved.request_id)
    await core.start()
    const restarted = (await core.connect()).broker
    const events: CoreEvent[] = []
    restarted.on('event', (event: CoreEvent) => events.push(event))
    successful(await restarted.subscribe())
    const sid = randomUUID()
    const params = { conversation_id: conversation.id, client_submission_id: sid, text: 'continue' }
    const failed = await restarted.request('submission.send', params, randomUUID())
    expect(successful(failed)).toMatchObject({ disposition: 'rejected', reason: 'checkpoint_unavailable', request_id: preserved.request_id, message_id: preserved.message_id })
    expect(await restarted.request('submission.send', params, randomUUID())).toEqual(failed)
    const snap = successful<Snapshot>(await restarted.request('conversation.snapshot', { conversation_id: conversation.id }))
    expect(snap.messages.items.filter((message) => message.role === 'user').map((message) => message.id)).toEqual([preserved.message_id])
    expect(snap.messages.items.filter((message) => message.role === 'notice' && message.request_id === preserved.request_id)).toEqual([
      expect.objectContaining({ client_submission_id: sid, text: expect.stringContaining('no longer resumable') })
    ])
    expect(snap.running).toBeNull()
    expect(events.some((event) => event.type === 'request.started' && event.payload.request_id === preserved.request_id && event.payload.generation === 2)).toBe(false)
  })
})
