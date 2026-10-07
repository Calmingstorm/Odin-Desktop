// Renderer reducers consume contracts emitted by real Python domain services.
import { execFileSync } from 'node:child_process'
import { readFileSync, readlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConversationSnapshot, CoreEvent, ToolOutputPage } from '../../src/shared/api'
import { appendPage, type OutputView } from '../../src/renderer/src/tool-output'

const root = resolve(process.cwd(), '..')
// Keep this renderer project independent of main-process TypeScript modules,
// but require the exact same real-core isolation boundary before Python starts.
function assertIsolated(): string {
  const home = process.env.ODIN_REAL_CORE_ROOT
  const outer = process.env.ODIN_REAL_CORE_OUTER_PID_NS
  if (process.platform !== 'linux' || !process.getuid || process.getuid() === 0 ||
      !outer || readlinkSync('/proc/self/ns/pid') === outer ||
      !home?.startsWith(join(tmpdir(), 'odrc-')) || process.env.HOME !== home) {
    throw new Error('Renderer real-core contracts require npm run test:real-core isolation, never the ordinary unit gate.')
  }
  const init = readFileSync('/proc/1/cmdline', 'utf8').split('\0')
  if (!init.includes(join(root, 'app/scripts/real-core-isolation.mjs')) || !init.includes('--inside-run')) {
    throw new Error('Renderer real-core namespace is not owned by the isolation runner.')
  }
  for (const [key, leaf] of Object.entries({ XDG_CONFIG_HOME: 'config', XDG_DATA_HOME: 'data', XDG_CACHE_HOME: 'cache', XDG_RUNTIME_DIR: 'run' })) {
    if (process.env[key] !== join(home, leaf)) throw new Error(`Unsafe ${key}`)
  }
  return home
}
const home = assertIsolated()
// Bound corpus generation under CI load; assertions, product deadlines and isolation checks stay unchanged.
const corpus = JSON.parse(execFileSync(process.env.ODIN_DESKTOP_ENGINE_PYTHON || join(root, '.venv/bin/python'),
  [resolve(process.cwd(), 'test/renderer/core-chat-contract.py')],
  { cwd: root, env: {
    PATH: '/usr/local/bin:/usr/bin:/bin', LANG: 'C.UTF-8', HOME: home,
    XDG_CONFIG_HOME: join(home, 'config'), XDG_DATA_HOME: join(home, 'data'),
    XDG_CACHE_HOME: join(home, 'cache'), XDG_RUNTIME_DIR: join(home, 'run'),
    PYTHONPATH: root, PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1'
  }, encoding: 'utf8', timeout: 120_000 }))
type Store = typeof import('../../src/renderer/src/store')
let store: Store

beforeEach(async () => {
  vi.resetModules()
  store = await import('../../src/renderer/src/store')
  store.state.activeId = corpus.initial.conversation.id
  store.state.conversations = [corpus.initial.conversation]
  store.state.app = { link: 'ready', coreInstanceId: 'contract', noTray: false, unreceipted: 0 }
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: { snapshotConversation: async () => ({ ok: true, result: corpus.initial }) }
  }
  await store.loadConversation(store.state.activeId!)
})

describe('real desktop chat contracts', () => {
  it('projects request queue message identity and guarded replies without any draft event', () => {
    const id = corpus.initial.conversation.id
    const view = store.state.views[id]!
    for (const event of corpus.before_reply as CoreEvent[]) store.applyEvent(event)
    expect(view.messages.map((m) => m.role)).toEqual(['user'])
    expect(view.queued).toEqual(corpus.after_reply.queued)
    expect(view.queued[0]?.message_id).toBe(corpus.admitted.message_id)
    expect(view.tools).toEqual(corpus.after_reply.tools)
    for (const event of corpus.reply_events as CoreEvent[]) store.applyEvent(event)
    expect(view.messages).toEqual(corpus.after_reply.messages.items)
    expect(view.messages.find((m) => m.role === 'assistant')?.text).toBe('Committed needle')
    const length = view.messages.length
    for (const event of corpus.reply_events as CoreEvent[]) store.applyEvent(event)
    expect(view.messages).toHaveLength(length)
  })

  it('holds real events during snapshot catch-up and applies only above its watermark', async () => {
    const id = corpus.initial.conversation.id
    let release!: (answer: unknown) => void
    window.odin.snapshotConversation = vi.fn(() => new Promise((r) => { release = r })) as typeof window.odin.snapshotConversation
    const pending = store.loadConversation(id)
    for (const event of [...corpus.before_reply, ...corpus.reply_events]) store.applyEvent(event)
    release({ ok: true, result: corpus.after_reply as ConversationSnapshot })
    await pending
    expect(store.state.views[id]!.messages).toEqual(corpus.after_reply.messages.items)
    expect(store.canAct(id)).toBe(true)
  })

  it('preserves real child inheritance/reset notices and applies CRUD revisions', async () => {
    const id = corpus.initial.conversation.id
    window.odin.createConversation = vi.fn(async () => ({ ok: true as const, result: corpus.child }))
    window.odin.snapshotConversation = vi.fn(async () => ({ ok: true as const, result: corpus.child_snapshot }))
    await store.startThread(id, corpus.admitted.message_id)
    expect(window.odin.createConversation).toHaveBeenCalledWith(expect.objectContaining({ parent_id: id, from_message_id: corpus.admitted.message_id }))
    expect(store.state.conversations.find((c) => c.parent_id === id)?.inherited_from).toEqual(corpus.child.conversation.inherited_from)
    for (const event of [...corpus.before_reply, ...corpus.reply_events, ...corpus.reset_events]) store.applyEvent(event)
    expect(store.state.views[id]!.messages.at(-1)?.text).toBe('Model context reset.')
    expect(store.state.views[id]!.messages.some((m) => m.text === 'Committed needle')).toBe(true)
    window.odin.updateConversation = vi.fn(async () => ({ ok: true as const, result: corpus.renamed }))
    await store.renameConversation(id, 'Renamed')
    window.odin.updateConversation = vi.fn(async () => ({ ok: true as const, result: corpus.archived }))
    await store.setArchived(id, true)
    expect(store.state.conversations.find((c) => c.id === id)).toEqual(corpus.archived.conversation)
    window.odin.deleteConversation = vi.fn(async () => ({ ok: true as const, result: corpus.deleted_child }))
    await store.deleteConversation(corpus.child.conversation.id)
    expect(store.state.conversations.some((c) => c.id === corpus.child.conversation.id)).toBe(false)
    expect(store.state.views[corpus.child.conversation.id]).toBeUndefined()
  })

  it('uses real search/around contracts without replacing the live view', async () => {
    window.odin.search = vi.fn(async () => ({ ok: true as const, result: corpus.search }))
    window.odin.messagesAround = vi.fn(async () => ({ ok: true as const, result: corpus.around }))
    await store.runSearch('needle')
    const userHit = store.state.search.hits.find((h) => h.role === 'user')!
    await store.jumpTo(userHit)
    expect(store.state.jump?.items).toEqual(corpus.around.items)
    expect(store.state.highlightId).toBe(corpus.admitted.message_id)
    expect(store.state.views[store.state.activeId!]!.messages).toEqual([])
  })

  it('shows each retained binary once while concatenating real paged text', () => {
    const view: OutputView = { text: '', files: [], next: null, eof: false }
    for (const page of corpus.pages as ToolOutputPage[]) appendPage(view, 'run_command', page)
    expect(corpus.pages.length).toBeGreaterThan(1)
    expect(corpus.pages[0].attachments).toEqual(corpus.pages[1].attachments)
    expect(view.text).toBe('first page second page')
    expect(view.files).toHaveLength(1)
    expect(view.eof).toBe(true)
  })
})
