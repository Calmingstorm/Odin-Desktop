// Personality, state and records against the fixture core, over the real broker, in the shapes of Odin's routes.
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it } from 'vitest'
import type {
  AuditEntry,
  ComputerStatus,
  HealthReport,
  KnowledgeHit,
  KnowledgeIngest,
  KnowledgeSource,
  KnowledgeVersion,
  MemoryIndex,
  Personality,
  TurnStateReport
} from '../src/shared/api'
import { Broker } from '../src/main/broker'
import { startFixture, waitFor } from './fixture-harness'

const cleanups: Array<() => Promise<void> | void> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
})

type Ok<T> = { ok: true; result: T }

async function connect() {
  const core = await startFixture()
  cleanups.push(() => core.stop())
  const broker = new Broker({
    socketPath: core.paths.socketPath,
    readToken: () => readFileSync(core.paths.tokenPath, 'utf8').trim(),
    profileId: 'default',
    clientVersion: 'test',
    reconnectDelaysMs: [50]
  })
  broker.connect()
  cleanups.push(() => broker.close())
  await waitFor(() => broker.linkState === 'ready')
  const read = async <T>(method: string, params: Record<string, unknown> = {}): Promise<T> => ((await broker.request(method, params)) as Ok<T>).result
  const command = (method: string, params: Record<string, unknown>) => broker.request(method, params, crypto.randomUUID())
  return { broker, read, command }
}

describe('personality', () => {
  it("chooses a preset or a custom one, and keeps Odin's built-ins from being overwritten or deleted", async () => {
    const { read, command } = await connect()
    const before = await read<Personality>('personality.get')
    expect(before).toMatchObject({ preset: 'odin', builtin_presets: ['odin', 'professional', 'friendly'], user_presets: [] })
    expect(before.presets.professional?.name).toBe('Mimir')
    expect(await command('personality.set', { preset: 'nobody' })).toMatchObject({ ok: false, error: { message: "unknown preset 'nobody'" } })
    expect(await command('personality.set', { preset: 'custom', custom_name: 'Huginn', custom_identity: 'A raven.', custom_voice: 'Brief.' })).toEqual({
      ok: true,
      result: { status: 'updated', preset: 'custom' }
    })
    expect(await read<Personality>('personality.get')).toMatchObject({ preset: 'custom', custom_name: 'Huginn' })
    expect(await command('personality.presets.save', { name: 'odin', identity: 'x' })).toMatchObject({ ok: false, error: { message: "cannot overwrite built-in preset 'odin'" } })
    expect(await command('personality.presets.save', { name: 'Night Shift', display_name: 'Night shift' })).toMatchObject({
      ok: false,
      error: { message: 'identity or voice is required' }
    })
    expect(await command('personality.presets.save', { name: 'Night Shift', display_name: 'Night shift', voice: 'Quiet.' })).toEqual({
      ok: true,
      result: { status: 'saved', name: 'night_shift' }
    })
    await command('personality.set', { preset: 'night_shift' })
    expect(await command('personality.presets.delete', { name: 'friendly' })).toMatchObject({ ok: false, error: { message: "cannot delete built-in preset 'friendly'" } })
    expect(await command('personality.presets.delete', { name: 'night_shift' })).toEqual({ ok: true, result: { status: 'deleted', name: 'night_shift' } })
    expect((await read<Personality>('personality.get')).preset).toBe('odin') // the preset in use was deleted
  })
})

describe('memory and named lists', () => {
  it('lists scopes with their keys, and sets, reads, deletes and bulk-deletes entries', async () => {
    const { read, command } = await connect()
    expect(await read<MemoryIndex>('memory.list')).toEqual({ global: { keys: ['deploy_window'], count: 1 }, owner: { keys: ['preferred_editor'], count: 1 } })
    expect(await command('memory.set', { scope: 'owner', key: 'shell', value: 'zsh' })).toEqual({ ok: true, result: { status: 'saved', scope: 'owner', key: 'shell' } })
    expect(await read('memory.get', { scope: 'owner', key: 'shell' })).toEqual({ scope: 'owner', key: 'shell', value: 'zsh' })
    expect(await read('memory.get', { scope: 'owner' })).toEqual({ scope: 'owner', entries: { preferred_editor: 'Uses VS Code.', shell: 'zsh' } })
    expect(await command('memory.delete', { scope: 'owner', key: 'nothing' })).toMatchObject({ ok: false, error: { code: 'not_found' } })
    expect(await command('memory.bulk_delete', { entries: [{ scope: 'owner', key: 'shell' }, { scope: 'owner', key: 'preferred_editor' }] })).toEqual({
      ok: true,
      result: { status: 'deleted', count: 2 }
    })
    expect((await read<MemoryIndex>('memory.list')).owner).toEqual({ keys: [], count: 0 })
  })

  it('lists, reads and deletes named lists', async () => {
    const { read, command } = await connect()
    expect(await read('lists.list')).toEqual({ items: [{ name: 'groceries', count: 3, updated_at: expect.any(String) }] })
    expect(await read('lists.get', { name: 'groceries' })).toEqual({ name: 'groceries', items: ['milk', 'eggs', 'coffee'] })
    expect(await command('lists.delete', { name: 'groceries' })).toEqual({ ok: true, result: { status: 'deleted', name: 'groceries' } })
    expect(await command('lists.get', { name: 'groceries' })).toMatchObject({ ok: false, error: { code: 'not_found' } })
  })
})

describe('knowledge', () => {
  it("stores a document, says when it is unchanged, a duplicate or a near-duplicate, and finds it by its words", async () => {
    const { read, command } = await connect()
    const runbook = 'Restart the web tier with systemctl restart web, then check the health page. '.repeat(8)
    const stored = (await command('knowledge.ingest', { source: 'runbook.md', content: runbook })) as Ok<KnowledgeIngest>
    expect(stored.result).toMatchObject({ source: 'runbook.md', outcome: 'created', chunks: 2 })
    expect(await command('knowledge.ingest', { source: 'runbook.md', content: runbook })).toMatchObject({ ok: true, result: { outcome: 'unchanged' } })
    expect(await command('knowledge.ingest', { source: 'copy.md', content: runbook })).toMatchObject({
      ok: true,
      result: { outcome: 'duplicate', duplicate_of: 'runbook.md', message: "Identical content is already stored as 'runbook.md'; no new source was created." }
    })
    expect(await command('knowledge.ingest', { source: 'nearly.md', content: runbook + ' One more line.' })).toMatchObject({
      ok: true,
      result: { outcome: 'conflict', duplicate_of: 'runbook.md' }
    })
    expect((await read<KnowledgeSource[]>('knowledge.list')).map((s) => [s.source, s.chunks])).toEqual([['runbook.md', 2]])
    const hits = await read<KnowledgeHit[]>('knowledge.search', { q: 'restart health' })
    expect(hits[0]).toMatchObject({ source: 'runbook.md', chunk_index: 0, score: 1 })
    expect(await command('knowledge.search', { q: '   ' })).toMatchObject({ ok: false, error: { code: 'bad_request' } })
  })

  it('keeps versions, restores one, and deletes a source with its chunks', async () => {
    const { read, command } = await connect()
    await command('knowledge.ingest', { source: 'notes.md', content: 'First version of the notes.' })
    await command('knowledge.ingest', { source: 'notes.md', content: 'Second version, longer than the first one.' })
    const versions = await read<KnowledgeVersion[]>('knowledge.versions', { source: 'notes.md' })
    expect(versions.map((v) => [v.version, v.action])).toEqual([[1, 'ingest'], [2, 'ingest']])
    expect(await command('knowledge.restore', { source: 'notes.md', version: 1 })).toEqual({
      ok: true,
      result: { status: 'restored', source: 'notes.md', version: 1, chunks: 1 }
    })
    expect((await read<KnowledgeSource[]>('knowledge.list'))[0]?.preview).toBe('First version of the notes.')
    expect(await command('knowledge.restore', { source: 'notes.md', version: 9 })).toMatchObject({ ok: false, error: { code: 'not_found' } })
    expect(await command('knowledge.delete', { source: 'notes.md' })).toEqual({ ok: true, result: { status: 'deleted', chunks_removed: 1 } })
  })
})

describe('records', () => {
  it('audits every tool call with its scrubbed input, filters the record, and verifies it', async () => {
    const { broker, read } = await connect()
    const conversation = ((await broker.request('conversations.create', { title: 'T' }, crypto.randomUUID())) as Ok<{ conversation: { id: string } }>).result.conversation.id
    const sub = crypto.randomUUID()
    await broker.request('submission.send', { client_submission_id: sub, conversation_id: conversation, text: 'hello there' }, sub)
    let all: AuditEntry[] = []
    for (let i = 0; i < 100 && all.length < 2; i++) {
      all = await read<AuditEntry[]>('audit.query')
      if (all.length < 2) await new Promise((r) => setTimeout(r, 50))
    }
    expect(all.map((e) => e.tool_name)).toEqual(['echo', 'run_command']) // newest first
    expect(await read<AuditEntry[]>('audit.query', { tool: 'run_command' })).toHaveLength(1)
    expect(await read<AuditEntry[]>('audit.query', { error_only: true })).toEqual([])
    expect(await read('audit.verify')).toMatchObject({ valid: true, total: 2, verified: 2 })
  })

  it('reports health by component, searches the logs by level, and shows preserved work', async () => {
    const { read, command } = await connect()
    const health = await read<HealthReport>('health.get')
    expect(health).toMatchObject({ overall: 'degraded', total: 5, healthy_count: 3, degraded_count: 1, unconfigured_count: 1 })
    expect(health.components.find((c) => c.name === 'mcp')).toMatchObject({ status: 'degraded', detail: '1 of 2 servers connected.' })
    expect((await read<{ entries: Array<{ level: string }> }>('logs.search', { level: 'error' })).entries.map((e) => e.level)).toEqual(['ERROR'])
    expect(await command('logs.search', { level: 'debug' })).toMatchObject({ ok: false })
    expect(await read<TurnStateReport>('turn_state.list')).toMatchObject({ schema_version: 1, availability: 'available', data: { turns: [] } })
  })

  it("releases a computer-use session only with Odin's acknowledgment", async () => {
    const { read, command } = await connect()
    const status = await read<ComputerStatus>('computer.status')
    expect(status).toMatchObject({ enabled: false, state: 'quarantined', sessions: [{ session_id: 'cs_7f3a', generation: 3, quarantined: true }] })
    expect(await command('computer.reconcile', { session_id: 'cs_7f3a', generation: 3, acknowledgment: 'yes' })).toMatchObject({
      ok: false,
      error: { message: 'explicit_acknowledgment_required' }
    })
    expect(await command('computer.reconcile', { session_id: 'cs_7f3a', generation: 3, acknowledgment: 'ACKNOWLEDGE UNVERIFIED CLEANUP cs_7f3a' })).toEqual({
      ok: true,
      result: { status: 'reconciled', session_id: 'cs_7f3a' }
    })
    expect(await read<ComputerStatus>('computer.status')).toMatchObject({ state: 'disabled', sessions: [] })
  })
})
