import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConfigField } from '../../src/shared/api'
import { flush, mount, type Mounted } from './component-host'

const ok = (result: unknown) => ({ ok: true, result })
const unavailable = { ok: false, error: { code: 'capability_unavailable', message: 'Unavailable' } }
let mounted: Mounted | undefined
let bridge: Record<string, any>
const field = (path: string, value: unknown): ConfigField => ({ path, label: 'Raw schema label', description: 'Raw schema description', type: typeof value === 'boolean' ? 'boolean' : 'array', enum: null, constraints: {}, desired: value, effective: value, sensitivity: 'public', apply_handler: 'settings.set', apply_state: 'applied' } as ConfigField)
const server = { name: 'docs', transport: 'stdio', state: 'connected', enabled: true, command: '/fixture/docs', args: [], header_keys: ['Authorization'], env_keys: ['TOKEN'], discovered_count: 2, published_count: 1 }
const mcp = { revision: 'm1', enabled: true, servers: [server], connected_count: 1, server_count: 1, published_tool_count: 1, max_published_tools_per_server: 10, max_published_tools_global: 20 }

beforeEach(() => {
  vi.resetModules()
  bridge = { mcpStatus: vi.fn(async () => ok(mcp)), mcpTools: vi.fn(async () => ok({ tools: [] })), mcpSetEnabled: vi.fn(async (params) => ok({ ...mcp, revision: 'm2', servers: [{ ...server, enabled: params.enabled }] })), mcpSetLimits: vi.fn(async () => ok({ ...mcp, revision: 'm2' })), mcpSave: vi.fn(async () => ok(mcp)), skillsList: vi.fn(async () => ok([{ name: 'hello', status: 'loaded', version: '1', description: 'Fixture' }])), settingsSet: vi.fn(async (params) => ok({ revision: 'r2', fields: params.changes.map((change: any) => field(change.path, change.value)) })) }
  ;(globalThis as any).window = { odin: new Proxy(bridge, { get: (target, key: string) => target[key] ?? (async () => unavailable) }) }
  ;(globalThis as any).document = { activeElement: null }
})
afterEach(() => { mounted?.unmount(); mounted = undefined })
async function view(name: string, fields: ConfigField[] = []) {
  const { settings } = await import('../../src/renderer/src/stores/settings')
  settings.meta = { revision: 'r1', fields } as any
  mounted = mount((await import(`../../src/renderer/src/views/settings/${name}.vue`)).default)
  await flush()
  return { root: mounted.root, settings }
}
describe('UI v1 curated managed destinations', () => {
  it('keeps MCP enablement a revision-bound availability switch, not an authorization grant', async () => {
    const { root } = await view('Mcp')
    expect(root.textContent()).toContain('each action still needs permission')
    expect(root.textContent()).toContain('runs its program on this computer')
    const control = root.findAll((n) => n.props.role === 'switch' && n.props['aria-label'] === 'Turn off docs')[0]!
    control.fire('change', { target: { checked: false } }); await flush()
    expect(bridge.mcpSetEnabled).toHaveBeenCalledExactlyOnceWith({ name: 'docs', enabled: false, expected_revision: 'm1' })
    expect(root.findAll((n) => n.props.role === 'switch' && n.props['aria-label'] === 'Turn on docs')[0]!.props.checked).toBe(false)
  })
  it('keeps Add/Edit credentials write-only and Cancel performs no server mutation', async () => {
    const { root } = await view('Mcp')
    expect(root.textContent()).toContain('Saved securely: Authorization, TOKEN')
    const actions = root.findAll(n => n.props.class === 'mcp-server-actions')[0]!
    expect(actions.children.filter(n => n.tag === 'button').map(n => n.textContent())).toEqual(['Edit', 'More'])
    expect(root.named('More actions for docs').props['aria-haspopup']).toBe('menu')
    root.button('Edit').fire('click'); await flush()
    expect(root.find('dialog')!.props['aria-label']).toBe('Edit MCP server docs')
    expect(root.find('dialog')!.props.class).toBe('settings-form-dialog')
    expect(root.find('dialog')!.findAll(n => n.props.class === 'settings-card')).toHaveLength(0)
    expect(root.textContent()).toContain('Leave a field blank to keep what is stored')
    expect(root.textContent()).toContain('Remove header Authorization')
    root.button('Add a header').fire('click'); await flush()
    const secret = root.findAll((n) => n.props.type === 'password')[0]!
    expect(secret.value).toBe(''); expect(secret.props.autocomplete).toBe('off')
    secret.type('draft-secret'); root.button('Cancel').fire('click'); await flush()
    expect(bridge.mcpSave).not.toHaveBeenCalled()
    expect(root.textContent()).not.toContain('draft-secret')
    root.button('Add server').fire('click'); await flush()
    expect(root.find('dialog')!.props['aria-label']).toBe('Add MCP server')
    expect(root.findAll((n) => n.tag === 'textarea').some((n) => n.value === JSON.stringify(mcp.servers))).toBe(false)
  })
  it('MCP limits stay deliberate, validate without dispatch, and preserve newer drafts on settlement', async () => {
    let settle!: (value: unknown) => void
    bridge.mcpSetLimits = vi.fn(() => new Promise((resolve) => { settle = resolve }))
    const { root } = await view('Mcp')
    const control = root.findAll((n) => n.props.id === 'mcp-limit-server')[0]!
    control.type('-1'); root.button('Save limits').fire('click'); await flush()
    expect(bridge.mcpSetLimits).not.toHaveBeenCalled(); expect(root.textContent()).toContain('Use whole numbers')
    control.type('5'); await flush(); expect(bridge.mcpSetLimits).not.toHaveBeenCalled()
    root.button('Save limits').fire('click'); await flush()
    expect(bridge.mcpSetLimits).toHaveBeenCalledExactlyOnceWith({ max_published_tools_per_server: 5, expected_revision: 'm1' })
    control.type('6'); settle(ok({ ...mcp, revision: 'm2' })); await flush()
    expect(String(control.value)).toBe('6')
    root.button('Cancel limits').fire('click'); await flush(); expect(control.value).toBe('')
  })
  it('locks MCP dialog cancel and submission while a receipt is pending', async () => {
    const { root } = await view('Mcp')
    root.named('Edit docs').fire('click'); await flush()
    const { management } = await import('../../src/renderer/src/stores/management')
    management.busy['mcp:docs'] = true; await flush()
    expect(root.named('Cancel MCP server changes').props.disabled).toBe(true)
    root.named('Cancel MCP server changes').fire('click')
    root.named('Save MCP server docs').fire('click'); await flush()
    expect(root.find('dialog')).toBeTruthy(); expect(bridge.mcpSave).not.toHaveBeenCalled()
    management.busy['mcp:docs'] = false
  })
  it('Skills exposes one curated endpoint editor with explicit multiline save and a real enablement switch', async () => {
    const path = 'tools.skill_allowed_urls'
    const { root } = await view('Skills', [field(path, ['https://example.org'])])
    expect(root.textContent()).toContain('Allowed skill endpoints')
    expect(root.textContent()).not.toContain('Raw schema')
    expect(root.findAll((n) => n.props.role === 'switch' && n.props['aria-label'] === 'Turn off hello')).toHaveLength(1)
    const control = root.find('textarea')!; control.type('https://new.example.org'); await flush()
    expect(bridge.settingsSet).not.toHaveBeenCalled()
    expect(control.props.onKeydown).toBeUndefined(); expect(control.props.onBlur).toBeUndefined()
    expect(bridge.settingsSet).not.toHaveBeenCalled()
    root.named('Save Allowed skill endpoints').fire('click'); await flush()
    const { dialog } = await import('../../src/renderer/src/dialog')
    expect(dialog.current?.title).toBe('Change access policy?')
    expect(bridge.settingsSet).not.toHaveBeenCalled()
    dialog.current!.resolve(true); await flush()
    expect(bridge.settingsSet).toHaveBeenCalledExactlyOnceWith({ expected_revision: 'r1', changes: [{ path, value: ['https://new.example.org'] }] })
  })
  it('Work exposes only reviewed policies while retaining incoming and running-work controls', async () => {
    const { root } = await view('Work', [field('learning.loop_reflection_enabled', false), field('turn_state.auto_resume', false), field('agents.max_iterations', true)])
    expect(root.textContent()).toContain('Learn from loops')
    expect(root.textContent()).toContain('Resume preserved work')
    expect(root.textContent()).toContain('Running now')
    expect(root.textContent()).not.toContain('Raw schema')
    expect(root.findAll((n) => n.props.role === 'switch')).toHaveLength(2)
  })
  it('Host enrollment and schedule editing are named dialogs with no write on Cancel', async () => {
    const { root } = await view('Hosts')
    const { hosts, beginAdd } = await import('../../src/renderer/src/stores/hosts')
    hosts.unavailable = false; beginAdd(); await flush()
    expect(root.find('dialog')!.props['aria-label']).toBe('Add host')
    root.button('Cancel').fire('click'); await flush()
    expect(root.find('dialog')).toBeUndefined()
    mounted!.unmount(); mounted = undefined
    const schedule = await view('Work')
    const { schedules } = await import('../../src/renderer/src/stores/schedules')
    schedules.unavailable = false; await flush()
    schedule.root.button('New schedule').fire('click'); await flush()
    expect(schedule.root.find('dialog')!.props['aria-label']).toBe('New schedule')
    schedule.root.button('Cancel').fire('click'); await flush()
    expect(schedule.root.find('dialog')).toBeUndefined()
    expect(bridge.settingsSet).not.toHaveBeenCalled()
  })
  it('Skills keeps dependencies and coding-session access distinct from Python execution', async () => {
    const { root } = await view('Skills')
    const { management } = await import('../../src/renderer/src/stores/management')
    management.editor = { name: 'hello', code: 'original', create: false }
    management.skill = { name: 'hello', handoff_to_codex: true, config: {}, metadata: { dependencies: ['fixture-package>=1'], config_schema: {}, has_config: false } } as any
    await flush()
    expect(root.textContent()).toContain('fixture-package>=1')
    expect(root.textContent()).toContain('Coding session')
    expect(root.textContent()).toContain('its access rules still apply')
    root.named('Cancel skill changes').fire('click'); await flush()
    expect(bridge.settingsSet).not.toHaveBeenCalled()
  })
  it('Hosts never dispatches a permission expansion before confirmation, or after revision drift', async () => {
    const path = 'tools.governor.block_critical'
    const { root, settings } = await view('Hosts', [field(path, true)])
    const { hosts } = await import('../../src/renderer/src/stores/hosts')
    hosts.unavailable = false; await flush()
    const { dialog } = await import('../../src/renderer/src/dialog')
    const control = root.findAll((n) => n.props.id === `hosts-policy-${path}`)[0]!
    const target = { checked: false }
    control.fire('change', { target }); await flush()
    expect(target.checked).toBe(true); expect(bridge.settingsSet).not.toHaveBeenCalled()
    expect(dialog.current?.title).toBe('Allow more command access?')
    dialog.current!.resolve(null); await flush(); expect(bridge.settingsSet).not.toHaveBeenCalled()
    control.fire('change', { target: { checked: false } }); await flush()
    settings.meta!.revision = 'r2'; dialog.current!.resolve(true); await flush()
    expect(bridge.settingsSet).not.toHaveBeenCalled(); expect(root.textContent()).toContain('Settings changed while you were confirming')
    control.fire('change', { target: { checked: false } }); await flush()
    dialog.current!.resolve(true); await flush()
    expect(bridge.settingsSet).toHaveBeenCalledExactlyOnceWith({ expected_revision: 'r2', changes: [{ path, value: false }] })
  })
  it('Hosts rejects confirmation across a changed session even when the revision string is unchanged', async () => {
    const path = 'tools.governor.owner_can_override'
    const { root } = await view('Hosts', [field(path, false)])
    const { hosts } = await import('../../src/renderer/src/stores/hosts')
    hosts.unavailable = false; await flush()
    const { dialog } = await import('../../src/renderer/src/dialog')
    const { state } = await import('../../src/renderer/src/store')
    root.findAll((n) => n.props.id === `hosts-policy-${path}`)[0]!.fire('change', { target: { checked: true } }); await flush()
    state.recoveryEpoch += 1; dialog.current!.resolve(true); await flush()
    expect(bridge.settingsSet).not.toHaveBeenCalled()
    expect(root.textContent()).toContain('Settings changed while you were confirming')
  })
})
