// Real client-compiled SFC + real draft store. Browser geometry is proved separately.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { flush, Host, mount, type Mounted } from './component-host'

let mounted: Mounted
let state: any
let store: typeof import('../../src/renderer/src/stores/composer')
let send: ReturnType<typeof vi.fn>
let stop: ReturnType<typeof vi.fn>
let dispatch: ReturnType<typeof vi.fn>
let pasted: ReturnType<typeof vi.fn>
let disconnected: ReturnType<typeof vi.fn>
const originals = new Map<string, PropertyDescriptor | undefined>()
const styles = new WeakMap<Host, Record<string, string>>()
function install(key: string, descriptor: PropertyDescriptor) {
  originals.set(key, Object.getOwnPropertyDescriptor(Host.prototype, key))
  Object.defineProperty(Host.prototype, key, { configurable: true, ...descriptor })
}
const field = () => mounted.root.find('textarea')! as Host & { style: Record<string, string> }
const type = async (text: string) => { field().type(text); await flush() }

beforeEach(async () => {
  vi.resetModules(); vi.useFakeTimers()
  install('__v_skip', { value: true })
  install('style', { get(this: Host) { if (!styles.has(this)) styles.set(this, {}); return styles.get(this) } })
  install('clientWidth', { get: () => 400 })
  install('parentElement', { get: () => null })
  disconnected = vi.fn()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect = disconnected })
  vi.stubGlobal('MutationObserver', undefined)
  vi.stubGlobal('getComputedStyle', () => ({ fontSize: '16px', lineHeight: '20px', paddingTop: '9px', paddingBottom: '9px' }))
  vi.stubGlobal('document', { activeElement: null, body: {}, querySelector: vi.fn() })
  pasted = vi.fn(async () => ({ ok: true, result: { id: 'pasted', name: 'pasted.png', size: 1, mime: 'image/png' } }))
  vi.stubGlobal('window', { addEventListener: vi.fn(), removeEventListener: vi.fn(), odin: {
    getDraft: vi.fn(async (id: string) => ({ ok: true, result: { text: id === 'c2' ? 'restored\ndraft' : '' } })),
    setDraft: vi.fn(async () => ({ ok: true, result: {} })), attachBytes: pasted,
    pickFiles: vi.fn(async () => ({ ok: true, result: { staged: [], errors: [] } })),
    attachFiles: vi.fn(async () => ({ ok: true, result: { staged: [], errors: [] } })),
    cancelAttachment: vi.fn(async () => ({ ok: true, result: { cancelled: true } })),
    status: vi.fn(async () => ({ ok: true, result: { limits: { attachments_per_turn: 10 } } })),
    onAttachmentProgress: vi.fn(() => () => {}),
    uploadAttachment: vi.fn(async () => ({ ok: true, result: { ref: 'ref-pasted', name: 'pasted.png', size: 1, mime: 'image/png' } }))
  } })
  state = reactive({ activeId: 'c1', app: { link: 'ready' }, views: {}, notice: '', panel: null })
  send = vi.fn(async () => true); stop = vi.fn(async () => undefined)
  vi.doMock('../../src/renderer/src/store', () => ({ state, send, stop, canAct: () => true, chatUnavailable: () => false, loadFailure: () => '', retry: vi.fn(), stopPending: () => false }))
  dispatch = vi.fn(async () => true)
  const commands = [{ name: 'status', usage: '/status', affects: 'Read status' }, { name: 'stop', usage: '/stop', affects: 'Stop' }]
  vi.doMock('../../src/renderer/src/commands', () => ({ dispatch, matchCommands: (text: string) => commands.filter((c) => c.name.startsWith(text.slice(1).trim())), parseCommand: () => ({ arg: '' }) }))
  vi.doMock('../../src/renderer/src/stores/status', () => ({ status: reactive({ usageUnavailable: false }) }))
  store = await import('../../src/renderer/src/stores/composer')
  mounted = mount((await import('../../src/renderer/src/components/Composer.vue')).default)
  const mirror = mounted.root.findAll((node) => node.props.class === 'composer-measurement')[0]!
  Object.defineProperty(mirror, 'textContent', { configurable: true, get() { return () => mirror.text }, set(value: string) { mirror.text = value } })
  Object.defineProperty(mirror, 'scrollHeight', { configurable: true, get() {
    const text = mirror.text
    return 18 + 20 * text.split('\n').length
  } })
  await flush()
})
afterEach(() => {
  mounted?.unmount()
  for (const [key, value] of originals) { if (value) Object.defineProperty(Host.prototype, key, value); else delete (Host.prototype as any)[key] }
  originals.clear(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks()
})

describe('compiled growing Composer', () => {
  it('starts one line, grows/caps/shrinks from input and recalculates restored conversation drafts', async () => {
    expect(field().props.rows).toBe('1'); expect(field().style.height).toBe('38px')
    await type('one\ntwo'); expect(field().style.height).toBe('58px')
    await type(Array(30).fill('line').join('\n'))
    expect(field().style).toMatchObject({ height: '178px', overflowY: 'auto' })
    await type('short'); expect(field().style.height).toBe('38px')
    state.activeId = 'c2'; await flush()
    expect(field().value).toBe('restored\ndraft'); expect(field().style.height).toBe('58px'); expect(store.box.owner).toBe('c2')
    mounted.unmount(); expect(disconnected).toHaveBeenCalledOnce()
  })
  it('resets accepted sends, retains rejected drafts and never clears newer text on late acceptance', async () => {
    await type('one\ntwo'); await (mounted.setup.submit as () => Promise<void>)(); await flush()
    expect(send).toHaveBeenLastCalledWith('one\ntwo', 'queue', []); expect(field().style.height).toBe('38px')
    send.mockResolvedValueOnce(false)
    await type('recoverable\ndraft'); await (mounted.setup.submit as () => Promise<void>)(); await flush()
    expect(field().value).toBe('recoverable\ndraft'); expect(field().style.height).toBe('58px')
    let accept!: (accepted: boolean) => void
    send.mockImplementationOnce(() => new Promise((resolve) => { accept = resolve }))
    const pending = (mounted.setup.submit as () => Promise<void>)()
    await type('newer\ntext\nstays'); accept(true); await pending; await flush()
    expect(field().value).toBe('newer\ntext\nstays'); expect(field().style.height).toBe('78px')
  })
  it('keeps IME/Shift+Enter native, sizes ordinary paste through input and preserves file paste routing', async () => {
    await type('draft')
    const preventDefault = vi.fn()
    field().fire('keydown', { key: 'Enter', isComposing: true, preventDefault })
    field().fire('keydown', { key: 'Enter', shiftKey: true, preventDefault })
    expect(preventDefault).not.toHaveBeenCalled(); expect(send).not.toHaveBeenCalled()
    field().fire('paste', { clipboardData: { files: [] }, preventDefault }); expect(preventDefault).not.toHaveBeenCalled()
    await type('ordinary\npasted\ntext'); expect(field().style.height).toBe('78px')
    field().fire('paste', { clipboardData: { files: [new File(['x'], 'paste.png', { type: 'image/png' })] }, preventDefault })
    await flush()
    expect(preventDefault).toHaveBeenCalledOnce(); expect(pasted).toHaveBeenCalledOnce(); expect(field().value).toBe('ordinary\npasted\ntext')
  })
  it('contains instructions only in palette, preserving navigation/completion/dismissal', async () => {
    expect(mounted.root.textContent()).toContain('Enter to send · Shift+Enter for a new line · / for commands')
    expect(mounted.root.textContent()).not.toContain('Home/End')
    await type('/')
    expect(mounted.root.textContent()).toContain('Home/End'); expect(field().props['aria-describedby']).toContain('composer-palette-help')
    const preventDefault = vi.fn()
    field().fire('keydown', { key: 'End', preventDefault }); await flush()
    expect(field().props['aria-activedescendant']).toBe('command-option-stop')
    field().fire('keydown', { key: 'Home', preventDefault }); await flush()
    field().fire('keydown', { key: 'ArrowDown', preventDefault }); await flush()
    field().fire('keydown', { key: 'ArrowUp', preventDefault }); await flush()
    field().fire('keydown', { key: 'Tab', preventDefault }); await flush()
    expect(field().value).toBe('/status '); expect(mounted.root.textContent()).not.toContain('Home/End')
    await type('/st'); field().fire('keydown', { key: 'Escape', preventDefault }); await flush()
    expect(field().value).toBe('/st'); expect(field().props['aria-describedby']).toBe('composer-help')
    await type('/status'); await (mounted.setup.submit as () => Promise<void>)(); await flush()
    expect(dispatch).toHaveBeenCalledOnce(); expect(field().value).toBe(''); expect(field().style.height).toBe('38px')
  })
  it('retains Steer/Queue and Stop labels/routing while growing', async () => {
    state.views.c1 = { running: { request_id: 'r1', generation: 1 } }; await flush()
    await type('guidance\nmore'); expect(mounted.root.named('Steer')).toBeDefined()
    await (mounted.setup.submit as () => Promise<void>)(); await flush(); expect(send).toHaveBeenLastCalledWith('guidance\nmore', 'steer', [])
    mounted.setup.mode = 'queue'; await type('follow-up'); expect(mounted.root.named('Queue')).toBeDefined()
    await (mounted.setup.submit as () => Promise<void>)(); await flush(); expect(send).toHaveBeenLastCalledWith('follow-up', 'queue', [])
    const button = mounted.root.named('Stop the current task')
    await button.fire('click', { currentTarget: button }); await flush(); expect(stop).toHaveBeenCalledOnce()
    field().fire('keydown', { key: '.', ctrlKey: true, preventDefault: vi.fn() }); expect(stop).toHaveBeenCalledTimes(2)
  })
  it('keeps attachment actions, report focus return, blank-send guard and failed commands intact', async () => {
    await (mounted.setup.submit as () => Promise<void>)(); expect(send).not.toHaveBeenCalled()
    await mounted.root.named('Attach files').fire('click'); await flush()
    expect(window.odin.pickFiles).toHaveBeenCalledOnce()
    const form = mounted.root.find('form')!
    form.fire('drop', { dataTransfer: { files: [new File(['x'], 'drop.txt')] }, preventDefault: vi.fn() }); await flush()
    expect(window.odin.attachFiles).toHaveBeenCalledOnce()
    form.fire('drop', { dataTransfer: null, preventDefault: vi.fn() }); await flush()
    store.composer.attachments.c1 = [{ id: 'a1', name: 'ready.txt', mime: 'text/plain', size: 1, status: 'ready', ref: 'ref', sent: 1, addToKnowledge: false }]
    await flush()
    ;(mounted.setup.onKnowledge as (id: string, checked: boolean) => void)('a1', true)
    expect(store.attachmentsFor('c1')[0]!.addToKnowledge).toBe(true)
    ;(mounted.setup.onRemove as (id: string) => void)('a1'); await flush()
    expect(store.attachmentsFor('c1')).toEqual([])
    const focus = vi.fn(); vi.mocked(document.querySelector).mockReturnValue({ focus } as any)
    state.panel = { title: 'Status', text: 'Report' }; await flush()
    await mounted.root.named('Close command report').fire('click'); await flush()
    expect(state.panel).toBeNull(); expect(focus).toHaveBeenCalledOnce()
    await type('/status'); dispatch.mockResolvedValueOnce(false)
    const preventDefault = vi.fn()
    field().fire('keydown', { key: 'Enter', preventDefault }); await flush()
    expect(preventDefault).toHaveBeenCalledOnce(); expect(field().value).toBe('/status')
    dispatch.mockResolvedValueOnce(true)
    await mounted.root.findAll((node) => node.props.role === 'option')[0]!.fire('click'); await flush()
    expect(field().value).toBe('')
  })
})
