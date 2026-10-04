import { describe, expect, it } from 'vitest'
import { controlSchema, parseRequest, steerSchema, submitSchema } from '../src/main/schemas'

const uuid = '0b6f1c1e-9a3e-4a8e-9d43-2f1f0c7d5a10'

describe('bridge request validation', () => {
  it('accepts a well-formed submission', () => {
    const r = parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: 'c_1', text: 'hi' })
    expect(r.ok).toBe(true)
  })

  it('refuses unknown fields, bad IDs and oversized text', () => {
    expect(parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: 'c_1', text: 'hi', extra: 1 }).ok).toBe(false)
    expect(parseRequest(submitSchema, { client_submission_id: 'not-a-uuid', conversation_id: 'c_1', text: 'hi' }).ok).toBe(false)
    expect(parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: '../etc', text: 'hi' }).ok).toBe(false)
    expect(parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: 'c_1', text: 'x'.repeat(32_001) }).ok).toBe(false)
  })

  it('binds controls to an exact request and generation', () => {
    const base = { control_command_id: uuid, conversation_id: 'c_1', request_id: 'r_1', generation: 1 }
    expect(parseRequest(controlSchema, base).ok).toBe(true)
    expect(parseRequest(controlSchema, { ...base, generation: -1 }).ok).toBe(false)
    expect(parseRequest(controlSchema, { control_command_id: uuid, conversation_id: 'c_1' }).ok).toBe(false)
  })

  it('caps steer text at Odin’s 4,000-character limit', () => {
    const base = { control_command_id: uuid, conversation_id: 'c_1', request_id: 'r_1', generation: 1 }
    expect(parseRequest(steerSchema, { ...base, text: 'x'.repeat(4_000) }).ok).toBe(true)
    expect(parseRequest(steerSchema, { ...base, text: 'x'.repeat(4_001) }).ok).toBe(false)
  })

  it('reports where a request was invalid', () => {
    const r = parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: 'c_1' })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toMatchObject({ code: 'bad_request', disposition: 'rejected' })
  })
})
