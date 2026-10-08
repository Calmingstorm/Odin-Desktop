// B3: real compiled form/view behavior, with store actions as the boundary.
// No browser, Electron, live core, or graphical session is started.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { flush, mount, type Host, type Mounted } from './component-host'

const paths = {
  store: '../../src/renderer/src/store', management: '../../src/renderer/src/stores/management',
  hosts: '../../src/renderer/src/stores/hosts', settings: '../../src/renderer/src/stores/settings',
  state: '../../src/renderer/src/stores/state', composer: '../../src/renderer/src/stores/composer',
  dialog: '../../src/renderer/src/dialog'
}
let mounted: Mounted[]
let actions: Record<string, ReturnType<typeof vi.fn>>
let ask: ReturnType<typeof vi.fn>
let late: (receipt: any) => void
let receipts: Array<(receipt: any) => void>
let bridge: Record<string, ReturnType<typeof vi.fn>>
let query: ReturnType<typeof vi.fn>
const fn = (name: string, answer: unknown = undefined) => (actions[name] ??= vi.fn(async () => answer))
const invoke = (v: Mounted, name: string, ...args: unknown[]) => (v.setup[name] as (...a: any[]) => any)(...args)
function deferred<T>() {
  let resolve!: (answer: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
const ok = (result: unknown = {}) => ({ ok: true, result })
const refused = { ok: false, error: { code: 'capability_unavailable', message: 'Unavailable', disposition: 'not_dispatched' } }
async function view(name: string) {
  const v = mount((await import(`../../src/renderer/src/views/settings/${name}.vue`)).default)
  mounted.push(v); await flush(); return v
}
async function component(name: string) {
  const v = mount((await import(`../../src/renderer/src/components/${name}.vue`)).default)
  mounted.push(v); await flush(); return v
}
function field(root: Host, label: string, tag = 'input'): Host {
  const namedLabel = root.findAll((h) => h.tag === 'label' && (h.textContent().trim() === label || h.children.some((child) => child.props.class === 'config-key' && child.textContent() === label)))[0]
  const control = namedLabel?.find(tag) ?? root.findAll((h) => h.tag === tag && !!namedLabel?.props.for && h.props.id === namedLabel.props.for)[0]
  if (!control) throw new Error(`No ${tag} labelled ${label}`)
  return control
}

beforeEach(() => {
  vi.resetModules()
  mounted = []; actions = {}; ask = vi.fn(async () => true)
  receipts = []; late = (receipt) => receipts.forEach((cb) => cb(receipt))
  bridge = { copyText: vi.fn(async () => ok()), codexOpenVerification: vi.fn(async () => ok()), codexRefresh: vi.fn(async () => ok({ email: 'a@example.com' })) }
  query = vi.fn(() => ({ focus: fn('focus') }))
  vi.stubGlobal('window', { odin: bridge, addEventListener: fn('addListener'), removeEventListener: fn('removeListener') })
  vi.stubGlobal('document', { activeElement: null, body: {}, querySelector: query })
  vi.stubGlobal('HTMLElement', class HTMLElement {})
  vi.doMock(paths.dialog, () => ({ ask, dialog: reactive({ current: null }) }))
  vi.doMock(paths.store, async (original) => ({
    ...await original<typeof import('../../src/renderer/src/store')>(),
    init: fn('init'), openSettings: fn('openSettings'), canAct: fn('canAct').mockReturnValue(true), chatUnavailable: fn('chatUnavailable').mockReturnValue(false),
    loadFailure: fn('loadFailure').mockReturnValue(''), retry: fn('retry'), send: fn('send', true), stop: fn('stop'), stopPending: fn('stopPending').mockReturnValue(false),
    onLateReceipt: (cb: typeof late) => { receipts.push(cb) }
  }))
  vi.doMock(paths.management, async (original) => {
    const real = await original<typeof import('../../src/renderer/src/stores/management')>()
    const mocked = Object.fromEntries(['loadMcp', 'loadMcpTools', 'deleteMcp', 'reconnectMcp', 'refreshMcpTools', 'saveMcp', 'setMcpEnabled', 'setMcpGlobal', 'setMcpLimits', 'loadSkills', 'deleteSkill', 'openSkill', 'saveSkillConfig', 'setSkillEnabled', 'testSkill', 'validateSkill', 'saveSkill'].map((name) => [name, fn(name, true)]))
    return { ...real, ...mocked }
  })
  vi.doMock(paths.hosts, async (original) => ({
    ...await original<typeof import('../../src/renderer/src/stores/hosts')>(),
    ...Object.fromEntries(['loadHosts', 'deleteHost', 'forceRevoke', 'saveHostSettings', 'setHostEnabled', 'scan', 'testConnection', 'activate', 'importLegacy'].map((name) => [name, fn(name, true)]))
  }))
  vi.doMock(paths.settings, async (original) => ({
    ...await original<typeof import('../../src/renderer/src/stores/settings')>(),
    ...Object.fromEntries(['loadCodex', 'labelAccount', 'removeAccount', 'activateAccount', 'beginLogin', 'retryLogin', 'stopLogin'].map((name) => [name, fn(name, true)]))
  }))
  vi.doMock(paths.state, async (original) => ({
    ...await original<typeof import('../../src/renderer/src/stores/state')>(),
    ...Object.fromEntries(['loadMemory', 'loadKnowledge', 'loadVersions', 'openScope', 'openList', 'deleteList', 'deleteMemory', 'deleteSource', 'ingest', 'reingest', 'reloadContext', 'restoreVersion', 'searchKnowledge', 'setMemory'].map((name) => [name, fn(name, true)]))
  }))
})
afterEach(() => {
  mounted.forEach((v) => v.unmount())
  Object.values(paths).forEach((path) => vi.doUnmock(path))
  vi.doUnmock('../../src/renderer/src/commands')
  for (const name of ['ConversationList', 'MessageList', 'Composer', 'SearchPanel', 'StatusBar', 'WorkPanel', 'ConfirmDialog', 'CleanupNotice', 'IconRail', 'ChatStatus', 'FirstRunBanner']) vi.doUnmock(`../../src/renderer/src/components/${name}.vue`)
  vi.doUnmock('../../src/renderer/src/views/Settings.vue')
  vi.unstubAllGlobals()
})

describe('B3 Hosts: settings, confirmation and enrollment controls', () => {
  it('sends only changed settings, keeps edits made in flight, and copies only public key material', async () => {
    const { hosts } = await import(paths.hosts)
    hosts.list = { default_host: 'local', configured_default_host: 'remote', tofu_enabled: false, hosts: [] }
    hosts.key = { public_key: 'public-fixture', authorized_keys_command: 'install-public-fixture', fingerprint: 'SHA256:public', permissions: '0600' }
    const v = await view('Hosts')
    await invoke(v, 'saveSettings'); expect(actions.saveHostSettings).not.toHaveBeenCalled()
    const select = v.root.find('select')!; select.value = 'build'; select.fire('change')
    const checkbox = v.root.find('input')!; checkbox.checked = true; checkbox.fire('change')
    const pending = deferred<boolean>(); actions.saveHostSettings!.mockReturnValueOnce(pending.promise)
    const saving = invoke(v, 'saveSettings')
    v.setup.defaultHost = 'newer'
    pending.resolve(true); await saving; await flush()
    expect(actions.saveHostSettings).toHaveBeenCalledWith({ default_host: 'build', allow_host_tofu: true })
    expect(v.setup.defaultHost).toBe('newer'); expect(v.setup.allowTofu).toBeNull()
    v.root.button('Copy the key').fire('click'); await flush()
    expect(bridge.copyText).toHaveBeenLastCalledWith('public-fixture')
    v.root.button('Copy the command that installs it').fire('click'); await flush()
    expect(bridge.copyText).toHaveBeenLastCalledWith('install-public-fixture')
    bridge.copyText!.mockResolvedValueOnce({ ok: false, error: { message: 'Clipboard denied' } })
    await invoke(v, 'copy', 'Key', 'public-fixture'); expect(v.setup.copied).toBe('Clipboard denied')
  })
  it('does not delete/revoke on cancellation and routes every enrollment step to its action', async () => {
    const { hosts } = await import(paths.hosts)
    const row = { host_id: 'h', alias: 'build', address: 'host.lan', port: 22, ssh_user: 'root', os: 'linux', description: '', trust_state: 'trusted', trust_mode: 'legacy', enabled: true, targetable: true, draining: true, last_test: { ok: false, checked_at: 10, detail: 'refused' } }
    hosts.list = { hosts: [row], tofu_enabled: true }; hosts.key = { public_key: 'public', authorized_keys_command: 'install', fingerprint: '', permissions: '' }
    const v = await view('Hosts')
    ask.mockResolvedValueOnce(false); await v.root.named('Delete host build…').fire('click')
    expect(actions.deleteHost).not.toHaveBeenCalled()
    await v.root.named('Delete host build…').fire('click'); expect(actions.deleteHost).toHaveBeenCalledWith('build')
    ask.mockResolvedValueOnce(false); await v.root.named('Force revoke host build…').fire('click'); expect(actions.forceRevoke).not.toHaveBeenCalled()
    await v.root.named('Force revoke host build…').fire('click'); expect(actions.forceRevoke).toHaveBeenCalledWith('build')
    const availability = v.root.findAll((n) => n.props.role === 'switch' && n.props['aria-label'] === 'Turn off host build')[0]!
    availability.fire('change', { target: { checked: false } }); expect(actions.setHostEnabled).toHaveBeenCalledWith('build', false)
    v.root.named('Enroll trusted key for host build').fire('click'); expect(actions.importLegacy).toHaveBeenCalledWith(row)
    v.root.named('Edit host build').fire('click'); await flush(); expect(hosts.enrollment.form.alias).toBe('build')
    v.root.button('Cancel').fire('click'); await flush(); expect(hosts.enrollment).toBeNull()
    v.root.button('Add host').fire('click'); await flush()
    field(v.root, 'Alias').type('new'); field(v.root, 'Address').type('host.lan'); await flush()
    v.root.button('Next').fire('click'); await flush(); expect(hosts.enrollment.step).toBe(2)
    v.root.button('Copy the command').fire('click'); await flush(); expect(bridge.copyText).toHaveBeenCalledWith('install')
    v.root.button('Next').fire('click'); await flush(); expect(hosts.enrollment.step).toBe(3)
    field(v.root, 'Expected fingerprints', 'textarea').type('SHA256:expected'); v.root.button('Scan and compare').fire('click'); expect(actions.scan).toHaveBeenCalled()
    hosts.enrollment.step = 4; await flush(); v.root.button('Test the connection').fire('click'); expect(actions.testConnection).toHaveBeenCalled()
    hosts.enrollment.step = 5; hosts.enrollment.tested = true; await flush(); v.root.button('Activate').fire('click'); expect(actions.activate).toHaveBeenCalled()
  })
})

describe('B3 MCP: patches and form ownership', () => {
  async function fixture() {
    const { management } = await import(paths.management)
    management.mcp = { enabled: true, servers: [{ name: 'tools', transport: 'http', enabled: true, state: 'connected', header_keys: ['Authorization'], env_keys: ['ENV'], discovered_count: 2, published_count: 1 }], connected_count: 1, server_count: 1, published_tool_count: 1, max_published_tools_per_server: 10, max_published_tools_global: 20 }
    return view('Mcp')
  }
  it('routes server actions, loads tools only on expansion, and respects delete cancellation', async () => {
    const v = await fixture()
    const availability = v.root.findAll((n) => n.props.role === 'switch' && n.props['aria-label'] === 'Turn off tools')[0]!
    availability.fire('change', { target: { checked: false } }); expect(actions.setMcpEnabled).toHaveBeenCalledWith('tools', false)
    await v.root.named('Reconnect tools').fire('click'); expect(actions.reconnectMcp).toHaveBeenCalledWith('tools')
    await v.root.named('Refresh tools for tools').fire('click'); expect(actions.refreshMcpTools).toHaveBeenCalledWith('tools')
    v.root.named('Tools for tools').fire('click'); await flush(); expect(actions.loadMcpTools).toHaveBeenCalledTimes(1)
    v.root.named('Hide tools for tools').fire('click'); await flush(); expect(actions.loadMcpTools).toHaveBeenCalledTimes(1)
    ask.mockResolvedValueOnce(false); await v.root.named('Remove tools…').fire('click'); expect(actions.deleteMcp).not.toHaveBeenCalled()
    await v.root.named('Remove tools…').fire('click'); expect(actions.deleteMcp).toHaveBeenCalledWith('tools')
    const global = v.root.findAll((h) => h.tag === 'input' && h.props.type === 'checkbox')[0]!; global.checked = false; global.fire('change'); expect(actions.setMcpGlobal).toHaveBeenCalledWith(false)
    field(v.root, 'Maximum tools per server').type('12')
    field(v.root, 'Maximum tools in all').type('40')
    await flush()
    expect((v.setup.limits as { perServer: unknown }).perServer).toBe(12)
    await v.root.button('Save limits').fire('click'); expect(actions.setMcpLimits).toHaveBeenCalledWith({ max_published_tools_per_server: 12, max_published_tools_global: 40 })
  })
  it('rejects invalid timeout, submits a typed patch, retains newer edits, and closes an unchanged successful form', async () => {
    const v = await fixture()
    await invoke(v, 'save'); expect(actions.saveMcp).not.toHaveBeenCalled()
    v.root.named('Edit tools').fire('click'); await flush()
    field(v.root, 'Timeout, in seconds').type('0'); await flush(); await v.root.named('Save MCP server tools').fire('click'); await flush()
    expect(actions.saveMcp).not.toHaveBeenCalled(); expect(v.setup.formError).toBeTruthy()
    field(v.root, 'Timeout, in seconds').type('15'); await flush(); expect(v.setup.formError).toBe('')
    v.root.button('Add a header').fire('click'); v.root.button('Add a variable').fire('click'); await flush()
    field(v.root, 'Header name 1').type('X-Public'); field(v.root, 'Header value 1').type('fixture'); field(v.root, 'Variable name 1').type('MODE'); field(v.root, 'Variable value 1').type('test')
    const pending = deferred<boolean>(); actions.saveMcp!.mockReturnValueOnce(pending.promise)
    const saving = invoke(v, 'save'); const form = v.setup.form as any; form.url = 'https://newer.example'
    pending.resolve(true); await saving; expect(v.setup.form).toBe(form)
    expect(actions.saveMcp).toHaveBeenCalledWith({ name: 'tools', create: false, transport: 'http', timeout_seconds: 15, headers_set: { 'X-Public': 'fixture' }, env_set: { MODE: 'test' } })
    await invoke(v, 'save'); await flush(); expect(v.setup.form).toBeNull()
    v.root.button('Add server').fire('click'); await flush(); field(v.root, 'Name').type('stdio_fixture'); field(v.root, 'Executable').type('/fixture/mcp'); field(v.root, 'Arguments, one per line', 'textarea').type('--test\n--safe')
    await v.root.named('Add MCP server').fire('click'); expect(actions.saveMcp).toHaveBeenLastCalledWith({ name: 'stdio_fixture', create: true, transport: 'stdio', command: '/fixture/mcp', args: ['--test', '--safe'] })
  })
})

describe('B3 Skills: typed configuration and action routing', () => {
  it('preserves enum types, parses numeric fields, and confirms deletion before dispatch', async () => {
    const { management } = await import(paths.management)
    management.skills = [{ name: 'fixture', description: 'Fixture', status: 'loaded', version: '1' }]
    management.editor = { name: 'fixture', code: 'original', create: false }
    management.skill = { name: 'fixture', metadata: { config_schema: { properties: { count: { type: 'integer' }, enabled: { type: 'boolean' }, mode: { enum: [1, 2] }, title: { type: 'string' } } } } }
    management.skillConfig = { count: 1, enabled: false, mode: 1, title: 'old' }
    const v = await view('Skills')
    field(v.root, 'count').type('7'); const checkbox = field(v.root, 'enabled'); checkbox.checked = true; checkbox.fire('change'); field(v.root, 'mode', 'select').choose(1); field(v.root, 'title').type('new')
    v.root.named('Save settings for fixture').fire('click'); expect(actions.saveSkillConfig).toHaveBeenCalledWith('fixture', { count: 7, enabled: true, mode: 2, title: 'new' })
    v.root.named('Validate skill fixture').fire('click'); expect(actions.validateSkill).toHaveBeenCalledWith('original')
    v.root.named('Save skill fixture').fire('click'); expect(actions.saveSkill).toHaveBeenCalled()
    v.root.named('Open fixture').fire('click'); expect(actions.openSkill).toHaveBeenCalledWith('fixture')
    const availability = v.root.findAll((n) => n.props.role === 'switch' && n.props['aria-label'] === 'Turn off fixture')[0]!
    availability.fire('change', { target: { checked: false } }); expect(actions.setSkillEnabled).toHaveBeenCalledWith('fixture', false)
    v.root.findAll((h) => h.tag === 'button' && h.props['aria-label'] === 'Test fixture')[0]!.fire('click'); expect(actions.testSkill).toHaveBeenCalledWith('fixture')
    ask.mockResolvedValueOnce(false); await v.root.named('Delete fixture…').fire('click'); expect(actions.deleteSkill).not.toHaveBeenCalled()
    await v.root.named('Delete fixture…').fire('click'); expect(actions.deleteSkill).toHaveBeenCalledWith('fixture')
    v.root.named('Cancel skill changes').fire('click'); await flush(); expect(management.editor).toBeNull()
    v.root.button('New skill').fire('click'); await flush(); expect(management.editor.create).toBe(true)
    const code = v.root.findAll((h) => h.props.id === 'skill-code')[0]!; code.type('edited fixture code'); await flush()
    v.root.named('Validate skill code').fire('click'); expect(actions.validateSkill).toHaveBeenLastCalledWith('edited fixture code')
  })
})

describe('B3 State: file import, edits and destructive confirmations', () => {
  async function fixture() {
    const { stateStore } = await import(paths.state)
    stateStore.memory = { global: { count: 1 }, user_1: { count: 0 }, team: { count: 0 } }
    stateStore.lists = [{ name: 'Tasks', count: 2, updated_at: '2026-10-07T00:00:00Z' }]
    stateStore.knowledge = [{ source: 'runbook.md', chunks: 1, ingested_at: '2026-10-07T00:00:00Z' }]
    return { v: await view('State'), stateStore }
  }
  it('loads and closes scopes/lists/versions, trims saved keys, and does not destroy data without approval', async () => {
    const { v, stateStore } = await fixture()
    v.root.named('Open Everywhere memory').fire('click'); await flush(); expect(actions.openScope).toHaveBeenCalledWith('global')
    stateStore.memoryEntries.global = { fixture: { foo: 'bar' } }; await flush()
    v.root.named('Edit fixture in Everywhere memory').fire('click'); await flush()
    expect(field(v.root, 'Value', 'input').value).toBe('{"foo":"bar"}')
    const key = v.root.findAll((h) => h.props['aria-label'] === 'Key in Everywhere memory')[0]!; key.type('  clean  ')
    await v.root.named('Save Everywhere memory entry').fire('click'); await flush()
    expect(actions.setMemory).toHaveBeenCalledWith('global', 'clean', '{"foo":"bar"}'); expect((v.setup.drafts as any).global).toBeUndefined()
    await invoke(v, 'saveEntry', 'global'); expect(actions.setMemory).toHaveBeenCalledTimes(1)
    await invoke(v, 'removePicked', 'global'); expect(actions.deleteMemory).not.toHaveBeenCalled()
    ;(v.setup.picked as any).global = ['fixture']; ask.mockResolvedValueOnce(false); await invoke(v, 'removePicked', 'global'); expect(actions.deleteMemory).not.toHaveBeenCalled()
    await invoke(v, 'removePicked', 'global'); expect(actions.deleteMemory).toHaveBeenCalledWith('global', ['fixture']); expect((v.setup.picked as any).global).toEqual([])
    v.root.named('Close Everywhere memory').fire('click'); await flush(); expect(stateStore.memoryEntries.global).toBeUndefined()
    v.root.named('Open list Tasks').fire('click'); expect(actions.openList).toHaveBeenCalledWith('Tasks')
    stateStore.listItems.Tasks = [{ name: 'finished', done: true }, { x: 1 }, 'plain']; await flush()
    expect(v.root.findAll((h) => h.props.id === 'named-list-Tasks')[0]!.findAll((h) => h.tag === 'li').map((h) => h.textContent())).toEqual(['Done: finished', '{"x":1}', 'plain'])
    v.root.named('Close list Tasks').fire('click'); expect(stateStore.listItems.Tasks).toBeUndefined()
    ask.mockResolvedValueOnce(false); await v.root.named('Delete list Tasks…').fire('click'); expect(actions.deleteList).not.toHaveBeenCalled()
    await v.root.named('Delete list Tasks…').fire('click'); expect(actions.deleteList).toHaveBeenCalledWith('Tasks')
    v.root.named('Versions for runbook.md').fire('click'); expect(actions.loadVersions).toHaveBeenCalledWith('runbook.md')
    stateStore.versions['runbook.md'] = [{ id: 'v', version: 2, action: 'update', created_at: '2026-10-07', diff_summary: 'Updated' }]; await flush()
    v.root.named('Restore runbook.md version 2').fire('click'); expect(actions.restoreVersion).toHaveBeenCalledWith('runbook.md', 2)
    v.root.named('Hide versions for runbook.md').fire('click'); expect(stateStore.versions['runbook.md']).toBeUndefined()
    v.root.named('Re-ingest runbook.md').fire('click'); expect(actions.reingest).toHaveBeenCalledWith('runbook.md')
    ask.mockResolvedValueOnce(false); await v.root.named('Delete source runbook.md…').fire('click'); expect(actions.deleteSource).not.toHaveBeenCalled()
    await v.root.named('Delete source runbook.md…').fire('click'); expect(actions.deleteSource).toHaveBeenCalledWith('runbook.md')
  })
  it('reads a text file without replacing the chosen source and clears only successfully ingested unchanged text', async () => {
    const { v } = await fixture()
    await invoke(v, 'readFile', { target: {} }); expect(v.setup.content).toBe('')
    const file = { name: 'import.md', text: vi.fn(async () => 'file contents') }
    await invoke(v, 'readFile', { target: { files: [file] } }); expect([v.setup.source, v.setup.content]).toEqual(['import.md', 'file contents'])
    v.setup.source = 'chosen.md'; await invoke(v, 'readFile', { target: { files: [file] } }); expect(v.setup.source).toBe('chosen.md')
    actions.ingest!.mockResolvedValueOnce(false); await invoke(v, 'add'); expect(v.setup.content).toBe('file contents')
    await invoke(v, 'add'); expect([v.setup.source, v.setup.content]).toEqual(['', ''])
    await invoke(v, 'add'); expect(actions.ingest).toHaveBeenCalledTimes(2)
    const search = field(v.root, 'Search'); search.type('needle'); expect(actions.searchKnowledge).toHaveBeenCalledWith('needle')
    v.root.button('Reload context').fire('click'); expect(actions.reloadContext).toHaveBeenCalled()
  })
})

describe('B3 Codex accounts: refresh admission, login and confirmation', () => {
  async function fixture() {
    const { settings } = await import(paths.settings)
    const account = { index: 0, account_id: 'fixture', email: 'a@example.com', label: 'First', plan_type: 'pro', is_current: false, quota: { primary: { used_percent: 10.1, window_minutes: 60 }, secondary: { used_percent: 20, window_minutes: 1440, resets_at: 1000 } } }
    settings.codex.status = { configured: true, accounts: [account] }
    return { v: await component('CodexAccounts'), settings, account }
  }
  it('trims account labels, asks before removing, copies only waiting login codes and records verification failures', async () => {
    const { v, settings, account } = await fixture()
    ask.mockResolvedValueOnce('  Work  '); await v.root.named('Rename First').fire('click'); expect(actions.labelAccount).toHaveBeenCalledWith(account, 'Work')
    ask.mockResolvedValueOnce(false); await v.root.named('Remove First').fire('click'); expect(actions.removeAccount).not.toHaveBeenCalled()
    await v.root.named('Remove First').fire('click'); expect(actions.removeAccount).toHaveBeenCalledWith(account)
    v.root.named('Use this account: First').fire('click'); expect(actions.activateAccount).toHaveBeenCalledWith(account)
    await invoke(v, 'copyCode'); expect(bridge.copyText).not.toHaveBeenCalled()
    settings.codex.login = { status: 'waiting', code: 'fixture-code', url: 'https://example.com/verify' }; await flush()
    await v.root.button('Copy sign-in code').fire('click'); expect(bridge.copyText).toHaveBeenCalledWith('fixture-code'); expect(v.setup.copyStatus).toBeTruthy()
    settings.codex.login.code = 'next-code'; await flush(); expect(v.setup.copyStatus).toBe('')
    bridge.copyText!.mockResolvedValueOnce(refused); await invoke(v, 'copyCode'); expect(v.setup.copyStatus).toBe('Could not copy the sign-in code.')
    bridge.codexOpenVerification!.mockResolvedValueOnce({ ok: false, error: { message: 'Browser failed' } }); await invoke(v, 'openVerification'); expect(settings.codex.error).toBe('Browser failed')
    v.root.button('Stop waiting').fire('click'); expect(actions.stopLogin).toHaveBeenCalled()
    settings.codex.login.status = 'failed'; await flush(); v.root.button('Retry login').fire('click'); expect(actions.retryLogin).toHaveBeenCalled()
    settings.codex.login.status = 'stopped'; await flush(); expect(v.setup.loginAnnouncement).toContain('Stopped waiting')
    settings.codex.login = { status: 'done', message: 'fixture complete' }; await flush(); expect(v.setup.loginAnnouncement).toBe('fixture complete')
    expect(invoke(v, 'quota', { quota: { primary: { used_percent: 30, window_minutes: 10080 } } })).toContain('30% of the weekly')
    expect(invoke(v, 'quota', {})).toBe('Quota not reported yet')
  })
  it('refreshes only the current identity, preserves unknown outcome admission, and responds to late refusal', async () => {
    const { v, settings, account } = await fixture()
    await invoke(v, 'refreshAccount', { ...account, account_id: 'replaced' }); expect(bridge.codexRefresh).not.toHaveBeenCalled()
    bridge.codexRefresh!.mockResolvedValueOnce({ ok: false, error: { code: 'no_receipt', disposition: 'outcome_unknown', command_id: 'refresh-1', message: 'Pending' } })
    await v.root.named('Refresh sign-in: First').fire('click'); await flush()
    expect(bridge.codexRefresh).toHaveBeenCalledExactlyOnceWith({ index: 0 }); expect(settings.codex.busy).toBe(true)
    await invoke(v, 'refreshAccount', account); expect(bridge.codexRefresh).toHaveBeenCalledTimes(1)
    late({ id: 'other', settled: refused }); expect(v.setup.refreshUnavailable).toBe(false)
    late({ id: 'refresh-1', settled: { ok: false, error: { disposition: 'outcome_unknown' } } }); expect(v.setup.refreshUnavailable).toBe(false)
    late({ id: 'refresh-1', settled: refused }); expect(v.setup.refreshUnavailable).toBe(true)
  })
  it('refresh success reloads accounts and releases busy, and a missing refresh route is never dispatched', async () => {
    const { v, settings, account } = await fixture()
    await invoke(v, 'refreshAccount', account); expect(actions.loadCodex).toHaveBeenCalledTimes(2); expect(settings.codex.busy).toBe(false); expect(settings.codex.stale).toBe(false)
    delete bridge.codexRefresh; await invoke(v, 'refreshAccount', account); expect(v.setup.refreshUnavailable).toBe(true)
  })
})

describe('B3 Composer: submission, shortcuts and attachment routing', () => {
  async function fixture() {
    vi.doMock(paths.composer, async (original) => {
      const real = await original<typeof import('../../src/renderer/src/stores/composer')>()
      return { ...real,
        edit: fn('edit').mockImplementation((text) => { real.box.text = text }),
        showDraft: fn('showDraft').mockImplementation(async (id) => { real.box.owner = id }),
        sendBox: fn('sendBox').mockImplementation(async (_id, send) => send(real.box.text, [{ ref: 'file-ref', add_to_knowledge: true }])),
        runBoxCommand: fn('runBoxCommand').mockImplementation(async (run) => run()),
        ...Object.fromEntries(['addFiles', 'addPasted', 'pickFiles', 'removeAttachment', 'setKnowledge'].map((name) => [name, fn(name)]))
      }
    })
    vi.doMock('../../src/renderer/src/commands', async (original) => ({ ...await original<typeof import('../../src/renderer/src/commands')>(), dispatch: fn('dispatch') }))
    const { state } = await import(paths.store)
    const composerStore = await import(paths.composer)
    state.activeId = 'c1'; state.app.link = 'ready'; state.views.c1 = { running: null }
    composerStore.box.owner = 'c1'; composerStore.box.text = 'body'
    const v = await component('Composer')
    return { v, state, composerStore }
  }
  it('sends the current box once with queue/steer mode and refuses busy or unready submission', async () => {
    const { v, state } = await fixture()
    const sent = deferred<boolean>(); actions.send!.mockReturnValueOnce(sent.promise)
    const submitting = invoke(v, 'submit'); expect(v.setup.busy).toBe(true)
    await invoke(v, 'submit'); expect(actions.sendBox).toHaveBeenCalledTimes(1)
    expect(actions.send).toHaveBeenCalledWith('body', 'queue', [{ ref: 'file-ref', add_to_knowledge: true }])
    sent.resolve(true); await submitting; expect(v.setup.busy).toBe(false)
    state.views.c1.running = { request_id: 'r', generation: 1 }; await flush()
    v.setup.mode = 'steer'; await invoke(v, 'submit'); expect(actions.send).toHaveBeenLastCalledWith('body', 'steer', expect.any(Array))
    v.setup.mode = 'queue'; await invoke(v, 'submit'); expect(actions.send).toHaveBeenLastCalledWith('body', 'queue', expect.any(Array))
    actions.canAct!.mockReturnValue(false); state.activeId = 'c2'; await flush()
    expect(v.setup.canSend).toBe(false)
    await invoke(v, 'submit'); expect(actions.send).toHaveBeenCalledTimes(3)
  })
  it('cycles suggestions, completes without a focus trap, dispatches selected commands and ignores IME/newline keys', async () => {
    const { v } = await fixture()
    const text = v.root.find('textarea')!; text.type('/'); await flush()
    const matches = v.setup.matches as any[]; expect(matches.length).toBeGreaterThan(2)
    const preventDefault = vi.fn()
    text.fire('keydown', { key: 'ArrowUp', preventDefault }); expect(v.setup.selected).toBe(matches.length - 1)
    text.fire('keydown', { key: 'ArrowDown', preventDefault }); expect(v.setup.selected).toBe(0)
    text.fire('keydown', { key: 'End', preventDefault }); expect(v.setup.selected).toBe(matches.length - 1)
    text.fire('keydown', { key: 'Home', preventDefault }); expect(v.setup.selected).toBe(0)
    const before = preventDefault.mock.calls.length
    text.fire('keydown', { key: 'Enter', isComposing: true, preventDefault }); text.fire('keydown', { key: 'Enter', shiftKey: true, preventDefault })
    expect(preventDefault).toHaveBeenCalledTimes(before); expect(actions.dispatch).not.toHaveBeenCalled()
    await invoke(v, 'pick', 1); expect(actions.dispatch).toHaveBeenCalledWith(matches[1], '')
    v.setup.busy = true; await invoke(v, 'runCommand'); expect(actions.dispatch).toHaveBeenCalledTimes(1); v.setup.busy = false
    text.type('/status detail'); await flush(); await invoke(v, 'submit'); expect(actions.dispatch).toHaveBeenLastCalledWith(expect.objectContaining({ name: 'status' }), 'detail')
    text.type('/sta'); await flush(); text.fire('keydown', { key: 'Tab', shiftKey: false, preventDefault }); await flush(); expect(v.setup.text).toBe('/status '); expect(v.setup.paletteOpen).toBe(false)
    text.type('/'); await flush(); text.fire('keydown', { key: 'Escape', preventDefault }); await flush(); expect(v.setup.paletteOpen).toBe(false); expect(v.setup.text).toBe('/')
    text.type('body'); await flush(); text.fire('keydown', { key: '.', ctrlKey: true, preventDefault }); expect(actions.stop).toHaveBeenCalledTimes(1)
  })
  it('routes drops, pastes, picks and attachment controls only to the active chat owner', async () => {
    const { v, state, composerStore } = await fixture()
    const files = [{ name: 'fixture.txt' }]; const preventDefault = vi.fn()
    await invoke(v, 'onDrop', { dataTransfer: { files } }); expect(actions.addFiles).toHaveBeenCalledWith('c1', files); expect(v.setup.dragging).toBe(false)
    await invoke(v, 'onPaste', { clipboardData: { files }, preventDefault }); expect(actions.addPasted).toHaveBeenCalledWith('c1', files); expect(preventDefault).toHaveBeenCalledTimes(1)
    await invoke(v, 'onPaste', { clipboardData: { files: [] }, preventDefault }); expect(preventDefault).toHaveBeenCalledTimes(1)
    v.root.named('Attach files').fire('click'); expect(actions.pickFiles).toHaveBeenCalledWith('c1')
    composerStore.composer.attachments.c1 = [{ id: 'a', name: 'fixture.txt', status: 'ready', size: 2, sent: 2, mime: 'text/plain', addToKnowledge: false }]; await flush()
    const checkbox = v.root.findAll((h) => h.props['aria-label'] === 'Add fixture.txt to knowledge')[0]!; checkbox.checked = true; checkbox.fire('change'); expect(actions.setKnowledge).toHaveBeenCalledWith('c1', 'a', true)
    await invoke(v, 'onRemove', 'a'); expect(actions.removeAttachment).toHaveBeenCalledWith('c1', 'a')
    actions.chatUnavailable!.mockReturnValue(true)
    await invoke(v, 'onDrop', { dataTransfer: { files } }); await invoke(v, 'onPaste', { clipboardData: { files }, preventDefault }); await invoke(v, 'attach')
    expect(actions.addFiles).toHaveBeenCalledTimes(1); expect(actions.addPasted).toHaveBeenCalledTimes(1); expect(actions.pickFiles).toHaveBeenCalledTimes(1)
    state.activeId = null; await flush(); await invoke(v, 'onRemove', 'a'); await invoke(v, 'onKnowledge', 'a', false)
    expect(actions.removeAttachment).toHaveBeenCalledTimes(1); expect(actions.setKnowledge).toHaveBeenCalledTimes(1)
  })
  it('stops once, restores message focus after stop removal, and closes the report with focus restoration', async () => {
    const { v, state } = await fixture()
    state.views.c1.running = { request_id: 'r', generation: 1 }; await flush()
    const button = { isConnected: false }
    Object.assign(document, { activeElement: button })
    actions.stop!.mockImplementation(async () => { Object.assign(document, { activeElement: document.body }); state.views.c1.running = null })
    await invoke(v, 'stopTask', { currentTarget: button }); expect(actions.stop).toHaveBeenCalledTimes(1); expect(query).toHaveBeenCalledWith('textarea[aria-label="Message"]'); expect(actions.focus).toHaveBeenCalled()
    state.panel = { title: 'fixture', text: 'private report' }; await flush()
    await v.root.named('Close command report').fire('click'); expect(state.panel).toBeNull(); expect(actions.focus).toHaveBeenCalledTimes(2)
  })
})

describe('B3 App shell: keyboard ownership and focus transitions', () => {
  async function fixture() {
    for (const name of ['ConversationList', 'MessageList', 'Composer', 'SearchPanel', 'StatusBar', 'WorkPanel', 'ConfirmDialog', 'CleanupNotice', 'IconRail', 'ChatStatus', 'FirstRunBanner']) vi.doMock(`../../src/renderer/src/components/${name}.vue`, () => ({ default: { render: () => null } }))
    vi.doMock('../../src/renderer/src/views/Settings.vue', () => ({ default: { render: () => null } }))
    const { state } = await import(paths.store); const { dialog } = await import(paths.dialog)
    state.view = 'chat'
    actions.openSettings!.mockImplementation(() => { state.view = 'settings' })
    const v = mount((await import('../../src/renderer/src/App.vue')).default); mounted.push(v); await flush()
    return { v, state, dialog }
  }
  it('routes keyboard shortcuts only outside modals and unregisters the exact listener on unmount', async () => {
    const { v, state, dialog } = await fixture()
    expect(actions.init).toHaveBeenCalledTimes(1)
    const listener = actions.addListener!.mock.calls[0]![1]
    const preventDefault = vi.fn()
    listener({ ctrlKey: true, shiftKey: true, key: 'F', preventDefault }); expect(state.search.open).toBe(true)
    listener({ ctrlKey: true, shiftKey: true, key: 'f', preventDefault }); expect(state.search.open).toBe(false)
    listener({ ctrlKey: true, key: ',', preventDefault }); await flush(); expect(state.view).toBe('settings'); expect(actions.openSettings).toHaveBeenCalledTimes(1)
    listener({ ctrlKey: true, key: ',', preventDefault }); await flush(); expect(state.view).toBe('chat')
    dialog.current = {}; listener({ ctrlKey: true, key: ',', preventDefault }); expect(state.view).toBe('chat'); expect(preventDefault).toHaveBeenCalledTimes(4)
    v.unmount(); mounted.splice(mounted.indexOf(v), 1); expect(actions.removeListener).toHaveBeenCalledExactlyOnceWith('keydown', listener)
  })
  it('restores a connected settings opener but leaves work and rail navigation focus alone', async () => {
    const { state } = await fixture()
    const opener = Object.assign(new HTMLElement(), { isConnected: true, focus: vi.fn(), closest: vi.fn(() => null) })
    Object.assign(document, { activeElement: opener })
    state.view = 'settings'; await flush(); expect(query).toHaveBeenCalledWith('.settings-nav .back')
    Object.assign(document, { activeElement: null }); state.view = 'chat'; await flush(); expect(opener.focus).toHaveBeenCalledTimes(1)
    Object.assign(document, { activeElement: opener }); state.view = 'settings'; await flush()
    opener.closest.mockReturnValue({} as any); query.mockClear(); state.view = 'chat'; await flush(); expect(query).not.toHaveBeenCalled(); expect(opener.focus).toHaveBeenCalledTimes(1)
  })
})
