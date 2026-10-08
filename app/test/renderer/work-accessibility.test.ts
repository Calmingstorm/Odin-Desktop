// Component/object-renderer checks prove the bindings and focus decisions, not browser/AT-SPI behaviour.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import type { WorkItem } from '../../src/shared/api'
import { changedWorkNotices, workAnnouncement, workName, type WorkNotice } from '../../src/renderer/src/work-accessibility'
import { flush, mount, type Host, type Mounted } from './component-host'

let view: Mounted | undefined
let workStore: typeof import('../../src/renderer/src/stores/work')
let store: typeof import('../../src/renderer/src/store')
let listed: WorkItem[]
let controls: Record<string, unknown>[]
let land: ((result: unknown) => void) | undefined
let snapshotLand: ((result: unknown) => void) | undefined
const agent = (): WorkItem => ({ id: 'a1', kind: 'agent', title: 'Check disks', state: 'running', detail: '', actions: ['stop'], conversation_id: 'child' })
const namedButton = (label: string): Host => {
  const buttons = view!.root.findAll((node) => node.tag === 'button' && node.props['aria-label'] === label)
  expect(buttons).toHaveLength(1)
  return buttons[0]!
}

beforeEach(async () => {
  vi.resetModules()
  listed = [agent()]
  controls = []
  land = undefined
  snapshotLand = undefined
  ;(globalThis as unknown as { window: unknown }).window = { odin: {
    workList: async () => ({ ok: true, result: { items: listed } }),
    workControl: (params: Record<string, unknown>) => {
      controls.push(params)
      return new Promise((resolve) => { land = resolve })
    },
    snapshotConversation: () => new Promise((resolve) => { snapshotLand = resolve })
  } }
  ;(globalThis as unknown as { document: unknown }).document = {
    activeElement: null, body: {}, getElementById: vi.fn(), querySelector: vi.fn()
  }
  workStore = await import('../../src/renderer/src/stores/work')
  store = await import('../../src/renderer/src/store')
  store.state.conversations = [{ id: 'child', title: 'Child task', rev: 1, parent_id: 'parent', unread: 0, archived: false, updated_at: '2026-10-05T00:00:00Z' }]
  await workStore.loadWork()
})

afterEach(() => { view?.unmount(); view = undefined; vi.useRealTimers() })

async function mountList(): Promise<void> {
  view = mount((await import('../../src/renderer/src/components/WorkList.vue')).default)
  await flush()
}

function settleSnapshot(): void {
  snapshotLand!({ ok: true, result: {
    conversation: store.state.conversations[0], watermark: '0', messages: { items: [], has_more: false },
    running: null, queued: [], recent: [], unresolved: [], tools: {}, controls: []
  } })
}

describe('work names, associations and controls', () => {
  it('qualifies every repeated action with kind and title, and gives its row state and note associations', async () => {
    listed.push({ ...agent(), id: 'a2', title: 'Check memory' })
    await workStore.loadWork()
    await mountList()
    const first = namedButton('Stop agent: Check disks')
    namedButton('Stop agent: Check memory')
    const ids = view!.root.findAll((node) => Boolean(node.props.id)).map((node) => node.props.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).toContain(first.props['aria-describedby'])
    workStore.work.notes['agent:a1'] = 'No receipt yet.'
    await flush()
    const descriptions = String(first.props['aria-describedby']).split(' ')
    expect(descriptions).toHaveLength(2)
    for (const id of descriptions) expect(view!.root.findAll((node) => node.props.id === id)).toHaveLength(1)
  })

  it('sends Stop directly, preserves the existing pending lock, and announces an unknown receipt without a new dialog', async () => {
    vi.useFakeTimers()
    await mountList()
    const button = namedButton('Stop agent: Check disks')
    const stopping = button.fire('click', { currentTarget: button })
    await flush()
    expect(controls).toHaveLength(1)
    expect(controls[0]).toMatchObject({ id: 'a1', kind: 'agent', action: 'stop' })
    expect(button.props['aria-disabled']).toBe(true)
    expect(button.props.disabled).toBeUndefined() // pending controls keep their position in the keyboard order
    await button.fire('click', { currentTarget: button })
    expect(controls).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(150)
    expect(view!.root.findAll((node) => node.props.role === 'status')[0]!.textContent()).toBe('agent: Check disks. Control pending.')
    land!({ ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown' } })
    await stopping
    await flush()
    await vi.advanceTimersByTimeAsync(150)
    expect(button.props['aria-disabled']).toBe(true)
    expect(view!.root.findAll((node) => node.props.role === 'status')[0]!.textContent()).toMatch(/waiting for Odin to confirm/)
    expect((await import('../../src/renderer/src/dialog')).dialog.current).toBeNull()
  })

  it('keeps one quiet live region, ignores detail churn, and announces lifecycle changes', async () => {
    vi.useFakeTimers()
    await mountList()
    const status = view!.root.findAll((node) => node.props.role === 'status')
    expect(status).toHaveLength(1)
    expect(status[0]!.textContent()).toBe('')
    workStore.work.items[0]!.detail = 'frequent output'
    await flush()
    await vi.advanceTimersByTimeAsync(150)
    expect(status[0]!.textContent()).toBe('')
    workStore.work.items[0]!.state = 'completed'
    await flush()
    await vi.advanceTimersByTimeAsync(150)
    expect(status[0]!.textContent()).toBe('agent: Check disks. Done.')
  })

  it('names the child conversation target with its originating work', async () => {
    await mountList()
    expect(namedButton('Open conversation Child task for agent: Check disks').textContent().trim()).toBe('Open conversation Child task')
  })

  it('moves keyboard navigation to history only if its initiating button still owns focus', async () => {
    await mountList()
    const button = namedButton('Open conversation Child task for agent: Check disks')
    const focus = vi.fn()
    Object.assign(document, { activeElement: button, getElementById: vi.fn(() => ({ focus })) })
    workStore.work.open = true
    const navigating = button.fire('click', { currentTarget: button })
    expect(store.state.activeId).toBe('child')
    expect(focus).not.toHaveBeenCalled()
    settleSnapshot()
    await navigating
    expect(workStore.work.open).toBe(false)
    expect(document.getElementById).toHaveBeenCalledWith('conversation-history')
    expect(focus).toHaveBeenCalledOnce()
  })

  it('does not steal focus when someone tabs away during child loading', async () => {
    await mountList()
    const button = namedButton('Open conversation Child task for agent: Check disks')
    const focus = vi.fn()
    Object.assign(document, { activeElement: button, getElementById: vi.fn(() => ({ focus })) })
    workStore.work.open = true
    const navigating = button.fire('click', { currentTarget: button })
    Object.assign(document, { activeElement: { elsewhere: true } })
    settleSnapshot()
    await navigating
    expect(workStore.work.open).toBe(true)
    expect(focus).not.toHaveBeenCalled()
  })

  it('offers background Resume and Run now with qualified names and sends Resume without a confirmation', async () => {
    listed = [{ id: 's1', kind: 'schedule', title: 'Disk report', state: 'paused', detail: '', actions: ['resume', 'run_now'] }]
    await workStore.loadWork()
    await mountList()
    namedButton('Run now schedule: Disk report')
    const button = namedButton('Resume schedule: Disk report')
    const resuming = button.fire('click', { currentTarget: button })
    expect(controls).toHaveLength(1)
    expect(controls[0]).toMatchObject({ action: 'resume', kind: 'schedule', id: 's1' })
    land!({ ok: true, result: { disposition: 'done' } })
    await resuming
    expect((await import('../../src/renderer/src/dialog')).dialog.current).toBeNull()
  })

  it('repairs a focused action removed by a later core update to its own row', async () => {
    await mountList()
    const button = namedButton('Stop agent: Check disks')
    const row = view!.root.find('article')!
    const active = { isConnected: true, closest: () => ({ id: row.props.id }) }
    const focus = vi.fn()
    Object.assign(document, { activeElement: active, getElementById: vi.fn(() => ({ focus })) })
    // Model a browser removing the focused button between the pre-update watcher and nextTick.
    Object.defineProperty(button, 'parent', { configurable: true, get: () => row, set: () => {
      active.isConnected = false
      Object.assign(document, { activeElement: document.body })
    } })
    workStore.work.items[0]!.actions = []
    await flush()
    expect(document.getElementById).toHaveBeenCalledWith(row.props.id)
    expect(focus).toHaveBeenCalledOnce()
  })

  it('repairs focus when a focused row moves from Running now to Finished in the Work column', async () => {
    // Review #86: one running agent and no schedules, so the move changes only the row's section.
    view = mount((await import('../../src/renderer/src/components/WorkList.vue')).default, { sections: true })
    await flush()
    const row = view!.root.find('article')!
    const active = { isConnected: true, closest: () => ({ id: row.props.id }) }
    const focus = vi.fn()
    Object.assign(document, { activeElement: active, getElementById: vi.fn(() => ({ focus })) })
    // The renderer detaches the old section, with the row inside it, when the row's section changes: the focused
    // node is gone, as in a browser.
    const section = row.parent!
    let parent = section.parent
    Object.defineProperty(section, 'parent', { configurable: true, get: () => parent, set: (next) => {
      parent = next
      if (next) return
      active.isConnected = false
      Object.assign(document, { activeElement: document.body })
    } })
    expect(workStore.work.items[0]!.actions).toEqual(['stop'])
    workStore.work.items[0]!.state = 'stopped'
    await flush()
    expect(view!.root.findAll((node) => node.tag === 'h2').map((h2) => h2.textContent().replace(/\s+/g, ' ').trim())).toEqual(['Finished 1'])
    expect(document.getElementById).toHaveBeenCalledWith(row.props.id)
    expect(focus).toHaveBeenCalledOnce()
  })

  it('keeps item ids distinct in two mounted lists', async () => {
    const WorkList = (await import('../../src/renderer/src/components/WorkList.vue')).default
    view = mount(defineComponent({ render: () => h('div', [h(WorkList), h(WorkList)]) }))
    await flush()
    const ids = view!.root.findAll((node) => Boolean(node.props.id)).map((node) => node.props.id)
    expect(ids).toHaveLength(6)
    expect(new Set(ids).size).toBe(ids.length)
  })
})

describe('inline work panel focus contract', () => {
  it('names close and refresh, closes with Escape, and restores its connected opener', async () => {
    const opener = { isConnected: true, focus: vi.fn() }
    Object.assign(document, { activeElement: opener })
    workStore.work.open = true
    view = mount((await import('../../src/renderer/src/components/WorkPanel.vue')).default)
    await flush()
    namedButton('Refresh work')
    namedButton('Close work')
    const panel = view.root.find('section')!
    expect(panel.props.role).not.toBe('dialog')
    expect(panel.props['aria-modal']).toBeUndefined()
    const preventDefault = vi.fn(), stopPropagation = vi.fn()
    panel.fire('keydown', { key: 'Escape', preventDefault, stopPropagation })
    expect(preventDefault).toHaveBeenCalledOnce()
    expect(stopPropagation).toHaveBeenCalledOnce()
    expect(workStore.work.open).toBe(false)
    expect(opener.focus).toHaveBeenCalledOnce()
  })

  it.each([true, false])('restores its opener on unmount only while focus is inside the wrapper (inside=%s)', async (inside) => {
    const opener = { isConnected: true, focus: vi.fn() }
    Object.assign(document, { activeElement: opener })
    view = mount((await import('../../src/renderer/src/components/WorkPanel.vue')).default)
    await flush()
    const active = { elsewhere: !inside }
    const panel = view.root.find('section')!
    Object.assign(panel, { contains: vi.fn((node) => inside && node === active) })
    Object.assign(document, { activeElement: active })
    view.unmount()
    view = undefined
    expect(opener.focus).toHaveBeenCalledTimes(inside ? 1 : 0)
  })
})

describe('concise work notice policy', () => {
  const notice = (changes: Partial<WorkNotice> = {}): WorkNotice => ({ key: 'agent:a1', name: 'agent: Check disks', state: 'running', busy: false, note: '', ...changes })
  it('does not narrate initial list contents or transient state churn', () => {
    expect(changedWorkNotices([notice()], [])).toEqual([])
    expect(changedWorkNotices([notice({ state: 'stopping' })], [notice()])).toEqual([])
    expect(changedWorkNotices([notice({ state: 'queued' })], [notice()])).toEqual([{ key: 'agent:a1', text: 'agent: Check disks. queued.' }])
    expect(changedWorkNotices([notice({ state: 'consumed' })], [notice({ state: 'queued' })])[0]!.text).toContain('consumed')
  })
  it('caps burst announcements, preserves the most useful receipt, and qualifies kind', () => {
    expect(workName(agent())).toBe('agent: Check disks')
    expect(workAnnouncement(['One.', 'Two.', 'Three.', 'Four.', 'Five.'])).toBe('One. Two. Three. 2 other work items changed.')
    expect(changedWorkNotices([notice({ state: 'completed', note: 'Stop: done' })], [notice()])).toEqual([{ key: 'agent:a1', text: 'agent: Check disks. Stop: done' }])
    expect(changedWorkNotices([notice({ note: 'Run now: done' })], [notice({ busy: true, note: 'Run now: done' })])[0]!.text).toContain('Run now: done')
  })
})
