import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Store = typeof import('../../src/renderer/src/stores/settings')
let store: Store
let begin: ReturnType<typeof vi.fn>
let poll: ReturnType<typeof vi.fn>

beforeEach(async () => {
  vi.resetModules()
  vi.useFakeTimers()
  begin = vi.fn().mockResolvedValue({ ok: true, result: {
    device_auth_id: 'isolated-device', user_code: 'TEST-CODE', interval: 1, verify_url: 'https://auth.openai.com/codex/device'
  } })
  poll = vi.fn().mockResolvedValue({ ok: true, result: { status: 'pending' } })
  ;(globalThis as unknown as { window: unknown }).window = { odin: {
    codexLoginBegin: begin,
    codexLoginPoll: poll,
    codexAccounts: vi.fn().mockResolvedValue({ ok: true, result: { configured: false, accounts: [] } })
  } }
  store = await import('../../src/renderer/src/stores/settings')
})

afterEach(() => { store.stopLogin(); vi.useRealTimers() })

describe('step5 device login', () => {
  it('retries the same authorized login after a failed keyring write, not another browser authorization', async () => {
    poll.mockResolvedValueOnce({ ok: false, error: { code: 'keyring_unavailable', message: 'The system keyring is locked or unavailable' } })
    const login = store.beginLogin()
    await vi.advanceTimersByTimeAsync(1000)
    await login
    expect(store.settings.codex.login?.status).toBe('failed')
    poll.mockResolvedValueOnce({ ok: true, result: { status: 'authenticated', email: 'test@example.invalid', account_id: 'test' } })
    const retry = store.retryLogin()
    await vi.advanceTimersByTimeAsync(1000)
    await retry
    expect(begin).toHaveBeenCalledTimes(1)
    expect(poll).toHaveBeenNthCalledWith(2, { device_auth_id: 'isolated-device', user_code: 'TEST-CODE' })
    expect(store.settings.codex.login?.status).toBe('done')
  })

  it('stops polling without claiming a remote cancellation or account save', async () => {
    const login = store.beginLogin()
    await vi.advanceTimersByTimeAsync(0)
    store.stopLogin()
    await vi.advanceTimersByTimeAsync(1000)
    await login
    expect(poll).not.toHaveBeenCalled()
    expect(store.settings.codex.login?.status).toBe('stopped')
  })

  it('does not start duplicate device codes while begin is in flight and discards a stopped begin', async () => {
    let resolve!: (result: unknown) => void
    begin.mockImplementation(() => new Promise((r) => { resolve = r }))
    const login = store.beginLogin()
    await store.beginLogin()
    expect(begin).toHaveBeenCalledTimes(1)
    store.stopLogin()
    resolve({ ok: true, result: { device_auth_id: 'late', user_code: 'late', interval: 1, verify_url: 'https://auth.openai.com/codex/device' } })
    await login
    expect(store.settings.codex.login).toBeNull()
    expect(poll).not.toHaveBeenCalled()
  })
})
