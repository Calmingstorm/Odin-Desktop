import { EventEmitter } from 'node:events'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  app: new (class {
    handlers: Record<string, (...args: any[]) => void> = {}
    on(name: string, handler: (...args: any[]) => void) { this.handlers[name] = handler }
  })(),
  protocol: { registerSchemesAsPrivileged: vi.fn(), handle: vi.fn() },
  session: { defaultSession: { setPermissionRequestHandler: vi.fn(), setPermissionCheckHandler: vi.fn() } },
  shell: { openExternal: vi.fn() },
  invoke: vi.fn(), on: vi.fn(), removeListener: vi.fn(), send: vi.fn(), expose: vi.fn(),
  filePath: vi.fn(), exec: vi.fn(), menus: vi.fn(), image: vi.fn(), trays: [] as any[]
}))
vi.mock('electron', () => ({
  app: mocks.app, protocol: mocks.protocol, session: mocks.session, shell: mocks.shell,
  contextBridge: { exposeInMainWorld: mocks.expose },
  ipcRenderer: { invoke: mocks.invoke, on: mocks.on, removeListener: mocks.removeListener, send: mocks.send },
  webUtils: { getPathForFile: mocks.filePath },
  Menu: { buildFromTemplate: mocks.menus }, nativeImage: { createFromPath: mocks.image },
  Tray: class {
    setToolTip = vi.fn(); on = vi.fn(); setContextMenu = vi.fn(); destroy = vi.fn()
    constructor() { mocks.trays.push(this) }
  }
}))
vi.mock('node:child_process', () => ({ execFile: mocks.exec }))

beforeEach(() => { vi.resetModules(); vi.clearAllMocks(); mocks.trays.length = 0 })

describe('Electron policy wiring without a desktop', () => {
  it('serves only app paths with CSP and denies native permissions/navigation', async () => {
    const security = await import('../src/main/security')
    const dir = await mkdtemp(join(tmpdir(), 'odin-policy-'))
    try {
      await writeFile(join(dir, 'index.html'), '<p>fixture</p>')
      security.registerAppScheme()
      security.serveAppScheme(dir)
      const handler = mocks.protocol.handle.mock.calls[0]![1]
      const response = await handler({ url: 'app://odin/index.html' })
      expect(response.status).toBe(200)
      expect(await response.text()).toContain('fixture')
      expect(response.headers.get('Content-Security-Policy')).toContain("default-src 'none'")
      expect((await handler({ url: 'https://invalid.test/' })).status).toBe(404)
      expect((await handler({ url: 'app://odin/missing' })).status).toBe(404)
      expect(security.hardenedWebPreferences('preload')).toMatchObject({ sandbox: true, nodeIntegration: false })
      security.installGuards()
      const callback = vi.fn()
      mocks.session.defaultSession.setPermissionRequestHandler.mock.calls[0]![0](null, 'camera', callback)
      expect(callback).toHaveBeenCalledWith(false)
      expect(mocks.session.defaultSession.setPermissionCheckHandler.mock.calls[0]![0]()).toBe(false)
      const contents = new EventEmitter() as EventEmitter & { setWindowOpenHandler: ReturnType<typeof vi.fn> }
      contents.setWindowOpenHandler = vi.fn()
      mocks.app.handlers['web-contents-created']!(null, contents)
      const event = { preventDefault: vi.fn() }
      contents.emit('will-navigate', event, 'app://odin/index.html')
      expect(event.preventDefault).not.toHaveBeenCalled()
      contents.emit('will-navigate', event, 'https://invalid.test')
      contents.emit('will-redirect', event, 'https://invalid.test')
      contents.emit('will-attach-webview', event)
      expect(event.preventDefault).toHaveBeenCalledTimes(3)
      const popup = contents.setWindowOpenHandler.mock.calls[0]![0]
      expect(popup({ url: 'https://example.test' })).toEqual({ action: 'deny' })
      popup({ url: 'file:///etc/passwd' })
      expect(mocks.shell.openExternal).toHaveBeenCalledTimes(1)
    } finally { await rm(dir, { recursive: true, force: true }) }
  })

  it('detects session tray support and routes menu actions', async () => {
    const { detectTray, OdinTray } = await import('../src/main/tray')
    mocks.exec.mockImplementation((_bin, _args, _opts, callback) => callback(null, '(true,)'))
    expect(await detectTray({})).toBe(true)
    mocks.exec.mockImplementation((_bin, _args, _opts, callback) => callback(new Error('absent'), ''))
    expect(await detectTray({ XDG_SESSION_TYPE: 'x11', XDG_CURRENT_DESKTOP: 'Cinnamon' })).toBe(true)
    expect(await detectTray({ XDG_SESSION_TYPE: 'wayland', XDG_CURRENT_DESKTOP: 'GNOME' })).toBe(false)
    const onOpen = vi.fn(), onExit = vi.fn()
    const tray = new OdinTray('icon', { onOpen, onExit })
    tray.setStatus('Ready'); tray.setTooltip('Unread')
    const template = mocks.menus.mock.calls.at(-1)![0]
    template[0].click(); template[3].click()
    mocks.trays[0].on.mock.calls[0][1]()
    expect(onOpen).toHaveBeenCalledTimes(2)
    expect(onExit).toHaveBeenCalledOnce()
    expect(template[1].label).toBe('Ready')
    tray.destroy()
    expect(mocks.trays[0].destroy).toHaveBeenCalledOnce()
  })

  it('exposes every bridge route without exposing native APIs and unsubscribes listeners', async () => {
    await import('../src/preload/index')
    const api = mocks.expose.mock.calls[0]![1]
    const { IPC, MANAGEMENT, SETTINGS_SHAPED } = await import('../src/shared/api')
    expect(mocks.expose.mock.calls[0]![0]).toBe('odin')
    expect(api.ipcRenderer).toBeUndefined()
    const exclude = new Set(['attachFiles', ...Object.keys(api).filter(key => key.startsWith('on'))])
    mocks.invoke.mockResolvedValue({ ok: true, result: {} })
    for (const [name, method] of Object.entries(api)) {
      if (exclude.has(name)) continue
      await (method as Function)({ fixture: name }, 'text')
    }
    for (const value of Object.values(MANAGEMENT)) expect(mocks.invoke).toHaveBeenCalledWith(value.channel, expect.anything())
    for (const value of Object.values(SETTINGS_SHAPED)) expect(mocks.invoke).toHaveBeenCalledWith(value.channel, expect.anything())
    for (const name of ['onEvent', 'onAppState', 'onReceipt', 'onReset', 'onOpenConversation', 'onAttachmentProgress']) {
      const listener = vi.fn()
      const cancel = api[name](listener)
      const [channel, handler] = mocks.on.mock.calls.at(-1)!
      handler({}, { payload: name })
      expect(listener).toHaveBeenCalledWith({ payload: name })
      cancel()
      expect(mocks.removeListener).toHaveBeenCalledWith(channel, handler)
    }
    expect(mocks.send).toHaveBeenCalledWith(IPC.notificationRouteReady)
    mocks.filePath.mockReturnValue('')
    expect(await api.attachFiles([{ name: 'virtual' }])).toMatchObject({ ok: true, result: { staged: [] } })
    mocks.filePath.mockImplementation(file => file.name === 'real' ? '/fixture/real' : '')
    mocks.invoke.mockResolvedValue({ ok: true, result: { staged: [{ id: 's1' }], errors: ['native error'] } })
    expect(await api.attachFiles([{ name: 'real' }, { name: '' }])).toMatchObject({
      result: { staged: [{ id: 's1' }], errors: ["That item isn't a file on disk.", 'native error'] }
    })
    mocks.invoke.mockResolvedValue({ ok: false, error: { code: 'offline' } })
    expect(await api.attachFiles([{ name: 'real' }])).toMatchObject({ ok: false })
    await api.workList(); await api.codexLoginBegin()
  })
})
