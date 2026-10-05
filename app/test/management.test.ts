// Tools, skills and MCP servers against the fixture core, over the real broker, in the shapes of Odin's routes.
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it } from 'vitest'
import type { ConfigMeta, HostCandidate, HostList, McpStatus, ScheduleRow, ScheduleRun, SkillSummary, ToolInventory, WorkItem } from '../src/shared/api'
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

describe('hosts and trust', () => {
  const fingerprintOf = async (read: <T>(m: string, p?: Record<string, unknown>) => Promise<T>, command: (m: string, p: Record<string, unknown>) => Promise<unknown>, address: string) => {
    // The fixture's scan is deterministic: a first TOFU look shows the key it would pin.
    await command('hosts.settings', { allow_host_tofu: true })
    const look = (await command('hosts.prepare', { alias: 'peek', address, ssh_user: 'u', trust_mode: 'tofu' })) as Ok<HostCandidate>
    void read
    return look.result.fingerprints[0]!
  }

  it("lists hosts in Odin's shape, and saves the default host and trust-on-first-use with Odin's checks", async () => {
    const { read, command } = await connect()
    const list = await read<HostList>('hosts.list')
    expect(list).toMatchObject({ default_host: 'localhost', tofu_enabled: false })
    expect(list.hosts.map((h) => [h.alias, h.trust_mode, h.targetable])).toEqual([['localhost', 'local', true], ['build_box', 'pinned', true]])
    expect(await command('hosts.settings', { default_host: 'nowhere' })).toMatchObject({ ok: false, error: { message: 'default_host must name a configured host' } })
    expect(await command('hosts.settings', { default_host: '' })).toMatchObject({ ok: true, result: { new_default_host: '' } }) // every command names its host
    expect(await read('hosts.public_key')).toMatchObject({ fingerprint: expect.stringMatching(/^SHA256:/), restart_pending: false })
  })

  it('adds a pinned host only after the key matches and the connection test passes', async () => {
    const { read, command } = await connect()
    const base = { alias: 'gpu_box', address: '10.0.0.9', ssh_user: 'odin', trust_mode: 'pinned' }
    expect(await command('hosts.prepare', base)).toMatchObject({ ok: false, error: { message: 'expected_fingerprints is required' } })
    expect(await command('hosts.prepare', { ...base, expected_fingerprints: ['SHA256:' + 'A'.repeat(43)] })).toMatchObject({
      ok: false,
      error: { message: 'scanned host key does not match the expected fingerprint' }
    })
    const right = await fingerprintOf(read, command, '10.0.0.9')
    const candidate = (await command('hosts.prepare', { ...base, expected_fingerprints: [right] })) as Ok<HostCandidate>
    expect(candidate.result).toMatchObject({ alias: 'gpu_box', trust_mode: 'pinned', tested: false, fingerprints: [right] })
    expect(await command('hosts.commit', { token: candidate.result.candidate_token })).toMatchObject({
      ok: false,
      error: { message: 'candidate must pass the connection test before activation' }
    })
    expect(await command('hosts.test', { token: candidate.result.candidate_token })).toMatchObject({ ok: true, result: { tested: true } })
    expect(await command('hosts.commit', { token: candidate.result.candidate_token })).toMatchObject({ ok: true, result: { result: 'saved', alias: 'gpu_box' } })
    expect((await read<HostList>('hosts.list')).hosts.map((h) => h.alias)).toContain('gpu_box')
  })

  it('trusts on first use only when allowed, and only with a second confirmation bound to the scanned key', async () => {
    const { command } = await connect()
    const base = { alias: 'pi', address: '10.0.0.30', ssh_user: 'pi', trust_mode: 'tofu' }
    expect(await command('hosts.prepare', base)).toMatchObject({ ok: false, error: { message: 'TOFU is disabled by configuration' } })
    await command('hosts.settings', { allow_host_tofu: true })
    const look = (await command('hosts.prepare', base)) as Ok<HostCandidate>
    await command('hosts.test', { token: look.result.candidate_token })
    expect(await command('hosts.commit', { token: look.result.candidate_token })).toMatchObject({
      ok: false,
      error: { message: 'TOFU candidate requires a second confirmation bound to its exact fingerprints' }
    })
    expect(await command('hosts.prepare', { ...base, candidate_fingerprints: look.result.fingerprints })).toMatchObject({
      ok: false,
      error: { message: 'TOFU requires confirm_tofu=true bound to the exact candidate_fingerprints' }
    })
    const confirmed = (await command('hosts.prepare', { ...base, candidate_fingerprints: look.result.fingerprints, confirm_tofu: true })) as Ok<HostCandidate>
    await command('hosts.test', { token: confirmed.result.candidate_token })
    expect(await command('hosts.commit', { token: confirmed.result.candidate_token })).toMatchObject({ ok: true, result: { alias: 'pi' } })
  })

  it('asks before a local target, reports a failed test, and refuses to delete a host that something still names', async () => {
    const { read, command } = await connect()
    expect(await command('hosts.prepare', { alias: 'self', address: '127.0.0.1', ssh_user: 'me', trust_mode: 'pinned', expected_fingerprints: [] })).toMatchObject({
      ok: false,
      error: { message: 'local targets execute inside Odin and require confirm_local=true' }
    })
    const right = await fingerprintOf(read, command, 'unreachable.lan')
    const candidate = (await command('hosts.prepare', {
      alias: 'far', address: 'unreachable.lan', ssh_user: 'u', trust_mode: 'pinned', expected_fingerprints: [right]
    })) as Ok<HostCandidate>
    expect(await command('hosts.test', { token: candidate.result.candidate_token })).toMatchObject({
      ok: true,
      result: { tested: false, error: 'connection refused' }
    })
    expect(await read('hosts.references', { alias: 'localhost' })).toEqual({ alias: 'localhost', references: [{ kind: 'default_host', location: 'tools.default_host' }] })
    expect(await command('hosts.delete', { alias: 'localhost' })).toMatchObject({ ok: false, error: { message: expect.stringMatching(/blocked by configured references/) } })
    expect(await command('hosts.delete', { alias: 'build_box' })).toMatchObject({ ok: true, result: { alias: 'build_box' } })
    expect(await command('hosts.set_enabled', { alias: 'localhost', enabled: false })).toMatchObject({ ok: true })
    expect((await read<HostList>('hosts.list')).hosts[0]).toMatchObject({ alias: 'localhost', enabled: false, targetable: false })
    expect(await command('hosts.force_revoke', { alias: 'localhost' })).toMatchObject({ ok: true, result: { result: 'revoked', processes: { killed: 0 } } })
  })
})

describe('schedules', () => {
  const later = (seconds: number) => new Date(Date.now() + seconds * 1000).toISOString()

  it("creates each kind with Odin's checks and messages", async () => {
    const { read, command } = await connect()
    const conversation = ((await command('conversations.create', { title: 'Reports' })) as Ok<{ conversation: { id: string } }>).result.conversation.id
    const refusal = async (params: Record<string, unknown>) => ((await command('schedules.save', params)) as { error: { message: string } }).error.message
    expect(await refusal({ action: 'reminder', cron: '0 9 * * *' })).toBe('description and channel_id are required')
    expect(await refusal({ description: 'x', action: 'reminder', channel_id: conversation })).toBe('Either cron or run_at is required')
    expect(await refusal({ description: 'x', action: 'check', channel_id: conversation, cron: '0 9 * * *' })).toBe("tool_name is required for 'check' actions")
    expect(await refusal({ description: 'x', action: 'check', channel_id: conversation, cron: '0 9 * * *', tool_name: 'web_search' })).toMatch(
      /^Tool 'web_search' is not allowed for scheduled checks\. Allowed: run_command, run_command_multi, run_script$/
    )
    expect(await refusal({ description: 'x', action: 'reminder', channel_id: conversation, cron: '0 9 * * *', report_format: 'paginated_embed_v1' })).toBe(
      "report_format is only valid for 'check' actions"
    )
    expect(await refusal({ description: 'x', action: 'workflow', channel_id: conversation, cron: '0 9 * * *', steps: [{ tool_input: {} }] })).toBe(
      "Step 0: must be a dict with 'tool_name'"
    )
    expect(await refusal({ description: 'x', action: 'webhook', cron: '0 9 * * *', webhook_config: { url: 'ftp://nope' } })).toBe(
      'webhook_config.url must be an http or https URL'
    )
    expect(await refusal({ description: 'x', action: 'reminder', channel_id: conversation, run_at: '2026-10-05T09:00:00' })).toMatch(/needs its UTC offset/)
    const check = (await command('schedules.save', {
      description: 'Disk check', action: 'check', channel_id: conversation, cron: '*/30 * * * *', tool_name: 'run_command',
      tool_input: { host: 'localhost', command: 'df -h' }, report_format: 'paginated_embed_v1'
    })) as Ok<ScheduleRow>
    expect(check.result).toMatchObject({ id: expect.stringMatching(/^[0-9a-f]{8}$/), one_time: false, timezone: 'UTC', max_retries: 0, retry_backoff_seconds: 60 })
    const reminder = (await command('schedules.save', { description: 'Stretch', action: 'reminder', channel_id: conversation, run_at: later(3600) })) as Ok<ScheduleRow>
    expect(reminder.result).toMatchObject({ one_time: true, message: 'Stretch', cron: null })
    expect((await read<ScheduleRow[]>('schedules.list')).map((s) => s.description)).toEqual(['Post the daily status to the dashboard', 'Disk check', 'Stretch'])
    expect((await read<{ items: WorkItem[] }>('work.list', { kind: 'schedule' })).items.map((i) => i.title)).toContain('Disk check')
    expect(await read('schedules.validate_cron', { expression: '0 9 * * 1-5' })).toMatchObject({ valid: true, next_runs: expect.any(Array) })
    expect(await command('schedules.validate_cron', { expression: 'every day' })).toMatchObject({ ok: false, error: { code: 'bad_request' } })
  })

  it('changes only what it is given, keeps the action, and lets new timing replace the old', async () => {
    const { command } = await connect()
    expect(await command('schedules.save', { id: '5d0a7c21', action: 'reminder' })).toMatchObject({ ok: false, error: { message: "A schedule's action is set when it is created" } })
    const changed = (await command('schedules.save', { id: '5d0a7c21', description: 'Post the status', run_at: later(600) })) as Ok<ScheduleRow>
    expect(changed.result).toMatchObject({ description: 'Post the status', action: 'webhook', cron: null, one_time: true, webhook_config: { method: 'POST' } })
    const paused = (await command('schedules.save', { id: '5d0a7c21', paused: true })) as Ok<ScheduleRow>
    expect(paused.result).toMatchObject({ paused: true, description: 'Post the status' })
  })

  it("runs on demand with Odin's answers and history, counts failures, and resets them", async () => {
    const { read, command } = await connect()
    const hook = (await command('schedules.save', {
      description: 'Ping a dead hook', action: 'webhook', cron: '0 * * * *', webhook_config: { url: 'https://hooks.example.net/fail' }
    })) as Ok<ScheduleRow>
    expect(await command('schedules.run', { id: hook.result.id })).toEqual({
      ok: true,
      result: { status: 'failure', schedule_id: hook.result.id, error: 'HTTP 500 from the webhook' }
    })
    const failing = (await read<ScheduleRow[]>('schedules.list')).find((s) => s.id === hook.result.id)!
    expect(failing).toMatchObject({ consecutive_failures: 1, last_error: 'HTTP 500 from the webhook' })
    expect(await read<ScheduleRun[]>('schedules.history', { id: hook.result.id })).toEqual([
      expect.objectContaining({ schedule_id: hook.result.id, action: 'webhook', status: 'failure', duration_ms: expect.any(Number), error: 'HTTP 500 from the webhook' })
    ])
    expect(await command('schedules.reset_failures', { id: hook.result.id })).toMatchObject({ ok: true, result: { consecutive_failures: 0, last_error: null } })
    await command('schedules.save', { id: '5d0a7c21', paused: true })
    expect(await command('schedules.run', { id: '5d0a7c21' })).toMatchObject({
      ok: true,
      result: { status: 'success', warning: 'schedule is paused — this was a manual override' }
    })
    expect(await command('schedules.delete', { id: hook.result.id })).toEqual({ ok: true, result: { status: 'deleted' } })
    expect(await command('schedules.run', { id: hook.result.id })).toMatchObject({ ok: false, error: { code: 'not_found' } })
  })

  it('goes inert when its one-time run passes while paused, refuses to run, and re-arms with a new time', async () => {
    const { read, command } = await connect()
    const conversation = ((await command('conversations.create', { title: 'Later' })) as Ok<{ conversation: { id: string } }>).result.conversation.id
    const once = (await command('schedules.save', { description: 'Once', action: 'reminder', channel_id: conversation, run_at: later(1) })) as Ok<ScheduleRow>
    await command('schedules.save', { id: once.result.id, paused: true })
    await new Promise((r) => setTimeout(r, 1300))
    const inert = (await read<ScheduleRow[]>('schedules.list')).find((s) => s.id === once.result.id)!
    expect(inert.inert_reason).toMatch(/passed while it was paused/)
    expect((await read<{ items: WorkItem[] }>('work.list', { kind: 'schedule' })).items.find((i) => i.id === once.result.id)).toMatchObject({ state: 'inert', actions: [] })
    expect(await command('schedules.run', { id: once.result.id })).toMatchObject({ ok: false, error: { message: expect.stringMatching(/passed while it was paused/) } })
    const rearmed = (await command('schedules.save', { id: once.result.id, run_at: later(3600) })) as Ok<ScheduleRow>
    expect(rearmed.result.inert_reason).toBeNull()
  })
})

