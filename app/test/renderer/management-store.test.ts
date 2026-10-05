// The management sections' state, driven through a fake bridge.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result, SkillValidation } from '../../src/shared/api'

type Management = typeof import('../../src/renderer/src/stores/management')

let management: Management
let calls: Record<string, Array<Record<string, unknown>>>
let validation: SkillValidation
let releaseToggle: (() => void) | null
let holdDetail = false
let heldDetail: Array<() => void> = []
let testAnswer: Result<unknown>
const toggles: Array<(answer: Result<unknown>) => void> = []

const ok = <T>(result: T): Result<T> => ({ ok: true, result })

beforeEach(async () => {
  vi.resetModules()
  calls = {}
  releaseToggle = null
  holdDetail = false
  heldDetail = []
  toggles.length = 0
  testAnswer = ok({ result: 'hello ran with empty input: fine.', is_error: false })
  validation = { valid: true, errors: [], warnings: [], metadata: null, definition_keys: [] }
  const record = (name: string) => (params: Record<string, unknown>) => {
    ;(calls[name] ??= []).push(params)
  }
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      skillsValidate: async (params: Record<string, unknown>) => (record('validate')(params), ok(validation)),
      skillsSave: async (params: Record<string, unknown>) => (record('save')(params), ok({ result: 'saved' })),
      skillsList: async () => ok([]),
      skillsGet: (params: { name: string }) => {
        const answer = ok({ name: params.name, code: 'x', config: {}, metadata: { config_schema: {} } })
        if (!holdDetail) return Promise.resolve(answer)
        return new Promise((resolve) => heldDetail.push(() => resolve(answer)))
      },
      skillsTest: async (params: Record<string, unknown>) => (record('test')(params), testAnswer),
      mcpStatus: async () => (record('mcpStatus')({}), ok({ enabled: false, servers: [], connected_count: 0 })),
      mcpSetGlobalEnabled: async (params: Record<string, unknown>) => (record('global')(params), ok({ saved: true, enabled: false, connected_count: 0 })),
      mcpSetEnabled: async (params: Record<string, unknown>) =>
        (record('serverSwitch')(params), ok({ enabled: true, servers: [{ name: 'LMMS', state: 'disabled', last_error: '' }], connected_count: 0 })),
      toolsSetEnabled: (params: Record<string, unknown>) => {
        record('toggle')(params)
        return new Promise<Result<unknown>>((resolve) => {
          releaseToggle = () => resolve(ok({ global_enabled: true, disabled_count: 1, tools: [] }))
        })
      }
    }
  }
  management = await import('../../src/renderer/src/stores/management')
})

describe('the management sections', () => {
  it('validates a skill before saving it, and saves nothing that fails validation', async () => {
    validation = { valid: false, errors: ['execute() is missing.'], warnings: [], metadata: null, definition_keys: [] }
    management.newSkill('x = 1')
    management.management.editor!.name = 'hello'
    expect(await management.saveSkill()).toBe(false)
    expect(calls.save).toBeUndefined()
    expect(management.management.validation?.errors).toEqual(['execute() is missing.'])
    validation = { valid: true, errors: [], warnings: [], metadata: null, definition_keys: [] }
    management.management.editor!.code = 'async def execute(inp, context): ...'
    expect(await management.saveSkill()).toBe(true)
    expect(calls.save).toEqual([{ name: 'hello', code: 'async def execute(inp, context): ...', create: true }])
    expect(management.management.notes['skill:hello']).toBe('saved')
  })

  it('sends one action per thing at a time: a second click while the first runs makes no second call', async () => {
    const first = management.setToolEnabled('web_search', false)
    await management.setToolEnabled('web_search', false)
    expect(calls.toggle).toHaveLength(1)
    releaseToggle?.()
    await first
    expect(management.management.notes['tool:web_search']).toBe('Off: Odin no longer sees this tool.')
  })
})

describe('review round 3: management answers, in order and never twice', () => {
  const UNKNOWN = { ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: 'cmd-1' } } as const

  it("keeps an unanswered skill test busy under its first command, and adopts that command's late receipt", async () => {
    testAnswer = UNKNOWN
    await management.testSkill('hello')
    await management.testSkill('hello')
    expect(calls.test).toHaveLength(1)
    expect(management.management.notes['skill:hello']).toMatch(/never sent twice/)
    const store = await import('../../src/renderer/src/store')
    store.applyReceipt({ id: 'cmd-1', settled: { ok: true, result: { result: 'late but fine', is_error: false } } })
    expect(management.management.busy['skill:hello']).toBe(false)
    expect(management.management.testResult).toEqual({ result: 'late but fine', is_error: false })
  })

  it('shows the skill asked for last, and none after closing, whatever order the answers come in', async () => {
    holdDetail = true
    void management.openSkill('alpha')
    void management.openSkill('beta')
    heldDetail[1]!()
    await new Promise((r) => setTimeout(r, 0))
    heldDetail[0]!()
    await new Promise((r) => setTimeout(r, 0))
    expect(management.management.skill?.name).toBe('beta')
    void management.openSkill('gamma')
    management.closeSkill()
    heldDetail[2]!()
    await new Promise((r) => setTimeout(r, 0))
    expect(management.management.skill).toBeNull()
  })

  it('never lets an older inventory answer replace a newer one', async () => {
    ;(window as unknown as { odin: Record<string, unknown> }).odin.toolsSetEnabled = () =>
      new Promise<Result<unknown>>((resolve) => toggles.push(resolve))
    const first = management.setToolEnabled('alpha', false)
    const second = management.setToolEnabled('beta', false)
    const inventory = (off: string[]) => ok({ global_enabled: true, disabled_count: off.length, tools: off.map((name) => ({ name, enabled: false })) })
    toggles[1]!(inventory(['alpha', 'beta']))
    await second
    toggles[0]!(inventory(['alpha']))
    await first
    expect(management.management.tools?.disabled_count).toBe(2)
  })

  it("takes the whole status from a server's switch, and reads it again after the global switch", async () => {
    await management.setMcpEnabled('LMMS', false)
    expect(management.management.mcp?.servers[0]?.state).toBe('disabled')
    expect(management.management.notes['mcp:LMMS']).toBe('Now disabled.')
    await management.setMcpGlobal(false)
    expect(calls.mcpStatus).toHaveLength(1)
    expect(management.management.notes.mcp).toMatch(/MCP is off/)
  })
})


describe('review round 4: a skill action that lands, now or late, finds the editor it belongs to', () => {
  const unknown = (id: string) => ({ ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: id } }) as const
  /** The core's skills, by name: what a save stores and a read returns. */
  let skills: Record<string, string>
  let held: Array<{ method: string; land: (answer?: Result<unknown>) => void }>
  let odin: Record<string, unknown>
  const settle = () => new Promise((r) => setTimeout(r, 0))

  beforeEach(() => {
    skills = { alpha: 'alpha v1', beta: 'beta v1' }
    held = []
    odin = (window as unknown as { odin: Record<string, unknown> }).odin
    odin.skillsGet = async (params: { name: string }) => {
      ;(calls.get ??= []).push(params)
      return ok({ name: params.name, code: skills[params.name], config: {}, metadata: { config_schema: {} } })
    }
  })

  /** Holds a method's answers: the core acts at once, and the test lands each answer, or loses it, when it chooses. */
  function hold(method: string, act: (params: Record<string, unknown>) => unknown): void {
    odin[method] = (params: Record<string, unknown>) => {
      const result = act(params)
      return new Promise((resolve) => held.push({ method, land: (answer) => resolve(answer ?? ok(result)) }))
    }
  }
  const saveInCore = (params: Record<string, unknown>) => ((skills[params.name as string] = params.code as string), { result: 'saved' })
  const store = () => import('../../src/renderer/src/store')

  it('reads a skill saved by a late receipt back into the editor (13.R4.1)', async () => {
    await management.openSkill('alpha')
    management.management.editor!.code = 'alpha v2'
    hold('skillsSave', saveInCore)
    const saving = management.saveSkill()
    await settle()
    held.shift()!.land(unknown('cmd-save'))
    expect(await saving).toBe(false)
    ;(await store()).applyReceipt({ id: 'cmd-save', settled: ok({ result: 'saved' }) })
    await settle()
    expect(management.management.skill?.code).toBe('alpha v2')
    expect(management.management.busy['skill:alpha']).toBe(false)
  })

  it('leaves create mode when a late receipt says the new skill was created (13.R4.1)', async () => {
    management.newSkill('fresh v1')
    management.management.editor!.name = 'fresh'
    hold('skillsSave', saveInCore)
    const saving = management.saveSkill()
    await settle()
    held.shift()!.land(unknown('cmd-create'))
    await saving
    ;(await store()).applyReceipt({ id: 'cmd-create', settled: ok({ result: 'created' }) })
    await settle()
    expect(management.management.editor).toMatchObject({ name: 'fresh', code: 'fresh v1', create: false })
    expect(management.management.skill?.name).toBe('fresh')
  })

  it("closes a skill's editor when a late receipt says it was deleted (13.R4.1)", async () => {
    await management.openSkill('alpha')
    hold('skillsDelete', () => ({ result: 'deleted' }))
    const deleting = management.deleteSkill('alpha')
    await settle()
    held.shift()!.land(unknown('cmd-delete'))
    await deleting
    expect(management.management.editor?.name).toBe('alpha')
    ;(await store()).applyReceipt({ id: 'cmd-delete', settled: ok({ result: 'deleted' }) })
    expect(management.management.editor).toBeNull()
    expect(management.management.skill).toBeNull()
  })

  it('keeps code typed while a new skill is being created (13.R4.2)', async () => {
    management.newSkill('as sent')
    management.management.editor!.name = 'fresh'
    hold('skillsSave', saveInCore)
    const saving = management.saveSkill()
    await settle()
    management.management.editor!.code = 'typed during create'
    held.shift()!.land()
    await saving
    await settle()
    expect(management.management.editor).toMatchObject({ name: 'fresh', code: 'typed during create', create: false })
  })

  it('leaves another skill opened meanwhile alone when a save lands (13.R4.3)', async () => {
    await management.openSkill('alpha')
    management.management.editor!.code = 'alpha v2'
    hold('skillsSave', saveInCore)
    const saving = management.saveSkill()
    await settle()
    await management.openSkill('beta')
    management.management.editor!.code = 'unsaved beta'
    const reads = calls.get!.length
    held.shift()!.land()
    await saving
    await settle()
    expect(management.management.editor).toMatchObject({ name: 'beta', code: 'unsaved beta' })
    expect(calls.get!.length).toBe(reads)
  })

  it("doesn't reopen a closed skill, or replace a new one, when its settings save lands (13.R4.3)", async () => {
    hold('skillsConfigSet', () => ({ result: 'saved' }))
    await management.openSkill('alpha')
    void management.saveSkillConfig('alpha', { units: 'metric' })
    await settle()
    management.closeSkill()
    held.shift()!.land()
    await settle()
    expect(management.management.editor).toBeNull()
    await management.openSkill('alpha')
    void management.saveSkillConfig('alpha', { units: 'imperial' })
    await settle()
    management.newSkill('a new draft')
    held.shift()!.land()
    await settle()
    expect(management.management.editor).toMatchObject({ code: 'a new draft', create: true })
  })

  it('leaves a new draft alone when an earlier save of a skill with its name lands', async () => {
    await management.openSkill('alpha')
    hold('skillsSave', saveInCore)
    const saving = management.saveSkill()
    await settle()
    management.newSkill('a new draft')
    management.management.editor!.name = 'alpha'
    held.shift()!.land()
    await saving
    await settle()
    expect(management.management.editor).toMatchObject({ name: 'alpha', code: 'a new draft', create: true })
  })

  it('keeps a new skill renamed while it was being created as a new draft', async () => {
    management.newSkill('fresh v1')
    management.management.editor!.name = 'fresh'
    hold('skillsSave', saveInCore)
    const saving = management.saveSkill()
    await settle()
    management.management.editor!.name = 'fresh_two'
    management.management.editor!.code = 'fresh two'
    held.shift()!.land()
    await saving
    await settle()
    expect(management.management.editor).toMatchObject({ name: 'fresh_two', code: 'fresh two', create: true })
  })

  it("leaves another skill opened meanwhile alone when a skill's settings save lands", async () => {
    hold('skillsConfigSet', () => ({ result: 'saved' }))
    await management.openSkill('alpha')
    void management.saveSkillConfig('alpha', { units: 'metric' })
    await settle()
    await management.openSkill('beta')
    management.management.editor!.code = 'unsaved beta'
    held.shift()!.land()
    await settle()
    expect(management.management.editor).toMatchObject({ name: 'beta', code: 'unsaved beta' })
  })

  it('never lets an older MCP status replace a newer one (13.R4.4)', async () => {
    const answers: Array<(status: Result<unknown>) => void> = []
    odin.mcpSetEnabled = () => new Promise((resolve) => answers.push(resolve))
    const status = (a: string, b: string) =>
      ok({ enabled: true, connected_count: 0, servers: [{ name: 'A', state: a, last_error: '' }, { name: 'B', state: b, last_error: '' }] })
    const first = management.setMcpEnabled('A', false)
    const second = management.setMcpEnabled('B', false)
    answers[1]!(status('disabled', 'disabled'))
    await second
    answers[0]!(status('disabled', 'connected'))
    await first
    expect(management.management.mcp?.servers.map((s) => s.state)).toEqual(['disabled', 'disabled'])
  })
})
