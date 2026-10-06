import { describe, expect, it } from 'vitest'
import { workControlSchema } from '../src/main/schemas'

const base = { control_command_id: 'a917643e-2f11-4b95-b1d4-045f2f5ff411', kind: 'agent', id: 'work01', action: 'cancel' }

describe('named work controls over the real-core contract', () => {
  it('preserves exact optional core bindings and schedule revision, without widening to generic RPC', () => {
    const params = { ...base, kind: 'schedule', action: 'pause', manager_generation: '2026-10-06T00:00:00Z', run_id: 'run01', conversation_id: 'conversation01', generation: 1, revision: 7 }
    expect(workControlSchema.parse(params)).toEqual(params)
    expect(workControlSchema.parse(base)).toEqual(base)
    for (const field of ['owner_id', 'manager_id', 'method']) expect(workControlSchema.safeParse({ ...base, [field]: 'untrusted' }).success).toBe(false)
  })

  it('accepts nonempty agent steer text, and bounds optional values', () => {
    const steer = { ...base, action: 'steer', text: 'Keep the original scope.' }
    expect(workControlSchema.parse(steer)).toEqual(steer)
    expect(workControlSchema.parse({ ...steer, text: '   ' }).text).toBe('   ')
    // Agent mailboxes have no 4,000-character chat-steer limit. Transport framing retains its own byte bound.
    expect(workControlSchema.parse({ ...steer, text: 'x'.repeat(4001) }).text).toHaveLength(4001)
    for (const params of [
      { ...base, action: 'steer' }, { ...steer, text: '' }, { ...steer, kind: 'task' },
      { ...base, text: 'unexpected' },
      { ...base, revision: -1 }, { ...base, generation: 1.5 }, { ...base, manager_generation: '' }
    ]) expect(workControlSchema.safeParse(params).success).toBe(false)
  })
})
