import { describe, expect, it } from 'vitest'
import { CODEX_VERIFICATION_URL, DeviceLoginBoundary } from '../src/main/device-login'

describe('main-owned provider verification', () => {
  const raw = { device_auth_id: 'synthetic-device-secret', user_code: 'TEST-CODE',
    interval: 1, expires_in: 10, verify_url: CODEX_VERIFICATION_URL, access_token: 'synthetic-oauth-secret' }

  it('projects only the intended code and an opaque handle, keeping device authorization in main', () => {
    const boundary = new DeviceLoginBoundary()
    const begun = boundary.begin(raw, 'core-a')
    expect(begun.ok).toBe(true)
    if (!begun.ok) throw new Error('begin failed')
    expect(JSON.stringify(begun)).not.toContain('synthetic-device-secret')
    expect(JSON.stringify(begun)).not.toContain('synthetic-oauth-secret')
    expect(boundary.poll(begun.result.login_id, 'core-a')).toEqual({ ok: true, result: {
      device_auth_id: raw.device_auth_id, user_code: raw.user_code
    } })
    expect(boundary.verification('core-a')).toEqual({ ok: true, result: { url: CODEX_VERIFICATION_URL } })
    expect(boundary.poll('unrelated', 'core-a').ok).toBe(false)
  })

  it('accepts only the recognized core verification URL, never a renderer-supplied navigation', () => {
    for (const url of ['https://example.org', CODEX_VERIFICATION_URL + '?token=x',
      'https://auth.openai.com.evil.example/codex/device', 'file:///tmp/test']) {
      const boundary = new DeviceLoginBoundary()
      expect(boundary.begin({ ...raw, verify_url: url }, 'core-a').ok).toBe(false)
      expect(boundary.verification('core-a').ok).toBe(false)
    }
  })

  it('also projects late receipts so a lost initial answer cannot leak the raw device secret', () => {
    const boundary = new DeviceLoginBoundary()
    boundary.track('begin-command', 'begin')
    boundary.settle('begin-command', { ok: false, error: { code: 'no_receipt', message: 'pending' } })
    const receipt = boundary.receipt({ id: 'begin-command', settled: { ok: true, result: raw } }, 'core-a')
    expect(receipt.settled.ok).toBe(true)
    expect(JSON.stringify(receipt)).not.toContain('synthetic-device-secret')
    expect(JSON.stringify(receipt)).not.toContain('synthetic-oauth-secret')
    boundary.track('poll-command', 'poll')
    const polled = boundary.receipt({ id: 'poll-command', settled: { ok: true, result: {
      status: 'authenticated', email: 'test@example.invalid', account_id: 'synthetic-account',
      access_token: 'synthetic-oauth-secret'
    } } }, 'core-a')
    expect(polled.settled).toEqual({ ok: true, result: { status: 'authenticated',
      email: 'test@example.invalid', account_id: 'synthetic-account' } })
    expect(JSON.stringify(polled)).not.toContain('synthetic-oauth-secret')
  })

  it('expires and fences handles by core incarnation, and forgets superseded material', () => {
    let now = 0
    const boundary = new DeviceLoginBoundary(() => now)
    const first = boundary.begin(raw, 'core-a')
    if (!first.ok) throw new Error('begin failed')
    const second = boundary.begin(raw, 'core-a')
    if (!second.ok) throw new Error('begin failed')
    expect(boundary.poll(first.result.login_id, 'core-a').ok).toBe(false)
    now = 10_000
    expect(boundary.poll(second.result.login_id, 'core-a').ok).toBe(false)
    expect(boundary.verification('core-a').ok).toBe(false)
    const third = boundary.begin(raw, 'core-a')
    if (!third.ok) throw new Error('begin failed')
    expect(boundary.poll(third.result.login_id, 'core-b').ok).toBe(false)
    expect(boundary.verification('core-a').ok).toBe(false)
  })
})
