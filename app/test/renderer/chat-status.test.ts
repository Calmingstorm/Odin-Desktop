// The chat header's model and context, the slim status bar and the rail's connection indicator, on Vue's
// plain-object renderer with the real components and stores.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Host } from './component-host'
import ChatStatus from '../../src/renderer/src/components/ChatStatus.vue'
import IconRail from '../../src/renderer/src/components/IconRail.vue'
import StatusBar from '../../src/renderer/src/components/StatusBar.vue'
import { state } from '../../src/renderer/src/store'
import { status } from '../../src/renderer/src/stores/status'

const measured = (value: number) => ({ value, kind: 'measured' as const })

function buttons(root: Host): string[] {
  return root.findAll((host) => host.tag === 'button').map((button) => button.textContent().replace(/\s+/g, ' ').trim())
}

describe('status in the chat header, the status bar and the rail', () => {
  beforeEach(() => {
    vi.stubGlobal('window', { odin: {} })
    state.app = { link: 'ready', coreInstanceId: 'core-1234567890', noTray: false, unreceipted: 0, cleanupWarning: null }
    status.core = { phase: 'ready', core_instance_id: 'core-1234567890', version: '0.1.0', capabilities: [],
      model: { main: 'gpt-6.1-sol', effort: 'medium', provider: 'codex' }, providers: [{ name: 'codex', health: 'ok' }] }
    status.usage = { period: '7d', tokens: measured(2400), summary: '',
      context: { used: measured(30), budget: measured(100) },
      quota: [{ account: 'Primary', window: 'weekly', used_percent: measured(34), resets_at: null }] }
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows the model and context in the header, each opening its report, and leaves them out of the status bar', async () => {
    const header = mount(ChatStatus)
    const bar = mount(StatusBar)
    await flush()
    expect(buttons(header.root)).toEqual(['gpt-6.1-sol · medium', 'Context 30% · Quota 34% · 2.4K tokens in 24h'])
    expect(header.root.findAll((host) => host.tag === 'button').every((button) => typeof button.props.onClick === 'function')).toBe(true)
    expect(buttons(bar.root).some((text) => text.includes('gpt-6.1-sol') || text.includes('Context'))).toBe(false)
    header.unmount()
    bar.unmount()
  })

  it('shows nothing stale in the header while the link is down', async () => {
    state.app = { ...state.app, link: 'reconnecting' }
    const header = mount(ChatStatus)
    await flush()
    expect(header.root.textContent().trim()).toBe('')
    header.unmount()
  })

  it('reports the connection from the rail, and names it in the status bar only while it is not connected', async () => {
    const rail = mount(IconRail)
    const bar = mount(StatusBar)
    await flush()
    const link = rail.root.findAll((host) => host.props.role === 'status')[0]!
    expect(link.props.class).toBe('link rail-link ready')
    expect(link.textContent()).toBe('Connected')
    expect(bar.root.textContent()).not.toContain('Connected')
    state.app = { ...state.app, link: 'reconnecting' }
    await flush()
    expect(link.props.class).toBe('link rail-link reconnecting')
    expect(link.textContent()).toBe('Reconnecting')
    // The rail announces the change; the status bar repeats it in words without a second live region.
    const words = bar.root.findAll((host) => String(host.props.class ?? '').split(' ').includes('link-text'))[0]!
    expect(words.textContent()).toBe('Reconnecting')
    expect(words.props.role).toBeUndefined()
    rail.unmount()
    bar.unmount()
  })
})
