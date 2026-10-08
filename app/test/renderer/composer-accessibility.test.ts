import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Mounted } from './component-host'

let mounted: Mounted
beforeEach(async () => {
  vi.resetModules()
  vi.stubGlobal('window', { odin: {}, addEventListener() {} })
  vi.stubGlobal('document', { activeElement: null, addEventListener() {}, visibilityState: 'hidden', hasFocus: () => false })
  const Component = (await import('../../src/renderer/src/components/Composer.vue')).default
  mounted = mount(Component)
  await flush()
})
afterEach(() => { mounted.unmount(); vi.unstubAllGlobals() })

describe('composer accessibility contract', () => {
  it('names the stopping invocation and elapsed time in both button text and accessible name', async () => {
    vi.useFakeTimers()
    try {
      vi.setSystemTime(new Date('2026-10-05T00:01:10Z'))
      const { state } = await import('../../src/renderer/src/store')
      Object.assign(window.odin, { getDraft: vi.fn(async () => ({ ok: true, result: { text: '' } })) })
      state.activeId = 'c1'
      state.views.c1 = { status: 'ready', hasData: true, epoch: 0, loadEpoch: 0, watermark: 0, loadToken: 0, held: [], messages: [], hasMore: false,
        loadingOlder: false, running: { request_id: 'run', generation: 1, started_at: '2026-10-04T00:00:00Z' }, queued: [], recent: [], unresolved: [], controls: {},
        tools: { run: [{ invocation_id: 'call', tool: 'run_command', summary: '', started_at: '2026-10-05T00:00:00Z', generation: 1 }] } }
      state.controls.push({ control_command_id: 'stop', kind: 'stop', conversation_id: 'c1', request_id: 'run', generation: 1, status: 'requested' })
      await flush()
      const button = mounted.root.named('Stopping… waiting for run_command to finish (1:10)')
      expect(button.textContent()).toContain('Stopping… waiting for run_command to finish (1:10)')
      expect(button.props['aria-disabled']).toBe(true)
      // aria-disabled is deliberately focusable; repeated clicks must not dispatch a second Stop.
      const stop = vi.fn()
      Object.assign(window.odin, { stop })
      await button.fire('click', { currentTarget: button })
      expect(stop).not.toHaveBeenCalled()
      await vi.advanceTimersByTimeAsync(1000); await flush()
      expect(mounted.root.named('Stopping… waiting for run_command to finish (1:11)')).toBe(button)
      state.views.c1!.tools.run![0]!.outcome = 'success'; await flush()
      expect(mounted.root.named('Stopping…')).toBe(button)
      // When the focused Stop disappears at task end, focus returns to the message field.
      const focus = vi.fn()
      const doc = document as unknown as { activeElement: unknown; body: unknown; querySelector: unknown }
      doc.body = {}
      let reads = 0
      const focusedStop = mounted.setup.stopButton
      Object.defineProperty(doc, 'activeElement', { configurable: true, get: () => reads++ === 0 ? focusedStop : doc.body })
      doc.querySelector = () => ({ focus })
      state.views.c1!.running = null
      // Object-hosts have no browser focus manager: model body becoming active after the removal.
      await flush()
      expect(focus).toHaveBeenCalledOnce()
    } finally { vi.useRealTimers() }
  })

  it('announces command report readiness structurally without speaking report contents or drafts', async () => {
    const announcement = mounted.root.findAll((h) => h.props.class === 'report-announcement')[0]!
    expect(announcement).toBeDefined()
    expect(announcement.props.role).toBe('status')
    expect(announcement.props['aria-live']).toBe('polite')
    expect(announcement.props['aria-atomic']).toBe('true')
    expect(announcement.textContent()).toBe('')
    const { state, showPanel } = await import('../../src/renderer/src/store')
    mounted.setup.text = 'private draft sentinel'
    showPanel('Status', 'private report contents sentinel')
    await flush()
    expect(announcement.textContent()).toBe('Status report ready.')
    expect(announcement.textContent()).not.toContain('private')
    expect(mounted.root.findAll((h) => h.props.class === 'report-announcement')).toEqual([announcement])
    state.panel!.text = 'updated private report contents sentinel'
    await flush()
    expect(announcement.textContent()).toBe('Status report ready.')
    showPanel('Usage, 7d', 'unspoken usage details')
    await flush()
    expect(announcement.textContent()).toBe('Usage, 7d report ready.')
    state.panel = null
    await flush()
    expect(announcement.textContent()).toBe('')
  })
  it('labels and describes the message field, associating attachment errors', async () => {
    const field = mounted.root.find('textarea')!
    expect(field.props['aria-label']).toBe('Message')
    expect(field.props['aria-describedby']).toBe('composer-help')
    const { composer } = await import('../../src/renderer/src/stores/composer')
    composer.errors = ['The attachment was refused.']
    await flush()
    expect(field.props['aria-invalid']).toBe(true)
    expect(field.props['aria-describedby']).toContain('composer-errors')
    expect(mounted.root.findAll((h) => h.props.id === 'composer-errors')[0]!.textContent()).toContain('refused')
  })
  it('exposes a native multiline textbox with suggestions, dismisses without erasing a draft and lets Shift+Tab leave', async () => {
    mounted.setup.text = '/sta'
    await flush()
    const field = mounted.root.find('textarea')!
    expect(field.props.role).toBeUndefined()
    expect(field.props['aria-autocomplete']).toBe('list')
    expect(field.props['aria-controls']).toBe('command-palette')
    expect(field.props['aria-activedescendant']).toMatch(/^command-option-/)
    const preventDefault = vi.fn()
    field.fire('keydown', { key: 'Tab', shiftKey: true, preventDefault })
    expect(preventDefault).not.toHaveBeenCalled()
    field.fire('keydown', { key: 'Escape', preventDefault })
    await flush()
    expect(mounted.setup.text).toBe('/sta')
    expect(field.props['aria-controls']).toBeUndefined()
    expect(field.props['aria-activedescendant']).toBeUndefined()
  })
  it('completes on Tab once, then allows the next Tab to leave', async () => {
    mounted.setup.text = '/sta'
    await flush()
    const field = mounted.root.find('textarea')!
    const preventDefault = vi.fn()
    field.fire('keydown', { key: 'Tab', shiftKey: false, preventDefault })
    await flush()
    expect(preventDefault).toHaveBeenCalledTimes(1)
    expect(mounted.setup.text).toBe('/status ')
    expect(field.props['aria-controls']).toBeUndefined()
    field.fire('keydown', { key: 'Tab', shiftKey: false, preventDefault })
    expect(preventDefault).toHaveBeenCalledTimes(1)
  })
})
