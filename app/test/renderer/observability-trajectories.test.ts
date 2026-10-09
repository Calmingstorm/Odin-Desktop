import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Observability from '../../src/renderer/src/components/ObservabilityDetails.vue'
import Trajectories from '../../src/renderer/src/components/TrajectoryDetails.vue'
import { completion } from '../../src/renderer/src/stores/completion'
import { management } from '../../src/renderer/src/stores/management'
import { applyReceipt } from '../../src/renderer/src/store'
import { flush, mount, type Mounted } from './component-host'
const mocks = vi.hoisted(() => ({ ask: vi.fn() }))
vi.mock('../../src/renderer/src/dialog', () => ({ ask: mocks.ask }))
let view: Mounted
const bridge = {
  observabilityStats: vi.fn(), recoveryStats: vi.fn(), recoveryRecent: vi.fn(), capacitySnapshot: vi.fn(), poolsSsh: vi.fn(), poolsHttp: vi.fn(), poolsClose: vi.fn(),
  trajectoriesList: vi.fn(), trajectoriesRead: vi.fn(), trajectoriesSearch: vi.fn(), trajectoriesMessage: vi.fn()
}
beforeEach(() => {
  delete management.busy['connection-pools']
  delete management.notes['connection-pools']
  for (const key of Object.keys(completion)) delete completion[key]
  for (const fn of Object.values(bridge)) fn.mockReset().mockResolvedValue({ ok: true, result: {} })
  mocks.ask.mockReset().mockResolvedValue(true)
  vi.stubGlobal('window', { odin: bridge })
})
afterEach(() => { view?.unmount(); vi.unstubAllGlobals() })
describe('smallest honest observability and trajectory sections', () => {
  it('uses section headings outside report and connection-action cards', () => {
    view = mount(Observability)
    const sections = view.root.findAll((n) => String(n.props.class).split(' ').includes('settings-section'))
    expect(sections).toHaveLength(7)
    for (const section of sections) {
      expect(section.findAll((n) => n.tag === 'h3')).toHaveLength(1)
      const card = section.findAll((n) => String(n.props.class).split(' ').includes('settings-card'))[0]!
      expect(card.findAll((n) => n.tag === 'h3')).toHaveLength(0)
    }
    expect(bridge.observabilityStats).not.toHaveBeenCalled()
    expect(bridge.poolsClose).not.toHaveBeenCalled()
  })

  it('shows unread before clicks and retains unavailable measurements as reported', async () => {
    bridge.observabilityStats.mockResolvedValue({ ok: true, result: { compression: { available: false, reason: 'not measured' } } })
    view = mount(Observability); await flush()
    expect(bridge.observabilityStats).not.toHaveBeenCalled()
    expect(view.root.textContent()).toContain('Not read yet.')
    await view.root.button('Read Runtime statistics').fire('click'); await flush()
    expect(view.root.textContent()).toContain('not measured')
    expect(view.root.textContent()).not.toContain('0 tokens')
    bridge.observabilityStats.mockResolvedValue({ ok: false, error: { code: 'capability_unavailable', message: 'old core' } })
    await view.root.button('Read Runtime statistics').fire('click'); await flush()
    expect(view.root.textContent()).toContain('Runtime statistics is unavailable.')
    expect(view.root.textContent()).not.toContain('not measured')
  })
  it('requires confirmation before close and calls the named mutation', async () => {
    view = mount(Observability)
    mocks.ask.mockResolvedValueOnce(false)
    await view.root.button('Close all pools…').fire('click'); await flush()
    expect(bridge.poolsClose).not.toHaveBeenCalled()
    await view.root.button('Close all pools…').fire('click'); await flush()
    expect(bridge.poolsClose).toHaveBeenCalledWith({})
    expect(bridge.poolsSsh).toHaveBeenCalledWith({})
  })
  it('passes selected trace filters and snapshots the label for the returned data', async () => {
    view = mount(Trajectories)
    Object.assign(view.setup, { filename: 'trace.jsonl' })
    Object.assign(view.setup.filters as object, { channel_id: 'c', user_id: 'owner', tool_name: 'read_file', errors_only: true, limit: 25 })
    await (view.setup.readTrace as (search: boolean) => Promise<void>)(false); await flush()
    expect(bridge.trajectoriesRead).toHaveBeenCalledWith({ filename: 'trace.jsonl', channel_id: 'c', user_id: 'owner', tool_name: 'read_file', errors_only: true, limit: 25 })
    expect(view.root.textContent()).toContain('trace.jsonl')
    await (view.setup.readTrace as (search: boolean) => Promise<void>)(true)
    expect(bridge.trajectoriesSearch).toHaveBeenCalledWith({ channel_id: 'c', user_id: 'owner', tool_name: 'read_file', errors_only: true, limit: 25 })
  })
  it('never repeats uncertain pool closure and handles a late capability refusal', async () => {
    bridge.poolsClose.mockResolvedValue({ ok: false, error: { code: 'outcome_unknown', message: 'Waiting', disposition: 'outcome_unknown', command_id: 'pool-1' } })
    view = mount(Observability)
    await (view.setup.closePools as (all: boolean) => Promise<void>)(true)
    await (view.setup.closePools as (all: boolean) => Promise<void>)(true)
    expect(bridge.poolsClose).toHaveBeenCalledTimes(1)
    expect(management.busy['connection-pools']).toBe(true)
    applyReceipt({ id: 'pool-1', settled: { ok: false, error: { code: 'capability_unavailable', message: 'old core' } } })
    await flush()
    expect(management.busy['connection-pools']).toBe(false)
    expect(view.root.textContent()).toContain('Connection pool actions is unavailable.')
  })

  it('lists trajectory files by name, and choosing one fills the filename to read (1.0.5 L12)', async () => {
    bridge.trajectoriesList.mockResolvedValue({ ok: true, result: { files: ['2026-10-08.jsonl', '2026-10-09.jsonl'], count: 2 } })
    view = mount(Trajectories); await flush()
    await view.root.button('List trajectory files').fire('click'); await flush()
    expect(view.root.textContent()).not.toContain('"count"')
    await view.root.button('2026-10-09.jsonl').fire('click'); await flush()
    expect(view.setup.filename).toBe('2026-10-09.jsonl')
    bridge.trajectoriesList.mockResolvedValue({ ok: true, result: { files: [], count: 0 } })
    await view.root.button('List trajectory files').fire('click'); await flush()
    expect(view.root.textContent()).toContain('No trajectory files yet.')
  })
})
