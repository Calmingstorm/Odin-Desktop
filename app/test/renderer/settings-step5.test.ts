// Real step-5 response shapes and renderer adoption. No core, SSH, or graphical desktop is used.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { HostList, HostRow, Result, ToolInventory, ToolTimeouts } from '../../src/shared/api'
import { flush, mount, type Mounted } from './component-host'

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
function deferred<T>() {
  let resolve!: (answer: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
const host = (change: Partial<HostRow> = {}): HostRow => ({
  alias: 'build', host_id: 'h', address: '10.0.0.9', ssh_user: 'odin', port: 22, os: 'linux', description: '',
  enabled: true, active: true, targetable: false, trust_mode: 'pinned', trust_state: 'mismatch', last_test: null,
  diagnostic: null, draining: false, generation: 1, ...change
})
const inventory = (state: 'available' | 'unavailable' | 'global_disabled' = 'available'): ToolInventory => ({
  global_enabled: state !== 'global_disabled', disabled_count: 0,
  tools: [{ name: 'run_command', description: '', enabled: true, is_core: false, state, input_schema: {} }]
})
const key = { public_key: 'ssh-ed25519 example', fingerprint: 'SHA256:example', authorized_keys_command: 'install key', permissions: '', effective_key_path: 'k', desired_key_path: 'k', restart_pending: false }
const saved = (change: Record<string, unknown> = {}) => ({
  saved: true, active: true, targetable: true, trust_state: 'pinned', last_test: null, draining: false,
  pending_references: [], registry_generation: 2,
  ssh_paths: { desired_key: 'k', effective_key: 'k', desired_known_hosts: '', effective_known_hosts: '', restart_pending: false },
  ...change
})
let bridge: Record<string, ReturnType<typeof vi.fn>>
let mounted: Mounted | undefined
beforeEach(() => {
  vi.resetModules()
  bridge = {
    hostsList: vi.fn(async () => ok({ hosts: [host()], default_host: '', generation: 1, tofu_enabled: false } satisfies HostList)),
    hostsPublicKey: vi.fn(async () => ok(key)),
    hostsSettings: vi.fn(async () => ok({ saved: true, default_host: '', configured_default_host: 'build', tofu_enabled: true, registry_generation: 2 })),
    hostsPrepare: vi.fn(async () => ok({ candidate_token: 'candidate', alias: 'build', host_id: 'h', fingerprints: [], trust_mode: 'legacy', tested: false })),
    hostsTest: vi.fn(async () => ok({ candidate_token: 'candidate', tested: true, last_test: { ok: true, checked_at: 1_791_000_000, detail: 'verified' } })),
    hostsCommit: vi.fn(async () => ok(saved())),
    hostsSetEnabled: vi.fn(async () => ok(saved())),
    toolsList: vi.fn(async () => ok(inventory())),
    toolsTimeoutsGet: vi.fn(async () => ok({ default_timeout: 60, overrides: {} })),
    toolsTimeoutsSet: vi.fn(async () => ok({ default_timeout: 120, overrides: {} })),
    toolsSetEnabled: vi.fn(async () => ok(inventory()))
  }
  vi.stubGlobal('window', { odin: bridge })
  vi.stubGlobal('document', { activeElement: null })
})
afterEach(() => { mounted?.unmount(); mounted = undefined; vi.unstubAllGlobals() })

describe('real step-5 hosts', () => {
  it('keeps a disabled host disabled when preparing its edited endpoint', async () => {
    const store = await import('../../src/renderer/src/stores/hosts')
    store.beginEdit(host({ enabled: false, active: false }))
    store.hosts.enrollment!.expected = 'SHA256:' + 'A'.repeat(43)
    await store.scan()
    expect(bridge.hostsPrepare).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }))
    await store.testConnection()
    bridge.hostsCommit!.mockResolvedValue(ok(saved({ active: false, targetable: false, trust_state: 'pinned' })))
    await store.activate()
    const { management } = await import('../../src/renderer/src/stores/management')
    expect(management.notes['host:build']).toBe('Saved; host remains off for new work.')
  })

  it('uses real targetability and draining, not a requested boolean, in toggle receipts', async () => {
    const store = await import('../../src/renderer/src/stores/hosts')
    const { management } = await import('../../src/renderer/src/stores/management')
    bridge.hostsSetEnabled!.mockResolvedValue(ok(saved({ targetable: false, trust_state: 'mismatch' })))
    await store.setHostEnabled('build', true)
    expect(management.notes['host:build']).toBe('Enabled, but not targetable: mismatch.')
    bridge.hostsSetEnabled!.mockResolvedValue(ok(saved({ active: false, targetable: false, draining: true })))
    await store.setHostEnabled('build', false)
    expect(management.notes['host:build']).toBe('Off for new work; existing uses are draining.')
  })

  it('renders epoch-second last tests and distinguishes enabled-but-untrusted hosts from off hosts', async () => {
    const checked_at = 1_791_000_000
    bridge.hostsList!.mockResolvedValue(ok({ hosts: [host({ last_test: { ok: true, checked_at, detail: 'verified' } })], default_host: '', generation: 1, tofu_enabled: false }))
    mounted = mount((await import('../../src/renderer/src/views/settings/Hosts.vue')).default)
    await flush()
    expect(mounted.root.textContent()).toContain('Not ready')
    expect(mounted.root.textContent()).toContain(new Date(checked_at * 1000).toLocaleString())
  })

  it('saves only changed host settings so a TOFU edit cannot erase a configured but ineffective default', async () => {
    mounted = mount((await import('../../src/renderer/src/views/settings/Hosts.vue')).default)
    await flush()
    mounted.setup.allowTofu = true
    await (mounted.setup.saveSettings as () => Promise<void>)()
    expect(bridge.hostsSettings).toHaveBeenCalledExactlyOnceWith({ allow_host_tofu: true })
    const { management } = await import('../../src/renderer/src/stores/management')
    expect(management.notes.hosts).toBe('Saved. Default host build is not currently targetable.')
    await (mounted.setup.saveSettings as () => Promise<void>)()
    expect(bridge.hostsSettings).toHaveBeenCalledTimes(1)
  })

  it('keeps host settings edited during a held save for the next Save', async () => {
    const receipt = deferred<Result<unknown>>()
    bridge.hostsSettings!.mockReturnValueOnce(receipt.promise)
    mounted = mount((await import('../../src/renderer/src/views/settings/Hosts.vue')).default)
    await flush()
    mounted.setup.allowTofu = true
    const saving = (mounted.setup.saveSettings as () => Promise<void>)()
    mounted.setup.allowTofu = false
    receipt.resolve(ok({ saved: true }))
    await saving
    expect(mounted.setup.allowTofu).toBe(false)
    await (mounted.setup.saveSettings as () => Promise<void>)()
    expect(bridge.hostsSettings).toHaveBeenLastCalledWith({ allow_host_tofu: false })
  })

  it('local enrollment does not validate or show an SSH fingerprint', async () => {
    const store = await import('../../src/renderer/src/stores/hosts')
    mounted = mount((await import('../../src/renderer/src/views/settings/Hosts.vue')).default)
    await flush()
    store.beginAdd()
    Object.assign(store.hosts.enrollment!.form, { alias: 'self', address: 'localhost', confirm_local: true })
    store.hosts.enrollment!.expected = 'not an SSH fingerprint'
    store.goTo(2)
    await flush()
    expect(mounted.root.textContent()).toContain('No SSH key installation is needed')
    store.goTo(3)
    await flush()
    expect(mounted.root.findAll((node) => node.props['aria-label'] === 'Expected fingerprints')).toHaveLength(0)
    await store.scan()
    expect(bridge.hostsPrepare).toHaveBeenCalledTimes(1)
    expect(bridge.hostsPrepare!.mock.calls[0]![0]).not.toHaveProperty('expected_fingerprints')
    expect(store.hosts.enrollment?.step).toBe(4)
  })
})

describe('real step-5 tools and timeout responses', () => {
  it.each(['unavailable', 'global_disabled'] as const)('never claims enabled tools are available when core state is %s', async (state) => {
    const store = await import('../../src/renderer/src/stores/management')
    bridge.toolsSetEnabled!.mockResolvedValue(ok(inventory(state)))
    await store.setToolEnabled('run_command', true)
    expect(store.management.notes['tool:run_command']).not.toBe('On.')
    expect(store.management.tools?.tools[0]?.state).toBe(state)
  })

  it('keeps a newer timeout write when an older load resolves afterward', async () => {
    const read = deferred<Result<ToolTimeouts>>()
    bridge.toolsTimeoutsGet!.mockReturnValueOnce(read.promise)
    const store = await import('../../src/renderer/src/stores/management')
    const loading = store.loadTools()
    await store.saveTimeouts({ default_timeout: 120 })
    read.resolve(ok({ default_timeout: 60, overrides: {} }))
    await loading
    expect(store.management.timeouts?.default_timeout).toBe(120)
  })

  it('still adopts timeout reads when an inventory toggle supersedes the tools read', async () => {
    const read = deferred<Result<ToolTimeouts>>()
    bridge.toolsTimeoutsGet!.mockReturnValueOnce(read.promise)
    const store = await import('../../src/renderer/src/stores/management')
    const loading = store.loadTools()
    await store.setToolEnabled('run_command', true)
    read.resolve(ok({ default_timeout: 60, overrides: {} }))
    await loading
    expect(store.management.timeouts?.default_timeout).toBe(60)
  })

  it('protects newer timeout input while a save receipt is held', async () => {
    const receipt = deferred<Result<ToolTimeouts>>()
    bridge.toolsTimeoutsSet!.mockReturnValueOnce(receipt.promise)
    mounted = mount((await import('../../src/renderer/src/views/settings/Tools.vue')).default)
    await flush()
    mounted.setup.defaultTimeout = '120'
    const saving = (mounted.setup.save as () => Promise<void>)()
    mounted.setup.defaultTimeout = '240'
    receipt.resolve(ok({ default_timeout: 120, overrides: {} }))
    await saving
    expect(mounted.setup.defaultTimeout).toBe('240')
    await (mounted.setup.save as () => Promise<void>)()
    expect(bridge.toolsTimeoutsSet).toHaveBeenLastCalledWith({ default_timeout: 240, overrides: {} })
  })
})
