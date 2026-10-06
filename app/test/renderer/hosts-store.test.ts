// The host enrollment steps, driven through a fake bridge in the shape of Odin's /api/hosts routes.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { HostList, HostRow, Result } from '../../src/shared/api'

type Hosts = typeof import('../../src/renderer/src/stores/hosts')

const SCANNED = 'SHA256:' + 'B'.repeat(43)
const legacy: HostRow = {
  alias: 'old', host_id: 'old-id', address: '10.0.0.8', ssh_user: 'deploy', os: 'linux', port: 2222,
  description: 'Existing host', enabled: false, active: false, targetable: false,
  trust_mode: 'legacy', trust_state: 'legacy_unverified', last_test: null, diagnostic: null, draining: false, generation: 1
}
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
      hostsImportLegacy: async (params: Record<string, unknown>) => {
        record('import', params)
        return ok({ candidate_token: 'import-candidate', alias: params.alias, host_id: 'old-id', fingerprints: [SCANNED], trust_mode: 'pinned', tested: false })
      },
      hostsPrepare: async (params: Record<string, unknown>) => {
        record('prepare', params)
        return ok({ candidate_token: `tok-${calls.length}`, alias: params.alias, host_id: 'h', fingerprints: [SCANNED], trust_mode: params.trust_mode, tested: false })
      },
      hostsTest: async (params: Record<string, unknown>) => (record('test', params), testAnswer),
      hostsCommit: async (params: Record<string, unknown>) => (record('commit', params), ok({ saved: true, active: true, targetable: true, trust_state: 'pinned', last_test: null, draining: false, pending_references: [], registry_generation: 2, ssh_paths: {} })),
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

describe('legacy trusted-key enrollment', () => {
  const odin = () => (window as unknown as { odin: Record<string, unknown> }).odin
  const imported = { candidate_token: 'import-candidate', alias: 'old', host_id: 'old-id', fingerprints: [SCANNED], trust_mode: 'pinned', tested: false }

  it('imports only the alias, preserves disabled intent, and requires test before commit', async () => {
    expect(await hosts.importLegacy(legacy)).toBe(true)
    expect(calls).toEqual([['import', { alias: 'old' }]])
    expect(hosts.hosts.enrollment).toMatchObject({ editing: true, step: 4, token: 'import-candidate', observed: [SCANNED], expected: SCANNED, tested: false, test: null,
      form: { alias: 'old', address: '10.0.0.8', port: 2222, ssh_user: 'deploy', enabled: false, trust_mode: 'pinned' } })
    expect(await hosts.activate()).toBe(false)
    await hosts.testConnection()
    expect(hosts.hosts.enrollment?.step).toBe(5)
    await hosts.activate()
    expect(calls.map(([name]) => name)).toEqual(['import', 'test', 'commit'])
  })

  it('does not import local or non-legacy hosts', async () => {
    expect(await hosts.importLegacy({ ...legacy, address: 'localhost' })).toBe(false)
    expect(await hosts.importLegacy({ ...legacy, trust_mode: 'pinned' })).toBe(false)
    expect(calls).toEqual([])
  })

  it('invalidates an imported candidate on Back and reprepares only as pinned trust, never legacy', async () => {
    await hosts.importLegacy(legacy)
    hosts.goTo(3)
    expect(hosts.hosts.enrollment).toMatchObject({ token: '', tested: false, form: { trust_mode: 'pinned' } })
    expect(await hosts.activate()).toBe(false)
    await hosts.scan()
    expect(calls.at(-1)).toEqual(['prepare', expect.objectContaining({ alias: 'old', trust_mode: 'pinned', enabled: false, expected_fingerprints: [SCANNED] })])
    expect(calls.map(([name]) => name)).not.toContain('commit')
  })

  it('keeps a failed connection candidate untested and refuses activation', async () => {
    await hosts.importLegacy(legacy)
    testAnswer = ok({ candidate_token: 'import-candidate', tested: false, last_test: { ok: false }, error: 'host key changed' })
    await hosts.testConnection()
    expect(hosts.hosts.enrollment).toMatchObject({ step: 4, tested: false, note: 'host key changed' })
    expect(await hosts.activate()).toBe(false)
    expect(calls.map(([name]) => name)).toEqual(['import', 'test'])
  })

  it('holds an unknown import under its command and adopts its late candidate without execution', async () => {
    odin().hostsImportLegacy = async (params: Record<string, unknown>) => {
      calls.push(['import', params])
      return { ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: 'cmd-import' } }
    }
    expect(await hosts.importLegacy(legacy)).toBe(false)
    expect(await hosts.importLegacy(legacy)).toBe(false)
    expect(calls).toEqual([['import', { alias: 'old' }]])
    expect(hosts.hosts.enrollment).toBeNull()
    const { management } = await import('../../src/renderer/src/stores/management')
    expect(management.busy['host:old']).toBe(true)
    const store = await import('../../src/renderer/src/store')
    store.applyReceipt({ id: 'cmd-import', settled: ok(imported) })
    expect(management.busy['host:old']).toBe(false)
    expect(hosts.hosts.enrollment).toMatchObject({ step: 4, token: 'import-candidate', tested: false })
    expect(calls.map(([name]) => name)).toEqual(['import'])
  })

  it('does not let a delayed import overwrite a newer wizard', async () => {
    let land!: (answer: unknown) => void
    odin().hostsImportLegacy = () => new Promise((resolve) => { land = resolve })
    const pending = hosts.importLegacy(legacy)
    hosts.beginAdd()
    hosts.hosts.enrollment!.form.alias = 'new-draft'
    land(ok(imported))
    await pending
    expect(hosts.hosts.enrollment).toMatchObject({ step: 1, token: '', form: { alias: 'new-draft' } })
  })

  it('keeps a denied import out of enrollment and handles capability refusal honestly', async () => {
    odin().hostsImportLegacy = async () => ({ ok: false, error: { code: 'bad_request', message: 'no matching legacy known_hosts entry was found' } })
    expect(await hosts.importLegacy(legacy)).toBe(false)
    expect(hosts.hosts.enrollment).toBeNull()
    const { management } = await import('../../src/renderer/src/stores/management')
    expect(management.notes['host:old']).toContain('no matching legacy')
    odin().hostsImportLegacy = async () => ({ ok: false, error: { code: 'capability_unavailable', message: 'not served' } })
    expect(await hosts.importLegacy(legacy)).toBe(false)
    expect(hosts.hosts.unavailable).toBe(true)
    expect(hosts.hosts.list).toBeNull()
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
    store.applyReceipt({ id: 'cmd-commit', settled: ok({ saved: true, active: true, targetable: true, trust_state: 'pinned' }) })
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
