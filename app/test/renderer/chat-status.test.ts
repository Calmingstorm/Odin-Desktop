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
    state.views = {}
    status.epoch = state.recoveryEpoch
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
    expect(buttons(header.root)).toEqual(['gpt-6.1-sol · medium', 'Context 30% · Quota 34% · 2.4K tokens in 7d'])
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

  it('reports the connection from the rail and always names it in the status bar', async () => {
    const rail = mount(IconRail)
    const bar = mount(StatusBar)
    await flush()
    const link = rail.root.findAll((host) => host.props.role === 'status')[0]!
    expect(link.props.class).toBe('link rail-link ready')
    expect(link.textContent()).toBe('Connected')
    expect(bar.root.textContent()).toContain('Connected')
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

  it('hides only absent context, retaining zero quota, zero tokens and the report link', async () => {
    status.usage = { period: '24h', tokens: measured(0), summary: '',
      context: { used: { value: null, kind: 'unknown' }, budget: { value: null, kind: 'unknown' } },
      quota: [{ account: 'Primary', window: 'weekly', used_percent: measured(0), resets_at: null }] }
    const header = mount(ChatStatus)
    await flush()
    expect(buttons(header.root)).toEqual(['gpt-6.1-sol · medium', 'Quota 0% · 0 tokens in 24h'])
    expect(header.root.textContent()).not.toContain('Context')
    expect(header.root.findAll((node) => node.tag === 'button')[1]!.props.title).toContain('measured')
    header.unmount()
  })

  it('retains actual zero context, estimates and unknown labels without inventing values', async () => {
    status.usage!.context.used = measured(0)
    status.usage!.tokens = { value: 20, kind: 'estimated' }
    status.usage!.quota[0]!.used_percent = { value: null, kind: 'unknown' }
    const header = mount(ChatStatus)
    await flush()
    expect(buttons(header.root)[1]).toBe('Context 0% · Quota — · ~20 tokens in 7d')
    header.unmount()
  })

  it('epoch or core-instance mismatch hides stale header facts and provider warnings', async () => {
    status.core!.providers = [{ name: 'codex', health: 'degraded' }]
    status.epoch = state.recoveryEpoch - 1
    const header = mount(ChatStatus)
    const bar = mount(StatusBar)
    await flush()
    expect(header.root.textContent()).toBe('')
    expect(bar.root.textContent()).not.toContain('codex')
    status.epoch = state.recoveryEpoch
    status.core!.core_instance_id = 'older-core'
    await flush()
    expect(header.root.textContent()).not.toContain('gpt-6.1-sol')
    expect(header.root.textContent()).toContain('2.4K tokens')
    expect(bar.root.textContent()).not.toContain('codex')
    header.unmount()
    bar.unmount()
  })

  it('shows only actionable provider problems and retains uncertainty plus report navigation', async () => {
    status.core!.providers = ['ok', 'unknown', 'disabled', 'degraded', 'unavailable'].map((health) => ({ name: health, health }))
    state.app.unreceipted = 2
    state.app.cleanupWarning = { id: 'notice' } as NonNullable<typeof state.app.cleanupWarning>
    state.views = { chat: { unresolved: [{ unknown_effects: 3 }] } as NonNullable<typeof state.views[string]> }
    const bar = mount(StatusBar)
    await flush()
    expect(buttons(bar.root)).toEqual(['Status', 'Usage', 'degraded degraded', 'unavailable unavailable'])
    expect(bar.root.textContent()).toContain('2 awaiting receipt')
    expect(bar.root.textContent()).toContain('3 unknown effects')
    expect(bar.root.textContent()).toContain('Cleanup needs attention')
    expect(bar.root.textContent()).not.toContain('Start at login')
    bar.root.button('degraded degraded').fire('click')
    expect([state.view, state.settingsSection]).toEqual(['settings', 'models'])
    bar.unmount()
  })

  it('retains current independent zero usage when core status fails', async () => {
    status.core = null
    status.coreError = 'Status could not be read'
    status.usage = { period: '24h', tokens: measured(0), summary: '',
      context: { used: { value: null, kind: 'unknown' }, budget: { value: null, kind: 'unknown' } },
      quota: [{ account: 'Primary', window: 'week', used_percent: measured(0), resets_at: null }] }
    const header = mount(ChatStatus)
    await flush()
    expect(buttons(header.root)).toEqual(['Quota 0% · 0 tokens in 24h'])
    header.unmount()
  })
})
