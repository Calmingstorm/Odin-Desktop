// Each settings page reads its own capability, with no schema gate substituting for its actual answer.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result } from '../../src/shared/api'
import { flush, mount, type Mounted } from './component-host'

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const refused: Result<never> = { ok: false, error: { code: 'capability_unavailable', message: 'Service is not available yet', disposition: 'not_dispatched' } }
const inventory = { global_enabled: true, disabled_count: 0, tools: [{ name: 'cached_tool', enabled: true, state: 'available', description: 'old fixture', input_schema: {}, is_core: false }] }
const timeouts = { default_timeout: 30, overrides: {} }
const skill = { name: 'cached_skill', status: 'loaded', version: '1', description: 'old fixture', diagnostics: [] }
const detail = { name: 'cached_skill', code: 'original code', config: { setting: 'old' }, metadata: { config_schema: {} } }
const mcp = { enabled: true, connected_count: 0, server_count: 0, published_tool_count: 0, servers: [], max_published_tools_per_server: 10, max_published_tools_global: 50 }
const hostList = { hosts: [], default_host: '', generation: 1, tofu_enabled: false }
const key = { public_key: 'old public key', authorized_keys_command: 'install public key', fingerprint: 'SHA256:key', permissions: '', restart_pending: false }

let api: Record<string, ReturnType<typeof vi.fn>>
let store: typeof import('../../src/renderer/src/stores/management')
let hostStore: typeof import('../../src/renderer/src/stores/hosts')
let mounted: Mounted[]

beforeEach(async () => {
  vi.resetModules()
  mounted = []
  api = {
    toolsList: vi.fn(async () => ok(inventory)), toolsTimeoutsGet: vi.fn(async () => ok(timeouts)),
    healthGet: vi.fn(async () => ok({ browser: { state: 'disabled', ready: false, reason: null, retry_available: false } })),
    computerStatus: vi.fn(async () => ok({ readiness: { management_available: true, foreground_available: false, dispatch: 'none', reason: 'not_enabled' }, session: null })),
    skillsList: vi.fn(async () => ok([skill])), skillsGet: vi.fn(async () => ok(detail)),
    mcpStatus: vi.fn(async () => ok(mcp)), mcpTools: vi.fn(async () => ok({ tools: [] })),
    hostsList: vi.fn(async () => ok(hostList)), hostsPublicKey: vi.fn(async () => ok(key)),
    toolsSetEnabled: vi.fn(async () => ok(inventory)), skillsTest: vi.fn(async () => ok({ result: 'ran', is_error: false }))
  }
  vi.stubGlobal('window', { odin: api })
  vi.stubGlobal('document', { activeElement: null })
  store = await import('../../src/renderer/src/stores/management')
  hostStore = await import('../../src/renderer/src/stores/hosts')
})

afterEach(() => {
  for (const view of mounted) view.unmount()
  vi.unstubAllGlobals()
})

async function view(name: string): Promise<Mounted> {
  const component = (await import(`../../src/renderer/src/views/settings/${name}.vue`)).default
  const result = mount(component)
  mounted.push(result)
  await flush()
  return result
}

describe('management capability refusals', () => {
  it('clears returned inventories, detail, configuration and errors without unlocking uncertain commands or erasing a local code draft', async () => {
    await store.loadTools()
    await store.loadSkills()
    await store.openSkill('cached_skill')
    store.management.editor!.code = 'unsaved local code'
    await store.loadMcp()
    store.management.mcpTools.cached = []
    store.management.error = 'old error'
    api.skillsTest!.mockResolvedValueOnce({ ok: false, error: { code: 'no_receipt', message: 'No receipt yet', disposition: 'outcome_unknown', command_id: 'held-test' } })
    await store.testSkill('cached_skill')
    for (const method of ['toolsList', 'toolsTimeoutsGet', 'skillsList', 'mcpStatus']) api[method]!.mockResolvedValueOnce(refused)
    await store.loadTools()
    await store.loadSkills()
    await store.loadMcp()
    expect(store.management).toMatchObject({ tools: null, timeouts: null, skills: [], skill: null, skillConfig: {}, validation: null, testResult: null, mcp: null, mcpTools: {}, error: '' })
    expect(store.management.unavailable).toEqual({ tools: true, timeouts: true, skills: true, mcp: true })
    expect(store.management.editor?.code).toBe('unsaved local code')
    expect(store.management.busy['skill:cached_skill']).toBe(true)
    expect(store.management.notes['skill:cached_skill']).toContain('never sent twice')
    const receipts = await import('../../src/renderer/src/store')
    receipts.applyReceipt({ id: 'held-test', settled: ok({ result: 'late answer', is_error: false }) })
    await flush()
    expect(store.management.busy['skill:cached_skill']).toBe(false)
    await store.openSkill('cached_skill')
    expect(store.management.editor?.code).toBe('unsaved local code')
    expect(store.management.skillConfig).toEqual(detail.config)
  })

  it('keeps tool inventory and timeout availability separate and restores each on a successful own load', async () => {
    api.toolsList!.mockResolvedValueOnce(refused)
    await store.loadTools()
    expect(store.management.unavailable.tools).toBe(true)
    expect(store.management.unavailable.timeouts).toBe(false)
    expect(store.management.timeouts).toEqual(timeouts)
    await store.loadTools()
    expect(store.management.unavailable.tools).toBe(false)
    expect(store.management.tools).toEqual(inventory)
    expect(store.management.unavailable.skills).toBe(false)
  })

  it('treats a refused skill detail as unavailable, clears the old loaded detail and prevents subsequent mutation dispatch', async () => {
    await store.loadSkills()
    await store.openSkill('cached_skill')
    store.management.validation = { valid: true, errors: [], warnings: [], metadata: null, definition_keys: [] }
    store.management.testResult = { result: 'old test result', is_error: false }
    api.skillsGet!.mockResolvedValueOnce(refused)
    await store.openSkill('other_skill')
    expect(store.management.unavailable.skills).toBe(true)
    expect(store.management.skill).toBeNull()
    expect(store.management.skills).toEqual([])
    expect(store.management.skillConfig).toEqual({})
    expect(store.management.validation).toBeNull()
    expect(store.management.testResult).toBeNull()
    await store.testSkill('cached_skill')
    expect(api.skillsTest).not.toHaveBeenCalled()
    await store.loadSkills()
    expect(store.management.unavailable.skills).toBe(false)
  })

  it('a mutation refusal invalidates returned tool data rather than displaying the raw service error', async () => {
    await store.loadTools()
    api.toolsSetEnabled!.mockResolvedValueOnce(refused)
    await store.setToolEnabled('cached_tool', false)
    expect(store.management.tools).toBeNull()
    expect(store.management.unavailable.tools).toBe(true)
    expect(store.management.busy['tool:cached_tool']).toBe(false)
    expect(store.management.notes['tool:cached_tool']).toBeUndefined()
    await store.setToolEnabled('cached_tool', false)
    expect(api.toolsSetEnabled).toHaveBeenCalledTimes(1)
  })

  it('keeps real failures distinguishable from capability refusals and isolates errors between resources', async () => {
    api.toolsList!.mockResolvedValueOnce({ ok: false, error: { code: 'unavailable', message: 'core restarting', disposition: 'not_dispatched' } })
    await store.loadTools()
    await store.loadSkills()
    expect(store.management.errors.tools).toBe('core restarting')
    expect(store.management.unavailable.tools).toBe(false)
    const tools = await view('Tools')
    expect(tools.root.textContent()).not.toContain('is unavailable.')
    api.skillsList!.mockResolvedValueOnce(refused)
    await store.loadSkills()
    expect(store.management.unavailable.skills).toBe(true)
    expect(store.management.unavailable.tools).toBe(false)
    expect(store.management.errors.skills).toBe('')
  })

  it('invalidates a host enrollment test and old key/references, preserves shared locks and recovers from successful loads', async () => {
    await hostStore.loadHosts()
    hostStore.beginAdd()
    Object.assign(hostStore.hosts.enrollment!, { token: 'old-test-token', tested: true, observed: ['old fingerprint'], test: { ok: true }, step: 5 })
    hostStore.hosts.references.cached = [{ kind: 'schedule', location: 'old' }]
    store.management.busy['host:cached'] = true
    api.hostsPublicKey!.mockResolvedValueOnce(refused)
    await hostStore.loadHosts()
    expect(hostStore.hosts).toMatchObject({ unavailable: true, error: '', list: null, key: null, references: {}, enrollment: { token: '', tested: false, test: null, observed: [], step: 1 } })
    expect(store.management.busy['host:cached']).toBe(true)
    await hostStore.loadHosts()
    expect(hostStore.hosts.unavailable).toBe(false)
    expect(hostStore.hosts.key).toEqual(key)
  })

  it.each([
    ['Tools', ['toolsList', 'toolsTimeoutsGet'], 'Tool management is unavailable.', 'Built-in tools', 'loadTools'],
    ['Skills', ['skillsList'], 'Skill management is unavailable.', 'Skills', 'loadSkills'],
    ['Mcp', ['mcpStatus'], 'MCP management is unavailable.', 'MCP servers', 'loadMcp'],
    ['Hosts', ['hostsList', 'hostsPublicKey'], 'Host management is unavailable.', 'Hosts', 'loadHosts']
  ])('the mounted %s view makes its own loads, shows a specific plain unavailable state, no mutation controls, then recovers', async (name, methods, message, label, reload) => {
    await store.loadTools()
    await store.loadSkills()
    await store.openSkill('cached_skill')
    await store.loadMcp()
    await hostStore.loadHosts()
    for (const method of methods) {
      api[method]!.mockClear()
      api[method]!.mockResolvedValueOnce(refused)
    }
    const screen = await view(name)
    for (const method of methods) expect(api[method]).toHaveBeenCalledTimes(1)
    const panel = screen.root.findAll((node) => node.props['aria-label'] === label)[0]!
    expect(panel.textContent()).toContain(message)
    expect(panel.findAll((node) => node.props.role === 'status')).toHaveLength(1)
    expect(screen.root.textContent()).not.toMatch(/Service is not available yet|cached_tool|cached_skill|old public key|Loading/)
    // Browser/email setup disclosures and status refresh remain independent of the built-in inventory.
    const controls = screen.root.findAll((node) => ['button', 'input', 'select', 'textarea'].includes(node.tag))
    if (name === 'Tools') {
      expect(controls.map((control) => control.props['aria-label']).sort()).toEqual(['Configure browser', 'Configure email', 'Refresh computer use', 'Refresh status for browser'].sort())
      expect(panel.findAll((node) => ['button', 'input', 'select', 'textarea'].includes(node.tag))).toEqual([])
      expect(screen.root.findAll((node) => node.props['aria-label'] === 'Tool timeouts')[0]!.findAll((node) => ['button', 'input', 'select', 'textarea'].includes(node.tag))).toEqual([])
      expect(api.healthGet).toHaveBeenCalledExactlyOnceWith({})
      expect(api.computerStatus).toHaveBeenCalledExactlyOnceWith({})
    } else expect(controls).toEqual([])
    expect(screen.root.findAll((node) => node.props.class === 'warn')).toEqual([])
    if (name === 'Tools') expect(screen.root.textContent()).toContain('Tool timeout management is unavailable.')
    if (reload === 'loadHosts') await hostStore.loadHosts()
    else await store[reload as 'loadTools' | 'loadSkills' | 'loadMcp']()
    await flush()
    expect(screen.root.textContent()).not.toContain(message)
    expect(screen.root.findAll((node) => node.tag === 'button').length).toBeGreaterThan(0)
  })

  it('does not allow an older successful read to overwrite a newer inventory or MCP refusal', async () => {
    let inventoryAnswer!: (value: Result<unknown>) => void
    let mcpAnswer!: (value: Result<unknown>) => void
    api.toolsList!.mockImplementationOnce(() => new Promise((resolve) => { inventoryAnswer = resolve }))
    api.mcpStatus!.mockImplementationOnce(() => new Promise((resolve) => { mcpAnswer = resolve }))
    const firstTools = store.loadTools()
    const firstMcp = store.loadMcp()
    api.toolsList!.mockResolvedValueOnce(refused)
    api.mcpStatus!.mockResolvedValueOnce(refused)
    await store.loadTools()
    await store.loadMcp()
    inventoryAnswer(ok(inventory))
    mcpAnswer(ok(mcp))
    await Promise.all([firstTools, firstMcp])
    expect(store.management.tools).toBeNull()
    expect(store.management.mcp).toBeNull()
    expect(store.management.unavailable.tools).toBe(true)
    expect(store.management.unavailable.mcp).toBe(true)
  })
})
