// Your name and pictures in chat, and a picture per personality: the store, the picture pipeline, chat messages, the
// General and Personality settings and the picker, with the real code over a fake bridge. Nothing reaches a core.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ArtifactRef, DisplayProfile, Message as ChatMessage, Result } from '../../src/shared/api'
import { flush, heldFrames, mount, type Mounted } from './component-host'

vi.mock('../../src/renderer/src/dialog', () => ({ ask: async () => true }))
vi.mock('../../src/renderer/src/markdown', () => ({ renderMarkdown: (text: string) => `<p>${text}</p>` }))
vi.mock('../../src/renderer/src/artifacts', () => ({
  showsInline: (a: ArtifactRef) => a.kind === 'image' && a.available,
  images: { acquire: () => ({ url: Promise.resolve('blob:fixture'), release: vi.fn() }) }
}))
vi.mock('../../src/renderer/src/components/FileCard.vue', () => ({ default: { render: () => null } }))
vi.mock('../../src/renderer/src/components/ReportViewer.vue', () => ({ default: { render: () => null } }))

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const refused = (message: string) => ({ ok: false, error: { code: 'bad_request', message } }) as const
const MINE = 'data:image/png;base64,bWluZQ=='
const CLIPPY = 'data:image/png;base64,Y2xpcHB5'
const saved: DisplayProfile = { name: 'Aaron', user: MINE, personalities: [{ key: 'clippy-astra', picture: CLIPPY }] }

let odin: Record<string, ReturnType<typeof vi.fn>>
let mounted: Mounted | undefined

beforeEach(() => {
  vi.resetModules()
  odin = {
    getDisplayProfile: vi.fn(async () => ok(saved)),
    setDisplayName: vi.fn(async (name: string) => ok({ ...saved, name })),
    setDisplayPicture: vi.fn(async () => ok(saved)),
    removeDisplayPicture: vi.fn(async () => ok({ ...saved, personalities: [] }))
  }
  ;(globalThis as unknown as { window: unknown }).window = { odin }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null, getElementById: vi.fn(() => null) }
})
afterEach(() => {
  mounted?.unmount()
  mounted = undefined
  vi.unstubAllGlobals()
})

const store = () => import('../../src/renderer/src/stores/display-profile')

describe('display profile store', () => {
  it('loads once, retries a failed load, and defaults to "You" and Odin\'s mark', async () => {
    odin.getDisplayProfile!.mockResolvedValueOnce(refused('Could not read.'))
    const s = await store()
    await s.loadDisplayProfile()
    expect(s.userName()).toBe('You')
    expect(s.userPicture()).toBeNull()
    expect(s.personalityPicture('clippy-astra')).toBeNull()
    await s.loadDisplayProfile()
    await s.loadDisplayProfile()
    expect(odin.getDisplayProfile).toHaveBeenCalledTimes(2)
    expect(s.userName()).toBe('Aaron')
    expect(s.userPicture()).toBe(MINE)
    const { activePersonality } = await import('../../src/renderer/src/assistant-name')
    activePersonality.value = { preset: 'clippy-astra' } as never
    expect(s.personalityPicture()).toBe(CLIPPY)
    activePersonality.value = { preset: 'default' } as never
    expect(s.personalityPicture()).toBeNull()
  })

  it('keeps the defaults on a page without the app bridge', async () => {
    ;(globalThis as unknown as { window: unknown }).window = { odin: {} }
    const s = await store()
    await expect(s.loadDisplayProfile()).resolves.toBeUndefined()
    expect(s.userName()).toBe('You')
  })

  it('crops the centred square and scales it to 256 x 256 PNG', async () => {
    const s = await store()
    expect(s.squareCrop(400, 200)).toEqual({ x: 100, y: 0, side: 200 })
    expect(s.squareCrop(300, 501)).toEqual({ x: 0, y: 100, side: 300 })
    const close = vi.fn()
    const drawImage = vi.fn()
    vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 400, height: 200, close })))
    const canvas = {
      width: 0, height: 0,
      getContext: () => ({ drawImage }),
      toBlob: (done: (blob: Blob) => void) => done(new Blob([new Uint8Array([1, 2, 3])], { type: 'image/png' }))
    }
    ;(globalThis as unknown as { document: unknown }).document = { createElement: () => canvas }
    const png = await s.squarePicture(new Blob(['photo'], { type: 'image/jpeg' }))
    expect(png).toBe(btoa(String.fromCharCode(1, 2, 3)))
    expect(canvas.width).toBe(256)
    expect(drawImage).toHaveBeenCalledWith(expect.anything(), 100, 0, 200, 200, 0, 0, 256, 256)
    expect(close).toHaveBeenCalled()
    expect(s.base64(new Uint8Array(70_000).fill(65))).toBe(btoa('A'.repeat(70_000)))
  })

  it('refuses the wrong kind or size of file before reading it or calling the bridge', async () => {
    const decode = vi.fn()
    vi.stubGlobal('createImageBitmap', decode)
    const s = await store()
    expect(await s.saveDisplayPicture({ target: 'user' }, new Blob(['x'], { type: 'image/gif' })))
      .toBe('Choose a PNG, JPEG or WebP picture.')
    expect(await s.saveDisplayPicture({ target: 'user' }, new Blob([new Uint8Array(2 * 1024 * 1024 + 1)], { type: 'image/png' })))
      .toBe('Choose a picture up to 2 MB.')
    vi.stubGlobal('createImageBitmap', vi.fn(async () => { throw new Error('decoder detail') }))
    expect(await s.saveDisplayPicture({ target: 'user' }, new Blob(['x'], { type: 'image/webp' })))
      .toBe('That picture could not be read.')
    expect(decode).not.toHaveBeenCalled()
    expect(odin.setDisplayPicture).not.toHaveBeenCalled()
  })

  it('applies what the app saved and returns its refusal otherwise', async () => {
    const s = await store()
    expect(await s.saveDisplayName('Aaron C')).toBeNull()
    expect(s.userName()).toBe('Aaron C')
    odin.setDisplayName!.mockResolvedValueOnce(refused('Use up to 40 characters on one line.'))
    expect(await s.saveDisplayName('x'.repeat(41))).toBe('Use up to 40 characters on one line.')
    expect(s.userName()).toBe('Aaron C')
    expect(await s.removeDisplayPicture({ target: 'personality', key: 'clippy-astra' })).toBeNull()
    expect(s.personalityPicture('clippy-astra')).toBeNull()
  })
})

describe('display profile keys, superseded pictures and unreadable pictures', () => {
  it("treats preset keys such as __proto__ and constructor as data", async () => {
    const PROTO = 'data:image/png;base64,cHJvdG8='
    odin.getDisplayProfile!.mockResolvedValue(ok({ name: '', user: null, personalities: [{ key: '__proto__', picture: PROTO }] }))
    const s = await store()
    await s.loadDisplayProfile()
    expect(s.personalityPicture('__proto__')).toBe(PROTO)
    expect(s.personalityPicture('constructor')).toBeNull()
    expect(s.personalityPicture('toString')).toBeNull()
    odin.removeDisplayPicture!.mockResolvedValueOnce(ok({ name: '', user: null, personalities: [] }))
    expect(await s.removeDisplayPicture({ target: 'personality', key: '__proto__' })).toBeNull()
    expect(s.personalityPicture('__proto__')).toBeNull()
  })

  /** createImageBitmap held until the test releases it, as a slow decode would be. */
  function heldDecode() {
    let release!: () => void
    const decoded = new Promise<void>((resolve) => (release = resolve))
    vi.stubGlobal('createImageBitmap', vi.fn(async () => { await decoded; return { width: 10, height: 10, close: vi.fn() } }))
    ;(globalThis as unknown as { document: unknown }).document = {
      activeElement: null,
      getElementById: vi.fn(() => null),
      createElement: () => ({ getContext: () => ({ drawImage: vi.fn() }), toBlob: (done: (b: Blob) => void) => done(new Blob(['p'])) })
    }
    return release
  }

  it('drops a picture still being prepared when its target is removed meanwhile', async () => {
    const release = heldDecode()
    const s = await store()
    const target = { target: 'personality', key: 'clippy' } as const
    const upload = s.saveDisplayPicture(target, new Blob(['photo'], { type: 'image/png' }))
    expect(await s.removeDisplayPicture(target)).toBeNull()
    release()
    expect(await upload).toBe('That picture was replaced or removed before it was saved.')
    expect(odin.setDisplayPicture).not.toHaveBeenCalled()
    expect(odin.removeDisplayPicture).toHaveBeenCalledExactlyOnceWith(target)
  })

  it('keeps the newest picture chosen for a target, never an older one that finishes later', async () => {
    const release = heldDecode()
    const s = await store()
    const older = s.saveDisplayPicture({ target: 'user' }, new Blob(['older'], { type: 'image/png' }))
    vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 10, height: 10, close: vi.fn() })))
    expect(await s.saveDisplayPicture({ target: 'user' }, new Blob(['newer'], { type: 'image/png' }))).toBeNull()
    release()
    expect(await older).toBe('That picture was replaced or removed before it was saved.')
    expect(odin.setDisplayPicture).toHaveBeenCalledTimes(1)
  })

  it('shows the fallback for a picture the window cannot decode', async () => {
    const s = await store()
    await s.loadDisplayProfile()
    expect(s.userPicture()).toBe(MINE)
    s.pictureFailed(MINE)
    expect(s.userPicture()).toBeNull()
    expect(s.shownPicture(MINE)).toBeNull()
    expect(s.personalityPicture('clippy-astra')).toBe(CLIPPY)
  })
})

describe('chat shows your name and pictures', () => {
  const message = (patch: Partial<ChatMessage>): ChatMessage =>
    ({ id: 'm', role: 'user', text: 'hello', created_at: '2026-10-08T12:00:00Z', ...patch })

  async function shown(patch: Partial<ChatMessage>) {
    const { activePersonality } = await import('../../src/renderer/src/assistant-name')
    activePersonality.value = { preset: 'clippy-astra', presets: { 'clippy-astra': { name: 'Clippy' } } } as never
    const Message = (await import('../../src/renderer/src/components/Message.vue')).default
    mounted = mount(Message, { message: message(patch), conversationId: 'chat' })
    await flush()
    const avatar = mounted.root.findAll((node) => node.props.class !== undefined && String(node.props.class).includes('avatar'))[0]!
    return { root: mounted.root, image: avatar.findAll((node) => node.tag === 'img')[0] }
  }

  it('names your messages and shows your picture', async () => {
    const { root, image } = await shown({ role: 'user' })
    expect(root.textContent()).toContain('Aaron')
    expect(root.textContent()).not.toContain('You')
    expect(image?.props.src).toBe(MINE)
  })

  it('falls back to your icon when your picture fails to decode', async () => {
    const { image } = await shown({ role: 'user' })
    image!.fire('error')
    await flush()
    const avatar = mounted!.root.findAll((node) => node.props.class !== undefined && String(node.props.class).includes('avatar'))[0]!
    expect(avatar.findAll((node) => node.tag === 'img')).toEqual([])
  })

  it("shows the active personality's picture beside its replies, and Odin's mark without one", async () => {
    const clippy = await shown({ role: 'assistant' })
    expect(clippy.root.textContent()).toContain('Clippy')
    expect(clippy.image?.props.src).toBe(CLIPPY)
    mounted?.unmount()
    odin.getDisplayProfile!.mockResolvedValue(ok({ name: '', user: null, personalities: [] }))
    vi.resetModules()
    const odinMark = await shown({ role: 'assistant' })
    expect(String(odinMark.image?.props.src)).not.toBe(CLIPPY)
    expect(odinMark.image?.props.class).toBe('app-icon')
  })
})

describe("an empty chat's pending message", () => {
  it('shows your saved name and picture before any message has loaded', async () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
    const conversation = { id: 'c1', title: 'c1', rev: 1, parent_id: null, updated_at: '2026-10-05T00:00:00Z', unread: 0, archived: false }
    Object.assign(odin, {
      getAppState: vi.fn(async () => ({ link: 'ready', coreInstanceId: 'core-1', noTray: false, unreceipted: 0 })),
      getSettings: vi.fn(async () => ok({ autostart: false, notifications: { enabled: true } })),
      listConversations: vi.fn(async () => ok({ items: [{ ...conversation, activity: { running: null, queued: [] } }], watermark: '1' })),
      snapshotConversation: vi.fn(async () => ok({ conversation, watermark: '1', messages: { items: [], has_more: false },
        running: null, queued: [], recent: [], unresolved: [], tools: {}, controls: [] })),
      markRead: vi.fn(async () => ok({ conversation })),
      onEvent: () => () => undefined,
      onAppState: () => () => undefined,
      onReceipt: () => () => undefined,
      onReset: () => () => undefined,
      onOpenConversation: () => () => undefined
    })
    ;(globalThis as unknown as { window: unknown }).window = { odin, addEventListener: () => undefined }
    ;(globalThis as unknown as { document: unknown }).document = {
      visibilityState: 'hidden', hasFocus: () => false, addEventListener: () => undefined, activeElement: null,
      getElementById: () => null
    }
    heldFrames()
    const app = await import('../../src/renderer/src/store')
    await app.init()
    app.state.pending.push({ client_submission_id: 'first', conversation_id: 'c1', text: 'First words', status: 'unknown' })
    mounted = mount((await import('../../src/renderer/src/components/MessageList.vue')).default)
    await flush()
    expect(odin.getDisplayProfile).toHaveBeenCalledTimes(1)
    const row = mounted.root.findAll((node) => String(node.props.class ?? '').includes('pending'))[0]!
    expect(row.textContent()).toContain('Aaron')
    expect(row.textContent()).not.toContain('You')
    expect(row.findAll((node) => node.tag === 'img')[0]?.props.src).toBe(MINE)
  })
})

describe('settings for your profile and personality pictures', () => {
  it('saves your name from General and reports a refusal where it was made', async () => {
    Object.assign(odin, {
      getDesktopInfo: vi.fn(async () => refused('Unavailable')),
      settingsSchema: vi.fn(async () => refused('Unavailable'))
    })
    const { state } = await import('../../src/renderer/src/store')
    state.notifications = { enabled: true, previews: true, muted: [], quietHours: { enabled: false, start: '22:00', end: '08:00' } }
    mounted = mount((await import('../../src/renderer/src/views/settings/General.vue')).default)
    await flush()
    const field = mounted.root.findAll((node) => node.props.id === 'display-name')[0]!
    expect(field.props.value).toBe('Aaron')
    field.type('Aaron C')
    mounted.root.named('Save your name').fire('click')
    await flush()
    expect(odin.setDisplayName).toHaveBeenCalledExactlyOnceWith('Aaron C')
    expect(mounted.root.textContent()).toContain('Saved.')
    odin.setDisplayName!.mockResolvedValueOnce(refused('Use up to 40 characters on one line.'))
    field.type('x'.repeat(41))
    mounted.root.named('Save your name').fire('click')
    await flush()
    expect(mounted.root.textContent()).toContain('Use up to 40 characters on one line.')
  })

  it("offers a picture for the chosen personality and removes it with a deleted preset", async () => {
    Object.assign(odin, {
      personalityGet: vi.fn(async () => ok({
        preset: 'clippy-astra', custom_name: '', custom_identity: '', custom_voice: '',
        presets: { default: { name: 'Odin', identity: 'i', voice: 'v' }, 'clippy-astra': { name: 'Clippy', identity: 'c', voice: 'c' } },
        builtin_presets: ['default'], user_presets: ['clippy-astra']
      })),
      personalityPresetsDelete: vi.fn(async () => ok({ deleted: 'clippy-astra' }))
    })
    mounted = mount((await import('../../src/renderer/src/views/settings/Personality.vue')).default)
    await flush()
    expect(mounted.root.textContent()).toContain("Shown beside Clippy's replies")
    expect(mounted.root.named("Remove Clippy's picture")).toBeTruthy()
    mounted.root.named('Delete preset clippy-astra…').fire('click')
    await flush()
    expect(odin.personalityPresetsDelete).toHaveBeenCalled()
    expect(odin.removeDisplayPicture).toHaveBeenCalledExactlyOnceWith({ target: 'personality', key: 'clippy-astra' })
  })

  it('a picture still being prepared does not come back after its preset is deleted', async () => {
    let release!: () => void
    const decoded = new Promise<void>((resolve) => (release = resolve))
    vi.stubGlobal('createImageBitmap', vi.fn(async () => { await decoded; return { width: 10, height: 10, close: vi.fn() } }))
    ;(globalThis as unknown as { document: unknown }).document = {
      activeElement: null,
      getElementById: vi.fn(() => null),
      createElement: () => ({ getContext: () => ({ drawImage: vi.fn() }), toBlob: (done: (b: Blob) => void) => done(new Blob(['p'])) })
    }
    Object.assign(odin, {
      personalityGet: vi.fn(async () => ok({
        preset: 'clippy-astra', custom_name: '', custom_identity: '', custom_voice: '',
        presets: { default: { name: 'Odin', identity: 'i', voice: 'v' }, 'clippy-astra': { name: 'Clippy', identity: 'c', voice: 'c' } },
        builtin_presets: ['default'], user_presets: ['clippy-astra']
      })),
      personalityPresetsDelete: vi.fn(async () => ok({ deleted: 'clippy-astra' }))
    })
    mounted = mount((await import('../../src/renderer/src/views/settings/Personality.vue')).default)
    await flush()
    const input = mounted.root.findAll((node) => node.tag === 'input' && node.props.type === 'file')[0]!
    input.fire('change', { target: { files: [new Blob(['photo'], { type: 'image/png' })], value: 'x' } })
    await flush()
    mounted.root.named('Delete preset clippy-astra…').fire('click')
    await flush()
    expect(odin.removeDisplayPicture).toHaveBeenCalledExactlyOnceWith({ target: 'personality', key: 'clippy-astra' })
    release()
    await flush()
    expect(odin.setDisplayPicture).not.toHaveBeenCalled()
  })

  it('the picker shows its fallback for a picture that fails to decode, and still offers Remove', async () => {
    const AvatarPicker = (await import('../../src/renderer/src/components/AvatarPicker.vue')).default
    mounted = mount(AvatarPicker, { target: { target: 'user' }, picture: MINE, label: 'your picture' })
    await flush()
    const preview = mounted.root.findAll((node) => node.tag === 'img')[0]!
    expect(preview.props.src).toBe(MINE)
    preview.fire('error')
    await flush()
    expect(mounted.root.findAll((node) => node.tag === 'img')).toEqual([])
    expect(mounted.root.named('Remove your picture')).toBeTruthy()
  })

  it('the picker saves a chosen file, reports a refusal and removes the picture', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 10, height: 10, close: vi.fn() })))
    ;(globalThis as unknown as { document: unknown }).document = {
      activeElement: null,
      createElement: () => ({ getContext: () => ({ drawImage: vi.fn() }), toBlob: (done: (b: Blob) => void) => done(new Blob(['p'])) })
    }
    const AvatarPicker = (await import('../../src/renderer/src/components/AvatarPicker.vue')).default
    mounted = mount(AvatarPicker, { target: { target: 'user' }, picture: MINE, label: 'your picture' })
    await flush()
    const input = mounted.root.findAll((node) => node.tag === 'input')[0]!
    const file = new Blob(['photo'], { type: 'image/png' })
    input.fire('change', { target: { files: [file], value: 'C:/fakepath/photo.png' } })
    await flush()
    expect(odin.setDisplayPicture).toHaveBeenCalledExactlyOnceWith({ target: 'user' }, btoa('p'))
    expect(mounted.root.textContent()).toContain('Saved.')
    odin.setDisplayPicture!.mockResolvedValueOnce(refused('That picture could not be used.'))
    input.fire('change', { target: { files: [file], value: 'x' } })
    await flush()
    expect(mounted.root.textContent()).toContain('That picture could not be used.')
    mounted.root.named('Remove your picture').fire('click')
    await flush()
    expect(odin.removeDisplayPicture).toHaveBeenCalledExactlyOnceWith({ target: 'user' })
    expect(mounted.root.textContent()).toContain('Removed.')
  })
})
