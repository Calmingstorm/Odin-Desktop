import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Host, type Mounted } from './component-host'

const ok = (result: unknown) => ({ ok: true as const, result })
const refused = { ok: false, error: { code: 'capability_unavailable', message: 'Not composed', disposition: 'not_dispatched' } }
let odin: Record<string, ReturnType<typeof vi.fn>>
let mounted: Mounted[]

beforeEach(() => {
  vi.resetModules()
  mounted = []
  odin = {
    knowledgeChunks: vi.fn(async () => ok([{ id: 'c1', content: '<b>plain text</b>', metadata: null }])),
    knowledgeDuplicates: vi.fn(async () => ok({ exact: [], near: [{ source_a: 'a', source_b: 'b', similarity: 0.87 }] })),
    knowledgeVersion: vi.fn(async () => ok({ source: 'a', version: 2, content: 'older snapshot', chunk_count: null })),
    knowledgeDiff: vi.fn(async () => ok({ source: 'a', v1: 1, v2: 2, diff: '-old\n+new' })),
    knowledgeMerge: vi.fn(async () => ok({ status: 'merged', chunks_removed: 4 })),
    knowledgeList: vi.fn(async () => ok([])),
    learnedList: vi.fn(async () => ok({ entries: [{ key: 'lesson', content: 'Preserve the original' }], count: null, categories: null, last_reflection: null })),
    learnedUpdate: vi.fn(async () => ok({ status: 'updated', key: 'lesson' })),
    learnedDelete: vi.fn(async () => ok({ status: 'deleted', key: 'lesson' }))
  }
  vi.stubGlobal('window', { odin })
  vi.stubGlobal('document', { activeElement: null })
})

afterEach(() => {
  mounted.forEach((v) => v.unmount())
  vi.unstubAllGlobals()
})

async function view(): Promise<Mounted> {
  const component = (await import('../../src/renderer/src/components/KnowledgeDetails.vue')).default
  const v = mount(component)
  mounted.push(v)
  await flush()
  return v
}

function form(v: Mounted, label: string): Host {
  return v.root.findAll((node) => node.tag === 'form' && node.props['aria-label'] === label)[0]!
}

function jsonText(v: Mounted, label: string): string {
  return v.root.findAll((node) => node.tag === 'pre' && node.props['aria-label'] === label)[0]!.textContent()
}

/** Saved documents, loaded through the state store as the Knowledge section does. */
async function withSources(...sources: string[]): Promise<void> {
  odin.knowledgeList!.mockImplementation(async () => ok(sources.map((source) => ({ source, chunks: 1, ingested_at: '2026-10-09T12:00:00Z' }))))
  await (await import('../../src/renderer/src/stores/state')).loadKnowledge()
  await flush()
}

function control(v: Mounted, id: string): Host {
  return v.root.findAll((node) => ['input', 'select'].includes(node.tag) && node.props.id === id)[0]!
}

async function answerDialog(value: true | null): Promise<void> {
  const { dialog } = await import('../../src/renderer/src/dialog')
  expect(dialog.current).not.toBeNull()
  dialog.current!.resolve(value)
  await flush()
}

describe('State knowledge details and learned context', () => {
  it('labels every knowledge query and merge control visibly, in shared rows', async () => {
    const v = await view()
    await withSources('a', 'b')
    const ids = ['knowledge-chunk-source', 'knowledge-duplicate-threshold', 'knowledge-version-source', 'knowledge-version-number', 'knowledge-diff-source', 'knowledge-diff-from', 'knowledge-diff-to', 'knowledge-merge-keep', 'knowledge-merge-remove']
    for (const id of ids) {
      const field = control(v, id)
      expect(field, id).toBeDefined()
      expect(v.root.findAll((node) => String(node.props.class).split(' ').includes('settings-row') && node.findAll((child) => child === field).length > 0), id).toHaveLength(1)
      let label = field.parent
      while (label && label.tag !== 'label') label = label.parent
      // The caption is the label's own text, not the options of the menu it holds.
      const caption = label!.textContent().replace(field.textContent(), '').trim()
      expect(caption, id).toBeTruthy()
      // The spoken name contains the visible caption.
      expect(String(field.props['aria-label']).toLowerCase(), id).toContain(caption.toLowerCase())
    }
    for (const title of ['Read knowledge chunks', 'Find knowledge duplicates', 'Read knowledge version', 'Read knowledge diff', 'Merge knowledge sources']) {
      expect(form(v, title).findAll((node) => node.tag === 'button' && node.props.type === 'submit'), title).toHaveLength(1)
    }
    // Every source menu offers exactly the saved documents.
    expect(control(v, 'knowledge-chunk-source').options.map((option) => option.textContent())).toEqual(['Choose a document', 'a', 'b'])
  })

  it('drives every source menu, number field and merge choice as a user would', async () => {
    const v = await view()
    await withSources('a', 'b')
    odin.knowledgeDuplicates!.mockImplementation(async () => ok({ exact: [{ sources: ['a', 'b'] }], near: [] }))
    control(v, 'knowledge-version-source').choose(2)
    control(v, 'knowledge-version-number').type('3')
    await form(v, 'Read knowledge version').fire('submit', { preventDefault() {} })
    control(v, 'knowledge-diff-source').choose(1)
    control(v, 'knowledge-diff-from').type('1')
    control(v, 'knowledge-diff-to').type('2')
    await form(v, 'Read knowledge diff').fire('submit', { preventDefault() {} })
    await form(v, 'Find knowledge duplicates').fire('submit', { preventDefault() {} })
    await flush()
    expect(odin.knowledgeVersion).toHaveBeenCalledWith({ source: 'b', version: 3 })
    expect(odin.knowledgeDiff).toHaveBeenCalledWith({ source: 'a', v1: 1, v2: 2 })
    expect(v.root.textContent()).toContain('Same text in a, b')
    control(v, 'knowledge-merge-keep').choose(1)
    control(v, 'knowledge-merge-remove').choose(2)
    await flush()
    expect([v.setup.keepSource, v.setup.removeSource]).toEqual(['a', 'b'])
    // The kept document is not offered as the one to remove.
    expect(control(v, 'knowledge-merge-remove').options.find((option) => option.textContent() === 'a')!.props.disabled).toBe(true)
  })

  it('shows a bridge that throws as an error, never as data', async () => {
    odin.knowledgeChunks!.mockImplementation(async () => { throw new Error('bridge went away') })
    const v = await view()
    await withSources('a')
    control(v, 'knowledge-chunk-source').choose(1)
    await form(v, 'Read knowledge chunks').fire('submit', { preventDefault() {} })
    await flush()
    expect(v.root.textContent()).toContain('bridge went away')
    expect(v.root.findAll((node) => node.props['aria-label'] === 'Knowledge chunks JSON')).toHaveLength(0)
  })

  it('opens and cancels the learned editor, and asks before deleting from its button', async () => {
    const v = await view()
    v.root.named('Edit learned entry lesson').fire('click')
    await flush()
    expect(v.root.findAll((node) => node.tag === 'form' && node.props['aria-label'] === 'Edit learned entry lesson')).toHaveLength(1)
    v.root.button('Cancel').fire('click')
    await flush()
    expect(v.setup.editing).toBeNull()
    v.root.named('Delete learned entry lesson…').fire('click')
    await answerDialog(null)
    expect(odin.learnedDelete).not.toHaveBeenCalled()
  })

  it('shows no read forms until a document is saved', async () => {
    const v = await view()
    expect(v.root.textContent()).toContain('No documents saved yet.')
    expect(v.root.findAll((node) => node.tag === 'form' && String(node.props['aria-label']).startsWith('Read knowledge'))).toHaveLength(0)
  })

  it('places headings outside cards and keeps internal terms out of the copy', async () => {
    const v = await view()
    await withSources('a', 'b')
    for (const title of ['Knowledge details', 'Learned context']) {
      const section = v.root.findAll((node) => node.tag === 'section' && node.props['aria-label'] === title)[0]!
      expect(section.find('h3')!.textContent()).toBe(title)
      const card = section.findAll((node) => node.props.class === 'settings-card')[0]!
      expect(card.findAll((node) => node.tag === 'h3')).toHaveLength(0)
    }
    expect(v.root.textContent()).not.toMatch(/\b(core|owner|transaction|cleanup|metadata)\b/i)
  })

  it('lists learned entries as returned, without synthetic counts', async () => {
    const v = await view()
    expect(odin.learnedList).toHaveBeenCalledWith({})
    const list = v.root.findAll((node) => node.props['aria-label'] === 'Learned entries')[0]!
    expect(list.textContent()).toContain('lesson')
    expect(list.textContent()).toContain('Preserve the original')
    expect(v.root.textContent()).not.toMatch(/\d+ entries/)
    expect(v.root.findAll((node) => node.props['aria-label'] === 'Learned context JSON')).toHaveLength(0)
  })

  it('submits read forms and shows readable results with the complete record, tied to what was asked', async () => {
    const v = await view()
    await withSources('a', 'b')
    control(v, 'knowledge-chunk-source').choose(1)
    await form(v, 'Read knowledge chunks').fire('submit', { preventDefault() {} })
    control(v, 'knowledge-duplicate-threshold').type('0.8')
    await form(v, 'Find knowledge duplicates').fire('submit', { preventDefault() {} })
    Object.assign(v.setup, { versionSource: 'a', version: '2', diffSource: 'a', v1: '1', v2: '2' })
    await form(v, 'Read knowledge version').fire('submit', { preventDefault() {} })
    await form(v, 'Read knowledge diff').fire('submit', { preventDefault() {} })
    await flush()
    expect(odin.knowledgeChunks).toHaveBeenCalledWith({ source: 'a' })
    expect(odin.knowledgeDuplicates).toHaveBeenCalledWith({ threshold: 0.8 })
    expect(odin.knowledgeVersion).toHaveBeenCalledWith({ source: 'a', version: 2 })
    expect(odin.knowledgeDiff).toHaveBeenCalledWith({ source: 'a', v1: 1, v2: 2 })
    // Readable first: markup in a chunk is shown as text, never rendered.
    expect(v.root.findAll((node) => node.props['aria-label'] === 'Knowledge chunks result')[0]!.textContent()).toContain('<b>plain text</b>')
    expect(v.root.textContent()).toContain('87% similar')
    expect(v.root.textContent()).toContain('older snapshot')
    expect(v.root.textContent()).toContain('-old\n+new')
    // The complete record stays one click away, null values included.
    expect(JSON.parse(jsonText(v, 'Knowledge chunks JSON'))).toEqual([{ id: 'c1', content: '<b>plain text</b>', metadata: null }])
    expect(JSON.parse(jsonText(v, 'Knowledge duplicates JSON'))).toEqual({ exact: [], near: [{ source_a: 'a', source_b: 'b', similarity: 0.87 }] })
    expect(JSON.parse(jsonText(v, 'Knowledge version JSON')).chunk_count).toBeNull()
    expect(JSON.parse(jsonText(v, 'Knowledge diff JSON')).diff).toBe('-old\n+new')
    // Choosing another document does not re-read or relabel the shown answer.
    control(v, 'knowledge-chunk-source').choose(2)
    await flush()
    expect(odin.knowledgeChunks).toHaveBeenCalledTimes(1)
    expect(JSON.parse(jsonText(v, 'Knowledge chunks JSON'))).toEqual([{ id: 'c1', content: '<b>plain text</b>', metadata: null }])
  })

  it('omits a blank optional threshold and rejects invalid version/threshold arguments before dispatch', async () => {
    const v = await view()
    await (v.setup.duplicates as () => Promise<void>)()
    expect(odin.knowledgeDuplicates).toHaveBeenCalledWith({})
    Object.assign(v.setup, { threshold: 'invalid', versionSource: 'a', version: '-1', diffSource: 'a', v1: '1.5', v2: '2' })
    await (v.setup.duplicates as () => Promise<void>)()
    await (v.setup.getVersion as () => Promise<void>)()
    await (v.setup.diff as () => Promise<void>)()
    expect(odin.knowledgeDuplicates).toHaveBeenCalledTimes(1)
    expect(odin.knowledgeVersion).not.toHaveBeenCalled()
    expect(odin.knowledgeDiff).not.toHaveBeenCalled()
    // Native number v-model returns a number, not a string.
    Object.assign(v.setup, { version: 0, threshold: 0.9 })
    await (v.setup.getVersion as () => Promise<void>)()
    await (v.setup.duplicates as () => Promise<void>)()
    expect(odin.knowledgeVersion).toHaveBeenCalledWith({ source: 'a', version: 0 })
    expect(odin.knowledgeDuplicates).toHaveBeenLastCalledWith({ threshold: 0.9 })
    v.setup.threshold = 2
    await (v.setup.duplicates as () => Promise<void>)()
    expect(odin.knowledgeDuplicates).toHaveBeenLastCalledWith({ threshold: 2 })
  })

  it('does not render refused or failed reads as empty data and drops stale answers', async () => {
    let resolve!: (value: unknown) => void
    odin.knowledgeChunks!.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const v = await view()
    await withSources('old', 'new')
    v.setup.chunkSource = 'old'
    const old = (v.setup.chunks as () => Promise<void>)()
    odin.knowledgeChunks!.mockImplementation(async () => refused)
    v.setup.chunkSource = 'new'
    await (v.setup.chunks as () => Promise<void>)()
    resolve(ok([{ content: 'STALE' }]))
    await old
    await flush()
    expect(v.root.textContent()).toContain('Knowledge chunks is unavailable.')
    expect(v.root.textContent()).not.toContain('STALE')
    odin.learnedList!.mockImplementation(async () => ({ ok: false, error: { code: 'read_failed', message: 'Store could not be read' } }))
    await (v.setup.learned as () => Promise<void>)()
    await flush()
    expect(v.root.textContent()).toContain('Store could not be read')
    expect(v.root.findAll((node) => node.props['aria-label'] === 'Learned entries')).toHaveLength(0)
  })

  it('requires merge confirmation, snapshots its targets, reports the receipt in words and refreshes knowledge', async () => {
    const v = await view()
    await withSources('a', 'b')
    Object.assign(v.setup, { keepSource: 'a', removeSource: 'b' })
    const cancelled = (v.setup.merge as () => Promise<void>)()
    expect(odin.knowledgeMerge).not.toHaveBeenCalled()
    const { dialog } = await import('../../src/renderer/src/dialog')
    expect(dialog.current!.message).toContain('delete b with all its chunks')
    expect(dialog.current!.message).toContain('does not copy its content')
    await answerDialog(null)
    await cancelled
    expect(odin.knowledgeMerge).not.toHaveBeenCalled()
    const sent = (v.setup.merge as () => Promise<void>)()
    v.setup.removeSource = 'changed-draft'
    await answerDialog(true)
    await sent
    await flush()
    expect(odin.knowledgeMerge).toHaveBeenCalledWith({ keep_source: 'a', remove_source: 'b' })
    expect(odin.knowledgeList).toHaveBeenCalledTimes(2)
    const receipt = v.root.findAll((node) => node.props['aria-label'] === 'Knowledge command receipt')
    expect(receipt.map((node) => node.textContent())).toEqual(['Kept a. Removed b and its 4 chunks.'])
  })

  it('shows the merge receipt only in its own row, never an add receipt', async () => {
    const v = await view()
    await withSources('a', 'b')
    const { management } = await import('../../src/renderer/src/stores/management')
    management.notes.knowledge = 'Stored as 1 chunk.'
    await flush()
    expect(v.root.textContent()).not.toContain('Stored as 1 chunk.')
  })

  it('edits only the changed learned fields, keeps the draft until saved and confirms deletion', async () => {
    const v = await view()
    v.root.named('Edit learned entry lesson').fire('click')
    await flush()
    expect(v.root.button('Save learned entry').props.disabled).toBe(true)
    ;(v.setup.editing as { content: string }).content = ''
    await flush()
    await (v.setup.updateLearned as () => Promise<void>)()
    await flush()
    expect(odin.learnedUpdate).toHaveBeenCalledWith({ key: 'lesson', content: '' })
    expect(v.setup.editing).toBeNull()
    expect(v.root.textContent()).toContain('Saved.')
    const cancelled = (v.setup.deleteLearned as (key: string) => Promise<void>)('lesson')
    expect(odin.learnedDelete).not.toHaveBeenCalled()
    await answerDialog(null)
    await cancelled
    odin.learnedList!.mockImplementation(async () => ok({ entries: [], count: null, categories: null, last_reflection: null }))
    const confirmed = (v.setup.deleteLearned as (key: string) => Promise<void>)('lesson')
    await answerDialog(true)
    await confirmed
    await flush()
    expect(odin.learnedDelete).toHaveBeenCalledWith({ key: 'lesson' })
    expect(odin.learnedList).toHaveBeenCalledTimes(3)
    // The deleted entry is gone from the list, so its receipt shows under the list.
    expect(v.root.textContent()).toContain('Nothing learned yet.')
    expect(v.root.textContent()).toContain('Deleted.')
  })

  it('uses management locks and settles unknown learned outcomes only by their late receipt', async () => {
    const v = await view()
    const { management } = await import('../../src/renderer/src/stores/management')
    Object.assign(v.setup, { keepSource: 'a', removeSource: 'b' })
    management.busy['knowledge:b'] = true
    await (v.setup.merge as () => Promise<void>)()
    expect(odin.knowledgeMerge).not.toHaveBeenCalled()
    odin.learnedUpdate!.mockImplementation(async () => ({ ok: false, error: { code: 'outcome_unknown', message: 'Waiting', disposition: 'outcome_unknown', command_id: 'learned-1' } }))
    ;(v.setup.startEdit as (entry: Record<string, unknown>) => void)({ key: 'lesson', content: 'Preserve the original' })
    ;(v.setup.editing as { category: string }).category = 'operations'
    await (v.setup.updateLearned as () => Promise<void>)()
    await (v.setup.updateLearned as () => Promise<void>)()
    await flush()
    expect(odin.learnedUpdate).toHaveBeenCalledTimes(1)
    expect(odin.learnedUpdate).toHaveBeenCalledWith({ key: 'lesson', category: 'operations' })
    expect(management.busy['learned:lesson']).toBe(true)
    expect(v.root.textContent()).toContain('never sent twice')
    const store = await import('../../src/renderer/src/store')
    store.applyReceipt({ id: 'learned-1', settled: ok({ status: 'updated', key: 'lesson' }) })
    await flush()
    expect(management.busy['learned:lesson']).toBe(false)
    expect(odin.learnedList).toHaveBeenCalledTimes(2)
  })

  it('handles an older missing bridge as unavailable, rather than inventing an empty list', async () => {
    delete odin.learnedList
    const v = await view()
    expect(v.root.textContent()).toContain('Learned context is unavailable.')
    expect(v.root.findAll((node) => node.props['aria-label'] === 'Learned entries')).toHaveLength(0)
    expect(v.root.findAll((node) => node.tag === 'button' && String(node.props['aria-label']).startsWith('Edit learned entry'))).toHaveLength(0)
  })

  it('holds both merge source locks through an unknown outcome until its receipt settles', async () => {
    const v = await view()
    const { management } = await import('../../src/renderer/src/stores/management')
    Object.assign(v.setup, { keepSource: 'a', removeSource: 'b' })
    odin.knowledgeMerge!.mockImplementation(async () => ({ ok: false, error: { code: 'outcome_unknown', message: 'Waiting', disposition: 'outcome_unknown', command_id: 'merge-1' } }))
    const sent = (v.setup.merge as () => Promise<void>)()
    await answerDialog(true)
    await sent
    expect([management.busy.knowledge, management.busy['knowledge:a'], management.busy['knowledge:b']]).toEqual([true, true, true])
    await (v.setup.merge as () => Promise<void>)()
    expect(odin.knowledgeMerge).toHaveBeenCalledTimes(1)
    const store = await import('../../src/renderer/src/store')
    store.applyReceipt({ id: 'merge-1', settled: ok({ status: 'merged' }) })
    await flush()
    expect([management.busy.knowledge, management.busy['knowledge:a'], management.busy['knowledge:b']]).toEqual([false, false, false])
    expect(odin.knowledgeList).toHaveBeenCalledTimes(1)
  })

  it('reports unavailable commands without success claims and releases their locks', async () => {
    const v = await view()
    await withSources('a', 'b')
    const { management } = await import('../../src/renderer/src/stores/management')
    Object.assign(v.setup, { keepSource: 'a', removeSource: 'b' })
    odin.knowledgeMerge!.mockImplementation(async () => refused)
    const sent = (v.setup.merge as () => Promise<void>)()
    await answerDialog(true)
    await sent
    odin.learnedUpdate!.mockImplementation(async () => refused)
    ;(v.setup.startEdit as (entry: Record<string, unknown>) => void)({ key: 'lesson', content: 'Preserve the original' })
    ;(v.setup.editing as { content: string }).content = 'draft'
    await (v.setup.updateLearned as () => Promise<void>)()
    await flush()
    expect(v.root.textContent()).toContain('Knowledge merge is unavailable.')
    expect(v.root.textContent()).toContain('Learned context changes is unavailable.')
    expect(v.root.textContent()).not.toContain('Kept a.')
    expect(v.root.textContent()).not.toContain('Saved.')
    expect([management.busy.knowledge, management.busy['knowledge-merge'], management.busy['knowledge:a'], management.busy['knowledge:b'], management.busy['learned:lesson']]).toEqual([false, false, false, false, false])
    expect((v.setup.editing as { content: string }).content).toBe('draft')
  })

  it('merges a document named "merge" without wedging the knowledge locks (review B3)', async () => {
    const v = await view()
    await withSources('merge', 'other')
    const { management } = await import('../../src/renderer/src/stores/management')
    Object.assign(v.setup, { keepSource: 'merge', removeSource: 'other' })
    const sent = (v.setup.merge as () => Promise<void>)()
    await answerDialog(true)
    await sent
    await flush()
    expect(odin.knowledgeMerge).toHaveBeenCalledWith({ keep_source: 'merge', remove_source: 'other' })
    expect([management.busy.knowledge, management.busy['knowledge:merge'], management.busy['knowledge:other'], management.busy['knowledge-merge']]).toEqual([false, false, false, false])
  })

  it('keeps edits typed while a learned save was on its way (review B4)', async () => {
    let finish!: (value: unknown) => void
    odin.learnedUpdate!.mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    const v = await view()
    ;(v.setup.startEdit as (entry: Record<string, unknown>) => void)({ key: 'lesson', content: 'Preserve the original' })
    const draft = v.setup.editing as { content: string; original: { content: string } }
    draft.content = 'first saved content'
    const saving = (v.setup.updateLearned as () => Promise<void>)()
    await flush()
    expect(odin.learnedUpdate).toHaveBeenCalledWith({ key: 'lesson', content: 'first saved content' })
    draft.content = 'SECOND unsaved edit while saving'
    finish({ ok: true, result: { status: 'updated', key: 'lesson' } })
    await saving
    await flush()
    // The newer text stays open, unsaved against what was saved.
    const kept = v.setup.editing as { content: string; original: { content: string } }
    expect(kept.content).toBe('SECOND unsaved edit while saving')
    expect(kept.original.content).toBe('first saved content')
    expect(v.root.button('Save learned entry').props.disabled).toBe(false)
    // An unchanged draft still closes once it is saved.
    odin.learnedUpdate!.mockImplementation(async () => ok({ status: 'updated', key: 'lesson' }))
    await (v.setup.updateLearned as () => Promise<void>)()
    await flush()
    expect(v.setup.editing).toBeNull()
  })

  it('keeps the editor when a learned deletion is refused, and closes it once one is confirmed (review B5)', async () => {
    const v = await view()
    ;(v.setup.startEdit as (entry: Record<string, unknown>) => void)({ key: 'lesson', content: 'Preserve the original' })
    ;(v.setup.editing as { content: string }).content = 'an unsaved draft'
    odin.learnedDelete!.mockImplementation(async () => ({ ok: false, error: { code: 'write_failed', message: 'write failed', disposition: 'rejected' } }))
    const refused = (v.setup.deleteLearned as (key: string) => Promise<void>)('lesson')
    await answerDialog(true)
    await refused
    await flush()
    expect((v.setup.editing as { content: string }).content).toBe('an unsaved draft')
    odin.learnedDelete!.mockImplementation(async () => ok({ status: 'deleted', key: 'lesson' }))
    const confirmed = (v.setup.deleteLearned as (key: string) => Promise<void>)('lesson')
    await answerDialog(true)
    await confirmed
    await flush()
    expect(v.setup.editing).toBeNull()
  })

  it('shows loaded learned entries without "Not read yet" (review N1)', async () => {
    const v = await view()
    const section = v.root.findAll((node) => node.tag === 'section' && node.props['aria-label'] === 'Learned context')[0]!
    expect(section.textContent()).toContain('Preserve the original')
    expect(section.textContent()).not.toContain('Not read yet.')
  })
})
