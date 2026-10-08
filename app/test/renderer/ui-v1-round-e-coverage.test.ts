import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConfigField } from '../../src/shared/api'
import { settingsControlId } from '../../src/renderer/src/settings-accessibility'
import { flush, mount, type Host, type Mounted } from './component-host'

const ok = (result: unknown) => ({ ok: true, result })
const field = (path: string, desired: unknown, extra = {}): ConfigField => ({
  path, desired, effective: desired, type: typeof desired, enum: null, constraints: {},
  sensitivity: 'public', apply_handler: 'providers.compat.set', apply_state: 'applied',
  nullable: false, configured: null, ...extra
} as ConfigField)
let mounted: Mounted | undefined
let bridge: Record<string, ReturnType<typeof vi.fn>>
const id = (root: Host, value: string) => root.findAll((node) => node.props.id === value)[0]!
const modelControl = (root: Host, path: string) => id(root, settingsControlId('curated', path))

beforeEach(() => {
  vi.resetModules()
  bridge = {
    codexAccounts: vi.fn(async () => ok({ configured: true, accounts: [] })),
    modelsStatus: vi.fn(async () => ok({ model_catalogue: { codex: [{ ref: 'gpt-6.1-sol', effort_capabilities: { values: ['high'] } }] } })),
    openrouterCatalogue: vi.fn(async () => ok({ recognized: false, models: [], quick_add: [] })),
    settingsSchema: vi.fn(), providersCompatSet: vi.fn(), editLeaf: vi.fn(async () => ok({ status: 'updated' })),
    memoryList: vi.fn(async () => ok({ global: { count: 2, keys: ['first', 'second'] } })),
    memoryGet: vi.fn(async () => ok({ scope: 'global', entries: { first: 'one', second: 'two' } })),
    memoryDelete: vi.fn(async () => ok({ status: 'deleted' })),
    listsList: vi.fn(async () => ok({ items: [] })),
    knowledgeList: vi.fn(async () => ok([])),
    knowledgeSearch: vi.fn(async () => ok([{ source: 'guide.md', chunk_id: 7, score: 0.9, content: 'A matching passage' }]))
  }
  vi.stubGlobal('window', { odin: bridge })
  vi.stubGlobal('document', { activeElement: null })
})
afterEach(() => { mounted?.unmount(); mounted = undefined; vi.unstubAllGlobals() })

async function models() {
  const { settings } = await import('../../src/renderer/src/stores/settings')
  settings.meta = {
    revision: 'r1', schema_version: 1,
    fields: [
      field('llm_provider.model', 'gpt-6.1-sol', { apply_handler: 'models.main.set', apply_state: 'invalid' }),
      field('openai_codex.reasoning_effort', 'high', { apply_state: 'drift' }),
      field('openai_compatible.enabled', true),
      field('openai_compatible.preset', 'generic', { enum: ['generic', 'openrouter'] }),
      field('openai_codex.auxiliary.model', 'gpt-6.1-sol'),
      field('openai_codex.auxiliary.enabled', false),
      field('agents.model', 'auto', { apply_handler: 'models.agents.set' }),
      field('agents.auto_model_allowlist', ['gpt-6.1-sol'], { type: 'array', apply_handler: 'models.agents.set' }),
      field('openai_codex.agent_reasoning_effort', 'high')
    ], status: { counts: {}, desired_revision: 'r1', effective_revision: null }
  }
  bridge.settingsSchema!.mockImplementation(async () => ok(settings.meta))
  bridge.providersCompatSet!.mockImplementation(async ({ changes }) => ok({ revision: 'r2', fields: changes.map(({ path, value }: { path: string; value: unknown }) => ({ ...settings.meta!.fields.find((item) => item.path === path), desired: value, effective: value })) }))
  mounted = mount((await import('../../src/renderer/src/components/CodexAccounts.vue')).default)
  await flush()
  return { root: mounted.root, settings }
}

describe('Round E coverage remediation through renderer actions', () => {
  it('retries an account read error and a stale account list without pretending either read succeeded', async () => {
    bridge.codexAccounts!.mockResolvedValueOnce({ ok: false, error: { code: 'bridge_error', message: 'Account read failed' } })
    const { root, settings } = await models()
    expect(root.textContent()).toContain('Account read failed')
    root.button('Retry accounts').fire('click'); await flush()
    expect(bridge.codexAccounts).toHaveBeenCalledTimes(2)
    expect(settings.codex.error).toBe('')
    settings.codex.stale = true; await flush()
    expect(root.textContent()).toContain("couldn't be refreshed")
    root.button('Refresh').fire('click'); await flush()
    expect(bridge.codexAccounts).toHaveBeenCalledTimes(3)
    expect(settings.codex.stale).toBe(false)
  })

  it('renders actionable saved-value warnings, saves a provider enum and cancels auxiliary drafts locally', async () => {
    const { root } = await models()
    expect(root.textContent()).toContain('This saved value is invalid. Correct it and save again.')
    expect(root.textContent()).toContain('The running value differs from the saved value.')
    root.named('Configure OpenAI-compatible').fire('click'); await flush()
    modelControl(root, 'openai_compatible.preset').fire('change', { target: { value: 'openrouter' } }); await flush()
    root.button('Save OpenAI-compatible setup').fire('click'); await flush()
    expect(bridge.providersCompatSet).toHaveBeenCalledExactlyOnceWith({ expected_revision: 'r1', changes: [{ path: 'openai_compatible.preset', value: 'openrouter' }] })
    modelControl(root, 'openai_codex.auxiliary.model').type('unsaved-model'); await flush()
    root.button('Cancel auxiliary changes').fire('click'); await flush()
    expect(modelControl(root, 'openai_codex.auxiliary.model').value).toBe('gpt-6.1-sol')
    expect(bridge.editLeaf).not.toHaveBeenCalled()
  })

  it('rejects a blank main choice and unsupported agent effort without sending either change', async () => {
    const { root } = await models()
    modelControl(root, 'llm_provider.model').fire('change', { target: { value: '' } }); await flush()
    id(root, 'main-model-actions').button('Save').fire('click'); await flush()
    expect(root.textContent()).toContain('Enter a model.')
    modelControl(root, 'openai_codex.agent_reasoning_effort').fire('change', { target: { value: 'unsupported' } }); await flush()
    expect(bridge.editLeaf).not.toHaveBeenCalled()
    expect(bridge.providersCompatSet).not.toHaveBeenCalled()
  })

  it('preserves an off-provider fixed agent selection and saves the canonical chosen reference', async () => {
    const { root } = await models()
    modelControl(root, 'agents.model').fire('change', { target: { value: 'fixed' } }); await flush()
    expect(modelControl(root, 'agents.model').options.map((node) => [node.props.value, node.props.disabled])).toEqual([['gpt-6.1-sol', true]])
    expect(root.textContent()).toContain('Codex is off. This saved selection is kept.')
    modelControl(root, 'agents.model').fire('change', { target: { value: 'gpt-6.1-sol' } }); await flush()
    id(root, 'agent-model-actions').button('Save').fire('click'); await flush()
    expect(bridge.editLeaf).toHaveBeenCalledExactlyOnceWith({ method: 'models.agents.set', params: { model: 'gpt-6.1-sol', expected_revision: 'r1' } })
  })

  it('refuses invalid provider enum drafts and leaves the saved setup unchanged', async () => {
    const { root, settings } = await models()
    root.named('Configure OpenAI-compatible').fire('click'); await flush()
    modelControl(root, 'openai_compatible.preset').fire('change', { target: { value: 'unsupported-preset' } }); await flush()
    root.button('Save OpenAI-compatible setup').fire('click'); await flush()
    expect(root.textContent()).toContain('Choose one of generic, openrouter.')
    expect(bridge.providersCompatSet).not.toHaveBeenCalled()
    expect(settings.meta!.fields.find((item) => item.path === 'openai_compatible.preset')!.desired).toBe('generic')
  })

  it('converts a rejected sign-in refresh transport into a visible failure and releases account controls', async () => {
    bridge.codexAccounts!.mockResolvedValue(ok({ configured: true, accounts: [{ index: 0, account_id: 'acct-test', email: 'test@example.test', is_current: true, expired: true }] }))
    bridge.codexRefresh = vi.fn().mockRejectedValue(new Error('test-only rejected transport'))
    const { root, settings } = await models()
    root.named('More actions for test@example.test').fire('click'); await flush()
    root.named('Refresh sign-in: test@example.test').fire('click'); await flush()
    const { management } = await import('../../src/renderer/src/stores/management')
    expect(bridge.codexRefresh).toHaveBeenCalledExactlyOnceWith({ index: 0 })
    expect(root.textContent()).toContain('The bridge could not return a result.')
    expect(settings.codex.busy).toBe(false)
    expect(management.busy['codex-refresh']).toBe(false)
    expect(root.named('More actions for test@example.test').props.disabled).toBe(false)
  })

  it('selects a memory key via its checkbox and deletes only that confirmed key', async () => {
    mounted = mount((await import('../../src/renderer/src/views/settings/State.vue')).default); await flush()
    const root = mounted.root
    root.named('Open Everywhere memory').fire('click'); await flush()
    const pick = root.findAll((node) => node.props['aria-label'] === 'Pick first in Everywhere memory')[0]!
    pick.checked = true; pick.fire('change'); await flush()
    root.named('Delete 1 picked in Everywhere memory…').fire('click'); await flush()
    const { dialog } = await import('../../src/renderer/src/dialog')
    expect(dialog.current?.title).toBe('Delete 1 entry?')
    dialog.current!.resolve(true); await flush()
    expect(bridge.memoryDelete).toHaveBeenCalledExactlyOnceWith({ scope: 'global', key: 'first' })
    expect(root.findAll((node) => node.tag === 'button' && String(node.props['aria-label']).startsWith('Delete 1 picked'))).toHaveLength(0)
  })

  it('renders returned knowledge hits and clears a typed document draft without ingesting', async () => {
    mounted = mount((await import('../../src/renderer/src/views/settings/State.vue')).default); await flush()
    const root = mounted.root
    id(root, 'knowledge-search').type('matching'); await flush()
    expect(bridge.knowledgeSearch).toHaveBeenCalledExactlyOnceWith({ q: 'matching', limit: 20 })
    expect(root.textContent()).toContain('A matching passage')
    expect(root.textContent()).toContain('score 0.9')
    id(root, 'knowledge-source').type('draft.md')
    id(root, 'knowledge-content').type('Unsent document'); await flush()
    root.named('Cancel document draft').fire('click'); await flush()
    expect(id(root, 'knowledge-source').value).toBe('')
    expect(id(root, 'knowledge-content').value).toBe('')
  })
})
