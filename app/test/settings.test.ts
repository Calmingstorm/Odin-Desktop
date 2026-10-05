// Settings, secrets, models and Codex accounts against the fixture core, over the real broker.
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it } from 'vitest'
import type { CodexStatus, ConfigField, ConfigMeta } from '../src/shared/api'
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
  const meta = async (): Promise<ConfigMeta> => ((await broker.request('settings.schema')) as Ok<ConfigMeta>).result
  const field = async (path: string): Promise<ConfigField> => (await meta()).fields.find((f) => f.path === path)!
  const command = (method: string, params: Record<string, unknown>) => {
    const id = crypto.randomUUID()
    return broker.request(method, params, id)
  }
  return { broker, meta, field, command }
}

describe("settings, in the shape of Odin's config meta", () => {
  it("describes every field with Odin's apply record, saved and running values apart", async () => {
    const { meta } = await connect()
    const current = await meta()
    expect(current.revision).toMatch(/^[0-9a-f]{16}$/)
    const modes = new Set(current.fields.map((f) => f.apply_mode))
    expect([...modes].sort()).toEqual(['activation_required', 'dormant', 'live_apply', 'live_for_new_work', 'live_read', 'restart'])
    const prompts = current.fields.find((f) => f.path === 'context.directory')!
    expect(prompts).toMatchObject({ type: 'string', apply_mode: 'restart', apply_state: 'applied' })
    expect(prompts.runtime_effect).toMatch(/starts/)
    expect(current.fields.find((f) => f.path === 'openai_codex.request_timeout_seconds')).toMatchObject({
      constraints: { minimum: 30, maximum: 7200 },
      apply_handler: 'providers.codex.set'
    })
    expect(current.image_models).toEqual({
      image_model: { effective: 'gpt-image-2.5-flare', default: 'gpt-image-2.5-flare', status: 'follow' },
      outer_model: { effective: 'gpt-6-astra', default: 'gpt-6-astra', status: 'follow' }
    })
    expect(current.image_models_revision).toMatch(/^[0-9a-f]{16}$/)
    expect(current.fields.find((f) => f.path === 'graceful_degradation.enabled')!.apply_state).toBe('dormant')
    expect(current.fields.find((f) => f.path === 'llm_provider.model')!.apply_handler).toBe('models.main.set')
  })

  it('saves all or nothing, names the field it refuses, and returns the changed records', async () => {
    const { meta, field, command } = await connect()
    const before = await meta()
    const refused = await command('settings.set', {
      expected_revision: before.revision,
      changes: [
        { path: 'timezone', value: 'Europe/Paris' },
        { path: 'agents.max_concurrent_agents', value: 0 }
      ]
    })
    expect(refused).toMatchObject({ ok: false, error: { code: 'bad_request', message: expect.stringMatching(/^agents.max_concurrent_agents:/) } })
    expect((await meta()).revision).toBe(before.revision)
    expect((await field('timezone')).desired).toBe('UTC')

    const saved = (await command('settings.set', {
      expected_revision: before.revision,
      changes: [{ path: 'context.directory', value: 'data/prompts' }]
    })) as Ok<{ revision: string; fields: ConfigField[] }>
    expect(saved.result.revision).not.toBe(before.revision)
    expect(saved.result.fields).toEqual([
      expect.objectContaining({ path: 'context.directory', desired: 'data/prompts', effective: 'data/context', pending_restart: true, apply_state: 'pending_restart' })
    ])
  })

  it('refuses a stale revision, a field with its own method, and an effort the model rejects', async () => {
    const { meta, command } = await connect()
    const { revision } = await meta()
    await command('settings.set', { expected_revision: revision, changes: [{ path: 'timezone', value: 'Asia/Tokyo' }] })
    expect(await command('settings.set', { expected_revision: revision, changes: [{ path: 'timezone', value: 'UTC' }] })).toMatchObject({
      ok: false,
      error: { code: 'stale_binding' }
    })
    const now = (await meta()).revision
    expect(await command('settings.set', { expected_revision: now, changes: [{ path: 'llm_provider.model', value: 'gpt-6-luna' }] })).toMatchObject({
      ok: false,
      error: { message: 'llm_provider.model: changed through models.main.set' }
    })
    expect(
      await command('providers.codex.set', { expected_revision: now, changes: [{ path: 'openai_codex.reasoning_effort', value: 'none' }] })
    ).toMatchObject({ ok: false, error: { message: expect.stringMatching(/^openai_codex.reasoning_effort: gpt-6.1-sol doesn't accept effort none/) } })
  })

  it('keeps secrets write-only: set and cleared, never read back', async () => {
    const { field, command } = await connect()
    expect(await command('secrets.set', { path: 'openai_compatible.api_key', value: 'sk-test-value' })).toEqual({ ok: true, result: { set: true } })
    const set = await field('openai_compatible.api_key')
    expect(set.desired).toBe('••••••••')
    expect(JSON.stringify(set)).not.toContain('sk-test-value')
    expect(await command('secrets.set', { path: 'timezone', value: 'x' })).toMatchObject({ ok: false, error: { code: 'bad_request' } })
    expect(await command('secrets.clear', { path: 'openai_compatible.api_key' })).toEqual({ ok: true, result: { set: false } })
    expect((await field('openai_compatible.api_key')).desired).toBeNull()
  })

  it('changes the main and agent models through their own methods', async () => {
    const { field, command } = await connect()
    expect(await command('models.main.set', { model: 'gpt-6-luna' })).toMatchObject({ ok: true, result: { main_model: 'gpt-6-luna' } })
    expect((await field('llm_provider.model')).desired).toBe('gpt-6-luna')
    expect(await command('models.main.set', { model: 'not-a-model' })).toMatchObject({ ok: false, error: { code: 'bad_request' } })
    expect(await command('models.agents.set', { auto_model_allowlist: ['gpt-6-sol', 'gpt-6-luna'] })).toMatchObject({
      ok: true,
      result: { auto_model_allowlist: ['gpt-6-sol', 'gpt-6-luna'] }
    })
    expect((await field('agents.auto_model_allowlist')).desired).toEqual(['gpt-6-sol', 'gpt-6-luna'])
  })
})

describe("Codex accounts, in the shape of Odin's /api/codex routes", () => {
  it('lists accounts with their quota, and activates, labels and removes one', async () => {
    const { broker, command } = await connect()
    const list = async (): Promise<CodexStatus> => ((await broker.request('codex.accounts.list')) as Ok<CodexStatus>).result
    const first = await list()
    expect(first).toMatchObject({ configured: true, account_count: 2, current_index: 0 })
    expect(first.accounts[1]).toMatchObject({ index: 1, limit_reached: true, quota: { primary: { used_percent: 100, window_minutes: 10080 } } })
    expect(await command('codex.accounts.activate', { index: 1 })).toEqual({ ok: true, result: { status: 'activated', active_index: 1 } })
    expect(await command('codex.accounts.label', { index: 1, label: 'Backup' })).toEqual({ ok: true, result: { status: 'updated', label: 'Backup' } })
    expect((await list()).accounts[1]).toMatchObject({ label: 'Backup', is_current: true })
    expect(await command('codex.accounts.remove', { index: 0 })).toMatchObject({ ok: true, result: { status: 'deleted', email: 'primary@example.com' } })
    expect((await list()).account_count).toBe(1)
    expect(await command('codex.accounts.activate', { index: 5 })).toMatchObject({ ok: false, error: { code: 'bad_request' } })
  })

  it('logs in by device code: pending until approved, then the same answer to a repeated check', async () => {
    const { broker, command } = await connect()
    const begun = (await command('codex.login.begin', {})) as Ok<{ device_auth_id: string; user_code: string; interval: number; verify_url: string }>
    expect(begun.result).toMatchObject({ interval: 1, verify_url: expect.stringMatching(/^https:/) })
    const poll = () => broker.request('codex.login.poll', { device_auth_id: begun.result.device_auth_id, user_code: begun.result.user_code })
    expect(await poll()).toEqual({ ok: true, result: { status: 'pending' } })
    const done = await poll()
    expect(done).toMatchObject({ ok: true, result: { status: 'authenticated', email: 'account3@example.com' } })
    expect(await poll()).toEqual(done)
    expect(((await broker.request('codex.accounts.list')) as Ok<CodexStatus>).result.account_count).toBe(3)
    expect(await broker.request('codex.login.poll', { device_auth_id: 'nope', user_code: 'X' })).toMatchObject({ ok: false, error: { code: 'not_found' } })
  })
})

describe('review round 2: dedicated settings methods have a contract', () => {
  it("save their own fields with settings.set's params and result, and refuse the rest by name", async () => {
    const { meta, field, command } = await connect()
    const before = await meta()
    expect(
      await command('settings.set', { expected_revision: before.revision, changes: [{ path: 'openai_codex.request_timeout_seconds', value: 900 }] })
    ).toMatchObject({ ok: false, error: { message: 'openai_codex.request_timeout_seconds: changed through providers.codex.set' } })
    expect(
      await command('providers.codex.set', { expected_revision: before.revision, changes: [{ path: 'timezone', value: 'Asia/Tokyo' }] })
    ).toMatchObject({ ok: false, error: { message: 'timezone: changed through settings.set' } })
    const saved = (await command('providers.codex.set', {
      expected_revision: before.revision,
      changes: [{ path: 'openai_codex.request_timeout_seconds', value: 900 }]
    })) as Ok<{ revision: string; fields: ConfigField[] }>
    expect(saved.result.revision).not.toBe(before.revision)
    expect(saved.result.fields).toEqual([
      expect.objectContaining({ path: 'openai_codex.request_timeout_seconds', desired: 900, effective: 900, apply_state: 'applied' })
    ])
    expect(await command('providers.codex.set', { expected_revision: before.revision, changes: [] })).toMatchObject({
      ok: false,
      error: { code: 'stale_binding' }
    })
    expect((await field('openai_codex.request_timeout_seconds')).desired).toBe(900)
  })

  it('restore the saved values when applying fails, so saved and running never part', async () => {
    const { meta, field, command } = await connect()
    const before = await meta()
    expect(
      await command('providers.ollama.set', {
        expected_revision: before.revision,
        changes: [
          { path: 'ollama.enabled', value: true },
          { path: 'ollama.base_url', value: 'http://unreachable.lan:11434' }
        ]
      })
    ).toMatchObject({ ok: false, error: { message: expect.stringMatching(/the saved settings were restored/) } })
    expect((await meta()).revision).toBe(before.revision)
    expect((await field('ollama.enabled')).desired).toBe(false)
  })

  it('activate and revoke computer use through its own method', async () => {
    const { meta, field, command } = await connect()
    const on = (await command('computer.activation.set', {
      expected_revision: (await meta()).revision,
      changes: [{ path: 'computer.enabled', value: true }]
    })) as Ok<{ fields: ConfigField[] }>
    expect(on.result.fields[0]).toMatchObject({ path: 'computer.enabled', desired: true, effective: true, apply_state: 'applied' })
    await command('computer.activation.set', { expected_revision: (await meta()).revision, changes: [{ path: 'computer.enabled', value: false }] })
    expect((await field('computer.enabled')).effective).toBe(false)
  })

  it('keep an image model following its default until pinned, even when pinned to the default', async () => {
    const { meta, field, command } = await connect()
    const start = await meta()
    await command('settings.set', { expected_revision: start.revision, changes: [{ path: 'image.openai.image_model', value: 'gpt-image-2.5-flare' }] })
    const same = await meta()
    expect(same.image_models?.image_model.status).toBe('follow') // writing the default keeps following it
    const pinned = (await command('models.image.intent', { expected_revision: same.image_models_revision, operations: { image_model: 'pin' } })) as Ok<{
      image_models: ConfigMeta['image_models']
      image_models_revision: string
      revision: string
    }>
    expect(pinned.result.image_models?.image_model).toEqual({ effective: 'gpt-image-2.5-flare', default: 'gpt-image-2.5-flare', status: 'pin' })
    expect(pinned.result.revision).not.toBe(same.revision)
    expect(pinned.result.image_models_revision).not.toBe(same.image_models_revision)
    expect(
      await command('models.image.intent', { expected_revision: same.image_models_revision, operations: { image_model: 'follow' } })
    ).toMatchObject({ ok: false, error: { code: 'stale_binding' } })
    await command('models.image.intent', { expected_revision: pinned.result.image_models_revision, operations: { image_model: 'follow' } })
    expect((await meta()).image_models?.image_model.status).toBe('follow')
    await command('settings.set', { expected_revision: (await meta()).revision, changes: [{ path: 'image.openai.outer_model', value: 'gpt-6-sol' }] })
    expect((await meta()).image_models?.outer_model).toEqual({ effective: 'gpt-6-sol', default: 'gpt-6-astra', status: 'pin' })
    expect((await field('image.openai.outer_model')).desired).toBe('gpt-6-sol')
  })
})

