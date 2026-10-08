// Object-renderer/CSS contracts, not native pixel qualification.
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { flush, mount, type Mounted } from './component-host'
let views: Mounted[] = []
const ok = (result: unknown) => ({ ok: true, result })
beforeEach(() => {
  vi.resetModules()
  ;(globalThis as any).document = { activeElement: null }
  ;(globalThis as any).window = { odin: new Proxy({
    getDesktopInfo: async () => ok({ desktop_version: '1' }),
    memoryList: async () => ok({ owner: { count: 0 }, global: { count: 0 } }),
    listsList: async () => ok({ items: [] }), knowledgeList: async () => ok([])
  }, { get: (target: any, key: string) => target[key] ?? (async () => ({ ok: false, error: { code: 'capability_unavailable', message: 'Unavailable' } })) }) }
})
afterEach(() => { views.forEach(v => v.unmount()); views = [] })
it('scopes stable width, scrollbar allocation, list padding, form labels/footer and selected nav to Settings', () => {
  const css = readFileSync(new URL('../../src/renderer/src/styles.css', import.meta.url), 'utf8')
  expect(css).toMatch(/\.settings-body\s*\{[^}]*scrollbar-gutter: stable/)
  expect(css).toMatch(/\.settings-content\s*\{[^}]*max-width: 880px/)
  expect(css).toContain('.settings-content .settings-card > .manage-list > .manage-row { padding: 16px var(--settings-padding); }')
  expect(css).toContain('.settings-form-actions { display: flex; justify-content: flex-end;')
  expect(css).toContain('.settings-subnav button[aria-current=page]')
  expect(css).toContain('.settings-form label:not(.toggle-inline):not(.settings-row-label)')
})
it('exposes section actions beside heading', async () => {
  const Section = (await import('../../src/renderer/src/components/settings/SettingsSection.vue')).default
  const { h } = await import('vue')
  const v = mount({ render: () => h(Section, { title: 'Accounts', description: 'Choose an account.' }, { actions: () => h('button', {}, 'Add account') }) }); views.push(v)
  expect(v.root.button('Add account').parent?.props.class).toBe('settings-section-actions')
  expect(v.root.button('Add account').parent?.parent?.tag).toBe('header')
})
it('visibly groups timezone search/select and removes empty Theme tail', async () => {
  const { settings } = await import('../../src/renderer/src/stores/settings')
  settings.meta = { revision: 'r1', fields: [{ path: 'timezone', type: 'string', desired: 'UTC', effective: 'UTC', apply_handler: 'settings.set', sensitivity: 'public', constraints: {}, apply_state: 'applied' }] } as any
  const v = mount((await import('../../src/renderer/src/views/settings/General.vue')).default); views.push(v); await flush()
  const search = v.root.findAll(n => n.props.placeholder === 'Search time zones')[0]!
  expect(search.parent?.props.class).toBe('settings-timezone')
  expect(search.parent?.find('select')?.props.id).toBe('settings-curated-timezone')
  const theme = v.root.findAll(n => n.tag === 'section' && n.textContent().startsWith('Appearance'))[0]!
  expect(theme.findAll(n => n.props.class === 'settings-row-note')).toHaveLength(0)
})
it('subsections expose selected state and personal memory says You, preserving raw owner scope for writes', async () => {
  const v = mount((await import('../../src/renderer/src/views/settings/DataPrivacy.vue')).default); views.push(v); await flush()
  expect(v.root.button('Memory and knowledge').props['aria-pressed']).toBe(true)
  expect(v.root.named('Open You memory').props['aria-controls']).toBe('memory-entries-owner')
  v.root.button('Conversations').fire('click'); await flush()
  expect(v.root.button('Conversations').props['aria-pressed']).toBe(true)
  expect(v.root.button('Memory and knowledge').props['aria-pressed']).toBe(false)
  v.root.button('Usage, logs and audit').fire('click'); await flush()
  expect(v.root.button('Usage, logs and audit').props['aria-current']).toBe('page')
})
