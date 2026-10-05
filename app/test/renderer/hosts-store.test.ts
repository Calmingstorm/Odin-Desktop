// The host enrollment steps, driven through a fake bridge in the shape of Odin's /api/hosts routes.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { HostList, Result } from '../../src/shared/api'

type Hosts = typeof import('../../src/renderer/src/stores/hosts')

const SCANNED = 'SHA256:' + 'B'.repeat(43)
let hosts: Hosts
let calls: Array<[string, Record<string, unknown>]>
let testAnswer: Result<{ candidate_token: string; tested: boolean; last_test: unknown; error?: string }>
let references: Array<{ kind: string; location: string }>

const list: HostList = { hosts: [], default_host: '', generation: 1, tofu_enabled: true }
const ok = <T>(result: T): Result<T> => ({ ok: true, result })

beforeEach(async () => {
  vi.resetModules()
  calls = []
  references = []
  testAnswer = ok({ candidate_token: 'tok', tested: true, last_test: { ok: true, detail: 'connected' } })
  const record = (name: string, params: Record<string, unknown>) => calls.push([name, params])
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      hostsList: async () => ok(list),
      hostsPublicKey: async () => ok({ public_key: 'ssh-ed25519 AAAA', fingerprint: 'SHA256:k', authorized_keys_command: 'echo', permissions: '', effective_key_path: 'k', desired_key_path: 'k', restart_pending: false }),
      hostsPrepare: async (params: Record<string, unknown>) => {
        record('prepare', params)
        return ok({ candidate_token: `tok-${calls.length}`, alias: params.alias, host_id: 'h', fingerprints: [SCANNED], trust_mode: params.trust_mode, tested: false })
      },
      hostsTest: async (params: Record<string, unknown>) => (record('test', params), testAnswer),
      hostsCommit: async (params: Record<string, unknown>) => (record('commit', params), ok({ result: 'saved', alias: 'gpu', host_id: 'h' })),
      hostsReferences: async (params: Record<string, unknown>) => (record('references', params), ok({ alias: String(params.alias), references })),
      hostsDelete: async (params: Record<string, unknown>) => (record('delete', params), ok({ result: 'saved', alias: String(params.alias), host_id: 'h' }))
    }
  }
  hosts = await import('../../src/renderer/src/stores/hosts')
})

const fill = (trust: 'pinned' | 'tofu'): void => {
  hosts.beginAdd()
  Object.assign(hosts.hosts.enrollment!.form, { alias: 'gpu', address: '10.0.0.9', ssh_user: 'odin', trust_mode: trust })
}

describe('adding a host', () => {
  it('pins the fingerprint you give, tests, then activates, in that order', async () => {
    fill('pinned')
    hosts.goTo(3)
    hosts.hosts.enrollment!.expected = SCANNED
    await hosts.scan()
    expect(hosts.hosts.enrollment!.step).toBe(4)
    expect(calls[0]).toEqual(['prepare', expect.objectContaining({ trust_mode: 'pinned', expected_fingerprints: [SCANNED], port: 22 })])
    await hosts.testConnection()
    expect(hosts.hosts.enrollment!.step).toBe(5)
    expect(await hosts.activate()).toBe(true)
    expect(calls.map(([name]) => name)).toEqual(['prepare', 'test', 'commit'])
    expect(hosts.hosts.enrollment).toBeNull()
  })

  it('refuses a malformed fingerprint before asking the core', async () => {
    fill('pinned')
    hosts.goTo(3)
    hosts.hosts.enrollment!.expected = 'not-a-fingerprint'
    await hosts.scan()
    expect(calls).toEqual([])
    expect(hosts.hosts.enrollment!.note).toMatch(/is not a fingerprint/)
  })

  it('trusts on first use in two scans: the first shows the key, the second binds the confirmation to it', async () => {
    fill('tofu')
    hosts.goTo(3)
    await hosts.scan()
    expect(hosts.hosts.enrollment).toMatchObject({ step: 3, observed: [SCANNED], token: '' })
    expect(calls[0]![1]).not.toHaveProperty('candidate_fingerprints')
    hosts.hosts.enrollment!.form.confirm_tofu = true
    await hosts.scan()
    expect(calls[1]![1]).toMatchObject({ candidate_fingerprints: [SCANNED], confirm_tofu: true })
    expect(hosts.hosts.enrollment!.step).toBe(4)
  })

  it('stays on the test step with the reason when the connection fails, and never activates', async () => {
    testAnswer = ok({ candidate_token: 'tok', tested: false, last_test: { ok: false, detail: 'connection refused' }, error: 'connection refused' })
    fill('pinned')
    hosts.goTo(3)
    hosts.hosts.enrollment!.expected = SCANNED
    await hosts.scan()
    await hosts.testConnection()
    expect(hosts.hosts.enrollment).toMatchObject({ step: 4, tested: false, note: 'connection refused' })
    expect(await hosts.activate()).toBe(false)
    expect(calls.map(([name]) => name)).not.toContain('commit')
  })

  it('goes back past a scan, so an old candidate is never activated', async () => {
    fill('pinned')
    hosts.goTo(3)
    hosts.hosts.enrollment!.expected = SCANNED
    await hosts.scan()
    hosts.goTo(1)
    expect(hosts.hosts.enrollment).toMatchObject({ token: '', tested: false, observed: [] })
  })
})

describe('deleting a host', () => {
  it('shows what still names it, and deletes nothing', async () => {
    references = [{ kind: 'schedule', location: 'schedule ab12: Disk check' }]
    expect(await hosts.deleteHost('build_box')).toBe('blocked')
    expect(hosts.hosts.references.build_box).toEqual(references)
    expect(calls.map(([name]) => name)).toEqual(['references'])
    references = []
    expect(await hosts.deleteHost('build_box')).toBe('deleted')
  })
})

describe('review round 4: hosts', () => {
  const UNKNOWN = { ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: 'cmd-commit' } } as const
  const odin = () => (window as unknown as { odin: Record<string, unknown> }).odin
  const tested = async (): Promise<void> => {
    fill('pinned')
    hosts.goTo(3)
    hosts.hosts.enrollment!.expected = SCANNED
    await hosts.scan()
    await hosts.testConnection()
  }

  it('holds an activation with no answer under its command, and settles it from the late receipt (15.R4.2)', async () => {
    await tested()
    odin().hostsCommit = async (params: Record<string, unknown>) => (calls.push(['commit', params]), UNKNOWN)
    expect(await hosts.activate()).toBe(false)
    expect(await hosts.activate()).toBe(false) // pressed again: never sent under a new command
    expect(calls.filter(([name]) => name === 'commit')).toHaveLength(1)
    const held = await import('../../src/renderer/src/stores/management')
    expect(held.management.notes['host:gpu']).toMatch(/never sent twice/)
    expect(hosts.hosts.enrollment).not.toBeNull()
    const store = await import('../../src/renderer/src/store')
    store.applyReceipt({ id: 'cmd-commit', settled: ok({ result: 'saved', alias: 'gpu', host_id: 'h' }) })
    expect(hosts.hosts.enrollment).toBeNull()
    const management = await import('../../src/renderer/src/stores/management')
    expect(management.management.notes['host:gpu']).toBe('Added and live.')
  })

  it('leaves a wizard opened since alone when an activation lands (15.R4.4)', async () => {
    await tested()
    let land!: () => void
    odin().hostsCommit = () => new Promise((resolve) => (land = () => resolve(ok({ result: 'saved', alias: 'gpu', host_id: 'h' }))))
    const activating = hosts.activate()
    hosts.beginAdd()
    hosts.hosts.enrollment!.form.alias = 'different-unsaved-host'
    land()
    await activating
    expect(hosts.hosts.enrollment?.form.alias).toBe('different-unsaved-host')
  })

  it('never lets an older list answer replace a newer one (15.R4.3)', async () => {
    const answers: Array<(list: Result<HostList>) => void> = []
    odin().hostsList = () => new Promise((resolve) => answers.push(resolve))
    const older = hosts.loadHosts()
    const newer = hosts.loadHosts()
    const row = (enabled: boolean, generation: number) =>
      ok({ ...list, generation, hosts: [{ alias: 'gpu', enabled } as HostList['hosts'][number]] })
    answers[1]!(row(false, 3))
    await newer
    answers[0]!(row(true, 2))
    await older
    expect(hosts.hosts.list?.generation).toBe(3)
    expect(hosts.hosts.list?.hosts[0]?.enabled).toBe(false)
  })

  it("moves on from the host key step for this computer, which Odin trusts without a key (15.R4.7)", async () => {
    hosts.beginAdd()
    Object.assign(hosts.hosts.enrollment!.form, { alias: 'self', address: '127.0.0.1', ssh_user: 'me', trust_mode: 'tofu', confirm_local: true })
    odin().hostsPrepare = async (params: Record<string, unknown>) =>
      (calls.push(['prepare', params]), ok({ candidate_token: 'tok-local', alias: 'self', host_id: 'h', fingerprints: [], trust_mode: 'legacy', tested: false }))
    hosts.goTo(3)
    await hosts.scan()
    expect(hosts.hosts.enrollment).toMatchObject({ step: 4, token: 'tok-local' })
  })

  it("calls exactly Odin's local addresses this computer (15.R4.8)", () => {
    expect(['127.0.0.1', 'localhost', '::1', ' localhost '].map(hosts.isLocal)).toEqual([true, true, true, true])
    expect(['LOCALHOST', '127.0.0.2', '127.1', 'localhost.localdomain'].map(hosts.isLocal)).toEqual([false, false, false, false])
  })
})
