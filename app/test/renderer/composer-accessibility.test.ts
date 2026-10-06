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
