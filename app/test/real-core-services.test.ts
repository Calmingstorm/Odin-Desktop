import { randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { afterEach, describe, expect, test } from 'vitest'
import type { Broker, Settled } from '../src/main/broker'
import { assertIsolated, RealCoreHarness, SERVED_CAPABILITIES } from './real-core-harness'

assertIsolated()
const code = readFileSync(resolve(__dirname, 'harmless-skill.py'), 'utf8')
const fixture = resolve(__dirname, 'harmless-mcp-stdio.py')
type Mcp = { revision: string; enabled: boolean; server_count: number; published_tool_count: number;
  servers: Array<{ name: string; state: string; last_error: string | null; published_count: number }> }
function result<T = unknown>(answer: Settled): T {
  expect(answer, JSON.stringify(answer)).toMatchObject({ ok: true })
  if (!answer.ok) throw new Error(answer.error.code)
  return answer.result as T
}
const refused = (answer: Settled, code: string): void => { expect(answer).toMatchObject({ ok: false, error: { code } }) }

describe('real 6A services through the app Broker, private profiles only', () => {
  let core: RealCoreHarness
  afterEach(async () => { await core?.dispose() })
  async function connect(keyring = false): Promise<Broker> {
    core = new RealCoreHarness({ memoryKeyring: keyring })
    await core.start()
    return (await core.connect()).broker
  }
  const status = async (broker: Broker): Promise<Mcp> => result<Mcp>(await broker.request('mcp.status'))
  async function mutate(broker: Broker, method: string, params: Record<string, unknown>): Promise<Mcp> {
    return result<Mcp>(await broker.request(method, { ...params, expected_revision: (await status(broker)).revision }, randomUUID()))
  }
  async function connectedServer(broker: Broker, name = 'constant'): Promise<Mcp> {
    const deadline = Date.now() + 8_000
    while (true) {
      const value = await status(broker)
      if (value.servers.find((server) => server.name === name)?.state === 'connected') return value
      if (Date.now() > deadline) throw new Error(`MCP did not connect: ${JSON.stringify(value)} ${core.diagnostics}`)
      await new Promise((accept) => setTimeout(accept, 50))
    }
  }

  test('advertises retained services and validates/saves/tests/reads/edits/enables/deletes a trusted constant', async () => {
    const broker = await connect()
    const observed = result<{ capabilities: string[] }>(await broker.request('status.get'))
    expect(observed.capabilities).toEqual(SERVED_CAPABILITIES)
    expect(observed.capabilities).toContain('skills.test')
    expect(result(await broker.request('skills.list'))).toEqual([])
    expect(result(await broker.request('skills.validate', { code }))).toMatchObject({ valid: true })
    expect(result(await broker.request('skills.validate', { code: 'This is not valid Python.' }))).toMatchObject({ valid: false })
    result(await broker.request('skills.save', { name: 'slice4_constant', code }, randomUUID()))
    expect(result(await broker.request('skills.get', { name: 'slice4_constant' }))).toMatchObject({ code, status: 'loaded' })
    expect(result(await broker.request('skills.list'))).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'slice4_constant', total_executions: 0 })
    ]))
    expect(result(await broker.request('skills.test', { name: 'slice4_constant' }, randomUUID())))
      .toEqual({ result: 'harmless constant', is_error: false })
    expect(result(await broker.request('skills.list'))).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'slice4_constant', total_executions: 1 })
    ]))
    result(await broker.request('skills.set_enabled', { name: 'slice4_constant', enabled: false }, randomUUID()))
    expect(result(await broker.request('skills.get', { name: 'slice4_constant' }))).toMatchObject({ status: 'disabled' })
    expect(result(await broker.request('skills.test', { name: 'slice4_constant' }, randomUUID())))
      .toEqual({ result: "Skill 'slice4_constant' is disabled. Use enable_skill to re-activate it.", is_error: true })
    expect(result(await broker.request('skills.list'))).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'slice4_constant', total_executions: 1 })
    ]))
    result(await broker.request('skills.set_enabled', { name: 'slice4_constant', enabled: true }, randomUUID()))
    const edited = code.replace('harmless constant', 'another harmless constant')
    result(await broker.request('skills.save', { name: 'slice4_constant', code: edited }, randomUUID()))
    expect(result(await broker.request('skills.get', { name: 'slice4_constant' }))).toMatchObject({ code: edited })
    result(await broker.request('skills.delete', { name: 'slice4_constant' }, randomUUID()))
    expect(result(await broker.request('skills.list'))).toEqual([])
    refused(await broker.request('skills.get', { name: 'slice4_constant' }), 'not_found')
    refused(await broker.request('skills.test', { name: 'slice4_constant' }, randomUUID()), 'not_found')
  })

  test('retains failed startup module cards instead of inventing ready skills, and deletes them through the real manager', async () => {
    core = new RealCoreHarness()
    // Establish actual owner identity before introducing any profile state.
    await core.start()
    await core.parentEOF()
    const directory = join(core.paths.dataDir, 'skills')
    mkdirSync(directory, { recursive: true, mode: 0o700 })
    writeFileSync(join(directory, 'broken_constant.py'), 'def broken(\n', { mode: 0o600 })
    await core.start()
    const { broker } = await core.connect()
    const cards = result<Array<{ name: string; status: string }>>(await broker.request('skills.list'))
    expect(cards).toEqual(expect.arrayContaining([expect.objectContaining({ name: 'broken_constant', status: 'error', total_executions: 0 })]))
    refused(await broker.request('skills.get', { name: 'broken_constant' }), 'not_found')
    result(await broker.request('skills.delete', { name: 'broken_constant' }, randomUUID()))
    expect(result(await broker.request('skills.list'))).toEqual([])
  })

  test('real stdio initialize/tools-list lifecycle, publication limits, stale mutations and durable no replay', async () => {
    const broker = await connect()
    expect((await status(broker)).server_count).toBe(0)
    await mutate(broker, 'mcp.save', { name: 'constant', transport: 'stdio', command: core.python, args: ['-B', fixture] })
    await mutate(broker, 'mcp.set_global_enabled', { enabled: true })
    const connected = await connectedServer(broker)
    expect(connected.servers[0]).toMatchObject({ state: 'connected', published_count: 1 })
    const tools = result<{ name: string; tools: Array<{ original_name: string }> }>(await broker.request('mcp.tools', { name: 'constant' }))
    expect(tools.name).toBe('constant')
    expect(JSON.stringify(tools.tools)).toContain('constant')
    await mutate(broker, 'mcp.refresh_tools', { name: 'constant' })
    await mutate(broker, 'mcp.reconnect', { name: 'constant' })
    await connectedServer(broker)
    const staleRevision = (await status(broker)).revision
    await mutate(broker, 'mcp.set_limits', { max_published_tools_per_server: 10, max_published_tools_global: 20 })
    const id = randomUUID()
    const staleParams = { name: 'constant', enabled: false, expected_revision: staleRevision }
    const stale = await broker.request('mcp.set_enabled', staleParams, id)
    refused(stale, 'stale_binding')
    expect(await broker.request('mcp.set_enabled', staleParams, id)).toEqual(stale)
    expect((await status(broker)).servers[0]).toMatchObject({ state: 'connected' })
    refused(await broker.request('mcp.set_enabled', { ...staleParams, expected_revision: (await status(broker)).revision }, id), 'id_conflict')
    refused(await broker.request('mcp.save', { name: 'constant', create: true, expected_revision: (await status(broker)).revision }), 'bad_request')
    await mutate(broker, 'mcp.set_enabled', { name: 'constant', enabled: false })
    expect((await status(broker)).servers[0]).toMatchObject({ state: 'disabled', published_count: 0 })
    await mutate(broker, 'mcp.set_enabled', { name: 'constant', enabled: true })
    await connectedServer(broker)
    await mutate(broker, 'mcp.set_global_enabled', { enabled: false })
    expect((await status(broker)).published_tool_count).toBe(0)
    await mutate(broker, 'mcp.delete', { name: 'constant' })
    expect((await status(broker)).server_count).toBe(0)
  })

  test('ephemeral keyring credentials redact server instructions and disk; a relocked vault blocks only its marked server', async () => {
    const broker = await connect(true)
    const secret = 'slice4-ephemeral-sentinel-value'
    const configuredCode = code.replace("    'input_schema':", "    'config_schema': {'type': 'object', 'properties': {'password': {'type': 'string'}}},\n    'input_schema':")
    result(await broker.request('skills.save', { name: 'slice4_constant', code: configuredCode }, randomUUID()))
    const configured = result(await broker.request('skills.config.set', { name: 'slice4_constant', config: { password: secret } }, randomUUID()))
    expect(JSON.stringify(configured)).not.toContain(secret)
    expect(JSON.stringify(result(await broker.request('skills.config.get', { name: 'slice4_constant' })))).not.toContain(secret)
    expect(core.persistedFilesContain(secret)).toBe(false)
    result(await broker.request('skills.delete', { name: 'slice4_constant' }, randomUUID()))
    await mutate(broker, 'mcp.save', { name: 'private_constant', command: core.python, args: ['-B', fixture], env_set: { FIXTURE_SECRET: secret } })
    await mutate(broker, 'mcp.save', { name: 'public_constant', command: core.python, args: ['-B', fixture] })
    await mutate(broker, 'mcp.set_global_enabled', { enabled: true })
    await connectedServer(broker, 'private_constant')
    const publicView = await status(broker)
    expect(JSON.stringify(publicView)).not.toContain(secret)
    expect(core.persistedFilesContain(secret)).toBe(false)
    await core.parentEOF()
    broker.close()
    core.lockKeyring()
    await core.start()
    const next = (await core.connect()).broker
    const after = await connectedServer(next, 'public_constant')
    expect(after.servers.find((server) => server.name === 'private_constant')).toMatchObject({ state: 'unavailable', last_error: expect.stringMatching(/keyring.*unavailable|unavailable.*keyring/i) })
    refused(await next.request('mcp.tools', { name: 'private_constant' }), 'capability_unavailable')
    expect(after.servers.find((server) => server.name === 'public_constant')).toMatchObject({ state: 'connected' })
  })

  test('reports real browser health and unqualified computer envelope; unknown reconcile is bounded and creates no session/input', async () => {
    const broker = await connect()
    const health = result<{ browser: { state: string; ready: boolean; reason: string; retry_available: boolean } }>(await broker.request('health.get'))
    expect(health.browser).toMatchObject({ state: 'disabled', ready: false, retry_available: false })
    const initial = result(await broker.request('computer.status'))
    expect(initial).toMatchObject({ session: null, readiness: { management_available: true, native_qualified: false, foreground_available: false, input_supported: false, dispatch: 'none' } })
    refused(await broker.request('computer.reconcile', { session_id: 'absent-disposable-identity', generation: 1 }, randomUUID()), 'not_found')
    expect(result(await broker.request('computer.status'))).toEqual(initial)
    refused(await broker.request('computer.reconcile', { session_id: 'absent-disposable-identity', generation: 1, acknowledgment: 'not required' }), 'invalid_params')
    refused(await broker.request('computer.act', {}), 'capability_unavailable')
  })

  test('enabled browser with an explicitly absent disposable bundle reports unavailable with next-use retry, never ready', async () => {
    const broker = await connect()
    const schema = result<{ revision: string }>(await broker.request('settings.schema'))
    result(await broker.request('settings.set', { expected_revision: schema.revision, changes: [{ path: 'browser.enabled', value: true }] }, randomUUID()))
    await core.parentEOF()
    broker.close()
    await core.start()
    const next = (await core.connect()).broker
    expect(result<{ browser: unknown }>(await next.request('health.get')).browser).toMatchObject({ state: 'unavailable', ready: false, retry_available: true, reason: expect.any(String) })
    expect(result<{ browser: unknown }>(await next.request('health.get')).browser).toMatchObject({ state: 'unavailable', ready: false, retry_available: true })
  })
})
