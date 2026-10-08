// The Import from Odin dialog: connect, choose, import, then the results and the host key.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Mounted } from './component-host'

let views: Mounted[] = []
const items = [
  { category: 'memory', id: 'global', label: "Odin's shared memory", detail: '2 entries', exists: false, notes: [], selected: true },
  { category: 'skills', id: 'weather', label: 'weather', detail: 'Reads the weather', exists: false, notes: [], selected: false },
  { category: 'skills', id: 'old', label: 'old', detail: '', exists: true, notes: [], selected: false },
  { category: 'hosts', id: 'server', label: 'server', detail: 'root@192.168.1.13', exists: false, notes: ['Needs Odin Desktop\'s SSH key on this host before it connects.'], selected: true }
]
const report = {
  outcomes: [
    { category: 'memory', id: 'global', label: "Odin's shared memory", status: 'imported', message: '2 entries added.' },
    { category: 'hosts', id: 'server', label: 'server', status: 'needs_attention', message: "Couldn't sign in to root@192.168.1.13." }
  ],
  public_key: 'ssh-ed25519 DESKTOPKEY desktop'
}

function odin(preview: unknown = { ok: true, result: { items } }) {
  return {
    odinImportPreview: vi.fn(async () => preview),
    odinImportApply: vi.fn(async () => ({ ok: true, result: report })),
    copyText: vi.fn(async () => ({ ok: true, result: { copied: true } }))
  }
}

beforeEach(() => vi.resetModules())
afterEach(() => { views.forEach((v) => v.unmount()); views = []; vi.unstubAllGlobals() })

async function fixture(api = odin()) {
  vi.stubGlobal('window', { odin: api })
  const v = mount((await import('../../src/renderer/src/components/settings/OdinImport.vue')).default)
  views.push(v)
  const dialog = () => v.root.find('dialog')
  const form = () => v.root.find('form')!
  const text = () => v.root.textContent()
  return { v, api, dialog, form, text }
}

describe('Import from Odin dialog', () => {
  it('asks Odin with the address and token, then offers only what is new, ticked as suggested', async () => {
    const { v, api, dialog, form, text } = await fixture()
    expect(dialog()).toBeUndefined()
    v.root.button('Import from Odin').fire('click')
    await flush()
    expect(dialog()).toBeDefined()
    const token = v.root.findAll((h) => h.tag === 'input' && h.props.type === 'password')[0]!
    token.type('tok-1')
    form().fire('submit', { preventDefault: () => {} })
    await flush()
    expect(api.odinImportPreview).toHaveBeenCalledWith({ url: 'http://localhost:3002', token: 'tok-1' })
    expect(text()).toContain('Already in Odin Desktop')
    const boxes = v.root.findAll((h) => h.tag === 'input' && h.props.type === 'checkbox')
    expect(boxes.find((b) => b.props.value === 'skills/old')?.props.disabled).toBe(true)
    expect(v.setup.picks).toEqual([{ category: 'memory', id: 'global' }, { category: 'hosts', id: 'server' }])
    expect(text()).toContain('Import 2')
  })

  it('imports the picks, shows the results with the SSH key, retries hosts, and forgets the token on close', async () => {
    const { v, api, dialog, form, text } = await fixture()
    v.root.button('Import from Odin').fire('click')
    await flush()
    v.root.findAll((h) => h.tag === 'input' && h.props.type === 'password')[0]!.type('tok-1')
    form().fire('submit', { preventDefault: () => {} })
    await flush()
    form().fire('submit', { preventDefault: () => {} })
    await flush()
    expect(api.odinImportApply).toHaveBeenCalledWith({ url: 'http://localhost:3002', token: 'tok-1', picks: [
      { category: 'memory', id: 'global' }, { category: 'hosts', id: 'server' }
    ] })
    expect(text()).toContain('Needs your attention')
    expect(text()).toContain('2 entries added.')
    v.root.button('Copy key').fire('click')
    await flush()
    expect(api.copyText).toHaveBeenCalledWith('ssh-ed25519 DESKTOPKEY desktop')
    v.root.button('Retry hosts').fire('click')
    await flush()
    expect(api.odinImportApply).toHaveBeenLastCalledWith({ url: 'http://localhost:3002', token: 'tok-1', picks: [{ category: 'hosts', id: 'server' }] })
    form().fire('submit', { preventDefault: () => {} })
    await flush()
    expect(dialog()).toBeUndefined()
    expect((v.setup.form as { token: string }).token).toBe('')
  })

  it('asks for the address and token first, and recovers from errors at each step', async () => {
    const api = odin()
    const { v, form, text } = await fixture(api)
    v.root.button('Import from Odin').fire('click')
    await flush()
    form().fire('submit', { preventDefault: () => {} })
    await flush()
    expect(text()).toContain("Enter Odin's address and an API token.")
    expect(api.odinImportPreview).not.toHaveBeenCalled()
    api.odinImportPreview.mockRejectedValueOnce(new Error('ipc'))
    v.root.findAll((h) => h.tag === 'input' && h.props.type === 'password')[0]!.type('tok-1')
    form().fire('submit', { preventDefault: () => {} })
    await flush()
    expect(text()).toContain("Couldn't ask Odin. Try again.")
    form().fire('submit', { preventDefault: () => {} })
    await flush()
    const skill = v.root.findAll((h) => h.tag === 'input' && h.props.value === 'skills/weather')[0]!
    skill.checked = true
    skill.fire('change')
    await flush()
    expect(v.setup.picks).toEqual(expect.arrayContaining([{ category: 'skills', id: 'weather' }]))
    api.odinImportApply.mockResolvedValueOnce({ ok: false, error: { code: 'import_failed', message: "Couldn't reach Odin." } } as never)
    form().fire('submit', { preventDefault: () => {} })
    await flush()
    expect(text()).toContain("Couldn't reach Odin.")
    api.odinImportApply.mockRejectedValueOnce(new Error('ipc'))
    form().fire('submit', { preventDefault: () => {} })
    await flush()
    expect(text()).toContain("The import didn't finish. Nothing more was changed.")
    v.root.button('Back').fire('click')
    await flush()
    expect(v.setup.step).toBe('connect')
  })

  it("shows Odin's refusal in plain words and stays on the address step", async () => {
    const { v, form, text } = await fixture(odin({ ok: false, error: { code: 'import_failed', message: "Odin didn't accept this token." } }))
    v.root.button('Import from Odin').fire('click')
    await flush()
    v.root.findAll((h) => h.tag === 'input' && h.props.type === 'password')[0]!.type('bad')
    form().fire('submit', { preventDefault: () => {} })
    await flush()
    expect(text()).toContain("Odin didn't accept this token.")
    expect(v.setup.step).toBe('connect')
  })
})
