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
    expect(await management.saveSkill('hello', 'x = 1', true)).toBe(false)
    expect(calls.save).toBeUndefined()
    expect(management.management.validation?.errors).toEqual(['execute() is missing.'])
    validation = { valid: true, errors: [], warnings: [], metadata: null, definition_keys: [] }
    expect(await management.saveSkill('hello', 'async def execute(inp, context): ...', true)).toBe(true)
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

