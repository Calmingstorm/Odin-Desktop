import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { flush, mount, type Mounted } from './component-host'

type Store = typeof import('../../src/renderer/src/store')
let store: Store
let mounted: Mounted
beforeEach(async () => {
  vi.resetModules(); vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-05T00:01:10Z'))
  store = await import('../../src/renderer/src/store')
  store.state.activeId = 'c1'
  store.state.views.c1 = { status: 'ready', hasData: true, epoch: 0, loadEpoch: 0, watermark: 0, loadToken: 0, held: [], messages: [], hasMore: false,
    loadingOlder: false, running: { request_id: 'run', generation: 2, started_at: '2026-10-04T00:00:00Z' }, queued: [], recent: [], unresolved: [], tools: {}, controls: {} }
  store.state.controls.push({ control_command_id: 'stop', kind: 'stop', conversation_id: 'c1', request_id: 'run', generation: 2, status: 'requested' })
  const { useStoppingLabel } = await import('../../src/renderer/src/stopping-label')
  mounted = mount(defineComponent({ setup() { const { label } = useStoppingLabel(); return () => h('p', label.value) } }))
})
afterEach(() => { mounted.unmount(); vi.useRealTimers() })

describe('stopping invocation clock', () => {
  it('shows plain stopping without a running tool, and never times from the request start', () => {
    expect(mounted.root.textContent()).toBe('Stopping…')
    expect(vi.getTimerCount()).toBe(0)
  })
  it('ignores settled and earlier-generation tools; snapshot-only tools have names but no invented age', async () => {
    store.state.views.c1!.tools.run = [
      { invocation_id: 'settled', tool: 'old', summary: '', outcome: 'success' },
      { invocation_id: 'prior', tool: 'prior', summary: '', generation: 1, started_at: '2026-10-05T00:00:00Z' },
      { invocation_id: 'live', tool: 'run_command', summary: '' }
    ]
    await flush()
    expect(mounted.root.textContent()).toBe('Stopping… waiting for run_command to finish')
  })
  it('clamps clock skew and clears the one-second ticker at unmount and conversation switch', async () => {
    store.state.views.c1!.tools.run = [{ invocation_id: 'call', tool: 'run_command', summary: '', generation: 2, started_at: '2026-10-05T00:02:00Z' }]
    await flush()
    expect(mounted.root.textContent()).toBe('Stopping… waiting for run_command to finish (0:00)')
    expect(vi.getTimerCount()).toBe(1)
    store.state.activeId = 'other'; await flush()
    expect(vi.getTimerCount()).toBe(0)
    store.state.activeId = 'c1'; await flush()
    expect(vi.getTimerCount()).toBe(1)
    mounted.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
