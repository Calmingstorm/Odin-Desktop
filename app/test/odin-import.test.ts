// Import from Odin: a fake Odin API and a fake core broker, so every read and write the importer makes is visible.
import { describe, expect, it, vi } from 'vitest'
import {
  ODIN_REDACTED,
  applyOdinImport,
  fingerprintOf,
  previewOdinImport,
  type FetchLike,
  type ImportBroker
} from '../src/main/odin-import'
import { odinImportApplySchema, odinImportPreviewSchema } from '../src/main/schemas'

// A throwaway public key and the fingerprint `ssh-keygen -lf` printed for it.
const KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPGfYwFXBev5NmLvSwQEC8gDGxBDSmS3iNsSbtLWXxJB import-test'
const FINGERPRINT = 'SHA256:2VvtQx2+HBjugyaM7W2gOt4naQ2ApZC3LZNbS7Dw/Jc'
const SOURCE = { url: 'http://odin.test:3002/ui/', token: 'tok-123' }

function odinApi(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    '/api/memory': { global: { keys: ['shared_a', 'shared_b'], count: 2 }, user_42: { keys: ['mine'], count: 1 } },
    '/api/memory/global': { scope: 'global', entries: { shared_a: 'A', shared_b: 'B' } },
    '/api/memory/user_42': { scope: 'user_42', entries: { mine: 'M' } },
    '/api/skills': [
      { name: 'weather', description: 'Reads the weather', status: 'loaded' },
      { name: 'existing_skill', description: 'Already here', status: 'loaded' }
    ],
    '/api/skills/weather': { code: 'def run():\n    return 1\n', config: { units: 'metric', api_key: ODIN_REDACTED } },
    '/api/config': {
      timezone: 'America/New_York',
      llm_provider: { model: 'gpt-6.1-sol', active_provider: 'codex' },
      openai_codex: { reasoning_effort: 'high', agent_reasoning_effort: 'auto', context_utilization: 60 },
      agents: { model: 'auto', auto_model_allowlist: ['gpt-6.1-sol', { model: 'gpt-6-luna', reasoning_effort: 'auto' }], max_concurrent_agents: 15 },
      mcp: { servers: {
        Grafana: { transport: 'stdio', command: '/usr/local/bin/mcp-grafana', args: ['-x'], env: { GRAFANA_URL: ODIN_REDACTED }, headers: {}, cwd: '', tool_allowlist: [], timeout_seconds: 120, enabled: true },
        Remote: { transport: 'http', url: ODIN_REDACTED, headers: { Authorization: ODIN_REDACTED }, env: {} },
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
      presets: { odin: { name: 'Odin' }, mine: { name: 'My preset', identity: 'I am', voice: 'calm' } },
      builtin_presets: ['odin'], user_presets: ['mine']
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

function desktop(answers: Record<string, unknown> = {}) {
  const defaults: Record<string, unknown> = {
    'memory.list': { global: { keys: ['shared_b'], count: 1 } },
    'skills.list': [{ name: 'existing_skill' }],
    'mcp.status': { revision: 'rev-mcp', servers: [] },
    'personality.get': { user_presets: [], builtin_presets: ['odin'] },
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
  const requests: Array<{ method: string; params: Record<string, unknown> }> = []
  const broker: ImportBroker = {
    request: vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
      requests.push({ method, params })
      const answer = method in defaults ? defaults[method] : { ok: true }
      if (answer instanceof Error) return { ok: false as const, error: { code: 'bad_request', message: answer.message } }
      return { ok: true as const, result: answer }
    })
  }
  return { broker, requests }
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
      'http://odin.test:3002/api/config', 'http://odin.test:3002/api/memory',
      'http://odin.test:3002/api/personality', 'http://odin.test:3002/api/skills'
    ])
    for (const call of odin.calls) {
      expect(call.init.headers.Authorization).toBe('Bearer tok-123')
      expect(call.init.redirect).toBe('error')
    }
    expect(requests.every((r) => ['memory.list', 'skills.list', 'mcp.status', 'personality.get', 'hosts.list'].includes(r.method))).toBe(true)
  })

  it('suggests new things, leaves replacements unticked and explains what needs finishing', async () => {
    const preview = await previewOdinImport(SOURCE, desktop().broker, odinApi().fetchImpl)
    if (!preview.ok) throw new Error(preview.error.message)
    const item = (category: string, id: string) => preview.result.items.find((i) => i.category === category && i.id === id)!
    expect(item('memory', 'global')).toMatchObject({ selected: true, detail: '2 entries' })
    expect(item('memory', 'user_42')).toMatchObject({ selected: false })
    expect(item('skills', 'weather')).toMatchObject({ selected: true, exists: false })
    expect(item('skills', 'existing_skill')).toMatchObject({ selected: false, exists: true })
    expect(item('mcp', 'Grafana').notes.join(' ')).toContain('GRAFANA_URL')
    expect(item('mcp', 'bad-name')).toMatchObject({ selected: false })
    expect(item('hosts', 'server')).toMatchObject({ selected: true, detail: 'root@192.168.1.13' })
    expect(item('hosts', 'legacy')).toMatchObject({ selected: false, detail: 'me@10.0.0.9:2222' })
    expect(preview.result.items.some((i) => i.category === 'hosts' && i.id === 'localhost')).toBe(false)
    expect(item('personality', 'active')).toMatchObject({ selected: false, detail: 'My preset' })
    expect(item('models', 'main')).toMatchObject({ selected: false, detail: 'gpt-6.1-sol · high' })
    expect(item('models', 'agent_effort').detail).toBe('Automatic')
    expect(item('models', 'timezone').detail).toBe('America/New_York')
  })

  it('turns failures into plain messages and never echoes the token', async () => {
    const cases: Array<[Record<string, unknown>, RegExp]> = [
      [{ '/api/memory': 401 }, /didn't accept this token/],
      [{ '/api/config': new Error('ECONNREFUSED') }, /Couldn't reach Odin at http:\/\/odin\.test:3002/],
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
})

describe('applyOdinImport', () => {
  const pick = (category: string, id: string) => ({ category, id }) as never

  it('writes memory, skills, MCP servers and presets through the core, skipping what exists', async () => {
    const { broker, requests } = desktop()
    const report = await applyOdinImport(SOURCE, [
      pick('memory', 'global'), pick('memory', 'user_42'), pick('skills', 'weather'), pick('skills', 'existing_skill'),
      pick('mcp', 'Grafana'), pick('mcp', 'Remote'), pick('personality', 'mine')
    ], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    const outcome = (id: string) => report.result.outcomes.find((o) => o.id === id)!
    expect(requests.filter((r) => r.method === 'memory.set').map((r) => r.params)).toEqual([
      { scope: 'global', key: 'shared_a', value: 'A' }, { scope: 'global', key: 'mine', value: 'M' }
    ])
    expect(outcome('global')).toMatchObject({ status: 'imported', message: '1 entry added, 1 already there.' })
    expect(requests.find((r) => r.method === 'skills.save')?.params).toEqual({ name: 'weather', code: 'def run():\n    return 1\n', create: true })
    expect(requests.find((r) => r.method === 'skills.config.set')?.params).toEqual({ name: 'weather', config: { units: 'metric' } })
    expect(outcome('weather')).toMatchObject({ status: 'needs_attention' })
    expect(outcome('weather').message).toContain('api_key')
    expect(outcome('existing_skill').status).toBe('skipped')
    const mcp = requests.find((r) => r.method === 'mcp.save')!.params
    expect(mcp).toMatchObject({ name: 'Grafana', create: true, enabled: false, expected_revision: 'rev-mcp', command: '/usr/local/bin/mcp-grafana', args: ['-x'] })
    expect(mcp).not.toHaveProperty('env_set')
    expect(outcome('Grafana')).toMatchObject({ status: 'needs_attention' })
    expect(outcome('Remote')).toMatchObject({ status: 'needs_attention' })
    expect(requests.filter((r) => r.method === 'mcp.save')).toHaveLength(1)
    expect(requests.find((r) => r.method === 'personality.presets.save')?.params).toEqual({ name: 'mine', display_name: 'My preset', identity: 'I am', voice: 'calm' })
  })

  it("pins a host by Odin's key fingerprint and hands back Desktop's key when it can't sign in", async () => {
    const { broker, requests } = desktop()
    const report = await applyOdinImport(SOURCE, [pick('hosts', 'server')], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(requests.find((r) => r.method === 'hosts.prepare')?.params).toMatchObject({
      alias: 'server', address: '192.168.1.13', ssh_user: 'root', trust_mode: 'pinned', expected_fingerprints: [FINGERPRINT]
    })
    expect(requests.some((r) => r.method === 'hosts.commit')).toBe(false)
    expect(report.result.outcomes[0]).toMatchObject({ status: 'needs_attention' })
    expect(report.result.public_key).toBe('ssh-ed25519 DESKTOPKEY desktop')
  })

  it('commits a host that passes the connection test', async () => {
    const { broker, requests } = desktop({ 'hosts.test': { tested: true }, 'hosts.commit': { saved: true } })
    const report = await applyOdinImport(SOURCE, [pick('hosts', 'server')], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(requests.find((r) => r.method === 'hosts.commit')?.params).toEqual({ token: 'cand-1' })
    expect(report.result.outcomes[0]).toMatchObject({ status: 'imported' })
    expect(report.result.public_key).toBeUndefined()
  })

  it('sets model choices through the methods and revisions the core names for each setting', async () => {
    const { broker, requests } = desktop()
    const report = await applyOdinImport(SOURCE, [
      pick('models', 'main'), pick('models', 'agents'), pick('models', 'agent_effort'), pick('models', 'max_agents'), pick('models', 'timezone')
    ], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(report.result.outcomes.every((o) => o.status === 'imported')).toBe(true)
    expect(requests.find((r) => r.method === 'models.main.set')?.params).toEqual({ model: 'gpt-6.1-sol', reasoning_effort: 'high', expected_revision: 'rev-settings' })
    expect(requests.find((r) => r.method === 'models.agents.set')?.params).toMatchObject({ model: 'auto', expected_revision: 'rev-settings' })
    expect(requests.find((r) => r.method === 'providers.codex.set')?.params).toEqual({ expected_revision: 'rev-settings', changes: [{ path: 'openai_codex.agent_reasoning_effort', value: 'auto' }] })
    expect(requests.filter((r) => r.method === 'settings.set').map((r) => r.params.changes)).toEqual([
      [{ path: 'agents.max_concurrent_agents', value: 15 }], [{ path: 'timezone', value: 'America/New_York' }]
    ])
  })

  it('reports refusals per item and picks Odin no longer has', async () => {
    const { broker } = desktop({ 'skills.save': new Error('Skill code failed validation') })
    const report = await applyOdinImport(SOURCE, [pick('skills', 'weather'), pick('skills', 'gone')], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(report.result.outcomes).toEqual([
      expect.objectContaining({ id: 'weather', status: 'failed', message: 'Skill code failed validation' }),
      expect.objectContaining({ id: 'gone', status: 'failed' })
    ])
  })
})

describe('applyOdinImport edges', () => {
  const pick = (category: string, id: string) => ({ category, id }) as never

  it('refuses an address it cannot parse before sending anything', async () => {
    const odin = odinApi()
    const preview = await previewOdinImport({ url: 'not a url', token: 't' }, desktop().broker, odin.fetchImpl)
    expect(preview.ok).toBe(false)
    if (!preview.ok) expect(preview.error.message).toBe('Enter an http:// or https:// address.')
    expect(odin.calls).toHaveLength(0)
  })

  it('skips a server Desktop already has and reports memory it could not save', async () => {
    const { broker } = desktop({ 'mcp.status': { revision: 'r', servers: [{ name: 'Grafana' }] }, 'memory.set': new Error('nope') })
    const preview = await previewOdinImport(SOURCE, broker, odinApi().fetchImpl)
    if (!preview.ok) throw new Error(preview.error.message)
    expect(preview.result.items.find((i) => i.id === 'Grafana')).toMatchObject({ exists: true, selected: false })
    const report = await applyOdinImport(SOURCE, [pick('mcp', 'Grafana'), pick('memory', 'global')], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(report.result.outcomes).toEqual([
      expect.objectContaining({ id: 'global', status: 'failed', message: "0 entries added, 1 already there, 1 couldn't be saved." }),
      expect.objectContaining({ id: 'Grafana', status: 'skipped' })
    ])
  })

  it("makes Odin's current personality Desktop's, importing its preset first", async () => {
    const { broker, requests } = desktop()
    const report = await applyOdinImport(SOURCE, [pick('personality', 'active')], broker, odinApi().fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(requests.map((r) => r.method).filter((m) => m.startsWith('personality.'))).toEqual(['personality.get', 'personality.presets.save', 'personality.set'])
    expect(requests.find((r) => r.method === 'personality.set')?.params).toEqual({ preset: 'mine' })
    expect(report.result.outcomes[0]).toMatchObject({ status: 'imported' })
    const refused = await applyOdinImport(SOURCE, [pick('personality', 'active')], desktop({ 'personality.presets.save': new Error('no') }).broker, odinApi().fetchImpl)
    if (!refused.ok) throw new Error(refused.error.message)
    expect(refused.result.outcomes[0]).toMatchObject({ status: 'failed', message: 'no' })
    const custom = odinApi({ '/api/personality': { preset: 'custom', custom_name: 'Raven', custom_identity: 'i', custom_voice: 'v', presets: {}, user_presets: [] } })
    const { broker: second, requests: seen } = desktop({ 'personality.set': new Error('rejected') })
    const set = await applyOdinImport(SOURCE, [pick('personality', 'active')], second, custom.fetchImpl)
    if (!set.ok) throw new Error(set.error.message)
    expect(seen.find((r) => r.method === 'personality.set')?.params).toEqual({ preset: 'custom', custom_name: 'Raven', custom_identity: 'i', custom_voice: 'v' })
    expect(set.result.outcomes[0]).toMatchObject({ status: 'failed', message: 'rejected' })
  })

  it("reports one item's Odin error without stopping the rest, and stops when Odin refuses the token", async () => {
    const odin = odinApi({ '/api/skills/weather': 404 })
    const report = await applyOdinImport(SOURCE, [pick('skills', 'weather'), pick('models', 'context')], desktop().broker, odin.fetchImpl)
    if (!report.ok) throw new Error(report.error.message)
    expect(report.result.outcomes).toEqual([
      expect.objectContaining({ id: 'weather', status: 'failed', message: expect.stringMatching(/Odin answered 404/) }),
      expect.objectContaining({ id: 'context', status: 'imported' })
    ])
    const refused = await applyOdinImport(SOURCE, [pick('skills', 'weather')], desktop().broker, odinApi({ '/api/memory': 403 }).fetchImpl)
    expect(refused.ok).toBe(false)
  })
})

describe('import schemas', () => {
  it('accept an http(s) address and a token, and refuse credentials in the address or unknown categories', () => {
    expect(odinImportPreviewSchema.safeParse({ url: 'http://localhost:3002', token: 't' }).success).toBe(true)
    expect(odinImportPreviewSchema.safeParse({ url: 'ftp://host', token: 't' }).success).toBe(false)
    expect(odinImportPreviewSchema.safeParse({ url: 'not a url', token: 't' }).success).toBe(false)
    expect(odinImportPreviewSchema.safeParse({ url: 'http://user:pw@host', token: 't' }).success).toBe(false)
    expect(odinImportPreviewSchema.safeParse({ url: 'http://host', token: '' }).success).toBe(false)
    expect(odinImportApplySchema.safeParse({ url: 'http://host', token: 't', picks: [{ category: 'skills', id: 'x' }] }).success).toBe(true)
    expect(odinImportApplySchema.safeParse({ url: 'http://host', token: 't', picks: [{ category: 'other', id: 'x' }] }).success).toBe(false)
    expect(odinImportApplySchema.safeParse({ url: 'http://host', token: 't', picks: [] }).success).toBe(false)
  })
})
