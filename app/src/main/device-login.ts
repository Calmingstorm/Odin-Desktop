// Device authorization material belongs to main, not to the display page.
// The renderer gets a random local handle and the intended human verification code.
import { randomUUID } from 'node:crypto'
import type { DeviceCode, LateReceipt, Result } from '../shared/api'

export const CODEX_VERIFICATION_URL = 'https://auth.openai.com/codex/device'

interface Login {
  id: string
  deviceAuthId: string
  userCode: string
  expiresAt: number
  incarnation: string
}

const refused = (): Result<never> => ({ ok: false, error: {
  code: 'not_found', message: 'This device login has expired or the core changed. Add an account to start again.', disposition: 'rejected'
} })

export class DeviceLoginBoundary {
  private login: Login | null = null
  private readonly pending = new Map<string, 'begin' | 'poll'>()

  constructor(private readonly now: () => number = Date.now) {}

  clear(): void { this.login = null }

  track(id: string, kind: 'begin' | 'poll'): void { this.pending.set(id, kind) }

  settle(id: string, answer: Result<unknown>): void {
    if (answer.ok || answer.error.code !== 'no_receipt') this.pending.delete(id)
  }

  /** The Broker's late-receipt route must use the same privacy boundary as the direct IPC answer. */
  receipt(receipt: LateReceipt, incarnation: string | null): LateReceipt {
    const kind = this.pending.get(receipt.id)
    if (!kind) return receipt
    this.pending.delete(receipt.id)
    const answer = receipt.settled
    if (!answer.ok) return receipt
    const projected = kind === 'begin' ? this.begin(answer.result, incarnation) : this.pollResult(answer.result)
    return { ...receipt, settled: projected }
  }

  pollResult(value: unknown): Result<unknown> {
    const raw = value as Record<string, unknown> | null
    if (raw?.status === 'pending') return { ok: true, result: { status: 'pending' } }
    if (raw?.status === 'authenticated' && typeof raw.email === 'string' && typeof raw.account_id === 'string') {
      this.clear()
      return { ok: true, result: { status: 'authenticated', email: raw.email, account_id: raw.account_id } }
    }
    return { ok: false, error: { code: 'internal', message: 'Invalid device login response.', disposition: 'rejected' } }
  }

  begin(raw: unknown, incarnation: string | null): Result<DeviceCode> {
    this.clear()
    if (!raw || typeof raw !== 'object' || !incarnation) return refused()
    const data = raw as Record<string, unknown>
    if (data.verify_url !== CODEX_VERIFICATION_URL || typeof data.device_auth_id !== 'string' ||
      !data.device_auth_id || data.device_auth_id.length > 512 || typeof data.user_code !== 'string' ||
      !data.user_code || data.user_code.length > 64 || typeof data.interval !== 'number' ||
      !Number.isFinite(data.interval) || data.interval < 1 || data.interval > 60) return refused()
    const expires = data.expires_in ?? 900
    if (typeof expires !== 'number' || !Number.isFinite(expires) || expires <= 0 || expires > 3600) return refused()
    const id = randomUUID()
    this.login = { id, deviceAuthId: data.device_auth_id, userCode: data.user_code,
      expiresAt: this.now() + expires * 1000, incarnation }
    return { ok: true, result: { login_id: id, user_code: data.user_code, interval: data.interval,
      verify_url: CODEX_VERIFICATION_URL, expires_in: expires } }
  }

  poll(id: string, incarnation: string | null): Result<{ device_auth_id: string; user_code: string }> {
    const login = this.login
    if (!login || login.id !== id || login.incarnation !== incarnation || this.now() >= login.expiresAt) {
      if (login && (login.incarnation !== incarnation || this.now() >= login.expiresAt)) this.clear()
      return refused()
    }
    return { ok: true, result: { device_auth_id: login.deviceAuthId, user_code: login.userCode } }
  }

  verification(incarnation: string | null): Result<{ url: string }> {
    const login = this.login
    if (!login || login.incarnation !== incarnation || this.now() >= login.expiresAt) return refused()
    return { ok: true, result: { url: CODEX_VERIFICATION_URL } }
  }
}
