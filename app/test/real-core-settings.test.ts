import { randomUUID } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { createServer, type Server } from 'node:http'
import { join } from 'node:path'
import { afterEach, describe, expect, test } from 'vitest'
import type { Broker, Settled } from '../src/main/broker'
import type { CoreEvent } from '../src/shared/api'
import { assertIsolated, RealCoreHarness, SERVED_CAPABILITIES, waitFor } from './real-core-harness'

assertIsolated()

type Field = { path: string; desired: unknown; effective: unknown; configured: boolean | null;
  sensitivity: string; apply_state: string; apply_handler: string; secret_route: string | null }
type Schema = { revision: string; fields: Field[]; status: { keyring_error: string | null };
  image_models_revision: string }
type Status = { phase: string; model: { main: string | null; provider: string | null };
  providers: { name: string; health: string }[] }
function result<T = unknown>(answer: Settled): T {
  expect(answer.ok, JSON.stringify(answer)).toBe(true)
  if (!answer.ok) throw new Error(`Expected success, received ${answer.error.code}`)
  return answer.result as T
}
function refused(answer: Settled, code: string, disposition = 'rejected'): void {
  expect(answer).toMatchObject({ ok: false, error: { code, disposition } })
}
async function schema(broker: Broker, id?: string): Promise<Schema> {
  return result<Schema>(await broker.request('settings.schema', {}, id))
}
function field(view: Schema, path: string): Field {
  const row = view.fields.find((item) => item.path === path)
  expect(row, path).toBeDefined()
  return row!
}

describe('served settings/management through actual Broker and isolated repository core', () => {
  let core: RealCoreHarness | undefined
  let server: Server | undefined
  afterEach(async () => {
    await core?.dispose()
    if (server) await new Promise<void>((resolve, reject) => server!.close((error) => error ? reject(error) : resolve()))
    server = undefined
  })
  async function connect(memoryKeyring = false, authBaseUrl?: string): Promise<Broker> {
    core = new RealCoreHarness({ memoryKeyring, authBaseUrl })
    await core.start()
    return (await core.connect()).broker
  }
  async function set(broker: Broker, method: string, path: string, value: unknown): Promise<Schema> {
    const before = await schema(broker)
    result(await broker.request(method, { expected_revision: before.revision, changes: [{ path, value }] }))
    return schema(broker)
  }
  async function localService(handler: (request: import('node:http').IncomingMessage, response: import('node:http').ServerResponse) => void): Promise<string> {
    server = createServer(handler)
    await new Promise<void>((resolve) => server!.listen(0, '127.0.0.1', resolve))
    const address = server.address()
    if (!address || typeof address === 'string') throw new Error('Missing isolated server port')
    return `http://127.0.0.1:${address.port}`
  }

  test('fresh real profile publishes only served names, local/default host, empty stores and unknown usage', async () => {
    const broker = await connect()
    result(await broker.request('events.subscribe', { after: null }))
    expect(result(await broker.request('status.get'))).toMatchObject({ phase: 'ready', capabilities: SERVED_CAPABILITIES,
      model: { main: expect.any(String), provider: 'codex' },
      providers: expect.arrayContaining([{ name: 'codex', health: 'unavailable' }]) })
    const hosts = result<{ hosts: unknown[]; default_host: string }>(await broker.request('hosts.list'))
    expect(hosts.default_host).toBe('localhost')
    expect(hosts.hosts).toEqual([expect.objectContaining({ alias: 'localhost', address: '127.0.0.1', active: true,
      targetable: true, trust_state: 'local' })])
    const memory = result<Record<string, { keys: string[]; count: number }>>(await broker.request('memory.list'))
    expect(memory).toEqual({ global: { keys: [], count: 0 } })
    expect(result(await broker.request('memory.get', { scope: 'global' }))).toEqual({ scope: 'global', entries: {} })
    refused(await broker.request('memory.get', { scope: 'absent_scope' }), 'not_found')
    expect(result(await broker.request('lists.list'))).toEqual({ items: [] })
    expect(result(await broker.request('knowledge.list'))).toEqual([])
    expect(result(await broker.request('audit.query'))).toEqual([])
    expect(result(await broker.request('logs.search'))).toEqual({ entries: [], count: 0 })
    expect(result(await broker.request('turn_state.list'))).toMatchObject({ schema_version: 1, availability: 'available', data: {} })
    expect(result(await broker.request('usage.get', { period: '7d' }))).toMatchObject({ period: '7d', tokens: { value: null, kind: 'unknown' },
      context: { used: { value: null, kind: 'unknown' }, budget: { value: null, kind: 'unknown' } }, quota: [] })
    expect(result(await broker.request('audit.verify'))).toMatchObject({ valid: false, verified: 0, availability: 'not_enabled' })
    expect(result(await broker.request('health.get'))).toMatchObject({ overall: expect.any(String),
      components: expect.any(Array), total: expect.any(Number), checked_at: expect.any(String) })
    result(await broker.request('runtime.reload', { scope: 'context' }))
    refused(await broker.request('usage.get', { period: 'invalid' }), 'bad_request')
    expect(result(await broker.request('conversations.list'))).toMatchObject({ items: [], watermark: expect.any(String) })
    expect(result(await broker.request('skills.list'))).toEqual([])
    expect(result(await broker.request('work.list'))).toEqual({ items: [] })
    expect(result(await broker.request('schedules.list'))).toEqual([])
    expect(result(await broker.request('schedules.history'))).toEqual([])
    expect(result(await broker.request('mcp.list'))).toMatchObject({ server_count: 0, started: true })
    expect(result(await broker.request('computer.status'))).toMatchObject({ readiness: {
      foreground_available: false, input_supported: false, dispatch: 'none' } })
    for (const method of ['turns.create', 'loops.list', 'agents.list', 'shell.execute']) {
      expect(SERVED_CAPABILITIES).not.toContain(method)
      refused(await broker.request(method), 'capability_unavailable')
    }
  })

  test('schema reads stay fresh; writes bind revisions and command IDs, emit real changes and persist across restart', async () => {
    const broker = await connect()
    const readId = randomUUID()
    const before = await schema(broker, readId)
    const events: CoreEvent[] = []
    broker.on('event', (event: CoreEvent) => events.push(event))
    result(await broker.subscribe())
    const id = randomUUID()
    const params = { expected_revision: before.revision, changes: [{ path: 'tools.enabled', value: false }] }
    const saved = await broker.request('settings.set', params, id)
    const changed = result<Schema>(saved)
    expect(changed.revision).not.toBe(before.revision)
    await waitFor(() => events.some((event) => event.type === 'settings.changed'), 'real settings change event')
    expect(events.find((event) => event.type === 'settings.changed')).toMatchObject({ payload: { rev: changed.revision,
      paths: expect.arrayContaining(['tools.enabled']) } })
    expect(field(await schema(broker, readId), 'tools.enabled')).toMatchObject({ desired: false, effective: false })
    expect(await broker.request('settings.set', params, id)).toEqual(saved)
    refused(await broker.request('settings.set', { ...params, changes: [{ path: 'tools.enabled', value: true }] }, id), 'id_conflict')
    refused(await broker.request('settings.set', { ...params, changes: [{ path: 'tools.enabled', value: true }] }), 'stale_binding', 'stale_binding')
    expect(await core!.parentEOF()).toEqual({ code: 0, signal: null })
    broker.close()
    await core!.start()
    const restarted = (await core!.connect()).broker
    expect(field(await schema(restarted), 'tools.enabled').desired).toBe(false)
    expect(await restarted.request('settings.set', params, id)).toEqual(saved)
  })

  test('missing keyring is explicit and never confused with service absence or a successful secret write', async () => {
    const broker = await connect()
    const view = await schema(broker)
    expect(view.status.keyring_error).toMatch(/unavailable|locked/i)
    expect(field(view, 'email.smtp.password')).toMatchObject({ configured: null, effective: null,
      apply_state: 'unknown', secret_route: 'secrets.set' })
    refused(await broker.request('codex.accounts.list'), 'keyring_unavailable')
    const secret = 'isolated-missing-vault-canary-92fca'
    const answer = await broker.request('secrets.set', { path: 'email.smtp.password', value: secret })
    refused(answer, 'keyring_unavailable')
    expect(JSON.stringify(answer)).not.toContain(secret)
    expect(core!.persistedFilesContain(secret)).toBe(false)
    expect(core!.diagnostics).not.toContain(secret)
    refused(await broker.request('secrets.get', { path: 'email.smtp.password' }), 'capability_unavailable')
  })

  test('write-only secret set/clear returns no readback in schema, events, receipts, logs or profile files', async () => {
    const broker = await connect(true)
    expect((await schema(broker)).status.keyring_error).toBeNull()
    const secret = 'isolated-vault-canary-28311a'
    const events: CoreEvent[] = []
    broker.on('event', (event: CoreEvent) => events.push(event))
    result(await broker.subscribe())
    const id = randomUUID()
    const params = { path: 'email.smtp.password', value: secret }
    const saved = await broker.request('secrets.set', params, id)
    expect(result(saved)).toEqual({ set: true })
    await waitFor(() => events.some((event) => event.type === 'settings.changed'), 'write-only secret metadata event')
    expect(await broker.request('secrets.set', params, id)).toEqual(saved)
    refused(await broker.request('secrets.set', { ...params, value: `${secret}-changed` }, id), 'id_conflict')
    const view = await schema(broker)
    expect(field(view, params.path)).toMatchObject({ configured: true, secret_route: 'secrets.set' })
    expect(JSON.stringify({ view, events, saved, status: result(await broker.request('status.get')),
      email: result(await broker.request('integrations.email.get')) })).not.toContain(secret)
    expect(core!.persistedFilesContain(secret)).toBe(false)
    expect(core!.diagnostics).not.toContain(secret)
    const before = await schema(broker)
    refused(await broker.request('settings.set', { expected_revision: before.revision, changes: [{ path: params.path, value: secret }] }), 'bad_request')
    expect(result(await broker.request('secrets.clear', { path: params.path }))).toEqual({ set: false })
    expect(field(await schema(broker), params.path).configured).toBe(false)
  })

  test('provider saves are distinct from effective main-model adoption; rejected apply leaves serving identity untouched', async () => {
    const broker = await connect(true)
    await set(broker, 'providers.codex.set', 'openai_codex.enabled', false)
    await set(broker, 'providers.auxiliary.set', 'openai_codex.auxiliary.enabled', false)
    const catalogueBase = await localService((request, response) => {
      response.setHeader('Content-Type', 'application/json')
      if (request.url === '/api/tags') response.end(JSON.stringify({ models: [{ name: 'contract-model' }] }))
      else { response.statusCode = 404; response.end('{}') }
    })
    expect(result(await broker.request('models.discover', { provider: 'ollama', base_url: catalogueBase }))).toEqual({ models: [{ name: 'contract-model' }] })
    // Compat stays disabled, so this is a real save without endpoint probing or key material.
    await set(broker, 'providers.compat.set', 'openai_compatible.model', 'contract-compat')
    const saved = await set(broker, 'providers.ollama.set', 'ollama.model', 'contract-model')
    expect(field(saved, 'ollama.model').desired).toBe('contract-model')
    const beforeApply = result<Status>(await broker.request('status.get'))
    expect(beforeApply.providers).toContainEqual({ name: 'ollama', health: 'disabled' })
    refused(await broker.request('models.main.set', { model: 'ollama:contract-model' }), 'bad_request')
    expect(result<Status>(await broker.request('status.get')).model).toEqual(beforeApply.model)
    await set(broker, 'providers.ollama.set', 'ollama.base_url', 'http://127.0.0.1:1')
    await set(broker, 'providers.ollama.set', 'ollama.enabled', true)
    const before = await schema(broker)
    const adopted = result(await broker.request('models.main.set', { model: 'ollama:contract-model', expected_revision: before.revision }))
    expect(adopted).toMatchObject({ main_model: 'ollama:contract-model', configured_provider: 'ollama' })
    expect(result<Status>(await broker.request('status.get')).model).toMatchObject({ main: 'contract-model', provider: 'ollama' })
    expect(field(await schema(broker), 'llm_provider.model')).toMatchObject({ desired: 'ollama:contract-model',
      effective: 'ollama:contract-model', apply_state: 'applied' })
    expect(result(await broker.request('status.get'))).toMatchObject({ first_run: {
      state: 'effective-ready', reason: 'provider_effective', keyring_unavailable: false
    } }) // Actual ProviderOwner has no guard: no extra success/probe gate is imposed.
    // The real client is adopted without a generation. This proves identity, not endpoint/generation readiness.
    // Persistence classification survives the owner's unpublished-graph rollback.
    refused(await broker.request('models.main.set', { model: 'ollama:another-model', expected_revision: before.revision }), 'stale_binding', 'stale_binding')
    expect(result<Status>(await broker.request('status.get')).model.main).toBe('contract-model')
    const image = await schema(broker)
    result(await broker.request('models.image.intent', { expected_revision: image.image_models_revision, operations: { image_model: 'pin' } }))
    refused(await broker.request('models.image.intent', { expected_revision: 'stale', operations: { image_model: 'follow' } }), 'stale_binding', 'stale_binding')
  })

  test('model agents, personality, tools and timeouts round-trip their real retained owners', async () => {
    const broker = await connect()
    expect(result(await broker.request('models.agents.get'))).toHaveProperty('auto_model_allowlist')
    result(await broker.request('models.agents.set', { model: 'ollama:contract-agent', thinking_mode: 'disabled' }))
    expect(result(await broker.request('models.agents.get'))).toMatchObject({ model: 'ollama:contract-agent', thinking_mode: 'disabled' })
    result(await broker.request('personality.presets.save', { name: 'contract', identity: 'An isolated test persona', voice: 'Brief' }))
    result(await broker.request('personality.set', { preset: 'contract' }))
    expect(result(await broker.request('personality.get'))).toMatchObject({ preset: 'contract', user_presets: ['contract'] })
    result(await broker.request('personality.presets.delete', { name: 'contract' }))
    expect(result(await broker.request('personality.get'))).toMatchObject({ preset: 'odin', user_presets: [] })
    const inventory = result<{ tools: { name: string; state: string }[] }>(await broker.request('tools.list'))
    expect(inventory.tools.length).toBeGreaterThan(10)
    // D17 restores the pinned fresh-install enabled browser. This is its wired
    // retry seam, not proof of a qualified Chromium launch in this source tree.
    expect(field(await schema(broker), 'browser.enabled').desired).toBe(true)
    expect(inventory.tools.find((tool) => tool.name === 'browser_read_page')?.state).toBe('available')
    result(await broker.request('tools.set_enabled', { name: 'browser_read_page', enabled: false }))
    expect(result<{ tools: unknown[] }>(await broker.request('tools.list')).tools).toContainEqual(expect.objectContaining({ name: 'browser_read_page', enabled: false, state: 'disabled' }))
    result(await broker.request('tools.set_enabled', { name: 'browser_read_page', enabled: true }))
    expect(result<{ tools: unknown[] }>(await broker.request('tools.list')).tools).toContainEqual(expect.objectContaining({ name: 'browser_read_page', enabled: true, state: 'available' }))
    result(await broker.request('tools.set_enabled', { name: 'run_command', enabled: false }))
    expect(result<{ tools: unknown[] }>(await broker.request('tools.list')).tools).toContainEqual(expect.objectContaining({ name: 'run_command', enabled: false, state: 'disabled' }))
    const rev = (await schema(broker)).revision
    result(await broker.request('tools.timeouts.set', { expected_revision: rev, default_timeout: 45, overrides: { run_command: 20 } }))
    expect(result(await broker.request('tools.timeouts.get'))).toEqual({ default_timeout: 45, overrides: { run_command: 20 } })
    refused(await broker.request('tools.timeouts.set', { expected_revision: rev, default_timeout: 50 }), 'stale_binding', 'stale_binding')
  })

  test('memory and knowledge writes use the real durable stores; lists read/delete the actual retained list corpus', async () => {
    const broker = await connect()
    result(await broker.request('memory.set', { scope: 'global', key: 'contract', value: 'disposable profile note' }))
    expect(result(await broker.request('memory.get', { scope: 'global', key: 'contract' }))).toEqual({ scope: 'global', key: 'contract', value: 'disposable profile note' })
    expect(result(await broker.request('memory.list'))).toMatchObject({ global: { keys: ['contract'], count: 1 } })
    refused(await broker.request('memory.get', { scope: 'user_someone_else', key: 'contract' }), 'not_found')
    result(await broker.request('memory.set', { scope: 'imported_scope', key: 'retained', value: 'single-owner scope' }))
    expect(result(await broker.request('memory.get', { scope: 'imported_scope', key: 'retained' }))).toEqual({ scope: 'imported_scope', key: 'retained', value: 'single-owner scope' })
    result(await broker.request('memory.delete', { scope: 'imported_scope', key: 'retained' }))
    result(await broker.request('memory.bulk_delete', { entries: [{ scope: 'global', key: 'contract' }] }))
    refused(await broker.request('memory.get', { scope: 'global', key: 'contract' }), 'not_found')
    result(await broker.request('memory.set', { scope: 'global', key: 'delete-me', value: 'temporary' }))
    result(await broker.request('memory.delete', { scope: 'global', key: 'delete-me' }))
    result(await broker.request('knowledge.ingest', { source: 'contract-source', content: 'Uniquecontractword. This disposable document checks retained full text search and durable versions.' }))
    expect(result<unknown[]>(await broker.request('knowledge.list'))).toContainEqual(expect.objectContaining({ source: 'contract-source' }))
    expect(result<unknown[]>(await broker.request('knowledge.search', { q: 'Uniquecontractword' })).length).toBeGreaterThan(0)
    result(await broker.request('knowledge.reingest', { source: 'contract-source' }))
    const versions = result<{ version: number }[]>(await broker.request('knowledge.versions', { source: 'contract-source' }))
    expect(versions.length).toBeGreaterThan(0)
    result(await broker.request('knowledge.restore', { source: 'contract-source', version: versions[0]!.version }))
    result(await broker.request('knowledge.delete', { source: 'contract-source' }))
    expect(result(await broker.request('knowledge.list'))).toEqual([])
    // There is no lists.create management route. Seed its retained on-disk format offline,
    // then exercise the actual read/delete adapters, never a fabricated transport reply.
    expect(await core!.parentEOF()).toEqual({ code: 0, signal: null })
    broker.close()
    writeFileSync(join(core!.paths.dataDir, 'lists.json'), JSON.stringify({ contract: { items: [{ text: 'One real list entry', added_at: '2026-01-01T00:00:00Z' }] } }), { mode: 0o600 })
    await core!.start()
    const restarted = (await core!.connect()).broker
    expect(result(await restarted.request('lists.list'))).toMatchObject({ items: [{ name: 'contract', count: 1 }] })
    expect(result(await restarted.request('lists.get', { name: ' CONTRACT ' }))).toMatchObject({ name: 'contract', items: [{ text: 'One real list entry' }] })
    result(await restarted.request('lists.delete', { name: 'contract' }))
    expect(result(await restarted.request('lists.list'))).toEqual({ items: [] })
  })

  test('hosts/trust settings and local activation round-trip without remote enrollment or an SSH connection', async () => {
    const broker = await connect()
    const key = result<{ public_key: string }>(await broker.request('hosts.public_key'))
    expect(JSON.stringify(key)).toContain('ssh-ed25519')
    expect(JSON.stringify(key)).not.toContain('PRIVATE KEY')
    result(await broker.request('hosts.settings', { default_host: 'localhost', allow_host_tofu: false }))
    expect(result(await broker.request('hosts.list'))).toMatchObject({ default_host: 'localhost', tofu_enabled: false })
    expect(result(await broker.request('hosts.references', { alias: 'localhost' }))).toHaveProperty('references')
    refused(await broker.request('hosts.settings', { default_host: 'missing' }), 'bad_request')
    result(await broker.request('hosts.set_enabled', { alias: 'localhost', enabled: false }))
    expect(result<{ hosts: unknown[] }>(await broker.request('hosts.list')).hosts).toContainEqual(expect.objectContaining({ alias: 'localhost', active: false, targetable: false }))
    result(await broker.request('hosts.set_enabled', { alias: 'localhost', enabled: true }))
    expect(result<{ hosts: unknown[] }>(await broker.request('hosts.list')).hosts).toContainEqual(expect.objectContaining({ alias: 'localhost', active: true, targetable: true }))
  })

  test('records query/search the retained profile corpus and never call unsigned audit data verified', async () => {
    const broker = await connect()
    expect(await core!.parentEOF()).toEqual({ code: 0, signal: null })
    broker.close()
    const rows = [
      { timestamp: '2026-01-01T00:00:00Z', tool_name: 'run_command', user_name: 'contract-owner',
        user_id: 'isolated', tool_input: { host: 'localhost' }, result: 'record alpha', error: null },
      { timestamp: '2026-01-02T00:00:00Z', tool_name: 'read_file', user_name: 'contract-owner',
        user_id: 'isolated', tool_input: { host: 'localhost' }, result: null, error: 'record beta harmless failure' }
    ]
    writeFileSync(join(core!.paths.dataDir, 'audit.jsonl'), rows.map((row) => JSON.stringify(row)).join('\n') + '\n', { mode: 0o600 })
    await core!.start()
    const restarted = (await core!.connect()).broker
    expect(result(await restarted.request('audit.query', { tool: 'read_file', host: 'localhost', q: 'beta' }))).toEqual([rows[1]])
    expect(result(await restarted.request('logs.search', { level: 'error', q: 'beta' }))).toEqual({ entries: [rows[1]], count: 1 })
    expect(result(await restarted.request('audit.verify'))).toMatchObject({ valid: false, verified: 0, availability: 'not_enabled' })
    refused(await restarted.request('logs.search', { level: 'made-up' }), 'bad_request')
  })

  test('email/outbound integrations read real profile settings and save/delete a disabled non-delivering webhook', async () => {
    const broker = await connect(true)
    expect(result(await broker.request('integrations.email.get'))).toMatchObject({ enabled: false })
    await set(broker, 'settings.set', 'email.smtp.host', 'mail.contract.invalid')
    expect(result(await broker.request('integrations.email.get'))).toMatchObject({ smtp: { host: 'mail.contract.invalid' } })
    expect(result(await broker.request('webhooks.outbound.list'))).toMatchObject({ webhook_count: 0, webhooks: [] })
    result(await broker.request('webhooks.outbound.save', {
      name: 'contract', url: 'https://example.com/isolated-contract', enabled: false, events: ['all']
    }))
    const current = result<{ webhooks: { id: string }[] }>(await broker.request('webhooks.outbound.list'))
    expect(current).toMatchObject({ webhook_count: 1, enabled_count: 0, webhooks: [{ name: 'contract', enabled: false }] })
    const id = current.webhooks[0]!.id
    result(await broker.request('webhooks.outbound.delete', { id }))
    expect(result(await broker.request('webhooks.outbound.list'))).toMatchObject({ webhook_count: 0 })
  })

  test('device code pending/authenticated receipts and account label/removal use an isolated local auth service only', async () => {
    let polls = 0
    const requests: string[] = []
    const access = `e30.${Buffer.from(JSON.stringify({ email: 'contract@example.invalid', chatgpt_account_id: 'contract-account' })).toString('base64url')}.isolated-signature`
    const refresh = 'isolated-refresh-token-canary-8263'
    const base = await localService((request, response) => {
      requests.push(request.url!)
      response.setHeader('Content-Type', 'application/json')
      if (request.url === '/device/code') response.end(JSON.stringify({ device_auth_id: 'isolated-device', user_code: 'ABCD-EFGH', interval: 1, expires_in: 30 }))
      else if (request.url === '/device/token') {
        polls++
        if (polls === 1) { response.statusCode = 403; response.end('{}') }
        else response.end(JSON.stringify({ authorization_code: 'isolated-code', code_verifier: 'isolated-verifier' }))
      } else if (request.url === '/oauth/token') response.end(JSON.stringify({ access_token: access, refresh_token: refresh, expires_in: 3600 }))
      else { response.statusCode = 404; response.end('{}') }
    })
    const broker = await connect(true, base)
    await set(broker, 'providers.auxiliary.set', 'openai_codex.auxiliary.enabled', false)
    expect(result(await broker.request('codex.accounts.list'))).toEqual({ configured: false, accounts: [] })
    const begun = result<{ device_auth_id: string; user_code: string; interval: number; verify_url: string }>(await broker.request('codex.login.begin'))
    expect(begun).toEqual({ device_auth_id: 'isolated-device', user_code: 'ABCD-EFGH', interval: 1, verify_url: `${base}/verify` })
    const binding = { device_auth_id: begun.device_auth_id, user_code: begun.user_code }
    refused(await broker.request('codex.login.poll', { ...binding, user_code: 'WRONG' }), 'not_found')
    const pendingId = randomUUID()
    const pending = await broker.request('codex.login.poll', binding, pendingId)
    expect(result(pending)).toEqual({ status: 'pending' })
    expect(polls).toBe(0)
    await new Promise((resolve) => setTimeout(resolve, 1_050))
    expect(result(await broker.request('codex.login.poll', binding))).toEqual({ status: 'pending' })
    expect(polls).toBe(1)
    expect(await broker.request('codex.login.poll', binding, pendingId)).toEqual(pending)
    await new Promise((resolve) => setTimeout(resolve, 1_050))
    const authenticated = result(await broker.request('codex.login.poll', binding))
    expect(authenticated).toEqual({ status: 'authenticated', email: 'contract@example.invalid', account_id: 'contract-account' })
    const accountView = result(await broker.request('codex.accounts.list'))
    expect(accountView).toMatchObject({ configured: true, account_count: 1, accounts: [{ email: 'contract@example.invalid' }] })
    result(await broker.request('codex.accounts.label', { index: 0, label: 'Disposable account' }))
    expect(result(await broker.request('codex.accounts.list'))).toMatchObject({ accounts: [{ label: 'Disposable account' }] })
    expect(result(await broker.request('codex.login.poll', binding))).toEqual(authenticated)
    expect(polls).toBe(2)
    expect(requests).toEqual(['/device/code', '/device/token', '/device/token', '/oauth/token'])
    const visible = JSON.stringify({ begun, authenticated, accountView, status: result(await broker.request('status.get')), schema: await schema(broker) })
    for (const secret of [access, refresh]) {
      expect(visible).not.toContain(secret)
      expect(core!.persistedFilesContain(secret)).toBe(false)
      expect(core!.diagnostics).not.toContain(secret)
    }
    result(await broker.request('codex.accounts.remove', { index: 0 }))
    expect(result(await broker.request('codex.accounts.list'))).toEqual({ configured: false, accounts: [] })
    expect(result(await broker.request('schedules.list'))).toEqual([])
  })
})
