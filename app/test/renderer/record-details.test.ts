import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RecordDetails from '../../src/renderer/src/components/RecordDetails.vue'
import { flush, mount, type Mounted } from './component-host'

const ok = (result: unknown) => ({ ok: true, result })
const page = (lines: string[], cursor = 'c1', extra: Record<string, unknown> = {}) => ok({ lines, cursor, ...extra })
let bridge: Record<string, ReturnType<typeof vi.fn>>
let mounted: Mounted | undefined

beforeEach(() => {
  vi.useFakeTimers()
  bridge = {
    auditDiffs: vi.fn().mockResolvedValue(ok({ diffs: [], total: 0 })),
    auditFailures: vi.fn().mockResolvedValue(ok({ failures: [], total: 0 })),
    logsStats: vi.fn().mockResolvedValue(ok({ count: 4 })),
    auditTail: vi.fn().mockResolvedValue(page(['audit line'])),
    logsTail: vi.fn().mockResolvedValue(page(['log line']))
  }
  ;(globalThis as unknown as { window: unknown }).window = { odin: bridge }
})
afterEach(() => {
  mounted?.unmount()
  mounted = undefined
  vi.useRealTimers()
})
function view(): Mounted { return mounted = mount(RecordDetails) }
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  return { promise: new Promise((done) => { resolve = done }), resolve }
}

describe('Records extras over the named bridge only', () => {
  it('keeps unknown and loading states distinct from an empty or zero result', async () => {
    const held = deferred<ReturnType<typeof ok>>()
    bridge.logsStats!.mockReturnValue(held.promise)
    const v = view()
    expect(Object.values(bridge).every((call) => call.mock.calls.length === 0)).toBe(true)
    expect(v.root.textContent()).toContain('Not read yet.')
    expect(v.root.textContent()).not.toContain('0 retained lines.')
    v.root.button('Read log statistics').fire('click')
    await flush()
    expect(v.root.textContent()).toContain('Reading…')
    expect(v.root.findAll((node) => node.tag === 'pre')).toHaveLength(0)
    held.resolve(ok({ count: 0 }))
    await flush()
    expect(bridge.logsStats).toHaveBeenCalledWith({})
    expect(v.root.textContent()).toContain('"count": 0')
  })

  it('sends minimal bounded filters and displays raw diff/failure results', async () => {
    const v = view()
    const inputs = v.root.findAll((node) => node.tag === 'input')
    inputs[0]!.type('  run_command  ')
    inputs[1]!.type('48')
    v.root.button('Read audit diffs').fire('click')
    v.root.button('Read audit failures').fire('click')
    await flush()
    expect(bridge.auditDiffs).toHaveBeenCalledWith({ limit: 50, tool: 'run_command' })
    expect(bridge.auditFailures).toHaveBeenCalledWith({ window: 48 })
    expect(v.root.textContent()).toContain('"diffs": []')
    expect(v.root.textContent()).toContain('"failures": []')
  })

  it('serializes tail reads, polls only after completion, and sends the source cursor', async () => {
    const held = deferred<ReturnType<typeof page>>()
    bridge.auditTail!.mockReturnValueOnce(held.promise).mockResolvedValue(page(['next'], 'c2'))
    const v = view()
    v.root.button('Follow audit tail').fire('click')
    await flush()
    expect(v.root.button('Stop audit tail').props.disabled).toBe(false)
    expect(v.root.button('Follow audit tail').props['aria-pressed']).toBe(true)
    // Even a programmatic click on the disabled other control cannot overlap reads.
    v.root.button('Follow log tail').fire('click')
    await vi.advanceTimersByTimeAsync(5000)
    expect(bridge.auditTail).toHaveBeenCalledTimes(1)
    expect(bridge.logsTail).not.toHaveBeenCalled()
    held.resolve(page(['first']))
    await flush()
    await vi.advanceTimersByTimeAsync(999)
    expect(bridge.auditTail).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    await flush()
    expect(bridge.auditTail).toHaveBeenNthCalledWith(1, { lines: 200 })
    expect(bridge.auditTail).toHaveBeenNthCalledWith(2, { lines: 200, cursor: 'c1' })
    expect(v.root.textContent()).toContain('first\nnext')
  })

  it('retains only 200 lines and displays its own truncation separately from source metadata', async () => {
    bridge.auditTail!.mockResolvedValueOnce(page(Array.from({ length: 200 }, (_, i) => `first ${i}`)))
      .mockResolvedValueOnce(page(['new 1', 'new 2'], 'c2', { truncated: true, reset: false, dropped: 7 }))
    const v = view()
    v.root.button('Follow audit tail').fire('click')
    await flush()
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    const output = v.root.findAll((node) => node.props['aria-label'] === 'Audit tail retained lines')[0]!
    expect(output.textContent().split('\n')).toHaveLength(200)
    expect(output.textContent()).not.toContain('first 0\n')
    expect(output.textContent()).toContain('new 1\nnew 2')
    expect(v.root.textContent()).toContain('2 older lines are no longer shown here.')
    expect(v.root.textContent()).toContain('"truncated": true')
    expect(v.root.textContent()).toContain('"dropped": 7')
  })

  it('replaces retained lines on a source reset and when reading latest explicitly', async () => {
    bridge.logsTail!.mockResolvedValueOnce(page(['old']))
      .mockResolvedValueOnce(page(['rotated'], 'c2', { reset: true, reset_reason: 'rotated' }))
      .mockResolvedValueOnce(page(['latest'], 'c3'))
    const v = view()
    v.root.button('Follow log tail').fire('click')
    await flush()
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    const output = () => v.root.findAll((node) => node.props['aria-label'] === 'Log tail retained lines')[0]!.textContent()
    expect(output()).toBe('rotated')
    expect(v.root.textContent()).toContain('"reset_reason": "rotated"')
    v.root.button('Stop log tail').fire('click')
    v.root.button('Read latest log tail').fire('click')
    await flush()
    expect(bridge.logsTail).toHaveBeenLastCalledWith({ lines: 200 })
    expect(output()).toBe('latest')
  })

  it.each([
    { ok: false, error: { code: 'unavailable', message: 'outcome unknown', disposition: 'unknown' } },
    ok({ lines: 'not a line array', cursor: 'x' })
  ])('stops after error or unrecognized result, without an automatic retry', async (answer) => {
    bridge.auditTail!.mockResolvedValueOnce(page(['last successful'])).mockResolvedValueOnce(answer)
    const v = view()
    v.root.button('Follow audit tail').fire('click')
    await flush()
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    expect(v.root.textContent()).toContain('Follow stopped.')
    expect(v.root.textContent()).toContain('No automatic retry.')
    expect(v.root.textContent()).toContain('last successful')
    expect(v.root.button('Follow audit tail').props['aria-pressed']).toBe(false)
    await vi.advanceTimersByTimeAsync(10000)
    expect(bridge.auditTail).toHaveBeenCalledTimes(2)
  })

  it('isolates a new capability refusal from other extras', async () => {
    const refusal = { ok: false, error: { code: 'capability_unavailable', message: 'not enabled', disposition: 'not_dispatched' } }
    bridge.auditTail!.mockResolvedValue(refusal)
    bridge.auditDiffs!.mockResolvedValue(refusal)
    const v = view()
    v.root.button('Follow audit tail').fire('click')
    v.root.button('Read audit diffs').fire('click')
    await flush()
    expect(v.root.textContent()).toContain('Audit tail is unavailable.')
    expect(v.root.textContent()).toContain('Audit diffs is unavailable.')
    expect(v.root.button('Read audit failures')).toBeDefined()
    v.root.button('Read log statistics').fire('click')
    await flush()
    expect(v.root.textContent()).toContain('"count": 4')
    await vi.advanceTimersByTimeAsync(10000)
    expect(bridge.auditTail).toHaveBeenCalledTimes(1)
  })

  it('new capability refusal does not hide the existing Records panels', async () => {
    const refusal = { ok: false, error: { code: 'capability_unavailable', message: 'not enabled', disposition: 'not_dispatched' } }
    Object.assign(bridge, {
      healthGet: vi.fn().mockResolvedValue(refusal),
      usage: vi.fn().mockResolvedValue(refusal),
      auditQuery: vi.fn().mockResolvedValue(ok([{ timestamp: '', tool_name: 'existing_tool', result_summary: 'existing audit result' }])),
      logsSearch: vi.fn().mockResolvedValue(ok({ entries: [], count: 0 })),
      turnStateList: vi.fn().mockResolvedValue(refusal),
      computerStatus: vi.fn().mockResolvedValue(refusal),
      auditDiffs: vi.fn().mockResolvedValue(refusal)
    })
    const Records = (await import('../../src/renderer/src/views/settings/Records.vue')).default
    mounted = mount(Records)
    await flush()
    mounted.root.button('Read audit diffs').fire('click')
    await flush()
    expect(mounted.root.textContent()).toContain('Audit diffs is unavailable.')
    expect(mounted.root.textContent()).toContain('existing audit result')
    expect(mounted.root.findAll((node) => node.props['aria-label'] === 'Logs')).toHaveLength(1)
  })

  it('stops on a missing source without claiming a known empty tail', async () => {
    bridge.logsTail!.mockResolvedValue(page([], 'c1', { availability: 'missing' }))
    const v = view()
    v.root.button('Follow log tail').fire('click')
    await flush()
    expect(v.root.textContent()).toContain('Source availability: missing. No current tail data.')
    expect(v.root.textContent()).not.toContain('0 retained lines.')
    expect(v.root.textContent()).toContain('"availability": "missing"')
    await vi.advanceTimersByTimeAsync(10000)
    expect(bridge.logsTail).toHaveBeenCalledTimes(1)
  })

  it('a one-shot latest read stops rather than silently stranding another follow', async () => {
    const v = view()
    v.root.button('Follow audit tail').fire('click')
    await flush()
    v.root.button('Read latest log tail').fire('click')
    await flush()
    expect(v.root.button('Follow audit tail').props['aria-pressed']).toBe(false)
    await vi.advanceTimersByTimeAsync(10000)
    expect(bridge.auditTail).toHaveBeenCalledTimes(1)
    expect(bridge.logsTail).toHaveBeenCalledTimes(1)
  })

  it('stops scheduled polling on unmount and ignores a late reply', async () => {
    const held = deferred<ReturnType<typeof page>>()
    bridge.auditTail!.mockReturnValue(held.promise)
    const v = view()
    v.root.button('Follow audit tail').fire('click')
    await flush()
    v.unmount()
    mounted = undefined
    held.resolve(page(['late']))
    await flush()
    await vi.advanceTimersByTimeAsync(10000)
    expect(bridge.auditTail).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('clears an already scheduled follow timer on unmount', async () => {
    const v = view()
    v.root.button('Follow audit tail').fire('click')
    await flush()
    expect(vi.getTimerCount()).toBe(1)
    v.unmount()
    mounted = undefined
    await vi.advanceTimersByTimeAsync(10000)
    expect(bridge.auditTail).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('stops on a rejected bridge promise without scheduling a retry', async () => {
    bridge.logsTail!.mockRejectedValue(new Error('bridge disconnected'))
    const v = view()
    v.root.button('Follow log tail').fire('click')
    await flush()
    expect(v.root.textContent()).toContain('bridge disconnected')
    expect(v.root.button('Follow log tail').props['aria-pressed']).toBe(false)
    await vi.advanceTimersByTimeAsync(10000)
    expect(bridge.logsTail).toHaveBeenCalledTimes(1)
  })

  it('stops while a read is outstanding and never schedules its late completion', async () => {
    const held = deferred<ReturnType<typeof page>>()
    bridge.logsTail!.mockReturnValue(held.promise)
    const v = view()
    v.root.button('Follow log tail').fire('click')
    await flush()
    v.root.button('Stop log tail').fire('click')
    held.resolve(page(['completed once']))
    await flush()
    await vi.advanceTimersByTimeAsync(10000)
    expect(bridge.logsTail).toHaveBeenCalledTimes(1)
    expect(v.root.textContent()).toContain('completed once')
    expect(v.root.button('Follow log tail').props['aria-pressed']).toBe(false)
  })
})
