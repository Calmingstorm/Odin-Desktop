// Step 5 service/store responses, exercised through actual stores and compiled Vue views.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Mounted } from './component-host'

const ok = (result: unknown) => ({ ok: true, result })
const refused = { ok: false, error: { code: 'capability_unavailable', message: 'unavailable', disposition: 'not_dispatched' } }
let odin: Record<string, ReturnType<typeof vi.fn>>
let mounted: Mounted[]

beforeEach(() => {
  vi.resetModules()
  mounted = []
  odin = Object.fromEntries([
    'usage', 'healthGet', 'computerStatus', 'reload'
  ].map((name) => [name, vi.fn(async () => refused)]))
  Object.assign(odin, {
    memoryList: vi.fn(async () => ok({ global: { count: 1, keys: ['note'] }, user_profile_owner: { count: 1, keys: ['private'] } })),
    memoryGet: vi.fn(async () => ok({ scope: 'user_profile_owner', entries: { private: 'private value' } })),
    memorySet: vi.fn(async () => ok({ status: 'saved', scope: 'user_profile_owner', key: 'new' })),
    listsList: vi.fn(async () => ok({ items: [{ name: 'shopping', count: 2, updated_at: '' }] })),
    listsGet: vi.fn(async () => ok({ name: 'shopping', items: [
      { name: 'coffee', done: false, added_by: 'owner', added_at: '' },
      { name: 'paper', done: true, added_by: 'owner', added_at: '' }
    ] })),
    knowledgeList: vi.fn(async () => ok([])),
    knowledgeIngest: vi.fn(async () => ok({ source: 'runbook.md', chunks: 3 })),
    knowledgeReingest: vi.fn(async () => ok({ source: 'runbook.md', chunks: 3 })),
    auditQuery: vi.fn(async () => ok([])),
    auditVerify: vi.fn(async () => ok({ valid: false, availability: 'not_enabled', total: 0, verified: 0, unsigned_prefix: 0, error: 'Signing not enabled' })),
    logsSearch: vi.fn(async () => ok({ count: 2, entries: [
      { timestamp: '2026-10-05T00:00:00Z', tool_name: 'read_file', error: null, result_summary: 'three lines read' },
      { timestamp: '2026-10-05T00:00:00Z', tool_name: 'run_command', error: 'permission denied', result_summary: 'failed' }
    ] })),
    turnStateList: vi.fn(async () => ok({ schema_version: 1, availability: 'available', observed_at: '', data: { turns: [
      { source: 'desktop', channel_id: 'conversation-a', message_id: 'request-a', turn_generation: 1, status: 'ACTIVE',
        created_at: 1791158400, last_progress_at: 1791158400, suspended_at: null, has_checkpoint: true,
        requires_attention: false, manual_resolution_operations: 0, outcome_unknown_operations: 2 },
      { source: 'desktop', channel_id: 'conversation-b', message_id: 'request-b', turn_generation: 1, status: 'SUSPENDED',
        created_at: 1791158400, last_progress_at: null, suspended_at: 1791158400, has_checkpoint: true,
        requires_attention: true, manual_resolution_operations: 1, outcome_unknown_operations: 0 }
    ] } }))
  })
  vi.stubGlobal('window', { odin })
  vi.stubGlobal('document', { activeElement: null })
})

afterEach(() => {
  mounted.forEach((v) => v.unmount())
  vi.unstubAllGlobals()
})

async function view(name: 'State' | 'Records'): Promise<Mounted> {
  const component = (await import(`../../src/renderer/src/views/settings/${name}.vue`)).default
  const v = mount(component)
  mounted.push(v)
  await flush()
  return v
}

describe('Step 5 renderer integration shapes', () => {
  it('puts record section headings outside their cards, including capability refusals', async () => {
    const v = await view('Records')
    for (const label of ['Health', 'Usage', 'Audit', 'Logs', 'Turn state', 'Computer use']) {
      const section = v.root.findAll((n) => n.props['aria-label'] === label)[0]!
      expect(String(section.props.class)).toContain('settings-section')
      const card = section.findAll((n) => String(n.props.class).split(' ').includes('settings-card'))[0]!
      expect(section.findAll((n) => n.tag === 'h3')).toHaveLength(1)
      expect(card.findAll((n) => n.tag === 'h3')).toHaveLength(0)
    }
  })

  it('keeps Data computer status read-only and links to its single management screen', async () => {
    const session = { session_id: 'record-session', generation: 9, state: 'quarantined', recovery: { status: 'unknown', reason: 'owned_input_release_unproven', complete: false, unknown_release: true, receiver_release_verified: false } }
    odin.computerStatus!.mockImplementation(async () => ok({ session, readiness: { management_available: true, foreground_available: false, native_qualified: false, input_supported: false, dispatch: 'none', reason: 'foreground_binding_and_native_qualification_pending' } }))
    odin.computerReconcile = vi.fn(async () => ok({}))
    const v = await view('Records')
    const report = v.root.findAll((n) => n.props['aria-label'] === 'Computer use')[0]!
    expect(report.textContent()).toContain('record-session')
    expect(report.textContent()).toContain('generation 9')
    expect(report.textContent()).toContain('quarantined')
    expect(report.textContent()).toContain('Input release remains unverified.')
    expect(report.textContent()).toContain('Recovery is incomplete. Do not resume desktop input.')
    expect(report.findAll((n) => n.tag === 'button').map((n) => n.textContent())).toEqual(['Refresh', 'Go to Tools'])
    await report.button('Refresh').fire('click')
    await flush()
    expect(odin.computerStatus).toHaveBeenCalledTimes(2)
    expect(odin.computerReconcile).not.toHaveBeenCalled()
    await report.button('Go to Tools').fire('click')
    const { state } = await import('../../src/renderer/src/store')
    expect(state.settingsSection).toBe('tools')
    expect(odin.computerReconcile).not.toHaveBeenCalled()
  })

  it('never treats no session or recorded recovery as proof that desktop input was released', async () => {
    const readiness = { management_available: true, foreground_available: true, native_qualified: false, input_supported: true, dispatch: 'x11', reason: 'available_on_x11' }
    odin.computerStatus!.mockImplementation(async () => ok({ session: null, readiness }))
    const v = await view('Records')
    expect(v.root.textContent()).toContain('Each request still needs consent and a verified target.')
    expect(v.root.textContent()).toContain('Odin must also accept the request before sending input.')
    expect(v.root.textContent()).toContain('does not confirm that mouse and keyboard input was released')
    odin.computerStatus!.mockImplementation(async () => ok({ readiness, session: { session_id: 'closed', generation: 10, state: 'closed', recovery: { status: 'complete', reason: 'recorded_recovery', complete: true, unknown_release: true, receiver_release_verified: false } } }))
    const store = await import('../../src/renderer/src/stores/records')
    await store.loadComputer()
    await flush()
    expect(v.root.textContent()).toContain('Recovery is recorded as complete; this does not confirm input is safe to resume.')
    expect(v.root.textContent()).toContain('Input release remains unverified.')
  })

  it('styles the real checker ok status as healthy without labeling unavailable backends failed', async () => {
    odin.healthGet!.mockImplementation(async () => ok({
      overall: 'healthy', healthy_count: 1, degraded_count: 0, down_count: 0, unconfigured_count: 0,
      unavailable_count: 1, total: 2, checked_at: '2026-10-05T00:00:00Z',
      components: [{ name: 'store', healthy: true, status: 'ok', detail: 'ready' },
        { name: 'desktop', healthy: true, status: 'unavailable', detail: 'not composed' }]
    }))
    const v = await view('Records')
    const chips = v.root.findAll((n) => n.tag === 'span' && String(n.props.class).includes('state-chip'))
    expect(chips.find((n) => n.textContent() === 'ok')!.props.class).toContain('connected')
    expect(chips.find((n) => n.textContent() === 'unavailable')!.props.class).toContain('disabled')
  })

  it('acknowledges fresh durable ingest and reingest without fixture-only outcome/status', async () => {
    const v = await view('State')
    Object.assign(v.setup, { source: 'runbook.md', content: 'full document' })
    await (v.setup.add as () => Promise<void>)()
    await flush()
    expect([v.setup.source, v.setup.content]).toEqual(['', ''])
    expect(v.root.textContent()).toContain('Stored as 3 chunks.')
    const store = await import('../../src/renderer/src/stores/state')
    await store.reingest('runbook.md')
    const { management } = await import('../../src/renderer/src/stores/management')
    expect(management.notes['knowledge:runbook.md']).toBe('Stored as 3 chunks.')
  })

  it.each(['duplicate', 'conflict'])('keeps an ingest draft for the %s outcome despite a successful transport receipt', async (outcome) => {
    odin.knowledgeIngest!.mockImplementation(async () => ok({ source: 'runbook.md', outcome, status: 'not ingested', message: 'not stored' }))
    const v = await view('State')
    Object.assign(v.setup, { source: 'runbook.md', content: 'full document' })
    await (v.setup.add as () => Promise<void>)()
    expect([v.setup.source, v.setup.content]).toEqual(['runbook.md', 'full document'])
  })

  it('clears an unchanged stored document and refuses oversized drafts before dispatch', async () => {
    odin.knowledgeIngest!.mockImplementation(async () => ok({ source: 'runbook.md', chunks: 3, outcome: 'unchanged', status: 'already stored, unchanged' }))
    const v = await view('State')
    Object.assign(v.setup, { source: 'runbook.md', content: 'full document' })
    await (v.setup.add as () => Promise<void>)()
    expect([v.setup.source, v.setup.content]).toEqual(['', ''])
    expect(odin.knowledgeIngest).toHaveBeenCalledTimes(1)
    Object.assign(v.setup, { source: 's'.repeat(101), content: 'full document' })
    await (v.setup.add as () => Promise<void>)()
    Object.assign(v.setup, { source: 'runbook.md', content: 'x'.repeat(500001) })
    await (v.setup.add as () => Promise<void>)()
    expect(odin.knowledgeIngest).toHaveBeenCalledTimes(1)
  })

  it('labels the authorized user scope while sending its exact identifier, and shows list item names/completion', async () => {
    const v = await view('State')
    expect(v.root.textContent()).toContain('Yours')
    expect(v.root.textContent()).not.toContain('Invalid Date')
    await (v.setup.editEntry as (scope: string, key: string, value: string) => void)('user_profile_owner', 'new', 'new value')
    await (v.setup.saveEntry as (scope: string) => Promise<void>)('user_profile_owner')
    expect(odin.memorySet).toHaveBeenCalledWith({ scope: 'user_profile_owner', key: 'new', value: 'new value' })
    const store = await import('../../src/renderer/src/stores/state')
    await store.openList('shopping')
    await flush()
    expect(v.root.textContent()).toContain('coffee')
    expect(v.root.textContent()).toContain('Done: paper')
    expect(v.root.textContent()).not.toContain('added_by')
  })

  it('renders raw audit log results and errors instead of assuming synthetic level/message fields', async () => {
    const v = await view('Records')
    const logs = v.root.findAll((n) => n.props['aria-label'] === 'Logs')[0]!
    expect(logs.textContent()).toContain('INFO')
    expect(logs.textContent()).toContain('three lines read')
    expect(logs.textContent()).toContain('ERROR')
    expect(logs.textContent()).toContain('permission denied')
    expect(logs.findAll((n) => n.tag === 'td' && n.textContent() === 'ERROR')[0]!.props.class).toContain('bad')
  })

  it('cannot restore deletion versions that have no content snapshot', async () => {
    odin.knowledgeList!.mockImplementation(async () => ok([{ source: 'runbook.md', chunks: 3, ingested_at: '', preview: 'document' }]))
    odin.knowledgeVersions = vi.fn(async () => ok([
      { id: 2, version: 2, action: 'delete', created_at: '', diff_summary: 'deleted', chunk_count: 3 },
      { id: 1, version: 1, action: 'ingest', created_at: '', diff_summary: 'created', chunk_count: 3 }
    ]))
    const v = await view('State')
    const store = await import('../../src/renderer/src/stores/state')
    await store.loadVersions('runbook.md')
    await flush()
    const restore = v.root.findAll((n) => n.tag === 'button' && n.textContent() === 'Restore')
    expect(restore).toHaveLength(2)
    expect(restore[0]!.props.disabled).toBe(true)
    expect(restore[1]!.props.disabled).not.toBe(true)
  })

  it('does not call disabled signing a broken audit chain', async () => {
    const v = await view('Records')
    v.root.button('Verify the record').fire('click')
    await flush()
    expect(v.root.textContent()).toContain('Signing is not enabled. The record is unverified')
    expect(v.root.textContent()).not.toContain('Not intact')
  })

  it('distinguishes verified signed history, unsigned history, and genuine chain errors', async () => {
    const v = await view('Records')
    const store = await import('../../src/renderer/src/stores/records')
    odin.auditVerify!.mockImplementation(async () => ok({ valid: true, availability: 'available', total: 8, verified: 5, unsigned_prefix: 3 }))
    await store.verifyAudit()
    await flush()
    expect(v.root.textContent()).toContain('5 signed entries verified; 3 unsigned entries remain unverified.')
    expect(v.root.textContent()).not.toContain('Intact:')
    odin.auditVerify!.mockImplementation(async () => ok({ valid: true, availability: 'available', total: 8, verified: 8, unsigned_prefix: 0 }))
    await store.verifyAudit()
    await flush()
    expect(v.root.textContent()).toContain('Intact: 8 signed entries verified.')
    odin.auditVerify!.mockImplementation(async () => ok({ valid: false, availability: 'available', total: 8, verified: 5, error: 'audit.jsonl: signature mismatch' }))
    await store.verifyAudit()
    await flush()
    expect(v.root.textContent()).toContain('Not intact: audit.jsonl: signature mismatch.')
  })

  it('uses real turn identity/epoch timestamps and separates attention from historical ambiguity', async () => {
    const { state } = await import('../../src/renderer/src/store')
    state.conversations = [{ id: 'conversation-a', title: 'My work' }] as typeof state.conversations
    const v = await view('Records')
    const turns = v.root.findAll((n) => n.props['aria-label'] === 'Turn state')[0]!
    const rows = turns.findAll((n) => n.tag === 'li')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.textContent()).toContain('My work, request request-a')
    expect(rows[0]!.textContent()).toContain(new Date(1791158400 * 1000).toLocaleString())
    expect(rows[0]!.textContent()).toContain('2 historical unknown (diagnostic only)')
    expect(rows[0]!.textContent()).not.toContain('Needs attention')
    expect(rows[1]!.textContent()).toContain('conversation-b, request request-b')
    expect(rows[1]!.textContent()).toContain('Needs attention')
    expect(rows[1]!.textContent()).toContain('1 need manual resolution')
  })
})
