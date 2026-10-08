import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConfigField, Conversation, HealthReport } from '../../src/shared/api'
import { flush, mount, type Mounted } from './component-host'

let mounted: Mounted | undefined
beforeEach(() => {
  vi.resetModules()
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
})
afterEach(() => { mounted?.unmount(); mounted = undefined })
const field = (extra: Partial<ConfigField> = {}): ConfigField => ({ path: 'email.password', label: 'Password', description: '', type: 'string', enum: null, constraints: {}, default: '', nullable: false, sensitivity: 'sensitive', apply_mode: 'live_read', apply_handler: 'settings.set', secret_route: 'secrets.set', restart_reason: null, activation_policy: null, consumers: [], save_effect: '', runtime_effect: null, desired: null, effective: null, configured: null, pending_restart: false, apply_state: 'applied', ...extra })

describe('UI v1 source-backed safety edge cases', () => {
  it('does not call the secret bridge when a displayed credential lacks authoritative metadata', async () => {
    const write = vi.fn()
    ;(globalThis as unknown as { window: unknown }).window = { odin: { secretsSet: write } }
    const { settings } = await import('../../src/renderer/src/stores/settings')
    expect(settings.meta).toBeNull()
    mounted = mount((await import('../../src/renderer/src/components/settings/SecretControl.vue')).default, { field: field(), label: 'Mail password' })
    expect(mounted.root.textContent()).toContain('Saved password status is unavailable.')
    mounted.root.find('input')!.type('not-sent')
    await flush()
    mounted.root.named('Store mail password').fire('click')
    await flush()
    expect(write).not.toHaveBeenCalled()
    // Write-only drafts are consumed even when authoritative metadata prevents dispatch.
    expect(mounted.root.find('input')!.value).toBe('')
    expect(settings.fields['email.password']).toBeUndefined()
    mounted.root.find('input')!.type('local-cancel')
    await flush()
    mounted.root.named('Cancel mail password draft').fire('click')
    await flush()
    expect(mounted.root.find('input')!.value).toBe('')
  })
  it('keeps malformed structured budget JSON out of existing rows, then builds a valid local draft', async () => {
    const input = vi.fn()
    const invalid = vi.fn()
    mounted = mount((await import('../../src/renderer/src/components/settings/StructuredSetting.vue')).default, { field: field({ path: 'llm_provider.model_budgets', sensitivity: 'public', type: 'object' }), value: '{malformed', fields: [], dirty: true, kind: 'budgets', onInput: input, onInvalid: invalid })
    expect(mounted.root.textContent()).toContain('No entries yet.')
    mounted.root.find('input')!.type('codex:test')
    await flush()
    mounted.root.button('Add entry').fire('click')
    await flush()
    expect(JSON.parse(input.mock.calls.at(-1)![0])).toEqual({ 'codex:test': '' })
    expect(invalid).toHaveBeenLastCalledWith('Enter a whole number.')
    const budget = mounted.root.findAll((item) => item.tag === 'input' && item.props.type === 'number')[0]!
    budget.type('8192')
    await flush()
    expect(JSON.parse(input.mock.calls.at(-1)![0])).toEqual({ 'codex:test': 8192 })
    expect(invalid).toHaveBeenLastCalledWith('')
    mounted.root.named('Remove codex:test').fire('click')
    await flush()
    expect(JSON.parse(input.mock.calls.at(-1)![0])).toEqual({})
  })
})

describe('UI v1 browser status is observation, never a retry action', () => {
  it.each([
    [false, true, 'Retry availability is not browser readiness.'],
    [true, true, 'Refresh only reads this status.'],
    [false, false, 'it does not launch or qualify a browser.']
  ])('describes ready=%s retry=%s without upgrading readiness', async (ready, retry_available, text) => {
    const { browserRetryNote } = await import('../../src/renderer/src/stores/browser')
    expect(browserRetryNote({ ready, retry_available } as NonNullable<HealthReport['browser']>)).toContain(text)
  })
  it('rejects an older health success and retains the newer failure instead', async () => {
    let settle!: (value: unknown) => void
    const healthGet = vi.fn().mockImplementationOnce(() => new Promise((resolve) => { settle = resolve })).mockResolvedValueOnce({ ok: false, error: { code: 'blocked', message: 'Not authorized' } })
    ;(globalThis as unknown as { window: unknown }).window = { odin: { healthGet } }
    const { browser, loadBrowserStatus } = await import('../../src/renderer/src/stores/browser')
    const old = loadBrowserStatus()
    await loadBrowserStatus()
    settle({ ok: true, result: { browser: { ready: true } } })
    await old
    expect(healthGet).toHaveBeenNthCalledWith(1, {})
    expect(healthGet).toHaveBeenNthCalledWith(2, {})
    expect(browser).toMatchObject({ status: null, error: 'Not authorized', loaded: false, busy: false })
  })
  it('releases busy after transport rejection and allows a subsequent read without a browser projection', async () => {
    const healthGet = vi.fn().mockRejectedValueOnce(new Error('transport')).mockResolvedValueOnce({ ok: true, result: {} })
    ;(globalThis as unknown as { window: unknown }).window = { odin: { healthGet } }
    const { browser, loadBrowserStatus } = await import('../../src/renderer/src/stores/browser')
    await loadBrowserStatus()
    expect(browser).toMatchObject({ error: 'Browser status could not be read.', loaded: false, busy: false })
    await loadBrowserStatus()
    expect(browser).toMatchObject({ status: null, error: '', loaded: true, busy: false })
  })
})

describe('UI v1 Data and privacy conversation management', () => {
  it('opens only the selected conversation and sends revision-bound archive, restore and confirmed delete operations', async () => {
    const conversations: Conversation[] = [
      { id: 'notes', title: 'Private notes', rev: 7, parent_id: null, updated_at: '', unread: 0, archived: false },
      { id: 'other', title: 'Other notes', rev: 3, parent_id: null, updated_at: '', unread: 0, archived: true }
    ]
    const snapshotConversation = vi.fn(async ({ conversation_id }) => ({ ok: true, result: { conversation: conversations.find((item) => item.id === conversation_id), watermark: '1', messages: { items: [], has_more: false }, running: null, queued: [], recent: [], tools: {}, controls: [] } }))
    const updateConversation = vi.fn(async ({ id, archived }) => ({ ok: true, result: { conversation: { ...conversations.find((item) => item.id === id), archived, rev: 8 } } }))
    const deleteConversation = vi.fn(async () => ({ ok: true, result: { deleted: true } }))
    ;(globalThis as unknown as { window: unknown }).window = { odin: {
      memoryList: vi.fn(async () => ({ ok: true, result: { global: { count: 0, keys: [] } } })),
      listsList: vi.fn(async () => ({ ok: true, result: { items: [] } })), knowledgeList: vi.fn(async () => ({ ok: true, result: [] })),
      snapshotConversation, updateConversation, deleteConversation
    } }
    const { state } = await import('../../src/renderer/src/store')
    state.conversations = conversations.map((item) => ({ ...item }))
    state.view = 'settings'
    const { dialog } = await import('../../src/renderer/src/dialog')
    mounted = mount((await import('../../src/renderer/src/views/settings/DataPrivacy.vue')).default)
    await flush()
    mounted.root.button('Conversations').fire('click')
    await flush()
    expect(mounted.root.textContent()).toContain('Saved conversation.')
    expect(mounted.root.textContent()).toContain('Archived conversation.')
    mounted.root.named('Open conversation Private notes').fire('click')
    await flush()
    expect(snapshotConversation).toHaveBeenCalledExactlyOnceWith({ conversation_id: 'notes' })
    expect(state.activeId).toBe('notes')
    expect(state.view).toBe('chat')
    mounted.root.named('Archive conversation Private notes').fire('click')
    await flush()
    expect(updateConversation).toHaveBeenLastCalledWith({ command_id: expect.any(String), id: 'notes', expected_rev: 7, archived: true })
    mounted.root.named('Restore conversation Private notes').fire('click')
    await flush()
    expect(updateConversation).toHaveBeenLastCalledWith({ command_id: expect.any(String), id: 'notes', expected_rev: 8, archived: false })
    mounted.root.named('Delete conversation Private notes…').fire('click')
    await flush()
    expect(dialog.current?.message).toContain('Other conversations are not changed.')
    dialog.current!.resolve(null)
    await flush()
    expect(deleteConversation).not.toHaveBeenCalled()
    mounted.root.named('Delete conversation Private notes…').fire('click')
    await flush()
    dialog.current!.resolve(true)
    await flush()
    expect(deleteConversation).toHaveBeenCalledExactlyOnceWith({ command_id: expect.any(String), id: 'notes', expected_rev: 8 })
    expect(state.conversations.map((item) => item.id)).toEqual(['other'])
  })
})
