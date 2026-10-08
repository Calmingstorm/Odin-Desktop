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

async function answerDialog(value: true | null): Promise<void> {
  const { dialog } = await import('../../src/renderer/src/dialog')
  expect(dialog.current).not.toBeNull()
  dialog.current!.resolve(value)
  await flush()
}

describe('State knowledge details and learned context', () => {
  it('uses shared labeled rows for every knowledge query and merge field', async () => {
    const v = await view()
    const ids = ['knowledge-chunk-source', 'knowledge-duplicate-threshold', 'knowledge-version-source', 'knowledge-version-number', 'knowledge-diff-source', 'knowledge-diff-from', 'knowledge-diff-to', 'knowledge-merge-keep', 'knowledge-merge-remove']
    for (const id of ids) {
      const input = v.root.findAll((node) => node.tag === 'input' && node.props.id === id)[0]!
      expect(input).toBeDefined()
      const row = v.root.findAll((node) => String(node.props.class).includes('settings-row') && node.findAll((child) => child === input).length > 0)[0]!
      expect(row).toBeDefined()
      expect(row.findAll((node) => node.tag === 'label' && node.props.for === id)).toHaveLength(1)
    }
    for (const title of ['Read knowledge chunks', 'Find knowledge duplicates', 'Read knowledge version', 'Read knowledge diff', 'Merge knowledge sources']) {
      expect(form(v, title).findAll((node) => node.props.class === 'panel-actions')[0]!.find('button')).toBeDefined()
    }
  })
  it('places headings outside cards without explanatory copy or internal terminology', async () => {
    const v = await view()
    for (const title of ['Knowledge details', 'Learned context']) {
      const section = v.root.findAll((node) => node.tag === 'section' && node.props['aria-label'] === title)[0]!
      expect(section.find('h3')!.textContent()).toBe(title)
      const card = section.findAll((node) => node.props.class === 'settings-card')[0]!
      expect(card.findAll((node) => node.tag === 'h3')).toHaveLength(0)
      expect(section.findAll((node) => node.tag === 'p' && node.textContent() !== 'Not read yet.')).toHaveLength(0)
    }
    expect(v.root.textContent()).not.toMatch(/\b(core|owner|transaction|cleanup|metadata)\b/i)
  })

  it('shows the exact learned envelope, including null unknowns, without synthetic counts', async () => {
    const v = await view()
    expect(odin.learnedList).toHaveBeenCalledWith({})
    expect(JSON.parse(jsonText(v, 'Learned context JSON'))).toEqual({
      entries: [{ key: 'lesson', content: 'Preserve the original' }], count: null, categories: null, last_reflection: null
    })
    expect(v.root.textContent()).not.toContain('0 entries')
    expect(v.root.textContent()).toContain('Not read yet.')
  })

  it('submits accessible read forms and displays complete payloads tied to their request snapshots', async () => {
    const v = await view()
    form(v, 'Read knowledge chunks').find('input')!.type(' a ')
    await form(v, 'Read knowledge chunks').fire('submit', { preventDefault() {} })
    form(v, 'Find knowledge duplicates').find('input')!.type('0.8')
    await form(v, 'Find knowledge duplicates').fire('submit', { preventDefault() {} })
    Object.assign(v.setup, { versionSource: 'a', version: '2', diffSource: 'a', v1: '1', v2: '2' })
    await form(v, 'Read knowledge version').fire('submit', { preventDefault() {} })
    await form(v, 'Read knowledge diff').fire('submit', { preventDefault() {} })
    await flush()
    expect(odin.knowledgeChunks).toHaveBeenCalledWith({ source: 'a' })
    expect(odin.knowledgeDuplicates).toHaveBeenCalledWith({ threshold: 0.8 })
    expect(odin.knowledgeVersion).toHaveBeenCalledWith({ source: 'a', version: 2 })
    expect(odin.knowledgeDiff).toHaveBeenCalledWith({ source: 'a', v1: 1, v2: 2 })
    expect(JSON.parse(jsonText(v, 'Knowledge chunks JSON'))).toEqual([{ id: 'c1', content: '<b>plain text</b>', metadata: null }])
    expect(JSON.parse(jsonText(v, 'Knowledge duplicates JSON'))).toEqual({ exact: [], near: [{ source_a: 'a', source_b: 'b', similarity: 0.87 }] })
    expect(JSON.parse(jsonText(v, 'Knowledge version JSON')).chunk_count).toBeNull()
    expect(JSON.parse(jsonText(v, 'Knowledge diff JSON')).diff).toBe('-old\n+new')
    v.setup.chunkSource = 'b'
    await flush()
    expect(JSON.parse(jsonText(v, 'Knowledge chunks request'))).toEqual({ source: 'a' })
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
    expect(v.root.findAll((node) => node.props['aria-label'] === 'Learned context JSON')).toHaveLength(0)
  })

  it('requires merge confirmation, snapshots its targets, records the exact receipt and refreshes knowledge', async () => {
    const v = await view()
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
    expect(odin.knowledgeMerge).toHaveBeenCalledWith({ keep_source: 'a', remove_source: 'b' })
    expect(odin.knowledgeList).toHaveBeenCalledTimes(1)
    expect(JSON.parse(jsonText(v, 'Knowledge command receipt'))).toEqual({ status: 'merged', chunks_removed: 4 })
  })

  it('updates only explicitly selected fields, keeps drafts and confirms deletion', async () => {
    const v = await view()
    Object.assign(v.setup, { learnedKey: ' lesson ', editContent: true, learnedContent: '', learnedCategory: 'not sent' })
    await (v.setup.updateLearned as () => Promise<void>)()
    await flush()
    expect(odin.learnedUpdate).toHaveBeenCalledWith({ key: 'lesson', content: '' })
    expect(JSON.parse(jsonText(v, 'Learned command receipt'))).toEqual({ status: 'updated', key: 'lesson' })
    expect(v.setup.learnedCategory).toBe('not sent')
    const cancelled = (v.setup.deleteLearned as () => Promise<void>)()
    expect(odin.learnedDelete).not.toHaveBeenCalled()
    await answerDialog(null)
    await cancelled
    const confirmed = (v.setup.deleteLearned as () => Promise<void>)()
    await answerDialog(true)
    await confirmed
    expect(odin.learnedDelete).toHaveBeenCalledWith({ key: 'lesson' })
    expect(odin.learnedList).toHaveBeenCalledTimes(3)
  })

  it('uses management locks and settles unknown learned outcomes only by their late receipt', async () => {
    const v = await view()
    const { management } = await import('../../src/renderer/src/stores/management')
    Object.assign(v.setup, { keepSource: 'a', removeSource: 'b', learnedKey: 'lesson', editCategory: true, learnedCategory: 'operations' })
    management.busy['knowledge:b'] = true
    await (v.setup.merge as () => Promise<void>)()
    expect(odin.knowledgeMerge).not.toHaveBeenCalled()
    odin.learnedUpdate!.mockImplementation(async () => ({ ok: false, error: { code: 'outcome_unknown', message: 'Waiting', disposition: 'outcome_unknown', command_id: 'learned-1' } }))
    await (v.setup.updateLearned as () => Promise<void>)()
    await (v.setup.updateLearned as () => Promise<void>)()
    await flush()
    expect(odin.learnedUpdate).toHaveBeenCalledTimes(1)
    expect(management.busy['learned:lesson']).toBe(true)
    expect(v.root.textContent()).toContain('never sent twice')
    const store = await import('../../src/renderer/src/store')
    store.applyReceipt({ id: 'learned-1', settled: ok({ status: 'updated', key: 'lesson' }) })
    await flush()
    expect(management.busy['learned:lesson']).toBe(false)
    expect(odin.learnedList).toHaveBeenCalledTimes(2)
  })

  it('handles an older missing bridge as unavailable, rather than inventing an empty envelope', async () => {
    delete odin.learnedList
    const v = await view()
    expect(v.root.textContent()).toContain('Learned context is unavailable.')
    expect(v.root.findAll((node) => node.props['aria-label'] === 'Learned context JSON')).toHaveLength(0)
    expect(v.root.button('Update learned entry').props.disabled).toBe(true)
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
    const { management } = await import('../../src/renderer/src/stores/management')
    Object.assign(v.setup, { keepSource: 'a', removeSource: 'b', learnedKey: 'lesson', editContent: true, learnedContent: 'draft' })
    odin.knowledgeMerge!.mockImplementation(async () => refused)
    const sent = (v.setup.merge as () => Promise<void>)()
    await answerDialog(true)
    await sent
    odin.learnedUpdate!.mockImplementation(async () => refused)
    await (v.setup.updateLearned as () => Promise<void>)()
    await flush()
    expect(v.root.textContent()).toContain('Knowledge merge is unavailable.')
    expect(v.root.textContent()).toContain('Learned context changes is unavailable.')
    expect(v.root.textContent()).not.toContain('"status": "merged"')
    expect(v.root.textContent()).not.toContain('"status": "updated"')
    expect([management.busy.knowledge, management.busy['knowledge:a'], management.busy['knowledge:b'], management.busy['learned:lesson']]).toEqual([false, false, false, false])
    expect(v.setup.learnedContent).toBe('draft')
  })
})
