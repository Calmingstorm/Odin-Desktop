// The management sections' state, driven through a fake bridge.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result, SkillValidation } from '../../src/shared/api'

type Management = typeof import('../../src/renderer/src/stores/management')

let management: Management
let calls: Record<string, Array<Record<string, unknown>>>
let validation: SkillValidation
let releaseToggle: (() => void) | null

const ok = <T>(result: T): Result<T> => ({ ok: true, result })

beforeEach(async () => {
  vi.resetModules()
  calls = {}
  releaseToggle = null
  validation = { valid: true, errors: [], warnings: [], metadata: null, definition_keys: [] }
  const record = (name: string) => (params: Record<string, unknown>) => {
    ;(calls[name] ??= []).push(params)
  }
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      skillsValidate: async (params: Record<string, unknown>) => (record('validate')(params), ok(validation)),
      skillsSave: async (params: Record<string, unknown>) => (record('save')(params), ok({ result: 'saved' })),
      skillsList: async () => ok([]),
      skillsGet: async (params: { name: string }) => ok({ name: params.name, code: 'x', config: {}, metadata: { config_schema: {} } }),
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
