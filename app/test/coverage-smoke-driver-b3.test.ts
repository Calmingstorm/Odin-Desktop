// Executes the actual driver against an inert, stateful port model. This is
// orchestration coverage, not native/Vue/provider qualification. No port can
// access a display, process, network, real filesystem, or live core.
import { EventEmitter } from 'node:events'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { dialog } from 'electron'
import { realCoreCapabilities, realCoreSmoke } from '../src/main/real-core-smoke'

const ports = vi.hoisted(() => ({ files: new Map<string, string | Buffer>(), read: vi.fn(), write: vi.fn(), exists: vi.fn(), link: vi.fn(), open: vi.fn(), save: vi.fn() }))
vi.mock('node:fs', () => ({ readFileSync: ports.read, writeFileSync: ports.write, existsSync: ports.exists, readlinkSync: ports.link }))
vi.mock('electron', () => ({ dialog: { showOpenDialog: ports.open, showSaveDialog: ports.save } }))
const root = '/tmp/odrc-inert-driver', out = root + '/result.png'
const sections = ['General', 'Models and providers', 'Personality', 'Tools', 'Skills', 'MCP servers', 'Hosts and access', 'Work', 'Data and privacy']
const missing = 'No LLM provider available. Please try again later.'
const submission = 'real-core smoke unavailable provider check'
const skillCode = 'inert constant fixture, never evaluated'
const ok = (result: any) => ({ ok: true, result })
const rejected = (code: string, message = code) => ({ ok: false, error: { code, message } })

beforeEach(() => {
  vi.clearAllMocks(); vi.useFakeTimers(); ports.files.clear()
  vi.stubEnv('HOME', root); vi.stubEnv('ODIN_REAL_CORE_ROOT', root)
  vi.stubEnv('ODIN_REAL_CORE_OUTER_PID_NS', 'outer'); vi.stubEnv('ODIN_SMOKE_REAL_CORE', '1')
  vi.stubEnv('ODIN_SMOKE_WORK_PROOF', '0'); vi.stubEnv('ODIN_SMOKE_PROVIDER_BASE_URL', '')
  vi.stubEnv('ODIN_SMOKE_SKILL_FIXTURE', root + '/skill'); vi.stubEnv('ODIN_SMOKE_MCP_FIXTURE', root + '/mcp')
  vi.stubEnv('ODIN_DESKTOP_ENGINE_PYTHON', '/inert/python'); vi.stubEnv('ODIN_SMOKE_EXPECT_VERSION', '0.1.0.dev1')
  vi.spyOn(process, 'getuid').mockReturnValue(1000)
  vi.spyOn(process, 'stdout', 'get').mockReturnValue({ write: vi.fn() } as any)
  vi.spyOn(process, 'argv', 'get').mockReturnValue(['node', '--smoke-test'])
  ports.link.mockReturnValue('private')
  ports.files.set('/proc/1/cmdline', 'node\0--inside-run\0')
  ports.files.set(root + '/skill', skillCode)
  ports.files.set(root + '/resume-seed.json', JSON.stringify({ request_id: 'r_seed', message_id: 'm_seed' }))
  ports.read.mockImplementation((path: string, encoding?: string) => {
    const value = ports.files.get(path)
    if (value === undefined) throw new Error('Unmodeled disk read: ' + path)
    return encoding ? String(value) : Buffer.from(value)
  })
  ports.write.mockImplementation((path: string, value: string | Buffer) => { ports.files.set(path, value) })
  ports.exists.mockImplementation((path: string) => ports.files.has(path))
})
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals() })

function fixture(provider = false, seeded = false, fault = '') {
  if (provider) vi.stubEnv('ODIN_SMOKE_PROVIDER_BASE_URL', 'http://127.0.0.1:43210')
  if (seeded) {
    vi.stubEnv('ODIN_SMOKE_WORK_PROOF', '1')
    ports.files.set(root + '/work-proof.json', JSON.stringify({ conversation_id: 'c_chat', report_id: 'report', recovery_id: 'recovery' }))
    for (const name of ['background', 'report']) ports.files.set(root + '/' + name + '-effects', 'one\n')
  }
  let section = '', input = '', search = '', mode = 'normal', dialogKind = '', title = 'Chat'
  let compat = false, modelConfigured = false, resumePending = provider, attached = false
  let skill = false, skillRuns = 0, mcp = false, mcpEnabled = false, revision = 0
  let outputPages = 0, reportPage = 0, cancelled = false, ingressEnabled = false, secret = '', sourceSecret = ''
  let webhookRow: any, nextId = 0
  let running: any = null, queued: any[] = []
  const messages: any[] = provider ? [{ id: 'm_seed', role: 'user', text: 'Preserved request', request_id: 'r_seed' }] : []
  const recent: any[] = [], histories: any[] = [], webhookMessages: any[] = [], clicks: string[] = [], operations: any[] = [], journal = new Map<string, any>()
  const conversations = [{ id: 'c_chat', title: 'Chat' }]
  const schema = () => ({ revision: String(revision), fields: [{ path: 'timezone' }, ...(fault === 'unknown-curated-log' ? [] : [{ path: 'logging.level' }])] })
  const computer = { session: null, readiness: { management_available: true, foreground_available: false, native_qualified: false, input_supported: false, dispatch: 'none' } }
  const mcpStatus = () => ({ revision: String(revision), servers: mcp ? [{ name: 'slice4_local', state: mcpEnabled ? 'connected' : 'disabled', published_count: 1 }] : [], configured_servers: mcp ? ['slice4_local'] : [], server_count: mcp ? 1 : 0, configured_server_count: mcp ? 1 : 0, connected_count: mcp && mcpEnabled ? 1 : 0, published_tool_count: mcp && mcpEnabled ? 1 : 0, started: true, closed: false })
  const ingress = () => ({ reason: !ingressEnabled ? 'disabled' : sourceSecret ? 'accepting' : 'no_eligible_schedule', address: ingressEnabled && sourceSecret ? ['127.0.0.1', 43211] : null, eligible_schedules: sourceSecret ? 1 : 0, unknown_deliveries: 0 })
  const status = () => ({ phase: 'ready', version: '0.1.0.dev1', core_instance_id: 'core-inert', capabilities: realCoreCapabilities,
    model: modelConfigured ? { main: 'canned-contract', effort: null, provider: 'compat' } : { main: 'gpt-6.1-sol', effort: null, provider: 'codex' },
    providers: [{ name: 'codex', health: 'unavailable' }, { name: 'ollama', health: 'disabled' }, { name: 'compat', health: 'disabled' }],
    limits: { chunk_bytes: 524288, attachment_bytes: 52428800, attachments_per_turn: 10 }, summary: 'Codex: unavailable',
    first_run: seeded ? { state: 'fresh', reason: 'provider_not_configured', keyring_unavailable: false } : { state: 'degraded', reason: 'keyring_unavailable', keyring_unavailable: true }, webhook_ingress: ingress() })
  const snapshot = () => ({ messages: { items: messages }, running, queued, recent, unresolved: [] })
  const workItems = ['agent', 'task', 'workflow', 'loop', 'process', 'schedule'].map((kind, index) => ({ kind, id: 'w_' + index, manager_generation: 1, run_id: 'run', generation: 1, conversation_id: 'c_chat', title: kind === 'task' ? 'Harmless cancellable task' : kind }))
  const core: any = new EventEmitter()
  core.linkState = 'ready'; core.coreInstanceId = 'core-inert'
  const event = (type: string, payload: any) => core.emit('event', { type, payload })
  const complete = (request: any, outcome = 'completed') => { recent.push({ ...request, outcome, unknown_effects: 0 }); running = null }
  const reply = (request: any, text: string, role = 'assistant', extras = {}) => messages.push({ id: 'm_' + (++nextId).toString(16), role, text, request_id: fault === 'wrong-reply-owner' && role === 'assistant' ? 'r_wrong' : request.request_id, ...extras })
  const submit = () => {
    operations.push(['submit', input, mode]); const value = input; input = ''
    if (value === '/status' || value === '/usage') return
    if (resumePending && value === 'continue') {
      resumePending = false; const request = { request_id: 'r_seed', generation: 2, conversation_id: 'c_chat' }
      event('request.started', request); complete(request); return
    }
    if (mode === 'steer') { operations.push(['steer', running.request_id, value]); return }
    const request = { request_id: 'r_' + (++nextId).toString(16), generation: 1, conversation_id: conversations.at(-1)!.id }
    const user: any = { id: 'm_' + (++nextId).toString(16), role: 'user', text: value, request_id: request.request_id }
    if (attached) { user.attachments = [{ name: 'smoke-upload.txt' }]; attached = false }
    messages.push(user)
    if (mode === 'queue') { queued.push(request); event('request.queued', request); return }
    if (value.startsWith('[hold-')) { running = request; return }
    if (!provider || !compat) { reply(request, missing, 'notice'); complete(request, 'failed'); return }
    if (value === '[fail]') { reply(request, 'LLM API error canned_failure'); complete(request, 'failed'); return }
    if (value === '[artifact]') reply(request, 'artifact', 'assistant', { artifacts: ['contract.txt', 'image.png'] })
    else reply(request, 'Canned provider reply: ' + value)
    complete(request)
  }
  core.request = vi.fn(async (method: string, params: any = {}) => {
    operations.push(['core', method, params])
    if (['turns.create', 'loops.list', 'agents.list', 'shell.execute', 'computer_act'].includes(method)) return rejected('capability_unavailable')
    switch (method) {
      case 'status.get': return ok(status())
      case 'settings.schema': return ok(schema())
      case 'observability.usage': return ok({ coverage: { backfill_complete: true } })
      case 'usage.get': return ok({ tokens: { value: 0, kind: 'measured' }, summary: '0 measured tokens' })
      case 'codex.accounts.list': return seeded || provider ? ok({ configured: false, accounts: [] }) : rejected('keyring_unavailable')
      case 'lists.list': return ok({ items: [] })
      case 'skills.list': return ok(skill ? [{ name: 'slice4_constant', total_executions: skillRuns }] : [])
      case 'mcp.list': case 'mcp.status': return ok(mcpStatus())
      case 'computer.status': return ok(computer)
      case 'work.list': return ok({ items: seeded ? workItems : [] })
      case 'schedules.list': return ok(webhookRow ? [webhookRow] : [])
      case 'schedules.history': return ok(histories)
      case 'audit.query': return ok([])
      case 'logs.search': return ok({ entries: [], count: 0 })
      case 'turn_state.list': return ok({ availability: 'available' })
      case 'conversations.list': return ok({ items: conversations })
      case 'conversation.snapshot': return ok(seeded && params.conversation_id === 'c_chat' ? { ...snapshot(), messages: { items: webhookMessages } } : snapshot())
      case 'messages.list': return ok({ items: messages })
      case 'search.query': return ok({ hits: messages.filter(m => m.text.includes(params.query)), next_cursor: null })
      case 'hosts.list': return ok({ hosts: [{ alias: 'localhost', trust_state: 'local' }], default_host: 'localhost' })
      case 'hosts.public_key': return ok('ssh-ed25519 inert')
      case 'tools.list': return ok({ tools: [{ name: 'run_command', cost: null, risk: null }] })
      case 'tools.timeouts.get': return ok({})
      case 'personality.get': case 'memory.list': case 'knowledge.list': return ok({})
      case 'health.get': return ok({ browser: { state: 'unavailable', ready: false, retry_available: true } })
      case 'audit.diffs': case 'audit.failures': case 'learned.list': return ok({ entries: [] })
      case 'audit.tail': case 'logs.tail': return ok({ lines: [], cursor: 'empty', availability: 'available' })
      case 'knowledge.duplicates': return ok({ exact: [], near: [] })
      case 'trajectories.list': return ok({ files: [] })
      case 'logs.stats': case 'observability.stats': case 'observability.risk': return ok({})
      case 'openrouter.catalogue': return rejected('not_found', 'Endpoint not recognized')
      case 'providers.compat.set': case 'providers.codex.set': case 'providers.auxiliary.set':
        expect(params.expected_revision).toBe(String(revision)); revision++
        if (method === 'providers.compat.set') for (const change of params.changes) if (change.path === 'openai_compatible.enabled') compat = change.value
        return ok({})
      case 'secrets.set': return ok({})
      case 'models.main.set': expect(params.expected_revision).toBe(String(revision)); modelConfigured = true; return ok({})
      case 'control.stop': case 'control.steer': return ok({ disposition: 'stale_binding' })
      case 'control.resume': return ok({ disposition: 'rejected', reason: 'stale_binding' })
      default: throw new Error('Unmodeled core method ' + method)
    }
  })
  const named: Record<string, string> = { status: 'status.get', settingsSchema: 'settings.schema', hostsList: 'hosts.list', hostsPublicKey: 'hosts.public_key', toolsList: 'tools.list', toolsTimeoutsGet: 'tools.timeouts.get', personalityGet: 'personality.get', memoryList: 'memory.list', listsList: 'lists.list', knowledgeList: 'knowledge.list', auditQuery: 'audit.query', logsSearch: 'logs.search', turnStateList: 'turn_state.list', usage: 'usage.get', codexAccounts: 'codex.accounts.list', listConversations: 'conversations.list', search: 'search.query', snapshotConversation: 'conversation.snapshot', auditDiffs: 'audit.diffs', auditFailures: 'audit.failures', logsStats: 'logs.stats', auditTail: 'audit.tail', logsTail: 'logs.tail', knowledgeDuplicates: 'knowledge.duplicates', learnedList: 'learned.list', observabilityStats: 'observability.stats', observabilityRisk: 'observability.risk', trajectoriesList: 'trajectories.list', openrouterCatalogue: 'openrouter.catalogue', skillsList: 'skills.list', mcpStatus: 'mcp.status', computerStatus: 'computer.status', healthGet: 'health.get', schedulesHistory: 'schedules.history' }
  const bridge = async (name: string, params: any = {}) => {
    operations.push(['bridge', name, params])
    if (named[name]) return core.request(named[name], params)
    if (name.startsWith('mcp')) {
      if (name === 'mcpTools') return ok({ tools: ['constant'] })
      expect(params.expected_revision).toBe(String(revision)); revision++
      if (name === 'mcpSave') mcp = true
      if (name === 'mcpDelete') mcp = false
      if (name === 'mcpSetGlobalEnabled') mcpEnabled = params.enabled
      return ok({})
    }
    switch (name) {
      case 'skillsValidate': return ok({ valid: params.code === skillCode })
      case 'skillsSave': skill = true; return ok({})
      case 'skillsGet': return ok({ code: skillCode })
      case 'skillsTest': skillRuns++; operations.push(['skill-execution', skillRuns]); return ok({ result: 'harmless constant', is_error: false })
      case 'skillsDelete': skill = false; return ok({})
      case 'resumeRequest': expect(params.request_id).toBe(recent.at(-1).request_id); return ok({ disposition: 'rejected', reason: 'not_resumable' })
      case 'createConversation': return ok({ conversation: { id: 'c_child', rev: 1, parent_id: params.parent_id, inherited_from: params.from_message_id } })
      case 'updateConversation': return ok({ conversation: { rev: params.expected_rev + 1, archived: params.archived } })
      case 'deleteConversation': return ok({})
      case 'workControl': {
        if (journal.has(params.control_command_id)) return journal.get(params.control_command_id)
        expect(params).toMatchObject({ kind: 'task', id: 'w_1', generation: 1, manager_generation: 1, run_id: 'run', action: 'cancel' })
        cancelled = true; operations.push(['cancel-effect']); const receipt = ok({ disposition: 'done' }); journal.set(params.control_command_id, receipt); return receipt
      }
      case 'schedulesSave': webhookRow = { ...params, id: 's_webhook' }; return ok(webhookRow)
      default: throw new Error('Unmodeled named method ' + name)
    }
  }
  vi.stubGlobal('fetch', vi.fn(async (url: any, init: any) => {
    operations.push(['http', String(url)])
    if (String(url).endsWith('/release')) {
      const held = running; complete(held); event('control.receipt', { request_id: held.request_id, disposition: 'consumed' })
      for (const request of queued) { reply(request, 'queued response'); recent.push({ ...request, outcome: 'completed' }) } queued = []
      return { ok: true }
    }
    if (!sourceSecret) throw new Error('inert listener closed')
    if (init.headers['X-Webhook-Secret'] !== sourceSecret) return { status: 403 }
    const body = JSON.parse(init.body); webhookMessages.push({ id: 'web_' + nextId++, role: 'notice', text: body.title })
    if (body.event === 'smoke-delivery') { histories.push({ status: 'success' }); webhookMessages.push({ id: 'rem_' + nextId++, role: 'notice', text: 'Real webhook schedule ran.' }) }
    return { status: 200, json: async () => ({ status: 'delivered' }) }
  }))
  const fullOutput = () => outputPages === 1 ? 'Evidence line 0000: first' : 'Evidence line 0000: first\nEvidence line 0899: last'
  const text = (selector: string): string => {
    if (selector === 'Advanced settings') return 'Advanced settings'
    if (['Save listener setup', 'Save trigger source and secret', 'Clear per-trigger secret'].includes(selector)) return selector
    if (selector === '.status') return '0.1.0.dev1'
    if (selector === '.conv.active .conv-title' || selector === '.conv-title') return title
    if (selector === '.message-scroll .msg.user .body' || selector === '.message-scroll .msg.highlight .body') return messages.find(m => m.role === 'user')?.text ?? ''
    if (selector === '.message-scroll .msg.notice .body') return missing
    if (selector === '.message-scroll .outcome') return 'The task failed.'
    if (selector === '.message-scroll') return messages.length ? messages.map(m => m.text).join('\n') + ' waiting for Odin' : seeded && title === 'Chat' ? 'Harmless catch-up notice Due: yesterday late by 1 Omitted slots: 1' : 'Ask Odin anything.'
    if (selector === '.composer .panel-text') return '0.1.0.dev1 0 measured tokens'
    if (selector === '.report-body') return reportPage ? 'no rerun' : 'produced once'
    if (selector === '.rail-link') return 'Connected'
    if (selector === '.work-panel') return seeded ? 'Harmless completed task Resource release is not confirmed ' + (cancelled ? 'cancelled' : '') : 'No work'
    if (selector === '.tool-output pre') return fullOutput()
    if (selector === '.tool-detail') return 'preview'
    if (selector === '.tool-output button') return outputPages > 1 ? 'All output loaded' : 'Load more'
    if (selector === '.msg-attachments') return 'smoke-upload.txt'
    if (selector === '.msg .file-card') return 'Saved contract.txt.'
    if (selector === '.search-panel .search-note') return messages.length ? '1 results.' : 'No matches.'
    if (selector === '.search-hits .hit-snippet') return submission
    if (selector === '.codex-accounts') return 'Add account ' + (seeded ? "Codex isn't configured." : 'keyring unavailable')
    if (selector === '.skill-editor .manage-json') return 'harmless constant'
    if (selector === '.mcp-tools') return 'constant'
    if (selector === 'pre[aria-label="Learned context JSON"]') return JSON.stringify({ entries: [] })
    if (selector === 'pre[aria-label="Knowledge duplicates JSON"]') return JSON.stringify({ exact: [], near: [] })
    if (/section\[aria-label="(?:Audit diffs|Audit failures|Log statistics)"\] pre/.test(selector)) return selector.includes('Log statistics') ? '{}' : '{"entries":[]}'
    if (selector === 'section[aria-label="Runtime statistics"] pre') return '{"risk":{}}'
    if (selector === '[data-testid="webhook-ingress-status"]') return !ingressEnabled ? 'Disabled' : sourceSecret ? 'Accepting' : 'Off: no eligible schedule'
    if (selector === '[data-testid="webhook-ingress-endpoint"]') return 'http://127.0.0.1:43211/webhook/generic/s_webhook'
    const panels: Record<string, string> = {
      Personality: 'preset personality', 'Built-in tools': 'run_command Cost: not reported. Risk: not reported.', 'Tool timeouts': 'Default seconds Timeouts',
      Skills: 'New skill slice4_constant ' + skillRuns + ' runs', MCP: '1 of 1 servers connected 1 tools offered', 'MCP servers': 'Add server slice4_local connected',
      Hosts: 'localhost', "Odin's key": 'ssh-ed25519 inert', Memory: '0 entries', 'Named lists': 'No lists.', Knowledge: 'Knowledge',
      Health: 'healthy degraded down not set up 1 host(s) configured', Usage: 'tokens in 7d (measured)',
      'Computer use': 'Refresh no session Foreground computer use is unavailable. Dispatch: none. Reason: computer disabled.', 'Browser runtime': 'unavailable', Context: 'Context reloaded context directory does not exist; nothing is loaded',
      Schedules: seeded ? 'D12 manual recovery check Recovery required No effects were replayed ' + (webhookRow?.description ?? '') : 'No schedules yet.',
      'Running work': 'Nothing is running.', Audit: 'Nothing recorded.', Logs: 'No entries.', 'Turn state': 'Preserved work',
      'OpenRouter models': 'OpenRouter endpoint not recognized', 'Audit diffs': 'Last successful read shown below.', 'Audit failures': 'Last successful read shown below.', 'Log statistics': 'Last successful read shown below.'
    }
    const panel = selector.match(/^section\[aria-label=(?:"([^"]+)"|([^\]]+))\]/)?.slice(1).find(Boolean)
    if (panel && panel in panels) {
      if (['Memory', 'Named lists', 'Knowledge', 'Context'].includes(panel) && section !== 'Data and privacy') throw new Error('State panel outside its Data and privacy owner')
      if (['Health', 'Usage', 'Computer use', 'Audit', 'Logs', 'Turn state', 'Audit diffs', 'Audit failures', 'Log statistics', 'Runtime statistics'].includes(panel) && section !== 'Usage, logs and audit') throw new Error('Records panel outside its Data and privacy subsection')
      if (selector.endsWith('.capability-unavailable')) return 'Foreground computer use is unavailable. Dispatch: none. Reason: computer disabled.'
      return panels[panel]!
    }
    if (selector === '.settings-body') return section === 'General' ? 'Start Odin when you log in' : section
    if (['body', '.main', 'nav[aria-label="Conversations"]', '.search-panel', '.composer', '.attachments', '[data-testid="webhook-ingress"]'].includes(selector)) return 'inert rendered ' + selector
    throw new Error('Unmodeled text ' + selector)
  }
  const absent = new Set(['.sidebar-notice', '#conversation-search-error', '.working, .msg.pending', '.message-scroll .msg.assistant', '.account', '.settings-body .warn', '.settings-body [role=alert]', '.settings-body .account', '.settings-body .work-item, .settings-body .account', 'section[aria-label="Computer use"] .manage-name, section[aria-label="Computer use"] .manage-actions', 'section[aria-label="Running work"] .work-item', 'section[aria-label="OpenRouter models"] li'])
  function size(selector: string): number {
    if (absent.has(selector)) return 0
    if (selector.endsWith(' .capability-unavailable')) return selector.startsWith('section[aria-label="Computer use"]') ? 1 : 0
    if (selector === '.conv-row') return conversations.length
    if (selector === '.msg') return seeded ? 2 : messages.length
    if (selector === '.search-hits li' || selector === '.search-hits .hit') return messages.length ? 1 : 0
    if (selector === '.settings-nav-item') return sections.length
    if (selector === '[id="settings-curated-timezone"]') return section === 'General' && fault !== 'missing-curated-timezone' ? 1 : 0
    if (selector === '[id="settings-curated-logging.level"]') return section === 'Advanced settings' ? 1 : 0
    if (selector === '.settings-subnav button:nth-of-type(2)') return section === 'Data and privacy' && fault !== 'missing-records-owner' ? 1 : 0
    if (selector === '.work-item') return seeded ? 6 : 0
    if (selector === '.composer button.danger') return running ? 1 : 0
    if (selector === '.first-run button') return 0
    if (selector === '.tool-output button:not([aria-disabled=true])') return outputPages === 1 ? 1 : 0
    if (selector === '[data-testid="webhook-ingress-endpoint"]') return sourceSecret ? 1 : 0
    return 1
  }
  const nodes = new Map<string, any>()
  function node(selector: string): any {
    if (!size(selector)) return null
    if (nodes.has(selector)) return nodes.get(selector)
    let value = selector === 'section[aria-label=Hosts] select' ? 'localhost' : '', checked = false
    const n: any = {
      get innerText() { return text(selector) }, get textContent() { return text(selector) }, set textContent(_value: string) {}, style: {},
      get value() { if (selector === '.composer textarea') return input; if (selector.includes('webhook-ingress-secret')) return secret; return value },
      set value(v: string) { value = v; if (selector === '.composer textarea') input = v; if (selector === '.search-form input') search = v; if (selector.includes('webhook-ingress-secret')) secret = v },
      get checked() { return checked }, set checked(v: boolean) { checked = v },
      get disabled() { return selector === '.composer button[type=submit]' ? !input : false }, complete: true, naturalWidth: 1,
      classList: { contains: () => false }, getAttribute: () => 'false', append: () => {},
      dispatchEvent: (e: any) => { if (e.type === 'submit' && selector === '.composer form') submit() },
      click: async () => {
        clicks.push(selector)
        if (selector === 'button[title="Settings (Ctrl+,)"]') section ||= 'General'
        else if (selector.includes('New conversation')) { conversations.push({ id: 'c_new', title: 'New chat' }); title = 'New chat' }
        else if (selector === '.composer button[type=submit]') submit()
        else if (selector === '.composer button.danger') { const stopped = running; operations.push(['stop', stopped.request_id]); complete(stopped, 'cancelled'); event('request.cancelled', stopped) }
        else if (selector.includes('input[value="queue"]')) mode = 'queue'
        else if (selector.includes('input[value="steer"]')) mode = 'steer'
        else if (selector === '.tool-output button') outputPages++
        else if (selector === '.report-nav button:nth-of-type(2)') reportPage++
        else if (selector.includes('Attach files')) { const choice = await dialog.showOpenDialog({}); expect(choice.filePaths).toEqual([root + '/smoke-upload.txt']); attached = true }
        else if (selector.includes('.file-actions')) { const choice = await dialog.showSaveDialog({}); ports.write(choice.filePath!, 'inert artifact bytes') }
        else if (selector === '.menu button:nth-child(5)') dialogKind = 'reset'
        else if (selector === '.menu button:first-child') dialogKind = 'rename'
        else if (selector === '.dialog button[type=submit]') { if (dialogKind === 'reset') messages.push({ id: 'reset', role: 'notice', text: 'Model context reset.' }); else title = node('.dialog input').value }
        else if (selector.startsWith('.settings-nav-item:nth-of-type')) section = sections[Number(selector.match(/\((\d+)\)/)![1]) - 2]!
        else if (selector === '.settings-subnav button:nth-of-type(2)' && section === 'Data and privacy') section = 'Usage, logs and audit'
        else if (selector === 'Advanced settings' && section === 'General') section = 'Advanced settings'
        else if (selector === 'button[aria-label="Test slice4_constant"]' || selector.includes('Test slice4_constant')) await bridge('skillsTest')
        else if (selector === '[data-testid="webhook-ingress-enabled"]') checked = !checked
        else if (selector === 'Save listener setup') ingressEnabled = true
        else if (selector === 'Save trigger source and secret') { sourceSecret = secret; secret = '' }
        else if (selector === 'Clear per-trigger secret') sourceSecret = ''
      }
    }; nodes.set(selector, n); return n
  }
  const document = {
    querySelector: node,
    querySelectorAll: (selector: string): any[] => {
      if (selector === '.settings-nav-item') return sections.map(label => ({ innerText: label }))
      if (selector.includes('.settings-body .field-path')) return section === 'General' ? [{ id: 'settings-curated-timezone' }] : section === 'Advanced settings' ? [{ id: 'settings-curated-logging.level' }] : []
      if (selector === '.settings-body button') return section === 'General' ? [node('Advanced settings')] : []
      if (selector === '.msg.user .body') return messages.filter(m => m.role === 'user').map(m => ({ textContent: m.text }))
      if (selector === '[data-testid="webhook-ingress"] button') return ['Save listener setup', 'Save trigger source and secret', 'Clear per-trigger secret'].map(node)
      return Array.from({ length: size(selector) }, () => node(selector))
    },
    getElementById: (id: string) => ({ innerText: messages.find(m => 'm-' + m.id === id)?.text ?? '' }),
    createElement: () => ({ style: {}, textContent: '' }), body: { append: () => {} }
  }
  const window = { odin: new Proxy({}, { get: (_target, name: string) => (params: any) => bridge(name, params) }) }
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
  const win: any = { webContents: { isLoading: vi.fn(() => false), capturePage: vi.fn(async () => ({ toPNG: () => Buffer.from('inert-png') })), executeJavaScript: vi.fn(async (script: string, gesture: boolean) => {
    expect(gesture).toBe(true)
    // Run exactly the expression emitted by the driver, against only inert DOM
    // and named-bridge ports. Unknown reads/methods fail rather than rubber-stamp.
    return new AsyncFunction('document', 'window', 'Event', 'return (' + script + ')')(document, window, class { constructor(public type: string, public options: any) {} })
  }) } }
  return { core, win, operations, clicks, messages, recent, journal, get skillRuns() { return skillRuns }, get mcp() { return mcp }, get sourceSecret() { return sourceSecret }, get outputPages() { return outputPages } }
}

async function execute(f: ReturnType<typeof fixture>) {
  const result = realCoreSmoke(f.win, f.core, out).then(() => ({ ok: true as const }), error => ({ ok: false as const, error }))
  await vi.runAllTimersAsync(); const settled = await result
  if (!settled.ok) throw settled.error
  return JSON.parse(String(ports.files.get(root + '/result-evidence.json')))
}

describe('real-core driver with entirely inert stateful ports', () => {
  it('runs fresh management, named bridge mutations, fenced controls, failure and committed search', async () => {
    const f = fixture(); const evidence = await execute(f)
    expect(evidence.phase).toBe('production entry / fresh real profile')
    expect(evidence.reads['conversation.snapshot'].recent[0]).toMatchObject({ outcome: 'failed', unknown_effects: 0 })
    expect(f.operations.filter(op => op[0] === 'submit').map(op => op[1])).toEqual(['/status', '/usage', submission])
    expect(f.skillRuns).toBe(2); expect(f.mcp).toBe(false)
    expect(evidence.screens.at(-1).screen).toContain('Search / committed transcript')
    expect(evidence.screens.map((screen: any) => screen.screen)).toEqual(expect.arrayContaining([
      'production entry / fresh real profile / Settings / Data and privacy / Memory and knowledge / Context reload',
      'production entry / fresh real profile / Settings / Usage, logs and audit',
      'production entry / fresh real profile / Settings / Advanced settings'
    ]))
    expect(f.clicks).toContain('.settings-subnav button:nth-of-type(2)')
    expect(f.clicks).toContain('Advanced settings')
    expect(f.core.listenerCount('event')).toBe(0)
    expect(dialog.showOpenDialog).toBe(ports.open); expect(dialog.showSaveDialog).toBe(ports.save)
    expect(f.core.request.mock.calls.filter(([method]: any[]) => method.startsWith('control.'))).toHaveLength(3)
  })
  it('owns resume/stop/steer targets and pages retained output without replaying requests', async () => {
    const f = fixture(true); const evidence = await execute(f)
    expect(evidence.typedResume).toEqual({ request_id: 'r_seed', generation: 2, userMessages: 1 })
    expect(evidence.ordinaryContinue.request_id).not.toBe('r_seed')
    expect(f.operations.filter(op => op[0] === 'submit' && op[1] === 'continue')).toHaveLength(2)
    expect(f.messages.filter(m => m.role === 'user' && m.text === 'continue')).toHaveLength(1)
    expect(evidence.outputPaging.pages).toBe(2); expect(f.outputPages).toBe(2)
    expect(f.operations.filter(op => op[0] === 'submit' && op[1] === '[paged-tool]')).toHaveLength(1)
    expect(evidence.resumeWithoutCheckpoint.result).toEqual({ disposition: 'rejected', reason: 'not_resumable' })
    expect(f.operations.find(op => op[0] === 'stop')![1]).toBe(evidence.stoppedRequest.request_id)
    expect(f.operations.find(op => op[0] === 'steer')![1]).toBe(evidence.steeredRequest.request_id)
    expect(evidence.events.map((e: any) => e.type)).toEqual(['request.started', 'request.cancelled', 'request.queued', 'control.receipt'])
    expect(evidence.guardedProviderError.text).toContain('canned_failure')
    expect(evidence.attachment.attachments).toHaveLength(1); expect(evidence.postedImage).toBe(true)
    expect(evidence.conversationLifecycle.deleted).toBe(true)
    expect(f.core.listenerCount('event')).toBe(0)
    expect(dialog.showOpenDialog).toBe(ports.open); expect(dialog.showSaveDialog).toBe(ports.save)
  })
  it('journals cancellation and webhook delivery exactly once, then closes its inert listener', async () => {
    const f = fixture(false, true); const evidence = await execute(f)
    expect(f.operations.filter(op => op[0] === 'cancel-effect')).toHaveLength(1)
    expect(f.operations.filter(op => op[0] === 'bridge' && op[1] === 'workControl')).toHaveLength(2)
    expect(f.journal.size).toBe(1)
    expect(evidence.webhookProof.deliveryStatus).toEqual({ rejected: 403, filtered: 200, accepted: 2 })
    expect(evidence.webhookProof.history).toEqual([{ status: 'success' }, { status: 'success' }])
    expect(evidence.webhookProof.cleared.address).toBeNull(); expect(f.sourceSecret).toBe('')
    expect(evidence.toolCounts).toEqual({ background: 1, report: 1 })
    expect(evidence.qualification).toContain('metadata seeds')
  })
  it('records and propagates a failed ownership assertion and always restores port owners', async () => {
    const f = fixture(true, false, 'wrong-reply-owner')
    await expect(execute(f)).rejects.toThrow('UI did not settle for D9 committed reply')
    const evidence = JSON.parse(String(ports.files.get(root + '/result-evidence.json')))
    expect(evidence.error).toContain('D9 committed reply')
    expect(evidence.renderedPage).toBe('inert rendered body')
    expect(f.core.listenerCount('event')).toBe(0)
    expect(dialog.showOpenDialog).toBe(ports.open); expect(dialog.showSaveDialog).toBe(ports.save)
  })
  it.each([
    ['missing-curated-timezone', 'real curated time zone before enumerating all sections'],
    ['missing-records-owner', 'missing UI control .settings-subnav button:nth-of-type(2)'],
    ['unknown-curated-log', 'rendered field logging.level must belong to the served schema']
  ])('rejects %s instead of passing a stale or nonexistent selector', async (fault, expected) => {
    const f = fixture(false, false, fault)
    await expect(execute(f)).rejects.toThrow(expected)
    expect(f.core.listenerCount('event')).toBe(0)
    expect(dialog.showOpenDialog).toBe(ports.open); expect(dialog.showSaveDialog).toBe(ports.save)
  })
})
