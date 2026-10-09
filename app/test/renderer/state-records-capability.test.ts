// Actual stores and compiled screens, with bridge answers controlled by the test. Capability refusals are not
// empty datasets, transient read failures, or permission to release a write whose receipt has not arrived.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result } from '../../src/shared/api'
import { flush, mount, type Host, type Mounted } from './component-host'

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const refused = { ok: false, error: { code: 'capability_unavailable', message: 'Service is not available yet', disposition: 'not_dispatched' } } as const
const failed = { ok: false, error: { code: 'unavailable', message: 'core restarting', disposition: 'not_dispatched' } } as const
const unknown = (id: string) => ({ ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: id } }) as const
const personality = { preset: 'custom', custom_name: 'Odin', custom_identity: 'loaded identity', custom_voice: 'loaded voice', presets: {}, builtin_presets: [], user_presets: [] }
const memory = { global: { count: 1, keys: ['old-entry'] } }
const knowledge = [{ source: 'old-source', chunks: 1, ingested_at: '', preview: 'OLD PREVIEW' }]
const computer = { available: true, enabled: true, state: 'quarantined', session_id: 's1', generation: 2 }
const served: Record<string, unknown> = {
  personalityGet: personality,
  memoryList: memory,
  listsList: { items: [{ name: 'old-list', count: 1, updated_at: '' }] },
  memoryGet: { scope: 'global', entries: { 'old-entry': 'OLD VALUE' } },
  listsGet: { items: ['OLD LIST ITEM'] },
  knowledgeList: knowledge,
  knowledgeVersions: [{ id: 1, version: 1, action: 'created', created_at: '', diff_summary: 'OLD VERSION' }],
  knowledgeSearch: [{ chunk_id: 'old:0', source: 'old-source', score: 1, content: 'OLD HIT', chunk_index: 0 }],
  auditQuery: [{ timestamp: '', tool_name: 'OLD TOOL' }],
  auditVerify: { valid: true, availability: 'available', total: 1, verified: 1, unsigned_prefix: 0 },
  usage: { period: '7d', tokens: { kind: 'measured', value: 123 }, quota: [], summary: 'OLD USAGE' },
  healthGet: { overall: 'healthy', components: [{ name: 'OLD HEALTH', status: 'healthy', detail: 'old' }], healthy_count: 1, degraded_count: 0, down_count: 0, unconfigured_count: 0, checked_at: '' },
  logsSearch: { entries: [{ timestamp: '', tool_name: 'read', result_summary: 'OLD LOG' }], count: 1 },
  turnStateList: { availability: 'available', data: { turns: [] } },
  computerStatus: computer
}

let odin: Record<string, ReturnType<typeof vi.fn>>
let mounted: Mounted[]
type State = typeof import('../../src/renderer/src/stores/state')
type Records = typeof import('../../src/renderer/src/stores/records')
let state: State
let records: Records
let management: typeof import('../../src/renderer/src/stores/management')['management']

beforeEach(async () => {
  vi.resetModules()
  mounted = []
  odin = Object.fromEntries(Object.keys(served).map((method) => [method, vi.fn(async () => refused)]))
  odin.settingsSchema = vi.fn(async () => refused)
  vi.stubGlobal('window', { odin })
  vi.stubGlobal('document', { activeElement: null })
  state = await import('../../src/renderer/src/stores/state')
  records = await import('../../src/renderer/src/stores/records')
  management = (await import('../../src/renderer/src/stores/management')).management
})

afterEach(() => {
  mounted.forEach((v) => v.unmount())
  vi.unstubAllGlobals()
})

function serve(...methods: string[]): void {
  for (const method of methods) odin[method]!.mockImplementation(async () => ok(served[method]))
}

async function view(name: 'Personality' | 'State' | 'Records' | 'Settings'): Promise<Mounted> {
  const component = name === 'Settings'
    ? (await import('../../src/renderer/src/views/Settings.vue')).default
    : (await import(`../../src/renderer/src/views/settings/${name}.vue`)).default
  const v = mount(component)
  mounted.push(v)
  await flush()
  return v
}

function panel(v: Mounted, name: string): Host {
  const panels = v.root.findAll((node) => node.props['aria-label'] === name)
  expect(panels).toHaveLength(1)
  return panels[0]!
}

function noControls(node: Host): void {
  expect(node.findAll((n) => ['button', 'input', 'select', 'textarea'].includes(n.tag))).toHaveLength(0)
  expect(node.textContent()).not.toContain('Service is not available yet')
  expect(node.textContent()).not.toMatch(/Loading|Nothing found|No entries|Nothing recorded|No lists/)
}

describe('per-resource state capability handling', () => {
  it('renders explicit refusal panels, not editor controls or empty datasets', async () => {
    const p = await view('Personality')
    expect(panel(p, 'Personality').textContent()).toContain('Personality is unavailable.')
    noControls(panel(p, 'Personality'))
    const v = await view('State')
    for (const [label, feature] of [['Memory', 'Memory'], ['Named lists', 'Named list management'], ['Knowledge', 'Knowledge']]) {
      expect(panel(v, label!).textContent()).toContain(`${feature} is unavailable.`)
      noControls(panel(v, label!))
    }
  })

  it('clears returned rows, detail, search and obsolete errors but retains pending notes and locks', async () => {
    serve('personalityGet', 'memoryList', 'listsList', 'memoryGet', 'listsGet', 'knowledgeList', 'knowledgeVersions', 'knowledgeSearch')
    await Promise.all([state.loadPersonality(), state.loadMemory(), state.loadKnowledge()])
    await Promise.all([state.openScope('global'), state.openList('old-list'), state.loadVersions('old-source'), state.searchKnowledge('old')])
    Object.assign(state.stateStore.errors, { personality: 'OLD ERROR', memory: 'OLD ERROR', lists: 'OLD ERROR', knowledge: 'OLD ERROR' })
    management.notes['memory:global'] = 'Waiting for receipt'
    management.busy['memory:global'] = true
    management.notes['knowledge:old-source'] = 'OLD NOTE'
    management.notes.preset = 'OLD NOTE'
    for (const method of ['personalityGet', 'memoryList', 'listsList', 'knowledgeList']) odin[method]!.mockImplementation(async () => refused)
    await Promise.all([state.loadPersonality(), state.loadMemory(), state.loadKnowledge()])
    expect(state.stateStore).toMatchObject({ personality: null, memory: null, memoryEntries: {}, lists: [], listItems: {}, knowledge: [], hits: null, versions: {} })
    expect(Object.values(state.stateStore.errors)).not.toContain('OLD ERROR')
    expect(management.notes['knowledge:old-source']).toBeUndefined()
    expect(management.notes.preset).toBeUndefined()
    expect(management.busy['memory:global']).toBe(true)
    expect(management.notes['memory:global']).toBe('Waiting for receipt')
  })

  it('handles memory, lists and knowledge independently, without waiting for the list read', async () => {
    let release!: (answer: Result<unknown>) => void
    odin.listsList!.mockImplementation(() => new Promise((r) => { release = r }))
    serve('knowledgeList')
    const loading = state.loadMemory()
    await state.loadKnowledge()
    await flush()
    expect(state.stateStore.unavailable.memory).toBe(true)
    expect(state.stateStore.knowledge).toEqual(knowledge)
    expect(state.stateStore.unavailable.knowledge).toBe(false)
    release(ok(served.listsList))
    await loading
    expect(state.stateStore.unavailable.lists).toBe(false)
    expect(state.stateStore.lists).toEqual((served.listsList as { items: unknown[] }).items)
  })

  it('recovers on success and restores controls while keeping personality edit intent and preset draft', async () => {
    serve('personalityGet')
    const v = await view('Personality')
    const identity = panel(v, 'Personality').findAll((n) => n.props.id === 'personality-identity')[0]!
    identity.type('UNSAVED IDENTITY')
    Object.assign(v.setup.draft as object, { name: 'unsaved', identity: 'UNSAVED PRESET' })
    odin.personalityGet!.mockImplementation(async () => refused)
    await state.loadPersonality()
    await flush()
    noControls(panel(v, 'Personality'))
    odin.personalityGet!.mockImplementation(async () => ok({ ...personality, custom_identity: 'new core identity' }))
    await state.loadPersonality()
    await flush()
    expect(state.stateStore.unavailable.personality).toBe(false)
    expect((v.setup.choice as Record<string, string>).custom_identity).toBe('UNSAVED IDENTITY')
    expect(v.setup.draft).toMatchObject({ name: 'unsaved', identity: 'UNSAVED PRESET' })
    expect(panel(v, 'Personality').button('Save').props.disabled).not.toBe(true)
  })

  it('keeps memory and ingest drafts through refusal and success, with no unavailable mutations dispatched', async () => {
    serve('memoryList', 'listsList', 'knowledgeList')
    const v = await view('State')
    ;(v.setup.editEntry as (scope: string, key: string, value: string) => void)('global', 'unsaved-key', 'UNSAVED VALUE')
    Object.assign(v.setup, { source: 'unsaved.md', content: 'UNSAVED DOCUMENT' })
    odin.memoryList!.mockImplementation(async () => refused)
    odin.knowledgeList!.mockImplementation(async () => refused)
    await Promise.all([state.loadMemory(), state.loadKnowledge()])
    await flush()
    noControls(panel(v, 'Memory'))
    noControls(panel(v, 'Knowledge'))
    // Adding a document is its own section; a refused knowledge capability hides it whole.
    expect(v.root.findAll((node) => node.props['aria-label'] === 'Add a document')).toHaveLength(0)
    odin.memorySet = vi.fn(async () => ok({}))
    odin.knowledgeIngest = vi.fn(async () => ok({ outcome: 'created' }))
    expect(await state.setMemory('global', 'unsaved-key', 'UNSAVED VALUE')).toBe(false)
    expect(await state.ingest('unsaved.md', 'UNSAVED DOCUMENT')).toBe(false)
    expect(odin.memorySet).not.toHaveBeenCalled()
    expect(odin.knowledgeIngest).not.toHaveBeenCalled()
    serve('memoryList', 'knowledgeList')
    await Promise.all([state.loadMemory(), state.loadKnowledge()])
    await flush()
    expect(v.setup.drafts).toMatchObject({ global: { key: 'unsaved-key', value: 'UNSAVED VALUE' } })
    expect([v.setup.source, v.setup.content]).toEqual(['unsaved.md', 'UNSAVED DOCUMENT'])
    expect(panel(v, 'Add a document').button('Add').props.disabled).not.toBe(true)
  })

  it('never resurrects an older detail or search answer after its capability was refused', async () => {
    serve('memoryList', 'listsList', 'knowledgeList')
    await Promise.all([state.loadMemory(), state.loadKnowledge()])
    const held: Array<(r: Result<unknown>) => void> = []
    for (const method of ['memoryGet', 'knowledgeVersions', 'knowledgeSearch']) odin[method]!.mockImplementation(() => new Promise((r) => held.push(r)))
    const pending = [state.openScope('global'), state.loadVersions('old-source'), state.searchKnowledge('old')]
    odin.memoryList!.mockImplementation(async () => refused)
    odin.knowledgeList!.mockImplementation(async () => refused)
    await Promise.all([state.loadMemory(), state.loadKnowledge()])
    held[0]!(ok(served.memoryGet))
    held[1]!(ok(served.knowledgeVersions))
    held[2]!(ok(served.knowledgeSearch))
    await Promise.all(pending)
    expect(state.stateStore.memoryEntries).toEqual({})
    expect(state.stateStore.versions).toEqual({})
    expect(state.stateStore.hits).toBeNull()
    expect(state.stateStore.unavailable).toMatchObject({ memory: true, knowledge: true })
  })

  it('refuses individual detail and search routes explicitly and recovers only through new served reads', async () => {
    serve('memoryList', 'listsList', 'knowledgeList')
    await Promise.all([state.loadMemory(), state.loadKnowledge()])
    await state.openScope('global')
    expect(state.stateStore.unavailable.memory).toBe(true)
    expect(state.stateStore.memory).toBeNull()
    expect(state.stateStore.unavailable.lists).toBe(false)
    await state.openList('old-list')
    expect(state.stateStore.unavailable.lists).toBe(true)
    expect(state.stateStore.lists).toEqual([])
    await state.loadVersions('old-source')
    expect(state.stateStore.unavailable.knowledge).toBe(true)
    expect(state.stateStore.knowledge).toEqual([])
    await state.loadKnowledge()
    await state.searchKnowledge('words')
    expect(state.stateStore.unavailable.knowledge).toBe(true)
    expect(state.stateStore.hits).toBeNull()
  })

  it('reports refused writes plainly without throwing away local intent or unlocking other pending work', async () => {
    serve('personalityGet', 'memoryList', 'listsList', 'knowledgeList')
    await Promise.all([state.loadPersonality(), state.loadMemory(), state.loadKnowledge()])
    odin.personalitySet = vi.fn(async () => refused)
    odin.memorySet = vi.fn(async () => refused)
    odin.knowledgeIngest = vi.fn(async () => refused)
    // The readback refuses as well. No write refusal is an instruction to claim saved or clear a draft.
    for (const method of ['personalityGet', 'memoryList', 'knowledgeList']) odin[method]!.mockImplementation(async () => refused)
    const saved = vi.fn()
    expect(await state.savePersonality({ preset: 'custom', custom_identity: 'DRAFT' }, saved)).toBe(false)
    expect(saved).not.toHaveBeenCalled()
    expect(await state.setMemory('global', 'draft', 'DRAFT')).toBe(false)
    expect(await state.ingest('draft.md', 'DRAFT')).toBe(false)
    expect(state.stateStore.unavailable).toMatchObject({ personality: true, memory: true, knowledge: true })
    expect(Object.values(management.notes).join(' ')).not.toContain('Service is not available yet')
  })

  it('retains an unknown write lock through refusal, then settles only its late receipt', async () => {
    serve('knowledgeList')
    await state.loadKnowledge()
    odin.knowledgeIngest = vi.fn(async () => unknown('ingest-1'))
    expect(await state.ingest('draft.md', 'DRAFT')).toBe(false)
    expect(management.busy.knowledge).toBe(true)
    odin.knowledgeList!.mockImplementation(async () => refused)
    await state.loadKnowledge()
    expect(management.busy.knowledge).toBe(true)
    expect(management.notes.knowledge).toContain('never sent twice')
    serve('knowledgeList')
    await state.loadKnowledge()
    expect(await state.ingest('draft.md', 'DRAFT')).toBe(false)
    expect(odin.knowledgeIngest).toHaveBeenCalledTimes(1)
    const store = await import('../../src/renderer/src/store')
    store.applyReceipt({ id: 'ingest-1', settled: ok({ source: 'draft.md', outcome: 'created', chunks: 1 }) })
    await flush()
    expect(management.busy.knowledge).toBe(false)
  })

  it('loads each own screen under a refused settings schema, instead of treating schema as its capability', async () => {
    const v = await view('Settings')
    for (const label of ['Personality', 'Data and privacy']) {
      v.root.findAll((n) => n.tag === 'button' && String(n.props.class).includes('settings-nav-item')).find((n) => n.textContent().trim() === label)!.fire('click')
      await flush()
    }
    v.root.button('Usage, logs and audit').fire('click')
    await flush()
    expect(odin.settingsSchema).toHaveBeenCalledTimes(1)
    for (const method of ['personalityGet', 'memoryList', 'listsList', 'knowledgeList', 'auditQuery', 'usage', 'healthGet', 'logsSearch', 'turnStateList', 'computerStatus']) expect(odin[method]).toHaveBeenCalledTimes(1)
    expect(v.root.textContent()).toContain('Settings are unavailable.')
    expect(panel(v, 'Computer use').textContent()).toContain('Computer use is unavailable.')
  })
})

describe('per-section records capability handling', () => {
  it('clears all stale facts/errors and renders specific unavailable panels without controls', async () => {
    serve(...Object.keys(served))
    await records.loadRecords()
    await records.verifyAudit()
    for (const section of ['audit', 'verify', 'usage', 'health', 'logs', 'turns', 'computer'] as const) records.records.errors[section] = 'OLD ERROR'
    management.busy['computer:s1'] = true
    management.notes['computer:s1'] = 'Waiting for receipt'
    for (const method of ['auditQuery', 'auditVerify', 'usage', 'healthGet', 'logsSearch', 'turnStateList', 'computerStatus']) odin[method]!.mockImplementation(async () => refused)
    await records.loadRecords()
    await records.verifyAudit()
    const v = await view('Records')
    for (const [label, feature] of [['Health', 'Health'], ['Usage', 'Usage'], ['Audit', 'Audit'], ['Logs', 'Log search'], ['Turn state', 'Preserved work'], ['Computer use', 'Computer use']]) {
      expect(panel(v, label!).textContent()).toContain(`${feature} is unavailable.`)
      noControls(panel(v, label!))
    }
    expect(records.records).toMatchObject({ audit: [], verify: null, usage: null, health: null, logs: [], turns: null, computer: null, errors: {}, loaded: {} })
    expect(v.root.textContent()).not.toMatch(/OLD|123 tokens|Intact|quarantined/)
    expect(management.busy['computer:s1']).toBe(true)
    expect(management.notes['computer:s1']).toBe('Waiting for receipt')
    odin.computerReconcile = vi.fn(async () => ok(computer))
    expect(await records.reconcileComputer(computer as never)).toBe(false)
    expect(odin.computerReconcile).not.toHaveBeenCalled()
  })

  it('recovers individual sections and preserves served behavior beside refused ones', async () => {
    const v = await view('Records')
    serve('auditQuery', 'auditVerify', 'usage')
    await Promise.all([records.loadAudit(), records.loadUsage('7d'), records.verifyAudit()])
    await flush()
    expect(panel(v, 'Audit').textContent()).toContain('OLD TOOL')
    expect(panel(v, 'Audit').textContent()).toContain('Intact')
    expect(panel(v, 'Audit').button('Verify the record')).toBeDefined()
    expect(panel(v, 'Usage').textContent()).toContain('123 tokens')
    expect(panel(v, 'Health').textContent()).toContain('Health is unavailable')
    expect(records.records.unavailable).toMatchObject({ audit: false, verify: false, usage: false, health: true })
    odin.auditVerify!.mockImplementation(async () => refused)
    await records.verifyAudit()
    await flush()
    expect(panel(v, 'Audit').textContent()).toContain('Audit verification is unavailable.')
    expect(panel(v, 'Audit').findAll((n) => n.tag === 'button' && n.textContent() === 'Verify the record')).toHaveLength(0)
    expect(panel(v, 'Audit').textContent()).not.toContain('Intact')
  })

  it('keeps transient read failures distinct from refused capabilities and ignores out-of-order reads', async () => {
    serve('healthGet')
    await records.loadHealth()
    odin.healthGet!.mockImplementation(async () => failed)
    await records.loadHealth()
    expect(records.records.health?.components[0]?.name).toBe('OLD HEALTH')
    expect(records.records.errors.health).toBe('core restarting')
    expect(records.records.unavailable.health).toBe(false)
    let release!: (r: Result<unknown>) => void
    odin.healthGet!.mockImplementationOnce(() => new Promise((r) => { release = r })).mockImplementation(async () => refused)
    const old = records.loadHealth()
    await records.loadHealth()
    release(ok(served.healthGet))
    await old
    expect(records.records.health).toBeNull()
    expect(records.records.unavailable.health).toBe(true)
    expect(records.records.errors.health).toBeUndefined()
  })

  it('holds unknown computer reconciliation under its original command until a late receipt settles it', async () => {
    serve('computerStatus')
    await records.loadComputer()
    odin.computerReconcile = vi.fn(async () => unknown('reconcile-1'))
    expect(await records.reconcileComputer(computer as never)).toBe(false)
    expect(management.busy['computer:s1']).toBe(true)
    odin.computerStatus!.mockImplementation(async () => refused)
    await records.loadComputer()
    expect(records.records.computer).toBeNull()
    expect(management.busy['computer:s1']).toBe(true)
    serve('computerStatus')
    await records.loadComputer()
    expect(await records.reconcileComputer(computer as never)).toBe(false)
    expect(odin.computerReconcile).toHaveBeenCalledTimes(1)
    const store = await import('../../src/renderer/src/store')
    store.applyReceipt({ id: 'reconcile-1', settled: ok({ ...computer, state: 'closed', recovery: { status: 'operator_acknowledged_unverified', complete: false } }) })
    await flush()
    expect(management.busy['computer:s1']).toBe(false)
    expect(management.notes['computer:s1']).toContain('Mouse and keyboard release stays unverified')
  })
})
