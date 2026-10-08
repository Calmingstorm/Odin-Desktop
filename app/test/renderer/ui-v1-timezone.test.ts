import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flush, mount, type Mounted } from './component-host'

let mounted: Mounted | undefined
const saves = vi.fn()
const meta = { schema_version: 1, revision: 'revision', status: { counts: {}, desired_revision: 'revision', effective_revision: 'revision' }, fields: [] as any[] }
const settings = { meta, fields: {} as Record<string, any>, error: '', unavailable: false }
beforeEach(async () => {
  vi.resetModules()
  saves.mockReset()
  meta.fields = [{ path: 'timezone', label: 'Timezone', description: '', type: 'string', enum: null, constraints: {}, desired: 'UTC', effective: 'UTC', sensitivity: 'public', apply_handler: null, apply_state: 'applied', pending_restart: false }]
  settings.fields = {}
  const { reactive } = await import('vue')
  vi.doMock('../../src/renderer/src/stores/settings', () => ({ settings: reactive(settings), saveField: saves, resetField: vi.fn() }))
  ;(globalThis as any).window = { odin: { getDesktopInfo: async () => ({ ok: false, error: { message: 'Unavailable' } }) } }
})
afterEach(() => { mounted?.unmount(); mounted = undefined; vi.doUnmock('../../src/renderer/src/stores/settings') })

it('searches valid named zones with the detected system first and never writes on search or mount', async () => {
  mounted = mount((await import('../../src/renderer/src/views/settings/General.vue')).default)
  await flush()
  expect(saves).not.toHaveBeenCalled()
  const select = mounted.root.find('select')!
  const system = Intl.DateTimeFormat().resolvedOptions().timeZone
  expect(select.findAll((node) => node.tag === 'option')[0]!.textContent()).toBe(`System: ${system}`)
  const search = mounted.root.findAll((node) => node.props['aria-label'] === 'Find a time zone')[0]!
  search.fire('input', { target: { value: 'tokyo' } }); await flush()
  expect(select.textContent()).toContain('Asia/Tokyo')
  expect(select.textContent()).not.toContain('Europe/Paris')
  expect(saves).not.toHaveBeenCalled()
  select.fire('change', { target: { value: 'not/a/zone' } }); await flush()
  expect(saves).not.toHaveBeenCalled()
  select.fire('change', { target: { value: 'Asia/Tokyo' } }); await flush()
  expect(saves).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ path: 'timezone' }), 'Asia/Tokyo')
  expect(mounted.root.textContent()).toContain('Unsaved changes')
  mounted.root.button('Cancel time zone change').fire('click'); await flush()
  expect(select.props.value).toBe('UTC')
})

it('omits unknown applied-value warnings without writing or claiming a running time zone', async () => {
  meta.fields[0].apply_state = 'unknown'
  meta.fields[0].effective = null
  mounted = mount((await import('../../src/renderer/src/views/settings/General.vue')).default)
  await flush()
  expect(mounted.root.find('select')!.props.value).toBe('UTC')
  expect(mounted.root.textContent()).not.toMatch(/running time zone|Check the connection|Ready/i)
  expect(saves).not.toHaveBeenCalled()
  expect(meta.fields[0].effective).toBeNull()
})

it('retains failed drafts for deliberate retry and exposes read-only and non-applied states', async () => {
  saves.mockResolvedValue(false)
  meta.fields[0].apply_state = 'drift'
  mounted = mount((await import('../../src/renderer/src/views/settings/General.vue')).default)
  await flush()
  const select = mounted.root.find('select')!
  select.fire('change', { target: { value: 'Europe/Paris' } }); await flush()
  expect(mounted.root.textContent()).toContain('saved and running time zones differ')
  expect(mounted.root.textContent()).not.toContain('Saved')
  mounted.root.button('Save time zone').fire('click'); await flush()
  expect(saves).toHaveBeenCalledTimes(2)
  const { settings: reactiveSettings } = await import('../../src/renderer/src/stores/settings')
  reactiveSettings.meta!.fields[0]!.apply_handler = 'unsupported.method'
  await flush()
  expect(select.props.disabled).toBe(true)
  expect(mounted.root.textContent()).toContain('cannot be changed right now')
})
