import { beforeEach, describe, expect, it } from 'vitest'
import type { Result } from '../../src/shared/api'
import { completion, readCompletion } from '../../src/renderer/src/stores/completion'
beforeEach(() => { for (const key of Object.keys(completion)) delete completion[key] })
describe('honest completion read state', () => {
  it('distinguishes unread, successful empty, failed stale, and refused data', async () => {
    expect(completion.metrics).toBeUndefined()
    await readCompletion('metrics', async () => ({ ok: true, result: { available: false, reason: 'not measured' } }))
    expect(completion.metrics!.value).toEqual({ available: false, reason: 'not measured' })
    await readCompletion('metrics', async () => ({ ok: false, error: { code: 'unavailable', message: 'read failed' } }))
    expect(completion.metrics).toMatchObject({ loaded: true, error: 'read failed', unavailable: false })
    await readCompletion('metrics', async () => ({ ok: false, error: { code: 'capability_unavailable', message: 'old core' } }))
    expect(completion.metrics).toMatchObject({ loaded: false, value: null, unavailable: true })
    await readCompletion('metrics', async () => ({ ok: true, result: [] }))
    expect(completion.metrics).toMatchObject({ loaded: true, value: [], unavailable: false })
  })
  it('keeps newer data and its request label when reads resolve out of order', async () => {
    let resolve!: (value: Result<unknown>) => void
    const old = readCompletion('trace', () => new Promise((done) => { resolve = done }), 'old filters')
    await readCompletion('trace', async () => ({ ok: true, result: ['new'] }), 'new filters')
    resolve({ ok: true, result: ['old'] }); await old
    expect(completion.trace).toMatchObject({ value: ['new'], label: 'new filters', busy: false })
  })
})
