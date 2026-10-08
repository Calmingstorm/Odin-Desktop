import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, Host, mount, type Mounted } from './component-host'

const ok = <T>(result: T) => ({ ok: true as const, result })
let mounted: Mounted | undefined
let descriptor: PropertyDescriptor | undefined
let bridge: Record<string, ReturnType<typeof vi.fn>>
const control = (id: string) => mounted!.root.findAll((node) => node.props.id === id)[0]!
const labelled = (text: string) => mounted!.root.findAll((node) => node.tag === 'label' && node.textContent().trim().startsWith(text))[0]!.find('input')!
beforeEach(() => {
  vi.resetModules()
  bridge = {
    hostsList: vi.fn(async () => ok({ hosts: [], default_host: '', generation: 1, tofu_enabled: false })),
    hostsPublicKey: vi.fn(async () => ok({ public_key: 'public', authorized_keys_command: 'install-public', fingerprint: 'fingerprint', permissions: 'safe', restart_pending: false })),
    hostsSettings: vi.fn(async () => ok({ saved: true })),
    mcpStatus: vi.fn(async () => ok({ enabled: true, servers: [{ name: 'docs', enabled: true, transport: 'stdio', state: 'connected', header_keys: [], env_keys: [], discovered_count: 1, published_count: 1 }], connected_count: 1, server_count: 1, published_tool_count: 1, max_published_tools_per_server: 10, max_published_tools_global: 20 })),
    mcpTools: vi.fn(async () => ok({ tools: [{ original_name: 'read', published_name: 'docs_read', description: 'Reads documentation', excluded: false }] })),
    mcpSave: vi.fn(async () => ok({ saved: true })),
    toolsList: vi.fn(async () => ok({ tools: [], disabled_count: 0 })),
    toolsTimeoutsGet: vi.fn(async () => ok({ default_timeout: 30, overrides: {} })),
    toolsTimeoutsSet: vi.fn(async (params) => ok(params)),
    healthGet: vi.fn(async () => ok({})),
    computerStatus: vi.fn(async () => ok({ readiness: { management_available: true, foreground_available: false, dispatch: 'none', reason: 'not_enabled' }, session: null })),
    memoryList: vi.fn(async () => ok({ global: { count: 1, keys: ['note'] } })),
    memoryGet: vi.fn(async () => ok({ entries: { note: 'Original value' } })),
    memorySet: vi.fn(async () => ok({ saved: true })),
    listsList: vi.fn(async () => ok({ items: [] })),
    knowledgeList: vi.fn(async () => ok([])),
    settingsSchema: vi.fn(async () => ok({ revision: 'rev-managed', fields: [], status: { counts: {}, desired_revision: 'rev-managed', effective_revision: null } })),
    openrouterCatalogue: vi.fn(async () => ok({ recognized: true, models: [{ id: 'author/model' }], quick_add: [] }))
  }
  vi.stubGlobal('window', { odin: bridge })
  vi.stubGlobal('document', { activeElement: null })
  descriptor = Object.getOwnPropertyDescriptor(Host.prototype, 'getRootNode')
  Object.defineProperty(Host.prototype, 'getRootNode', { configurable: true, value: () => document })
})
afterEach(() => {
  mounted?.unmount()
  mounted = undefined
  if (descriptor) Object.defineProperty(Host.prototype, 'getRootNode', descriptor)
  vi.unstubAllGlobals()
})
async function view(name: string) {
  mounted = mount((await import(`../../src/renderer/src/views/settings/${name}.vue`)).default)
  await flush()
  return mounted.root
}

describe('mounted managed settings missing interactions', () => {
  it('omits unknown applied-value warnings for host policy without changing it', async () => {
    const { settings } = await import('../../src/renderer/src/stores/settings')
    settings.meta = { revision: 'unknown-policy', fields: [{ path: 'tools.governor.block_critical', type: 'boolean', desired: true, effective: null, apply_handler: 'settings.set', sensitivity: 'public', constraints: {}, apply_state: 'unknown' }] } as any
    const root = await view('Hosts')
    expect(control('hosts-policy-tools.governor.block_critical').props.checked).toBe(true)
    expect(root.textContent()).not.toMatch(/running value|Refresh before relying/i)
    expect(bridge.hostsSettings).not.toHaveBeenCalled()
    expect(settings.meta!.fields[0]!.effective).toBeNull()
  })
  it('cancels a host default and trust draft without dispatching either setting', async () => {
    const root = await view('Hosts')
    control('hosts-default').fire('change', { target: { value: 'build' } })
    control('hosts-tofu').checked = true
    control('hosts-tofu').fire('change')
    await flush()
    expect(root.button('Save trust policy')).toBeTruthy()
    root.button('Cancel').fire('click')
    await flush()
    expect(control('hosts-default').value).toBe('')
    expect(control('hosts-tofu').checked).toBe(false)
    expect(root.findAll((node) => node.tag === 'button' && node.textContent() === 'Save trust policy')).toHaveLength(0)
    expect(bridge.hostsSettings).not.toHaveBeenCalled()
  })

  it('requires fresh confirmation after host data changes and preserves the unsent trust draft', async () => {
    const root = await view('Hosts')
    control('hosts-tofu').checked = true
    control('hosts-tofu').fire('change')
    await flush()
    root.button('Save trust policy').fire('click')
    const { dialog } = await import('../../src/renderer/src/dialog')
    expect(dialog.current?.title).toBe('Allow trust on first use?')
    const { state } = await import('../../src/renderer/src/store')
    state.recoveryEpoch += 1
    dialog.current!.resolve(true)
    await flush()
    expect(root.textContent()).toContain('Hosts changed while you were confirming')
    expect(bridge.hostsSettings).not.toHaveBeenCalled()
    root.button('Cancel trust changes').fire('click')
    await flush()
    expect(control('hosts-tofu').checked).toBe(false)
  })

  it('edits host enrollment fields through the mounted form and returns from the public-key step', async () => {
    const root = await view('Hosts')
    root.button('Add host').fire('click')
    await flush()
    labelled('Alias').type('build')
    labelled('Address').type('host.lan')
    labelled('Port').type('2222')
    labelled('SSH user').type('builder')
    labelled('Description').type('Build machine')
    const dialogRoot = root.find('dialog')!
    const selects = dialogRoot.findAll((node) => node.tag === 'select')
    selects[0]!.choose(1)
    selects[1]!.choose(1)
    await flush()
    root.button('Next').fire('click')
    await flush()
    expect(root.textContent()).toContain('builder@host.lan')
    root.button('Back').fire('click')
    await flush()
    expect(labelled('Port').value).toBe(2222)
    expect(labelled('Description').value).toBe('Build machine')
    const returnedSelects = root.find('dialog')!.findAll((node) => node.tag === 'select')
    expect(returnedSelects[0]!.selectedIndex).toBe(1)
    expect(returnedSelects[1]!.selectedIndex).toBe(1)
    root.find('dialog')!.fire('cancel', { preventDefault: () => undefined })
    await flush()
    expect(root.find('dialog')).toBeUndefined()
  })

  it('reads real MCP tool rows and changes transport locally without saving on dialog cancellation', async () => {
    const root = await view('Mcp')
    root.named('Tools for docs').fire('click')
    await flush()
    expect(root.textContent()).toContain('docs_read')
    expect(root.textContent()).toContain('Reads documentation')
    root.named('Edit docs').fire('click')
    await flush()
    labelled('Working directory').type('/tmp/docs')
    labelled('Clear its arguments').checked = true
    labelled('Clear its arguments').fire('change')
    await flush()
    expect(root.find('textarea')!.props.disabled).toBe(true)
    root.find('dialog')!.find('select')!.choose(1)
    await flush()
    labelled('URL').type('https://docs.invalid/mcp')
    await flush()
    expect(labelled('URL').value).toBe('https://docs.invalid/mcp')
    root.find('dialog')!.fire('cancel', { preventDefault: () => undefined })
    await flush()
    expect(root.find('dialog')).toBeUndefined()
    expect(bridge.mcpTools).toHaveBeenCalledWith({ name: 'docs' })
    expect(bridge.mcpSave).not.toHaveBeenCalled()
  })

  it('edits memory using its rendered key/value controls and discards the local draft', async () => {
    const root = await view('State')
    root.named('Open Everywhere memory').fire('click')
    await flush()
    root.named('Edit note in Everywhere memory').fire('click')
    await flush()
    const inputs = root.findAll((node) => node.tag === 'input')
    inputs.find((node) => node.props['aria-label'] === 'Key in Everywhere memory')!.type('replacement')
    inputs.find((node) => node.props['aria-label'] === 'Value in Everywhere memory')!.type('Unsent value')
    await flush()
    expect(inputs.find((node) => node.props['aria-label'] === 'Value in Everywhere memory')!.value).toBe('Unsent value')
    root.named('Cancel Everywhere memory edit').fire('click')
    await flush()
    expect(root.textContent()).toContain('Original value')
    expect(root.findAll((node) => node.props.placeholder === 'What to remember')).toHaveLength(0)
    expect(bridge.memorySet).not.toHaveBeenCalled()
  })

  it('skips an unnamed timeout draft and removes a named override locally before saving', async () => {
    const root = await view('Tools')
    root.button("Add a tool's own timeout").fire('click')
    await flush()
    root.button('Save timeouts').fire('click')
    await flush()
    expect(bridge.toolsTimeoutsSet).toHaveBeenCalledWith({ default_timeout: 30, overrides: {} })
    root.button("Add a tool's own timeout").fire('click')
    await flush()
    root.findAll((node) => node.props.placeholder === 'Tool')[0]!.type('read_file')
    root.findAll((node) => node.props.placeholder === 'Seconds')[0]!.type('12')
    await flush()
    expect(root.named('Remove timeout for read_file')).toBeTruthy()
    root.named('Remove timeout for read_file').fire('click')
    await flush()
    expect(root.findAll((node) => node.props.placeholder === 'Tool')).toHaveLength(0)
    root.button('Save timeouts').fire('click')
    await flush()
    expect(bridge.toolsTimeoutsSet).toHaveBeenCalledTimes(2)
  })

  it('shows explicit unavailable diagnostics, endpoints, and routing for an older bridge', async () => {
    await (await import('../../src/renderer/src/stores/settings')).loadSettings()
    mounted = mount((await import('../../src/renderer/src/components/OpenRouterAdmin.vue')).default)
    await flush()
    const root = mounted.root
    root.button('author/model').fire('click')
    await flush()
    expect(control('openrouter-model').value).toBe('author/model')
    root.button('Read endpoints').fire('click')
    root.button('Read compatibility diagnostic').fire('click')
    root.find('form')!.fire('submit', { preventDefault: () => undefined })
    await flush()
    expect(root.textContent()).toContain('OpenRouter endpoints is unavailable.')
    expect(root.textContent()).toContain('Compatibility provider diagnostic is unavailable.')
    expect(root.textContent()).toContain('OpenRouter selection is unavailable.')
    expect(root.button('Save routing').props.disabled).toBe(true)
  })

  it('turns catalogue transport rejection into a rendered bridge failure rather than stale model data', async () => {
    mounted = mount((await import('../../src/renderer/src/components/OpenRouterAdmin.vue')).default)
    await flush()
    expect(mounted.root.button('author/model')).toBeTruthy()
    bridge.openrouterCatalogue!.mockRejectedValueOnce(new Error('transport disconnected'))
    mounted.root.button('Reload catalogue').fire('click')
    await flush()
    expect(mounted.root.textContent()).toContain('The bridge could not return a result.')
    expect(mounted.root.findAll((node) => node.tag === 'button' && node.textContent() === 'author/model')).toHaveLength(0)
  })
})
