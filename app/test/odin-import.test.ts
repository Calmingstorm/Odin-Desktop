// Import from Odin: a fake Odin API and a fake core that keeps the real contracts (create-only refusals, if_absent,
// revisions and unconfirmed outcomes), so every read and write the importer makes is visible and judged.
import { EventEmitter } from 'node:events'
import { describe, expect, it, vi } from 'vitest'
const handlers = vi.hoisted(() => new Map<string, Function>())
vi.mock('electron', () => ({ ipcMain: { handle: (name: string, handler: Function) => handlers.set(name, handler) } }))
import { registerIpc, type IpcDeps } from '../src/main/ipc'
import {
  ODIN_REDACTED,
  applyOdinImport,
  fingerprintOf,
  previewOdinImport,
  type FetchLike,
  type ImportBroker
} from '../src/main/odin-import'
import { odinImportApplySchema, odinImportPreviewSchema } from '../src/main/schemas'
import { IPC } from '../src/shared/api'

// A throwaway public key and the fingerprint `ssh-keygen -lf` printed for it.
const KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPGfYwFXBev5NmLvSwQEC8gDGxBDSmS3iNsSbtLWXxJB import-test'
const FINGERPRINT = 'SHA256:2VvtQx2+HBjugyaM7W2gOt4naQ2ApZC3LZNbS7Dw/Jc'
const SOURCE = { url: 'http://localhost:3002/ui/', token: 'tok-123' }
const pick = (category: string, id: string) => ({ category, id }) as never

function odinApi(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    '/api/memory': { user_7: { keys: [], count: 0 }, user_42: { keys: ['mine'], count: 1 }, global: { keys: ['shared_a', 'shared_b'], count: 2 } },
    '/api/memory/global': { scope: 'global', entries: { shared_a: 'A', shared_b: 'B' } },
    '/api/memory/user_42': { scope: 'user_42', entries: { mine: 'M' } },
    '/api/skills': [
      { name: 'weather', description: 'Reads the weather', status: 'loaded' },
      { name: 'existing_skill', description: 'Already here', status: 'loaded' },
      { name: 'quiet', description: 'Off in Odin', status: 'disabled' }
    ],
    '/api/skills/weather': { code: 'def run():\n    return 1\n', config: { units: 'metric', api_key: ODIN_REDACTED } },
    '/api/skills/quiet': { code: 'def run():\n    return 2\n', config: {} },
    '/api/config': {
      timezone: 'America/New_York',
      llm_provider: { model: 'gpt-6.1-sol', active_provider: 'codex' },
      openai_codex: { reasoning_effort: 'high', agent_reasoning_effort: 'auto', context_utilization: 60 },
      openai_compatible: { reasoning_effort: 'medium' },
      agents: { model: 'auto', auto_model_allowlist: ['gpt-6.1-sol', { model: 'gpt-6-luna', reasoning_effort: 'auto' }], max_concurrent_agents: 15 },
      mcp: { servers: {
        Grafana: { transport: 'stdio', command: '/usr/local/bin/mcp-grafana', args: ['-x'], env: { GRAFANA_URL: ODIN_REDACTED }, headers: {}, cwd: '', tool_allowlist: [], timeout_seconds: 120, enabled: true },
        Docs: { transport: 'http', url: 'https://docs.example/mcp', headers: { Authorization: ODIN_REDACTED }, env: {} },
        Remote: { transport: 'http', url: ODIN_REDACTED, headers: {}, env: {} },
        'bad-name': { transport: 'stdio', command: 'x' }
      } },
      tools: { hosts: {
        server: { address: '192.168.1.13', ssh_user: 'root', port: 22, os: 'linux', description: 'Server', enabled: true, trust_mode: 'pinned', host_keys: [KEY] },
        legacy: { address: '10.0.0.9', ssh_user: 'me', port: 2222, os: 'linux', trust_mode: 'legacy', host_keys: [] },
        localhost: { address: '127.0.0.1', ssh_user: 'odin' }
      } }
    },
    '/api/personality': {
      preset: 'mine', custom_name: '', custom_identity: '', custom_voice: '',
      presets: { odin: { name: 'Odin' }, mine: { name: 'My preset', identity: 'I am', voice: 'calm' }, active: { name: 'A preset called active', identity: 'x', voice: 'y' } },
      builtin_presets: ['odin'], user_presets: ['mine', 'active']
    },
    ...overrides
  }
  const calls: Array<{ url: string; init: Parameters<FetchLike>[1] }> = []
  const fetchImpl: FetchLike = vi.fn(async (url, init) => {
    calls.push({ url, init })
    const path = new URL(url).pathname
    if (!(path in routes)) return { ok: false, status: 404, json: async () => ({}) }
    const body = routes[path]
    if (body instanceof Error) throw body
    if (body === 'NOT_JSON') return { ok: true, status: 200, json: async () => { throw new SyntaxError('bad') } }
    if (typeof body === 'number') return { ok: false, status: body, json: async () => ({}) }
    return { ok: true, status: 200, json: async () => body }
  })
  return { fetchImpl, calls }
}

type Answer = unknown | ((params: Record<string, unknown>, seen: number) => unknown)
const refuse = (code: string, message: string, disposition = 'rejected') => ({ __error: { code, message, disposition } })

/** A fake core keeping Desktop's real write contracts. */
function desktop(answers: Record<string, Answer> = {}) {
  const memory = new Set(['shared_b'])
  const skills = new Set(['existing_skill'])
  const presets = new Set<string>()
  const defaults: Record<string, Answer> = {
    'skills.list': () => [...skills].map((name) => ({ name })),
    'skills.save': (p: Record<string, unknown>) => (p.create === true && skills.has(String(p.name)) ? refuse('conflict', 'a skill with this name already exists') : (skills.add(String(p.name)), { result: 'ok' })),
    'memory.set': (p: Record<string, unknown>) => (p.if_absent === true && memory.has(String(p.key)) ? { status: 'exists' } : (memory.add(String(p.key)), { status: 'saved' })),
    'mcp.status': { revision: 'rev-mcp', servers: [] },
    'personality.get': () => ({ user_presets: [...presets], builtin_presets: ['odin'] }),
    'personality.presets.save': (p: Record<string, unknown>) => (p.create === true && presets.has(String(p.name)) ? refuse('conflict', 'a preset with this name already exists') : (presets.add(String(p.name)), { status: 'saved' })),
    'hosts.list': { hosts: [{ alias: 'localhost' }] },
    'hosts.prepare': { candidate_token: 'cand-1' },
    'hosts.test': { tested: false, error: 'Permission denied' },
    'hosts.public_key': { public_key: 'ssh-ed25519 DESKTOPKEY desktop' },
    'settings.schema': { revision: 'rev-settings', fields: [
      { path: 'openai_codex.agent_reasoning_effort', apply_handler: 'providers.codex.set' },
      { path: 'agents.max_concurrent_agents', apply_handler: 'settings.set' },
      { path: 'openai_codex.context_utilization', apply_handler: 'providers.codex.set' },
      { path: 'timezone', apply_handler: 'settings.set' }
    ] },
    ...answers
  }
  const requests: Array<{ method: string; params: Record<string, unknown>; id?: string }> = []
  const seen: Record<string, number> = {}
  const receipts = new EventEmitter()
  const broker: ImportBroker = {
    on: (event, listener) => receipts.on(event, listener),
    request: vi.fn(async (method: string, params: Record<string, unknown> = {}, id?: string) => {
      requests.push({ method, params, id })
      seen[method] = (seen[method] ?? 0) + 1
      const raw = method in defaults ? defaults[method] : { ok: true }
      const answer = typeof raw === 'function' ? (raw as (p: Record<string, unknown>, n: number) => unknown)(params, seen[method]!) : raw
      const error = (answer as { __error?: { code: string; message: string; disposition: string } } | undefined)?.__error
      if (error) return { ok: false as const, error }
      return { ok: true as const, result: answer }
    })
  }
  return { broker, requests, receipts }
}

describe('fingerprintOf', () => {
  it("matches OpenSSH's SHA256 fingerprint and rejects lines without a key", () => {
    expect(fingerprintOf(KEY)).toBe(FINGERPRINT)
    expect(fingerprintOf(`host.example ${KEY}`)).toBe(FINGERPRINT)
    expect(fingerprintOf('not a key')).toBeNull()
    expect(fingerprintOf('ssh-ed25519 !!!')).toBeNull()
  })
})

describe('previewOdinImport', () => {
  it("reads Odin's API at the address's origin with the token, refuses redirects and changes nothing", async () => {
    const odin = odinApi()
    const { broker, requests } = desktop()
    const preview = await previewOdinImport(SOURCE, broker, odin.fetchImpl)
    expect(preview.ok).toBe(true)
    expect(odin.calls.map((c) => c.url).sort()).toEqual([
      'http://localhost:3002/api/config', 'http://localhost:3002/api/memory',
      'http://localhost:3002/api/personality', 'http://localhost:3002/api/skills'
    ])
    for (const call of odin.calls) {
      expect(call.init.headers.Authorization).toBe('Bearer tok-123')
      expect(call.init.redirect).toBe('error')
    }
    expect(requests.map((r) => r.method).sort()).toEqual(['hosts.list', 'mcp.status', 'personality.get', 'skills.list'])
  })

  it('suggests new things, leaves replacements and off skills unticked, and explains what needs finishing', async () => {
    const preview = await previewOdinImport(SOURCE, desktop().broker, odinApi().fetchImpl)
    if (!preview.ok) throw new Error(preview.error.message)
    const item = (category: string, id: string) => preview.result.items.find((i) => i.category === category && i.id === id)!
    expect(preview.result.items.filter((i) => i.category === 'memory').map((i) => i.id)).toEqual(['global', 'user_42'])
    expect(item('memory', 'global')).toMatchObject({ selected: true, detail: '2 entries' })
    expect(item('memory', 'user_42')).toMatchObject({ selected: false })
    expect(item('skills', 'weather')).toMatchObject({ selected: true, exists: false })
    expect(item('skills', 'existing_skill')).toMatchObject({ selected: false, exists: true })
    expect(item('skills', 'quiet')).toMatchObject({ selected: false, notes: ["It's off in Odin and stays off here."] })
    expect(item('mcp', 'Grafana').notes.join(' ')).toContain('GRAFANA_URL')
    expect(item('mcp', 'bad-name')).toMatchObject({ selected: false })
    expect(item('hosts', 'server')).toMatchObject({ selected: true, detail: 'root@192.168.1.13' })
    expect(item('hosts', 'legacy')).toMatchObject({ selected: false, detail: 'me@10.0.0.9:2222' })
    expect(preview.result.items.some((i) => i.category === 'hosts' && i.id === 'localhost')).toBe(false)
    expect(item('personality', 'preset:active')).toMatchObject({ label: 'A preset called active', selected: true })
    expect(item('personality', 'current')).toMatchObject({ selected: false, detail: 'My preset' })
    expect(item('models', 'main')).toMatchObject({ selected: false, detail: 'gpt-6.1-sol · high' })
    expect(item('models', 'agent_effort').detail).toBe('Automatic')
    expect(item('models', 'timezone').detail).toBe('America/New_York')
  })

  it('turns failures into plain messages and never echoes the token', async () => {
    const cases: Array<[Record<string, unknown>, RegExp]> = [
      [{ '/api/memory': 401 }, /didn't accept this token/],
      [{ '/api/config': new Error('ECONNREFUSED') }, /Couldn't reach Odin at http:\/\/localhost:3002/],
      [{ '/api/skills': 500 }, /Odin answered 500/],
      [{ '/api/personality': 'NOT_JSON' }, /didn't answer like Odin's API/]
    ]
    for (const [routes, message] of cases) {
      const preview = await previewOdinImport(SOURCE, desktop().broker, odinApi(routes).fetchImpl)
      expect(preview.ok).toBe(false)
      if (!preview.ok) {
        expect(preview.error.message).toMatch(message)
        expect(preview.error.message).not.toContain('tok-123')
      }
    }
  })

  it('sends the token to a remote http:// address only after an explicit choice; loopback and https need none', async () => {
    const odin = odinApi()
    const refused = await previewOdinImport({ url: 'http://192.168.1.13:3002', token: 't' }, desktop().broker, odin.fetchImpl)
    expect(refused.ok).toBe(false)
    if (!refused.ok) expect(refused.error.message).toMatch(/isn't encrypted/)
    expect(odin.calls).toHaveLength(0)
    expect((await previewOdinImport({ url: 'http://192.168.1.13:3002', token: 't', allow_insecure_http: true }, desktop().broker, odin.fetchImpl)).ok).toBe(true)
    expect((await previewOdinImport({ url: 'https://odin.example', token: 't' }, desktop().broker, odin.fetchImpl)).ok).toBe(true)
    expect((await previewOdinImport({ url: 'http://[::1]:3002', token: 't' }, desktop().broker, odin.fetchImpl)).ok).toBe(true)
    const garbled = await previewOdinImport({ url: 'not a url', token: 't' }, desktop().broker, odin.fetchImpl)
    expect(garbled.ok).toBe(false)
    if (!garbled.ok) expect(garbled.error.message).toBe('Enter an http:// or https:// address.')
  })
})

describe('applyOdinImport', () => {
  it('writes memory, skills, MCP servers and presets create-only, keeping what exists', async () => {
    const { broker, requests } = desktop()
    const report = await applyOdinImport(SOURCE, [
      pick('memory', 'global'), pick('memory', 'user_42'), pick('skills', 'weather'), pick('skills', 'existing_skill'),
      pick('mcp', 'Grafana'), pick('mcp', 'Docs'), pick('mcp', 'Remote'), pick('personality', 'preset:mine')
    ], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    const outcome = (id: string) => report.result.outcomes.find((o) => o.id === id)!
    expect(requests.filter((r) => r.method === 'memory.set').map((r) => r.params)).toEqual([
      { scope: 'global', key: 'shared_a', value: 'A', if_absent: true }, { scope: 'global', key: 'shared_b', value: 'B', if_absent: true },
      { scope: 'global', key: 'mine', value: 'M', if_absent: true }
    ])
    expect(outcome('global')).toMatchObject({ status: 'imported', message: '1 entry added, 1 already there.' })
    expect(requests.find((r) => r.method === 'skills.save')?.params).toEqual({ name: 'weather', code: 'def run():\n    return 1\n', create: true })
    expect(requests.find((r) => r.method === 'skills.config.set')?.params).toEqual({ name: 'weather', config: { units: 'metric' } })
    expect(outcome('weather')).toMatchObject({ status: 'needs_attention' })
    expect(outcome('weather').message).toContain('api_key')
    expect(outcome('existing_skill').status).toBe('skipped')
    const saves = requests.filter((r) => r.method === 'mcp.save').map((r) => r.params)
    expect(saves[0]).toEqual({ name: 'Grafana', transport: 'stdio', enabled: false, tool_allowlist: [], expected_revision: 'rev-mcp',
      timeout_seconds: 120, command: '/usr/local/bin/mcp-grafana', args: ['-x'] })
    expect(saves[1]).toEqual({ name: 'Docs', transport: 'http', enabled: false, tool_allowlist: [], expected_revision: 'rev-mcp', url: 'https://docs.example/mcp' })
    expect(saves.some((params) => 'create' in params)).toBe(false)
    expect(outcome('Grafana')).toMatchObject({ status: 'needs_attention' })
    expect(outcome('Docs')).toMatchObject({ status: 'needs_attention' })
    expect(outcome('Remote')).toMatchObject({ status: 'needs_attention' })
    expect(requests.find((r) => r.method === 'personality.presets.save')?.params).toEqual({ name: 'mine', display_name: 'My preset', identity: 'I am', voice: 'calm', create: true })
  })

  it('keeps a skill, preset or server that appears in Desktop while the import runs', async () => {
    const { broker } = desktop({
      'skills.save': refuse('conflict', 'a skill with this name already exists'),
      'personality.presets.save': refuse('conflict', 'a preset with this name already exists'),
      'mcp.status': (_p: unknown, n: number) => ({ revision: 'r', servers: n === 1 ? [] : [{ name: 'Grafana' }] })
    })
    const report = await applyOdinImport(SOURCE, [pick('skills', 'weather'), pick('mcp', 'Grafana'), pick('personality', 'preset:mine')],
      broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(report.result.outcomes.map((o) => [o.id, o.status])).toEqual([['weather', 'skipped'], ['Grafana', 'skipped'], ['preset:mine', 'skipped']])
  })

  it('reports a server save refused for a changed revision instead of retrying it, and a plain MCP refusal as is', async () => {
    const changed = await applyOdinImport(SOURCE, [pick('mcp', 'Grafana')], desktop({ 'mcp.save': refuse('stale_binding', 'revision moved') }).broker, odinApi().fetchImpl)
    if (!changed.ok) throw new Error(changed.error.message)
    expect(changed.result.outcomes[0]).toMatchObject({ status: 'failed', message: expect.stringMatching(/changed during the import/) })
    const refused = await applyOdinImport(SOURCE, [pick('mcp', 'Grafana'), pick('mcp', 'bad-name')], desktop({ 'mcp.save': refuse('bad_request', 'bad command') }).broker, odinApi().fetchImpl)
    if (!refused.ok) throw new Error(refused.error.message)
    expect(refused.result.outcomes.map((o) => [o.id, o.status, o.message])).toEqual([
      ['Grafana', 'failed', 'bad command'],
      ['bad-name', 'failed', 'Odin Desktop server names use letters, digits and underscores only.']
    ])
    const plain = odinApi({ '/api/config': { mcp: { servers: { Plain: { transport: 'stdio', command: 'x', args: [], env: { MODE: 'fast' } } } } } })
    const { broker: b, requests: r } = desktop()
    const report = await applyOdinImport(SOURCE, [pick('mcp', 'Plain')], b, plain.fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(report.result.outcomes[0]).toMatchObject({ status: 'imported' })
    expect(r.find((x) => x.method === 'mcp.save')?.params).toMatchObject({ env_set: { MODE: 'fast' } })
  })

  it("imports a skill that is off in Odin switched off, and the saved preset named 'active' never activates anything", async () => {
    const { broker, requests } = desktop()
    const report = await applyOdinImport(SOURCE, [pick('skills', 'quiet'), pick('personality', 'preset:active')], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(requests.find((r) => r.method === 'skills.save')?.params).toEqual({ name: 'quiet', code: 'def run():\n    return 2\n', create: true, enabled: false })
    expect(requests.some((r) => r.method === 'skills.set_enabled')).toBe(false)
    expect(report.result.outcomes[0]).toMatchObject({ status: 'imported', message: 'Imported. Switched off, as in Odin.' })
    expect(requests.some((r) => r.method === 'personality.set')).toBe(false)
    expect(requests.find((r) => r.method === 'personality.presets.save')?.params).toMatchObject({ name: 'active', create: true })
    const configFails = await applyOdinImport(SOURCE, [pick('skills', 'weather')], desktop({ 'skills.config.set': refuse('bad_request', 'no') }).broker, odinApi().fetchImpl)
    if (!configFails.ok) throw new Error(configFails.error.message)
    expect(configFails.result.outcomes[0]).toMatchObject({ status: 'needs_attention', message: expect.stringMatching(/settings weren't/) })
    const empty = await applyOdinImport(SOURCE, [pick('skills', 'weather')], desktop().broker, odinApi({ '/api/skills/weather': { code: '  ', config: {} } }).fetchImpl)
    if (!empty.ok) throw new Error(empty.error.message)
    expect(empty.result.outcomes[0]).toMatchObject({ status: 'failed' })
  })

  it("makes Odin's current personality Desktop's, importing its preset first or using Desktop's own", async () => {
    const { broker, requests } = desktop()
    const report = await applyOdinImport(SOURCE, [pick('personality', 'current')], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(requests.map((r) => r.method).filter((m) => m.startsWith('personality.'))).toEqual(['personality.get', 'personality.presets.save', 'personality.set'])
    expect(requests.find((r) => r.method === 'personality.set')?.params).toEqual({ preset: 'mine' })
    const kept = await applyOdinImport(SOURCE, [pick('personality', 'current')],
      desktop({ 'personality.presets.save': refuse('conflict', 'exists') }).broker, odinApi().fetchImpl)
    if (!kept.ok) throw new Error(kept.error.message)
    expect(kept.result.outcomes[0]).toMatchObject({ status: 'imported' })
    const custom = odinApi({ '/api/personality': { preset: 'custom', custom_name: 'Raven', custom_identity: 'i', custom_voice: 'v', presets: {}, user_presets: [] } })
    const { broker: second, requests: seen } = desktop({ 'personality.set': refuse('bad_request', 'rejected') })
    const set = await applyOdinImport(SOURCE, [pick('personality', 'current')], second, custom.fetchImpl)
    if (!set.ok) throw new Error(set.error.message)
    expect(seen.find((r) => r.method === 'personality.set')?.params).toEqual({ preset: 'custom', custom_name: 'Raven', custom_identity: 'i', custom_voice: 'v' })
    expect(set.result.outcomes[0]).toMatchObject({ status: 'failed', message: 'rejected' })
    const refused = await applyOdinImport(SOURCE, [pick('personality', 'current')], desktop({ 'personality.presets.save': refuse('bad_request', 'no') }).broker, odinApi().fetchImpl)
    if (!refused.ok) throw new Error(refused.error.message)
    expect(refused.result.outcomes[0]).toMatchObject({ status: 'failed', message: 'no' })
    const builtin = odinApi({ '/api/personality': { preset: 'odin', presets: { odin: { name: 'Odin' } }, user_presets: [] } })
    const { broker: third, requests: odinSeen } = desktop()
    await applyOdinImport(SOURCE, [pick('personality', 'current')], third, builtin.fetchImpl)
    expect(odinSeen.some((r) => r.method === 'personality.presets.save')).toBe(false)
    expect(odinSeen.find((r) => r.method === 'personality.set')?.params).toEqual({ preset: 'odin' })
  })

  it("pins a host by Odin's key fingerprint and hands back Desktop's key when it can't sign in", async () => {
    const { broker, requests } = desktop()
    const report = await applyOdinImport(SOURCE, [pick('hosts', 'server'), pick('hosts', 'legacy')], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(requests.find((r) => r.method === 'hosts.prepare')?.params).toMatchObject({
      alias: 'server', address: '192.168.1.13', ssh_user: 'root', trust_mode: 'pinned', expected_fingerprints: [FINGERPRINT]
    })
    expect(requests.some((r) => r.method === 'hosts.commit')).toBe(false)
    expect(report.result.outcomes.map((o) => [o.id, o.status])).toEqual([['server', 'needs_attention'], ['legacy', 'needs_attention']])
    expect(report.result.public_key).toBe('ssh-ed25519 DESKTOPKEY desktop')
    const unprepared = await applyOdinImport(SOURCE, [pick('hosts', 'server')], desktop({ 'hosts.prepare': refuse('bad_request', 'key mismatch') }).broker, odinApi().fetchImpl)
    if (!unprepared.ok) throw new Error(unprepared.error.message)
    expect(unprepared.result.outcomes[0]).toMatchObject({ status: 'failed', message: 'key mismatch' })
  })

  it('commits a tested host, but keeps one added in Desktop between the check and the commit', async () => {
    const { broker, requests } = desktop({ 'hosts.test': { tested: true }, 'hosts.commit': { saved: true } })
    const report = await applyOdinImport(SOURCE, [pick('hosts', 'server')], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(requests.find((r) => r.method === 'hosts.commit')?.params).toEqual({ token: 'cand-1' })
    expect(report.result.outcomes[0]).toMatchObject({ status: 'imported' })
    expect(report.result.public_key).toBeUndefined()
    const late = desktop({
      'hosts.test': { tested: true },
      'hosts.list': (_p: unknown, n: number) => ({ hosts: n <= 2 ? [] : [{ alias: 'server' }] })
    })
    const kept = await applyOdinImport(SOURCE, [pick('hosts', 'server')], late.broker, odinApi().fetchImpl)
    if (!kept.ok) throw new Error(kept.error.message)
    expect(kept.result.outcomes[0]).toMatchObject({ status: 'skipped' })
    expect(late.requests.some((r) => r.method === 'hosts.commit')).toBe(false)
    const refusedCommit = await applyOdinImport(SOURCE, [pick('hosts', 'server')],
      desktop({ 'hosts.test': { tested: true }, 'hosts.commit': refuse('conflict', 'host changed after this candidate was prepared') }).broker, odinApi().fetchImpl)
    if (!refusedCommit.ok) throw new Error(refusedCommit.error.message)
    expect(refusedCommit.result.outcomes[0]).toMatchObject({ status: 'failed' })
  })

  it('stops at a change the core did not confirm and never retries it blindly', async () => {
    const { broker, requests } = desktop({ 'skills.save': refuse('no_receipt', 'No receipt yet.', 'outcome_unknown') })
    const report = await applyOdinImport(SOURCE, [pick('memory', 'global'), pick('skills', 'weather'), pick('mcp', 'Grafana'), pick('hosts', 'server')],
      broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(report.result.outcomes.map((o) => [o.id, o.status])).toEqual([
      ['global', 'imported'], ['weather', 'unknown'], ['Grafana', 'not_attempted'], ['server', 'not_attempted']
    ])
    const sent = requests.filter((r) => r.method === 'skills.save')
    expect(sent).toHaveLength(1)
    expect(sent[0]!.id).toMatch(/^[0-9a-f-]{36}$/)
    expect(report.result.outcomes[1]!.command_id).toBe(sent[0]!.id)
    expect(requests.some((r) => r.method === 'mcp.save' || r.method === 'hosts.prepare')).toBe(false)
    const testLate = await applyOdinImport(SOURCE, [pick('hosts', 'server')],
      desktop({ 'hosts.test': refuse('no_receipt', 'No receipt yet.', 'outcome_unknown') }).broker, odinApi().fetchImpl)
    if (!testLate.ok) throw new Error(testLate.error.message)
    expect(testLate.result.outcomes[0]).toMatchObject({ status: 'needs_attention', message: expect.stringMatching(/didn't answer in time/) })
    expect(testLate.result.public_key).toBeUndefined()
  })

  it('refuses to send an unconfirmed change again until its late receipt arrives', async () => {
    let lost = true
    const { broker, requests, receipts } = desktop({ 'models.main.set': () => (lost ? refuse('no_receipt', 'No receipt yet.', 'outcome_unknown') : { ok: true }) })
    const first = await applyOdinImport(SOURCE, [pick('models', 'main')], broker, odinApi().fetchImpl)
    if (!first.ok) throw new Error(first.error.message)
    const original = first.result.outcomes[0]!.command_id
    expect(first.result.outcomes[0]).toMatchObject({ status: 'unknown' })
    // Importing it again while it is unresolved sends nothing and names the original command.
    const again = await applyOdinImport(SOURCE, [pick('models', 'main'), pick('models', 'timezone')], broker, odinApi().fetchImpl)
    if (!again.ok) throw new Error(again.error.message)
    expect(again.result.outcomes.map((o) => [o.id, o.status])).toEqual([['main', 'unknown'], ['timezone', 'imported']])
    expect(again.result.outcomes[0]!.command_id).toBe(original)
    expect(requests.filter((r) => r.method === 'models.main.set')).toHaveLength(1)
    // An unrelated receipt changes nothing; the original command's late receipt clears it.
    receipts.emit('receipt', { id: 'someone-else' })
    lost = false
    const still = await applyOdinImport(SOURCE, [pick('models', 'main')], broker, odinApi().fetchImpl)
    if (!still.ok) throw new Error(still.error.message)
    expect(still.result.outcomes[0]).toMatchObject({ status: 'unknown' })
    receipts.emit('receipt', { id: original })
    const settled = await applyOdinImport(SOURCE, [pick('models', 'main')], broker, odinApi().fetchImpl)
    if (!settled.ok) throw new Error(settled.error.message)
    expect(settled.result.outcomes[0]).toMatchObject({ status: 'imported' })
    expect(requests.filter((r) => r.method === 'models.main.set')).toHaveLength(2)
  })

  it('refuses a second import while one is still running, and runs again once it has finished', async () => {
    const { broker } = desktop()
    const odin = odinApi()
    let release!: () => void
    const gate = new Promise<void>((resolve) => { release = resolve })
    const slow: FetchLike = async (url, init) => { await gate; return odin.fetchImpl(url, init) }
    const first = applyOdinImport(SOURCE, [pick('models', 'timezone')], broker, slow)
    expect(await applyOdinImport(SOURCE, [pick('models', 'timezone')], broker, odin.fetchImpl))
      .toMatchObject({ ok: false, error: { code: 'busy' } })
    release()
    expect(await first).toMatchObject({ ok: true })
    const failing = odinApi({ '/api/config': new Error('offline') })
    expect(await applyOdinImport(SOURCE, [pick('models', 'timezone')], broker, failing.fetchImpl)).toMatchObject({ ok: false })
    expect(await applyOdinImport(SOURCE, [pick('models', 'timezone')], broker, odin.fetchImpl)).toMatchObject({ ok: true })
  })

  it('sets model choices through the methods and revisions the core names, with only the effort a provider takes', async () => {
    const { broker, requests } = desktop()
    const report = await applyOdinImport(SOURCE, [
      pick('models', 'main'), pick('models', 'agents'), pick('models', 'agent_effort'), pick('models', 'max_agents'),
      pick('models', 'context'), pick('models', 'timezone')
    ], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(report.result.outcomes.every((o) => o.status === 'imported')).toBe(true)
    expect(requests.find((r) => r.method === 'models.main.set')?.params).toEqual({ model: 'gpt-6.1-sol', reasoning_effort: 'high', expected_revision: 'rev-settings' })
    expect(requests.find((r) => r.method === 'models.agents.set')?.params).toMatchObject({ model: 'auto', expected_revision: 'rev-settings' })
    expect(requests.filter((r) => r.method === 'providers.codex.set').map((r) => r.params.changes)).toEqual([
      [{ path: 'openai_codex.agent_reasoning_effort', value: 'auto' }], [{ path: 'openai_codex.context_utilization', value: 60 }]
    ])
    expect(requests.filter((r) => r.method === 'settings.set').map((r) => r.params.changes)).toEqual([
      [{ path: 'agents.max_concurrent_agents', value: 15 }], [{ path: 'timezone', value: 'America/New_York' }]
    ])
    for (const [model, effort] of [['ollama:llama3.1:8b', undefined], ['compat:deepseek', 'medium']] as const) {
      const config = odinApi({ '/api/config': { llm_provider: { model }, openai_codex: { reasoning_effort: 'high' }, openai_compatible: { reasoning_effort: 'medium' } } })
      const { broker: b, requests: r } = desktop()
      await applyOdinImport(SOURCE, [pick('models', 'main')], b, config.fetchImpl)
      expect(r.find((x) => x.method === 'models.main.set')?.params).toEqual({ model, ...(effort ? { reasoning_effort: effort } : {}), expected_revision: 'rev-settings' })
    }
    const refusals = await applyOdinImport(SOURCE, [pick('models', 'main'), pick('models', 'agents'), pick('models', 'timezone')], desktop({
      'models.main.set': refuse('bad_request', 'no provider'), 'models.agents.set': refuse('bad_request', 'bad allowlist'),
      'settings.schema': { revision: 'r', fields: [{ path: 'timezone', apply_handler: 'hosts.settings' }] }
    }).broker, odinApi().fetchImpl)
    if (!refusals.ok) throw new Error(refusals.error.message)
    expect(refusals.result.outcomes.map((o) => o.message)).toEqual(['no provider', 'bad allowlist', 'Odin Desktop changes this setting elsewhere.'])
    const moved = await applyOdinImport(SOURCE, [pick('models', 'main'), pick('models', 'agents'), pick('models', 'timezone')], desktop({
      'settings.set': refuse('stale_binding', 'revision moved'), 'models.main.set': refuse('stale_binding', 'revision moved'),
      'models.agents.set': refuse('stale_binding', 'revision moved')
    }).broker, odinApi().fetchImpl)
    if (!moved.ok) throw new Error(moved.error.message)
    expect(moved.result.outcomes.every((o) => o.status === 'failed' && /changed during the import/.test(o.message))).toBe(true)
    const missing = await applyOdinImport(SOURCE, [pick('models', 'max_agents')], desktop({ 'settings.schema': { revision: 'r', fields: [] } }).broker, odinApi().fetchImpl)
    if (!missing.ok) throw new Error(missing.error.message)
    expect(missing.result.outcomes[0]).toMatchObject({ status: 'failed', message: "Odin Desktop doesn't have this setting." })
  })

  it('reports refusals per item, picks Odin no longer has, and Odin errors without stopping', async () => {
    const report = await applyOdinImport(SOURCE, [pick('skills', 'weather'), pick('skills', 'gone')],
      desktop({ 'skills.save': refuse('bad_request', 'Skill code failed validation') }).broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(report.result.outcomes).toEqual([
      expect.objectContaining({ id: 'weather', status: 'failed', message: 'Skill code failed validation' }),
      expect.objectContaining({ id: 'gone', status: 'failed' })
    ])
    const odin = odinApi({ '/api/skills/weather': 404 })
    const partial = await applyOdinImport(SOURCE, [pick('skills', 'weather'), pick('models', 'timezone')], desktop().broker, odin.fetchImpl)
    if (!partial.ok) throw new Error(partial.error.message)
    expect(partial.result.outcomes.map((o) => o.status)).toEqual(['failed', 'imported'])
    const memoryRefused = await applyOdinImport(SOURCE, [pick('memory', 'user_42')],
      desktop({ 'memory.set': refuse('bad_request', 'no') }).broker, odinApi().fetchImpl)
    if (!memoryRefused.ok) throw new Error(memoryRefused.error.message)
    expect(memoryRefused.result.outcomes[0]).toMatchObject({ status: 'failed', message: "0 entries added, 1 couldn't be saved." })
    const mixed = await applyOdinImport(SOURCE, [pick('memory', 'global')],
      desktop({ 'memory.set': (p: Record<string, unknown>) => (p.key === 'shared_a' ? { status: 'saved' } : refuse('bad_request', 'no')) }).broker, odinApi().fetchImpl)
    if (!mixed.ok) throw new Error(mixed.error.message)
    expect(mixed.result.outcomes[0]).toMatchObject({ status: 'needs_attention' })
    const skipped = await applyOdinImport(SOURCE, [pick('memory', 'global')],
      desktop({ 'memory.set': { status: 'exists' } }).broker, odinApi().fetchImpl)
    if (!skipped.ok) throw new Error(skipped.error.message)
    expect(skipped.result.outcomes[0]).toMatchObject({ status: 'skipped' })
    const refused = await applyOdinImport(SOURCE, [pick('skills', 'weather')], desktop().broker, odinApi({ '/api/memory': 403 }).fetchImpl)
    expect(refused.ok).toBe(false)
    const desktopDown = await previewOdinImport(SOURCE, desktop({ 'skills.list': refuse('unavailable', 'core down') }).broker, odinApi().fetchImpl)
    expect(desktopDown.ok).toBe(false)
  })
})

describe('import schemas', () => {
  it('accept an http(s) address and a token, and refuse credentials in the address or unknown categories', () => {
    expect(odinImportPreviewSchema.safeParse({ url: 'http://localhost:3002', token: 't' }).success).toBe(true)
    expect(odinImportPreviewSchema.safeParse({ url: 'http://host', token: 't', allow_insecure_http: true }).success).toBe(true)
    expect(odinImportPreviewSchema.safeParse({ url: 'ftp://host', token: 't' }).success).toBe(false)
    expect(odinImportPreviewSchema.safeParse({ url: 'not a url', token: 't' }).success).toBe(false)
    expect(odinImportPreviewSchema.safeParse({ url: 'http://user:pw@host', token: 't' }).success).toBe(false)
    expect(odinImportPreviewSchema.safeParse({ url: 'http://host', token: '' }).success).toBe(false)
    expect(odinImportApplySchema.safeParse({ url: 'http://host', token: 't', picks: [{ category: 'skills', id: 'x' }] }).success).toBe(true)
    expect(odinImportApplySchema.safeParse({ url: 'http://host', token: 't', picks: [{ category: 'other', id: 'x' }] }).success).toBe(false)
    expect(odinImportApplySchema.safeParse({ url: 'http://host', token: 't', picks: [] }).success).toBe(false)
  })
})

describe('the import IPC handlers', () => {
  const event = { sender: { id: 7 }, senderFrame: { url: 'app://odin/index.html', processId: 10, routingId: 20 } }
  const register = (broker: ImportBroker, odinFetch: FetchLike) => {
    const forbidden = vi.fn(() => { throw new Error('import reached an unrelated dependency') })
    registerIpc({ broker, odinFetch, windowId: () => 7, mainFrame: () => ({ processId: 10, routingId: 20 }),
      drafts: { set: forbidden, flush: forbidden }, artifacts: { saveAs: forbidden, open: forbidden },
      setAutostart: forbidden, setNotifications: forbidden, setConversationMuted: forbidden } as unknown as IpcDeps)
  }
  const apply = (params: Record<string, unknown>) => handlers.get(IPC.odinImportApply)!(event, params)

  it('keeps the choice to send the token over unencrypted HTTP for the import itself', async () => {
    const odin = odinApi()
    register(desktop().broker, odin.fetchImpl)
    const remote = { url: 'http://192.168.1.13:3002', token: 't', picks: [{ category: 'models', id: 'timezone' }] }
    expect(await apply(remote)).toMatchObject({ ok: false })
    expect(odin.fetchImpl).not.toHaveBeenCalled()
    const report = await apply({ ...remote, allow_insecure_http: true })
    expect(report).toMatchObject({ ok: true, result: { outcomes: [{ id: 'timezone', status: 'imported' }] } })
  })

  it("never sends a change again whose answer the window lost, until the core's late receipt settles it", async () => {
    let lost = true
    const { broker, requests, receipts } = desktop({ 'settings.set': () => (lost ? refuse('no_receipt', 'No receipt yet.', 'outcome_unknown') : { ok: true }) })
    const odin = odinApi()
    let release!: () => void
    const gate = new Promise<void>((resolve) => { release = resolve })
    register(broker, async (url, init) => { await gate; return odin.fetchImpl(url, init) })
    const timezone = { ...SOURCE, picks: [{ category: 'models', id: 'timezone' }] }
    // The window's dialog closes and reopens while its import runs; the first answer is never read.
    const unread = apply(timezone)
    expect(await apply(timezone)).toMatchObject({ ok: false, error: { code: 'busy' } })
    release()
    const original = (await unread).result.outcomes[0].command_id
    expect(original).toEqual(requests.find((r) => r.method === 'settings.set')!.id)
    // A fresh import from the reopened dialog is refused, naming the original command.
    expect(await apply(timezone)).toMatchObject({ ok: true, result: { outcomes: [{ status: 'unknown', command_id: original }] } })
    expect(requests.filter((r) => r.method === 'settings.set')).toHaveLength(1)
    lost = false
    receipts.emit('receipt', { id: original })
    expect(await apply(timezone)).toMatchObject({ ok: true, result: { outcomes: [{ status: 'imported' }] } })
    expect(requests.filter((r) => r.method === 'settings.set')).toHaveLength(2)
  })
})
