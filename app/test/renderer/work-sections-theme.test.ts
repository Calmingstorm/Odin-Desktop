// The Work column's sections and General's theme choice, with the real stores and components on Vue's plain-object
// renderer. The preload bridge is a stub; nothing reaches a core.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount } from './component-host'
import General from '../../src/renderer/src/views/settings/General.vue'
import WorkList from '../../src/renderer/src/components/WorkList.vue'
import { state } from '../../src/renderer/src/store'
import { bySection, grouped, work } from '../../src/renderer/src/stores/work'
import type { WorkItem } from '../../src/shared/api'

function item(kind: WorkItem['kind'], id: string, itemState: string, started: number): WorkItem {
  return { kind, id, title: `${kind} ${id}`, state: itemState, started_at: started, detail: '', actions: [] }
}

describe('the Work column groups work by what it is doing', () => {
  beforeEach(() => {
    vi.stubGlobal('window', { odin: {} })
    work.items = [
      item('process', 'old', 'exited', 100), item('agent', 'a', 'running', 300), item('schedule', 's', 'active', 50),
      item('task', 't', 'completed', 200), item('process', 'p', 'stopping', 400), item('loop', 'l', 'admitted', 350)
    ]
  })
  afterEach(() => vi.unstubAllGlobals())

  it('puts every item in exactly one section: running now, scheduled, finished, most recent first', () => {
    const sections = bySection()
    expect(sections.map((s) => [s.label, s.items.map((i) => i.id)])).toEqual([
      ['Running now', ['p', 'l', 'a']],
      ['Scheduled', ['s']],
      ['Finished', ['t', 'old']]
    ])
    const listed = sections.flatMap((s) => s.items.map((i) => `${i.kind}:${i.id}`)).sort()
    expect(listed).toEqual(work.items.map((i) => `${i.kind}:${i.id}`).sort())
  })

  it('shows each item with its kind in the column, and keeps kind groups elsewhere', async () => {
    const column = mount(WorkList, { sections: true })
    await flush()
    const headings = column.root.findAll((host) => host.tag === 'h2').map((h) => h.textContent().replace(/\s+/g, ' ').trim())
    expect(headings).toEqual(['Running now 3', 'Scheduled 1', 'Finished 2'])
    const kinds = column.root.findAll((host) => String(host.props.class ?? '') === 'work-kind').map((k) => k.textContent())
    expect(kinds).toEqual(['Process', 'Loop', 'Agent', 'Schedule', 'Task', 'Process'])
    column.unmount()
    const settings = mount(WorkList)
    await flush()
    const groups = settings.root.findAll((host) => host.tag === 'h2').map((h) => h.textContent().replace(/\s+/g, ' ').trim())
    expect(groups).toEqual(grouped().map((g) => `${g.label} ${g.items.length}`))
    expect(settings.root.findAll((host) => String(host.props.class ?? '') === 'work-kind')).toHaveLength(0)
    settings.unmount()
  })
})

describe("General's theme choice", () => {
  const setAppearance = vi.fn(async (appearance: string) => ({ ok: true, result: { appearance } }))
  beforeEach(() => {
    vi.stubGlobal('window', { odin: { setAppearance, checkReleases: async () => ({ ok: false, error: { code: 'x', message: 'x' } }) } })
    state.appearance = 'system'
    state.notifications = null
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    setAppearance.mockClear()
  })

  it('offers System, Dark and Light as one named radio group and saves a choice through the bridge', async () => {
    const view = mount(General)
    await flush()
    const group = view.root.findAll((host) => host.tag === 'fieldset')[0]!
    expect(group.find('legend')!.textContent()).toBe('Theme')
    const radios = group.findAll((host) => host.tag === 'input')
    expect(radios.map((r) => [r.props.type, r.props.name, r.props.value, r.props.checked])).toEqual([
      ['radio', 'appearance', 'system', true], ['radio', 'appearance', 'dark', false], ['radio', 'appearance', 'light', false]
    ])
    expect(group.findAll((host) => host.tag === 'label').map((l) => l.textContent().trim())).toEqual(['System', 'Dark', 'Light'])
    radios[1]!.fire('change')
    await flush()
    expect(setAppearance).toHaveBeenCalledExactlyOnceWith('dark')
    expect(state.appearance).toBe('dark')
    expect(radios.map((r) => r.props.checked)).toEqual([false, true, false])
    view.unmount()
  })
})
