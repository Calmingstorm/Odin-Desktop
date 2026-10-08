// The Records, Personality and State sections, mounted with their real code and the real stores over a fake bridge.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result } from '../../src/shared/api'
import { flush, mount, type Mounted } from './component-host'

vi.mock('../../src/renderer/src/dialog', () => ({ ask: async () => true }))

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const failed = { ok: false, error: { code: 'unavailable', message: 'core restarting', disposition: 'not_dispatched' } } as const

let odin: Record<string, unknown>
/** Answers held until the test lands them, by method. */
let held: Record<string, Array<(answer?: Result<unknown>) => void>>

function hold(method: string, answer: () => Result<unknown>): void {
  odin[method] = () => new Promise((resolve) => (held[method] ??= []).push((given) => resolve(given ?? answer())))
}

beforeEach(() => {
  vi.resetModules()
  held = {}
  odin = {}
  ;(globalThis as unknown as { window: unknown }).window = { odin }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
})

async function view(path: string): Promise<Mounted> {
  const component = (await import(`../../src/renderer/src/views/settings/${path}.vue`)).default
  const mounted = mount(component)
  await flush()
  return mounted
}

const call = (v: Mounted, name: string, ...args: unknown[]): Promise<unknown> => Promise.resolve((v.setup[name] as (...a: unknown[]) => unknown)(...args))

describe('review round 4: Records says what it knows', () => {
  beforeEach(() => {
    Object.assign(odin, {
      auditQuery: async () => ok([{ timestamp: '2026-10-05T00:00:00Z', tool_name: 'run_command', tool_input: { command: 'uptime' }, result_summary: 'up 3 days' }]),
      usage: async () => ok({ period: '24h', tokens: { value: 24, kind: 'measured' }, context: {}, quota: [], summary: '' }),
      healthGet: async () => ok({ overall: 'healthy', components: [], healthy_count: 0, degraded_count: 0, down_count: 0, unconfigured_count: 0, total: 0, checked_at: '' }),
      logsSearch: async () => failed,
      turnStateList: async () => failed,
      computerStatus: async () => ok({ available: true, state: 'quarantined', session_id: 's1', generation: 1, session_generation: 3, recovery: { status: 'operator_reconciliation_required', reason: 'controller_lost', complete: false } }),
      auditVerify: async () => failed
    })
  })

  it("says a section couldn't be read instead of showing it empty (16.R4.5)", async () => {
    const text = (await view('Records')).root.textContent()
    expect(text).toContain("Couldn't search the logs: core restarting")
    expect(text).toContain("Couldn't read preserved work: core restarting")
    expect(text).not.toContain('No entries.')
    expect(text).not.toContain('Nothing preserved.')
  })

  it("gives no verdict when the record couldn't be checked (16.R4.5)", async () => {
    const v = await view('Records')
    v.root.button('Verify the record').fire('click')
    await flush()
    expect(v.root.textContent()).toContain("Couldn't check the record: core restarting")
    expect(v.root.textContent()).not.toContain('Not intact')
  })

  it('shows each call with its scrubbed input (16.R4.6)', async () => {
    expect((await view('Records')).root.textContent()).toContain('"command": "uptime"')
  })

  it('names the period the usage shown covers (16.R4.4)', async () => {
    expect((await view('Records')).root.textContent()).toContain('24 tokens in the last 24 hours')
  })

  it('says a release left the session quarantined when Odin says so (16.R4.1)', async () => {
    const remaining = { available: true, state: 'quarantined', session_id: 's1', generation: 1, session_generation: 3, recovery: { status: 'unknown', reason: 'owned_process_remaining', complete: false } }
    odin.computerReconcile = async () => ok(remaining)
    Object.assign(odin, {
      toolsList: async () => ok({ tools: [] }),
      toolsTimeoutsGet: async () => ok({ default_timeout: 30, overrides: {} }),
      browserStatus: async () => ok({ state: 'unavailable', ready: false, retry_available: false })
    })
    const v = await view('Tools')
    odin.computerStatus = async () => ok(remaining)
    v.root.button('Release…').fire('click')
    await flush()
    const text = v.root.textContent()
    expect(text).toContain('Not released: a process the session started is still running. The session stays quarantined.')
    expect(text).not.toContain('released.')
  })
})

describe('review round 4: Personality keeps newer edits (16.R4.2)', () => {
  const personality = (preset: string) =>
    ok({
      preset,
      custom_name: '',
      custom_identity: '',
      custom_voice: '',
      presets: { default: { name: 'Odin', identity: 'i', voice: 'v' }, professional: { name: 'Professional', identity: 'p', voice: 'p' } },
      builtin_presets: ['default', 'professional'],
      user_presets: []
    })
  let core: string

  beforeEach(() => {
    core = 'default'
    odin.personalityGet = async () => personality(core)
    hold('personalitySet', () => ok({ preset: core }))
    hold('personalityPresetsSave', () => ok({ name: 'first' }))
  })

  it('keeps a choice and an identity made while a save was on its way', async () => {
    const v = await view('Personality')
    const select = v.root.findAll((node) => node.tag === 'select')[0]!
    const choose = async (preset: string) => {
      const index = select.options.findIndex((option) => option.props.value === preset)
      expect(index).toBeGreaterThanOrEqual(0)
      select.choose(index)
      await flush()
    }
    await choose('professional')
    void call(v, 'save')
    await flush()
    await choose('custom')
    const identity = v.root.findAll((node) => node.tag === 'textarea' && node.props.id === 'personality-identity')[0]!
    identity.type('UNSAVED NEW IDENTITY')
    await flush()
    core = 'professional'
    held.personalitySet!.shift()!()
    await flush()
    expect((v.setup.choice as Record<string, string>)).toMatchObject({ preset: 'custom', custom_identity: 'UNSAVED NEW IDENTITY' })
  })

  it('follows what Odin has for a field left as it was', async () => {
    const v = await view('Personality')
    core = 'professional'
    void call(v, 'save')
    await flush()
    held.personalitySet!.shift()!()
    await flush()
    expect((v.setup.choice as Record<string, string>).preset).toBe('professional')
  })

  it('keeps a second preset typed while the first was saved', async () => {
    const v = await view('Personality')
    const draft = v.setup.draft as Record<string, string>
    Object.assign(draft, { name: 'first', identity: 'first identity' })
    void call(v, 'saveAsPreset')
    await flush()
    Object.assign(draft, { name: 'second', identity: 'second identity' })
    held.personalityPresetsSave!.shift()!()
    await flush()
    expect(draft).toMatchObject({ name: 'second', identity: 'second identity' })
  })

  it('cancels custom text and preset drafts without writing', async () => {
    const v = await view('Personality')
    const choice = v.setup.choice as Record<string, string>
    Object.assign(choice, { preset: 'custom', custom_identity: 'UNSAVED' })
    v.root.named('Cancel personality changes').fire('click')
    Object.assign(v.setup.draft as object, { name: 'unsaved', identity: 'UNSAVED' })
    v.root.named('Cancel preset draft').fire('click')
    await flush()
    expect(choice).toMatchObject({ preset: 'default', custom_identity: '' })
    expect(v.setup.draft).toMatchObject({ name: '', identity: '' })
    expect(held.personalitySet ?? []).toHaveLength(0)
    expect(held.personalityPresetsSave ?? []).toHaveLength(0)
  })
})

describe('review round 4: State keeps newer drafts (16.R4.3)', () => {
  beforeEach(() => {
    Object.assign(odin, {
      memoryList: async () => ok({ global: { count: 2, keys: ['a', 'b'] } }),
      listsList: async () => ok({ items: [] }),
      memoryGet: async () => ok({ scope: 'global', entries: { a: 1, b: 2, c: 3 } }),
      knowledgeList: async () => ok([])
    })
    hold('knowledgeIngest', () => ok({ outcome: 'created', source: 'first.md', chunks: 1 }))
    hold('memorySet', () => ok({ scope: 'global', key: 'k1' }))
    hold('memoryBulkDelete', () => ok({ count: 2 }))
  })

  it('keeps a document typed while the first was stored', async () => {
    const v = await view('State')
    Object.assign(v.setup, { source: 'first.md', content: 'FIRST' })
    void call(v, 'add')
    await flush()
    Object.assign(v.setup, { source: 'second.md', content: 'UNSAVED SECOND DOCUMENT' })
    held.knowledgeIngest!.shift()!()
    await flush()
    expect([v.setup.source, v.setup.content]).toEqual(['second.md', 'UNSAVED SECOND DOCUMENT'])
  })

  it('keeps an entry editor opened while the first entry was saved', async () => {
    const v = await view('State')
    await call(v, 'editEntry', 'global', 'k1', 'v1')
    void call(v, 'saveEntry', 'global')
    await flush()
    await call(v, 'editEntry', 'global', 'k2', 'UNSAVED SECOND VALUE')
    held.memorySet!.shift()!()
    await flush()
    expect((v.setup.drafts as Record<string, unknown>).global).toEqual({ key: 'k2', value: 'UNSAVED SECOND VALUE' })
  })

  it('keeps keys picked while others were deleted', async () => {
    const v = await view('State')
    const picked = v.setup.picked as Record<string, string[]>
    picked.global = ['a', 'b']
    void call(v, 'removePicked', 'global')
    await flush()
    picked.global = [...picked.global!, 'c']
    held.memoryBulkDelete!.shift()!()
    await flush()
    expect(picked.global).toEqual(['c'])
  })
})
