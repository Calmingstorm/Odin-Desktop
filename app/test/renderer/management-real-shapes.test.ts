import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flush, type Mounted } from './component-host'
import type { McpStatus } from '../../src/shared/api'

const ok = (result: unknown) => ({ ok: true, result })
const refused = { ok: false, error: { code: 'capability_unavailable', message: 'Profile keyring is locked', disposition: 'not_dispatched' } }
const row = (name: string) => ({ name, transport: 'stdio' as const, enabled: true, state: 'connected', last_error: '', blocked_reason: '', published_count: 1, discovered_count: 1, excluded_count: 0, published_tools: [], last_refresh_age_seconds: 0, stderr_tail: '', url_display: null, header_keys: [], env_keys: [] })
const status = (revision = 'r1'): McpStatus => ({ revision, enabled: true, servers: [row('public'), { ...row('private'), state: 'unavailable', blocked_reason: 'Profile keyring is locked' }], connected_count: 1, server_count: 2, enabled_server_count: 2, published_tool_count: 1, max_published_tools_per_server: 10, max_published_tools_global: 50 })
let store: typeof import('../../src/renderer/src/stores/management')
let api: Record<string, ReturnType<typeof vi.fn>>
let views: Mounted[]

beforeEach(async () => {
  vi.resetModules()
  views = []
  api = {
    mcpStatus: vi.fn(async () => ok(status())), mcpTools: vi.fn(async () => ok({ name: 'public', tools: [] })),
    status: vi.fn(async () => ok({ capabilities: ['skills.list', 'skills.save'] })),
    skillsList: vi.fn(async () => ok([{ name: 'hello', status: 'loaded', description: 'Harmless', diagnostics: [] }, { name: 'broken', status: 'error', diagnostics: [{ level: 'error', message: 'Failed to load module' }] }])),
    skillsGet: vi.fn(async () => ok({ name: 'hello', code: 'original', config: { setting: 'old' }, metadata: { config_schema: { properties: { setting: { type: 'string' } } } } })),
    skillsValidate: vi.fn(async () => ok({ valid: true, errors: [], warnings: [], metadata: null, definition_keys: [] })),
    skillsSave: vi.fn(async () => ok({ result: 'Saved' })), skillsTest: vi.fn(async () => refused),
    skillsSetEnabled: vi.fn(async () => ok({ result: 'Off' })), skillsDelete: vi.fn(async () => ok({ result: 'Deleted' })),
    skillsConfigSet: vi.fn(async () => ok({ config: { setting: 'new' } }))
  }
  for (const method of ['mcpSave', 'mcpSetEnabled', 'mcpDelete', 'mcpReconnect', 'mcpRefreshTools', 'mcpSetGlobalEnabled', 'mcpSetLimits']) {
    api[method] = vi.fn(async () => ok(status('r2')))
  }
  vi.stubGlobal('window', { odin: api })
  vi.stubGlobal('document', { activeElement: null })
  store = await import('../../src/renderer/src/stores/management')
})

afterEach(() => { for (const view of views) view.unmount(); vi.unstubAllGlobals() })

describe('real management contracts', () => {
  it('binds every MCP operation to status revision and adopts full-status outcomes', async () => {
    const cases: Array<[string, () => Promise<unknown>, object]> = [
      ['mcpSave', () => store.saveMcp({ name: 'public', create: true, command: '/bin/true' }), { name: 'public', command: '/bin/true' }],
      ['mcpSetEnabled', () => store.setMcpEnabled('public', false), { name: 'public', enabled: false }],
      ['mcpDelete', () => store.deleteMcp('public'), { name: 'public' }],
      ['mcpReconnect', () => store.reconnectMcp('public'), { name: 'public' }],
      ['mcpRefreshTools', () => store.refreshMcpTools('public'), { name: 'public' }],
      ['mcpSetGlobalEnabled', () => store.setMcpGlobal(false), { enabled: false }],
      ['mcpSetLimits', () => store.setMcpLimits({ max_published_tools_global: 5 }), { max_published_tools_global: 5 }]
    ]
    for (const [method, run, params] of cases) {
      api.mcpStatus!.mockResolvedValue(ok(status('r2')))
      store.management.mcp = status() as McpStatus
      await run()
      expect(api[method]).toHaveBeenLastCalledWith({ ...params, expected_revision: 'r1' })
      expect(store.management.mcp?.revision).toBe('r2')
    }
    expect(store.management.notes['mcp:public']).not.toContain('undefined')
  })

  it('retains the fixture create flag only when no real revision exists', () => {
    store.management.mcp = { ...status(), revision: undefined } as McpStatus
    expect(store.mcpSaveParams({ name: 'public', create: true })).toEqual({ name: 'public', create: true })
    store.management.mcp = status() as McpStatus
    expect(store.mcpSaveParams({ name: 'public', create: false })).toEqual({ name: 'public', expected_revision: 'r1' })
  })

  it('reads fresh status on stale binding but does not replay or discard the editor', async () => {
    store.management.mcp = status() as McpStatus
    api.mcpSave!.mockResolvedValueOnce({ ok: false, error: { code: 'stale_binding', message: 'Settings changed' } })
    api.mcpStatus!.mockResolvedValueOnce(ok(status('r3')))
    const draft = { name: 'public', create: false, command: '/bin/true' }
    expect(await store.saveMcp(draft)).toBe(false)
    expect(api.mcpSave).toHaveBeenCalledTimes(1)
    expect(store.management.mcp?.revision).toBe('r3')
    expect(draft.create).toBe(false)
    expect(store.management.notes['mcp:public']).toBe('Settings changed')
  })

  it('isolates server keyring refusals during mutation and tool reads', async () => {
    await store.loadMcp()
    store.management.mcpTools.public = []
    api.mcpReconnect!.mockResolvedValueOnce(refused)
    expect(await store.reconnectMcp('private')).toBe(false)
    api.mcpTools!.mockResolvedValueOnce(refused)
    await store.loadMcpTools('private')
    expect(store.management.unavailable.mcp).toBe(false)
    expect(store.management.mcp?.servers).toHaveLength(2)
    expect(store.management.mcpTools.public).toEqual([])
    expect(store.management.notes['mcp:private']).toBe('Profile keyring is locked')
    expect(await store.setMcpEnabled('public', false)).toBe(true)
  })

  it('keeps MCP late receipts bound once and adopts their real status', async () => {
    store.management.mcp = status() as McpStatus
    api.mcpReconnect!.mockResolvedValueOnce({ ok: false, error: { code: 'no_receipt', message: 'Pending', disposition: 'outcome_unknown', command_id: 'reconnect-once' } })
    await store.reconnectMcp('public')
    await store.reconnectMcp('public')
    expect(api.mcpReconnect).toHaveBeenCalledTimes(1)
    const receipts = await import('../../src/renderer/src/store')
    receipts.applyReceipt({ id: 'reconnect-once', settled: ok(status('r4')) as never })
    await flush()
    expect(store.management.mcp?.revision).toBe('r4')
    expect(store.management.busy['mcp:public']).toBe(false)
  })

  it('renders a per-server keyring reason without hiding the other server or mutation controls', async () => {
    const component = (await import('../../src/renderer/src/views/settings/Mcp.vue')).default
    const view = mount(component); views.push(view); await flush()
    expect(view.root.textContent()).toContain('Profile keyring is locked')
    expect(view.root.textContent()).toContain('public')
    expect(view.root.findAll((node) => node.props['aria-label'] === 'Reconnect public')).toHaveLength(1)
    expect(view.root.textContent()).not.toContain('MCP management is unavailable in this core.')
  })

  it('refreshes limits/global refusal state without marking unrelated MCP servers unavailable', async () => {
    await store.loadMcp()
    api.mcpSetLimits!.mockResolvedValueOnce(refused)
    api.mcpSetGlobalEnabled!.mockResolvedValueOnce(refused)
    await store.setMcpLimits({ max_published_tools_global: 5 })
    await store.setMcpGlobal(true)
    expect(store.management.unavailable.mcp).toBe(false)
    expect(store.management.mcp?.servers).toHaveLength(2)
    expect(store.management.notes['mcp-limits']).toBe('Profile keyring is locked')
    expect(store.management.notes.mcp).toBe('Profile keyring is locked')
  })

  it('shows only Test unavailable, preserving failed cards, editor and all other skill actions', async () => {
    const component = (await import('../../src/renderer/src/views/settings/Skills.vue')).default
    const view = mount(component); views.push(view); await flush()
    expect(view.root.textContent()).toContain('Test is unavailable in this core.')
    expect(view.root.textContent()).toContain('Failed to load module')
    expect(view.root.findAll((node) => node.props['aria-label'] === 'Test hello')[0]?.props.disabled).toBe(true)
    expect(store.management.unavailable.skills).toBe(false)
    await store.testSkill('hello')
    expect(api.skillsTest).not.toHaveBeenCalled()
    await store.openSkill('hello')
    store.management.editor!.code = 'updated'
    expect(await store.saveSkill()).toBe(true)
    expect(api.skillsSave).toHaveBeenCalledWith({ name: 'hello', code: 'updated', create: false })
    expect(await store.saveSkillConfig('hello', { setting: 'new' })).toBe(true)
    await store.setSkillEnabled('hello', false)
    await store.deleteSkill('broken')
    expect(api.skillsDelete).toHaveBeenCalledWith({ name: 'broken' })
    expect(store.management.unavailable.skills).toBe(false)
    store.newSkill('draft')
    expect(store.management.editor?.code).toBe('draft')
  })

  it('a Test refusal alone never blanks skills or the unsaved draft', async () => {
    delete api.status
    await store.loadSkills()
    await store.openSkill('hello')
    store.management.editor!.code = 'unsaved'
    await store.testSkill('hello')
    expect(store.management.skillTestUnavailable).toBe(true)
    expect(store.management.unavailable.skills).toBe(false)
    expect(store.management.skills).toHaveLength(2)
    expect(store.management.editor?.code).toBe('unsaved')
  })
})
