import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount } from './component-host'

type Store = typeof import('../../src/renderer/src/stores/settings')
let store: Store
let begin: ReturnType<typeof vi.fn>
let poll: ReturnType<typeof vi.fn>
let verification: ReturnType<typeof vi.fn>

beforeEach(async () => {
  vi.resetModules()
  vi.useFakeTimers()
  begin = vi.fn().mockResolvedValue({ ok: true, result: {
    login_id: 'isolated-login', user_code: 'TEST-CODE', interval: 1, verify_url: 'https://auth.openai.com/codex/device'
  } })
  poll = vi.fn().mockResolvedValue({ ok: true, result: { status: 'pending' } })
  verification = vi.fn().mockResolvedValue({ ok: true, result: { opened: true } })
  ;(globalThis as unknown as { window: unknown }).window = { odin: {
    codexLoginBegin: begin, codexLoginPoll: poll, codexOpenVerification: verification,
    codexAccounts: vi.fn().mockResolvedValue({ ok: true, result: { configured: false, accounts: [] } }),
    status: vi.fn().mockResolvedValue({ ok: false, error: { code: 'unavailable', message: 'unavailable' } }),
    usage: vi.fn().mockResolvedValue({ ok: false, error: { code: 'unavailable', message: 'unavailable' } })
  } }
  store = await import('../../src/renderer/src/stores/settings')
})

afterEach(() => { store.stopLogin(); vi.useRealTimers() })

describe('step5 device login with main-owned authorization', () => {
  it('retries the same opaque login after a failed keyring write, not another browser authorization', async () => {
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
    expect(poll).toHaveBeenNthCalledWith(2, { login_id: 'isolated-login' })
    expect(store.settings.codex.login?.status).toBe('done')
    expect(JSON.stringify(store.settings)).not.toContain('device_auth_id')
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

  it('does not start duplicate codes while begin is in flight and discards a stopped begin', async () => {
    let resolve!: (result: unknown) => void
    begin.mockImplementation(() => new Promise((r) => { resolve = r }))
    const login = store.beginLogin()
    await store.beginLogin()
    expect(begin).toHaveBeenCalledTimes(1)
    store.stopLogin()
    resolve({ ok: true, result: { login_id: 'late', user_code: 'late', interval: 1, verify_url: 'https://auth.openai.com/codex/device' } })
    await login
    expect(store.settings.codex.login).toBeNull()
    expect(poll).not.toHaveBeenCalled()
  })

  it('shows expiry and permits a new login instead of retrying an expired authorization', async () => {
    poll.mockResolvedValueOnce({ ok: false, error: { code: 'expired', message: 'The verification code expired' } })
    const login = store.beginLogin()
    await vi.advanceTimersByTimeAsync(1000)
    await login
    expect(store.settings.codex.login?.status).toBe('expired')
    await store.retryLogin()
    expect(poll).toHaveBeenCalledTimes(1)
    const component = mount((await import('../../src/renderer/src/components/CodexAccounts.vue')).default)
    await flush()
    expect(component.root.button('Add account').props.disabled).toBe(false)
    expect(component.root.findAll((n) => n.props['data-testid'] === 'codex-retry-login')).toHaveLength(0)
    component.unmount()
  })

  it('uses only the named main-owned verification opener, never forwarding an arbitrary URL', async () => {
    const login = store.beginLogin()
    await vi.advanceTimersByTimeAsync(0)
    const component = mount((await import('../../src/renderer/src/components/CodexAccounts.vue')).default)
    await flush()
    const button = component.root.findAll((n) => n.props['data-testid'] === 'codex-open-verification')[0]!
    await button.fire('click')
    expect(verification).toHaveBeenCalledWith()
    expect(component.root.findAll((n) => n.tag === 'a')).toHaveLength(0)
    store.stopLogin()
    await vi.advanceTimersByTimeAsync(1000)
    await login
    component.unmount()
  })
})
