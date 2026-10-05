// Tools, skills and MCP servers against the fixture core, over the real broker, in the shapes of Odin's routes.
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it } from 'vitest'
import type { ConfigMeta, McpStatus, SkillSummary, ToolInventory } from '../src/shared/api'
import { Broker } from '../src/main/broker'
import { startFixture, waitFor } from './fixture-harness'

const cleanups: Array<() => Promise<void> | void> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
})

type Ok<T> = { ok: true; result: T }

async function connect() {
  const core = await startFixture()
  cleanups.push(() => core.stop())
  const broker = new Broker({
    socketPath: core.paths.socketPath,
    readToken: () => readFileSync(core.paths.tokenPath, 'utf8').trim(),
    profileId: 'default',
    clientVersion: 'test',
    reconnectDelaysMs: [50]
  })
  broker.connect()
  cleanups.push(() => broker.close())
  await waitFor(() => broker.linkState === 'ready')
  const read = async <T>(method: string, params: Record<string, unknown> = {}): Promise<T> =>
    ((await broker.request(method, params)) as Ok<T>).result
  const command = (method: string, params: Record<string, unknown>) => {
    const id = crypto.randomUUID()
    return broker.request(method, params, id)
  }
  return { read, command }
}

describe('built-in tools', () => {
  it("lists every tool with what the model sees, and switches one off and on", async () => {
    const { read, command } = await connect()
    const inventory = await read<ToolInventory>('tools.list')
    const state = (name: string) => inventory.tools.find((t) => t.name === name)?.state
    expect(state('run_command')).toBe('available')
    expect(state('email_send')).toBe('disabled')
    expect(state('computer_act')).toBe('unavailable') // hidden while computer use is off, as in Odin
    const off = (await command('tools.set_enabled', { name: 'web_search', enabled: false })) as Ok<ToolInventory>
    expect(off.result.tools.find((t) => t.name === 'web_search')).toMatchObject({ enabled: false, state: 'disabled' })
    expect(off.result.disabled_count).toBe(2)
    expect(await command('tools.set_enabled', { name: 'no_such_tool', enabled: false })).toMatchObject({ ok: false, error: { code: 'not_found' } })
  })

  it('keeps per-tool timeouts in one place, refuses bad ones, and settings.set leaves them to their own method', async () => {
    const { read, command } = await connect()
    expect(await read('tools.timeouts.get')).toEqual({ default_timeout: 300, overrides: { run_command: 900 } })
    expect(await command('tools.timeouts.set', { overrides: { run_command: 0 } })).toMatchObject({
      ok: false,
      error: { message: "invalid timeout for 'run_command': must be a positive integer" }
    })
    expect(await command('tools.timeouts.set', { overrides: { generate_image: 600 }, default_timeout: 120 })).toEqual({
      ok: true,
      result: { default_timeout: 120, overrides: { generate_image: 600 } }
    })
    const meta = await read<ConfigMeta>('settings.schema')
    const field = meta.fields.find((f) => f.path === 'tools.tool_timeouts')!
    expect(field).toMatchObject({ desired: { generate_image: 600 }, apply_handler: 'tools.timeouts.set' })
    expect(await command('settings.set', { expected_revision: meta.revision, changes: [{ path: field.path, value: {} }] })).toMatchObject({
      ok: false,
      error: { message: 'tools.tool_timeouts: changed through tools.timeouts.set' }
    })
  })
})

describe('skills', () => {
  it('validates by compiling, never running, and refuses to save code that fails', async () => {
    const { read, command } = await connect()
    expect(await read('skills.validate', { code: 'def broken(:\n' })).toMatchObject({ valid: false, errors: [expect.stringMatching(/^Syntax error at line 1/)] })
    expect(await read('skills.validate', { code: 'SKILL_DEFINITION = {}\ndef execute(inp, context):\n    return 1\n' })).toMatchObject({
      valid: true,
      warnings: [expect.stringMatching(/not async/)]
    })
    expect(await command('skills.save', { name: 'bad', code: 'x = 1\n', create: true })).toMatchObject({
      ok: false,
      error: { message: expect.stringMatching(/^Skill 'bad' failed to load: SKILL_DEFINITION is missing/) }
    })
  })

  it('creates, refuses a duplicate, turns off and on, tests, configures and deletes a skill', async () => {
    const { read, command } = await connect()
    const code = 'SKILL_DEFINITION = {"name": "hello"}\nasync def execute(inp, context):\n    return "hi"\n'
    expect(await command('skills.save', { name: 'hello', code, create: true })).toEqual({ ok: true, result: { result: "Skill 'hello' created." } })
    expect(await command('skills.save', { name: 'hello', code, create: true })).toMatchObject({ ok: false, error: { message: "Skill 'hello' already exists." } })
    const listed = await read<SkillSummary[]>('skills.list')
    expect(listed.map((s) => [s.name, s.status])).toEqual([['weather', 'loaded'], ['broken_sync', 'error'], ['hello', 'loaded']])
    expect(listed.find((s) => s.name === 'broken_sync')!.diagnostics).toEqual([{ level: 'error', message: expect.stringMatching(/Syntax error/) }])
    await command('skills.set_enabled', { name: 'hello', enabled: false })
    expect(await command('skills.test', { name: 'hello' })).toEqual({ ok: true, result: { result: "Skill 'hello' is disabled.", is_error: true } })
    await command('skills.set_enabled', { name: 'hello', enabled: true })
    expect(await command('skills.test', { name: 'hello' })).toEqual({ ok: true, result: { result: 'hello ran with empty input: fine.', is_error: false } })
    expect(await command('skills.config.set', { name: 'weather', config: { units: 'kelvin' } })).toMatchObject({ ok: false, error: { message: 'units: must be one of metric, imperial' } })
    expect(await command('skills.config.set', { name: 'weather', config: { units: 'imperial' } })).toEqual({ ok: true, result: { config: { units: 'imperial', days: 3 } } })
    expect(await read('skills.config.get', { name: 'weather' })).toMatchObject({ config: { units: 'imperial' }, schema: { properties: { days: { maximum: 14 } } } })
    expect(await command('skills.delete', { name: 'hello' })).toEqual({ ok: true, result: { result: "Skill 'hello' deleted." } })
    expect(await command('skills.test', { name: 'hello' })).toMatchObject({ ok: false, error: { code: 'not_found' } })
  })
})

describe('MCP servers', () => {
  it('reports servers with secret names only, never values, and a masked URL', async () => {
    const { read } = await connect()
    const status = await read<McpStatus>('mcp.status')
    expect(status).toMatchObject({ enabled: true, server_count: 2, connected_count: 1, published_tool_count: 3, max_published_tools_per_server: 40 })
    const grafana = status.servers.find((s) => s.name === 'Grafana')!
    expect(grafana).toMatchObject({ transport: 'http', state: 'disabled', header_keys: ['Authorization'], url_display: 'https://•••/mcp' })
    expect(JSON.stringify(status)).not.toContain('Bearer secret')
    expect(JSON.stringify(status)).not.toContain('/srv/lmms')
  })

  it("adds a server with Odin's checks, keeps what an edit leaves out, and takes secrets only as patches", async () => {
    const { read, command } = await connect()
    expect(await command('mcp.save', { name: '9lives', create: true, transport: 'stdio', command: '/bin/true' })).toMatchObject({
      ok: false,
      error: { message: expect.stringMatching(/letters, digits, underscores, no leading digit/) }
    })
    expect(await command('mcp.save', { name: 'tools_box', create: true, transport: 'stdio' })).toMatchObject({
      ok: false,
      error: { message: "tools_box: stdio transport requires 'command'" }
    })
    expect(await command('mcp.save', { name: 'tools_box', create: true, transport: 'stdio', command: '/opt/box', env_set: { TOKEN: 'xyz' } })).toEqual({
      ok: true,
      result: { saved: true, connected: true, state: 'connected', last_error: '' }
    })
    await command('mcp.save', { name: 'tools_box', create: false, timeout_seconds: 90, env_remove: ['TOKEN'], env_set: { MODE: 'fast' } })
    const row = (await read<McpStatus>('mcp.status')).servers.find((s) => s.name === 'tools_box')!
    expect(row).toMatchObject({ state: 'connected', env_keys: ['MODE'] }) // the command stayed: the edit didn't send it
    expect(await command('mcp.save', { name: 'tools_box', create: false, env_set: { MODE: '••••••••' } })).toMatchObject({
      ok: false,
      error: { message: 'env_set contains a redaction mask; secrets must be re-entered' }
    })
  })

  it('switches servers and MCP itself on and off, sets limits, and removes a server', async () => {
    const { read, command } = await connect()
    expect(await command('mcp.set_enabled', { name: 'Grafana', enabled: true })).toMatchObject({ ok: true, result: { state: 'connected' } })
    const off = (await command('mcp.set_global_enabled', { enabled: false })) as Ok<McpStatus>
    expect(off.result).toMatchObject({ enabled: false, connected_count: 0, published_tool_count: 0 })
    await command('mcp.set_global_enabled', { enabled: true })
    expect(await command('mcp.set_limits', { max_published_tools_per_server: 128 })).toMatchObject({ ok: true, result: { max_published_tools_per_server: 128, max_published_tools_global: 40 } })
    expect(await read('mcp.tools', { name: 'LMMS' })).toMatchObject({
      server: 'LMMS',
      tools: expect.arrayContaining([expect.objectContaining({ published_name: 'mcp_LMMS_create_track', published: true })])
    })
    expect(await command('mcp.delete', { name: 'LMMS' })).toMatchObject({ ok: true, result: { state: 'removed' } })
    expect((await read<McpStatus>('mcp.status')).server_count).toBe(1)
  })
})
