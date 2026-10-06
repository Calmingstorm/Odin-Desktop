// Mount the actual detail/output card. Unknown/late reads never execute a tool.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result, ToolDetail } from '../../src/shared/api'
import { flush, mount, type Mounted } from './component-host'

let mounted: Mounted
const pending: Array<(result: Result<ToolDetail>) => void> = []
const entry = { invocation_id: 'invocation', tool: 'run_command', summary: 'run_command', outcome: 'success' as const }
type Entry = typeof entry
const detail = (text: string): Result<ToolDetail> => ({ ok: true, result: {
  tool: 'run_command', arguments: { command: 'pwd' },
  previews: [{ label: 'Output preview', text, truncated: false }], output: {}
} })

beforeEach(async () => {
  pending.length = 0
  ;(globalThis as unknown as { window: unknown }).window = { odin: {
    toolDetail: vi.fn(() => new Promise((resolve) => pending.push(resolve as (r: Result<ToolDetail>) => void)))
  } }
  const component = (await import('../../src/renderer/src/components/ToolActivity.vue')).default
  mounted = mount(component, { entries: [entry], requestId: 'request', live: true })
  await flush()
})

afterEach(() => mounted.unmount())

describe('retained tool details', () => {
  it('does not let an old read replace a collapsed and reopened invocation', async () => {
    const toggle = mounted.setup.toggle as (value: Entry) => Promise<void>
    const first = toggle(entry)
    await flush()
    await toggle(entry) // collapse while the first read is still unanswered
    const second = toggle(entry)
    await flush()
    pending[1]!(detail('new read'))
    await second
    pending[0]!(detail('old read'))
    await first
    await flush()
    expect(mounted.root.textContent()).toContain('new read')
    expect(mounted.root.textContent()).not.toContain('old read')
    expect(window.odin.toolDetail).toHaveBeenCalledTimes(2)
  })

  it('shows the real service refusal instead of invented detail/output', async () => {
    const toggle = mounted.setup.toggle as (value: Entry) => Promise<void>
    const read = toggle(entry)
    pending[0]!({ ok: false, error: { code: 'not_found', message: 'Tool detail is unavailable' } })
    await read
    await flush()
    expect(mounted.root.textContent()).toContain('Tool detail is unavailable')
    expect(mounted.root.textContent()).not.toContain('Show full output')
  })
})
