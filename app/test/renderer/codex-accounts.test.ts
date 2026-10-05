// The Codex accounts panel, mounted with its real code and the real settings store over a fake bridge.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result } from '../../src/shared/api'
import { flush, mount, type Host } from './component-host'

const account = (index: number, id: string, current = false) => ({ index, account_id: id, email: `${id}@example.com`, plan_type: 'pro', is_current: current })

let root: Host
let accounts: Result<unknown>
let landActivate: () => void

beforeEach(async () => {
  vi.resetModules()
  accounts = { ok: true, result: { configured: true, accounts: [account(0, 'acct_1', true), account(1, 'acct_2')] } }
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      codexAccounts: async () => accounts,
      codexActivate: () => new Promise<Result<unknown>>((resolve) => (landActivate = () => resolve({ ok: true, result: { status: 'activated' } })))
    }
  }
  const CodexAccounts = (await import('../../src/renderer/src/components/CodexAccounts.vue')).default
  root = mount(CodexAccounts).root
  await flush()
})

const warning = (): boolean => root.textContent().includes("couldn't be refreshed")

describe('review round 4: the accounts panel', () => {
  it('locks the controls during an action without warning that the list is out of date', async () => {
    root.button('Use this account').fire('click')
    await flush()
    expect(root.findAll((host) => host.tag === 'button' && host.textContent().trim() === 'Remove…').every((b) => b.props.disabled)).toBe(true)
    expect(warning()).toBe(false)
    landActivate()
    await flush()
    expect(warning()).toBe(false)
  })

  it('warns when the list could not be read after the action', async () => {
    root.button('Use this account').fire('click')
    await flush()
    accounts = { ok: false, error: { code: 'unavailable', message: 'core restarting', disposition: 'not_dispatched' } }
    landActivate()
    await flush()
    expect(warning()).toBe(true)
  })
})
