// Main-process orchestration under inert boundaries. No Electron process, core,
// native session, profile directory, notification or logout hook is created.
import { EventEmitter } from 'node:events'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { IPC } from '../src/shared/api'

const m = vi.hoisted(() => ({
  app: null as any, windows: [] as any[], brokers: [] as any[], supervisors: [] as any[], trays: [] as any[],
  journal: null as any, deps: null as any, ready: Promise.resolve() as Promise<void>,
  packaged: false, lock: true, trayAvailable: true, trayDetection: null as Promise<boolean> | null,
  initialLink: 'ready', read: vi.fn(), write: vi.fn(),
  coreCommand: vi.fn(), guardian: null as any, acquire: vi.fn(), admit: vi.fn(), inspect: vi.fn(),
  security: { registerAppScheme: vi.fn(), installGuards: vi.fn(), serveAppScheme: vi.fn(), hardenedWebPreferences: vi.fn(() => ({ sandbox: true })) },
  native: vi.fn(), onboarding: vi.fn(), realSmoke: vi.fn(), register: vi.fn(),
  theme: null as any, power: null as any, ipc: null as any, screen: null as any,
  menu: vi.fn(), menuSet: vi.fn(), clipboard: vi.fn(), open: vi.fn(), openPath: vi.fn(), reveal: vi.fn(),
  errorBox: vi.fn(), pick: vi.fn(), save: vi.fn(), autostart: vi.fn(), enabled: vi.fn(),
  monitorClose: vi.fn(), hookRemove: vi.fn(), sessionEnd: null as any
}))
vi.mock('electron', () => ({
  get app() { return m.app },
  BrowserWindow: class extends EventEmitter {
    id = 7; visible = false; minimized = false; destroyed = false; options: any;
    webContents = Object.assign(new EventEmitter(), {
      id: 8, mainFrame: { url: 'app://odin/index.html', processId: 2, routingId: 3 },
      crashed: false, isCrashed() { return this.crashed }, send: vi.fn(),
      capturePage: vi.fn(async () => ({ toPNG: () => Buffer.from('mock PNG') })),
      executeJavaScript: vi.fn(async (script: string) => {
        if (script.includes('conv-title')) return 'Fixture';
        if (script.includes('Math.round(s.scrollHeight')) return 200;
        if (script.includes('id?.slice')) return 'message1';
        if (script.includes('JSON.stringify({ top:')) return JSON.stringify({ top: 0, view: 800, height: 900, highlighted: true });
        if (script.includes('reopened in')) return '5001 blocks; reopened in 20/21/20 ms; relayout 1 ms; 2 code copy buttons';
        return true;
      }), forcefullyCrashRenderer: vi.fn(), getOSProcessId: vi.fn(() => 100)
    });
    constructor(options: any) { super(); this.options = options; m.windows.push(this) }
    show = vi.fn(() => { this.visible = true; this.emit('show') });
    hide = vi.fn(() => { this.visible = false }); focus = vi.fn();
    restore = vi.fn(() => { this.minimized = false });
    close = vi.fn(() => this.emit('close', { preventDefault: vi.fn() }));
    loadURL = vi.fn(async () => undefined); setBackgroundColor = vi.fn();
    isVisible() { return this.visible } isFocused() { return false }
    isMinimized() { return this.minimized } isDestroyed() { return this.destroyed }
    isMaximized() { return false } isFullScreen() { return false }
    getNormalBounds() { return { x: this.options.x ?? 0, y: this.options.y ?? 0, width: this.options.width, height: this.options.height } }
    getBounds() { return this.getNormalBounds() }
    setBounds = vi.fn((bounds: any) => { Object.assign(this.options, bounds); this.emit('resize') });
    setMinimumSize = vi.fn(); maximize = vi.fn(); unmaximize = vi.fn(); minimize = vi.fn(); setFullScreen = vi.fn();
  },
  get nativeTheme() { return m.theme }, get powerMonitor() { return m.power }, get ipcMain() { return m.ipc },
  get screen() { return m.screen },
  Menu: { buildFromTemplate: m.menu, setApplicationMenu: m.menuSet },
  clipboard: { writeText: m.clipboard },
  shell: { openExternal: m.open, openPath: m.openPath, showItemInFolder: m.reveal },
  dialog: { showErrorBox: m.errorBox, showOpenDialog: m.pick, showSaveDialog: m.save }, Notification: class {}
}))
vi.mock('node:fs', () => ({ readFileSync: m.read, writeFileSync: m.write, mkdirSync: vi.fn(), readlinkSync: () => 'isolated-pid-ns' }))
vi.mock('../src/main/security', () => m.security)
vi.mock('../src/main/core-command', () => ({ coreCommand: m.coreCommand }))
vi.mock('../src/main/paths', () => ({
  profilePaths: () => ({ profileId: 'fixture', configDir: '/mock/config', dataDir: '/mock/data',
    cacheDir: '/mock/cache', logDir: '/mock/log', appStatePath: '/mock/app.json', socketPath: '/mock/socket', tokenPath: '/mock/token' }),
  ensureProfileDirs: vi.fn(), ensureToken: vi.fn()
}))
vi.mock('../src/main/package-ownership', () => ({ acquirePackagedApp: m.acquire, admitPackagedApp: m.admit }))
vi.mock('../src/main/package-state', () => ({ inspectPackagedState: m.inspect }))
vi.mock('../src/main/broker', () => ({ Broker: class extends EventEmitter {
  linkState = m.initialLink; coreInstanceId: string | null = 'core1'; unreceiptedCount = 0; cursor = 2;
  request = vi.fn(async (method: string, _params?: any, _id?: string): Promise<any> => {
    if (method === 'conversations.list') return { ok: true, result: { items: [{ id: 'c1', title: 'Fixture', unread: 2 }], watermark: '2' } };
    return { ok: true, result: {} };
  });
  connect = vi.fn(); startEvents = vi.fn(); close = vi.fn(); quiesce = vi.fn();
  waitForShutdownReady = vi.fn(async () => true);
  originalRequest = this.request;
  constructor(public options: any) { super(); m.brokers.push(this) }
} }))
vi.mock('../src/main/core-supervisor', () => ({ CoreSupervisor: class extends EventEmitter {
  pid = 101; current = 'running'; start = vi.fn(); stop = vi.fn(async () => 'exited');
  constructor(public options: any) { super(); m.supervisors.push(this) }
} }))
vi.mock('../src/main/drafts', () => ({ DraftStore: class { flush = vi.fn(); get = vi.fn(); set = vi.fn() } }))
vi.mock('../src/main/attachments', () => ({ AttachmentManager: class extends EventEmitter {
  constructor(public broker: any, public limits: any) { super() }
} }))
vi.mock('../src/main/artifacts', () => ({ safeFileName: (name: string) => name.replaceAll('/', '_'), ArtifactStore: class {
  forget = vi.fn(); constructor(public broker: any, public path: any, public chunk: any, public native: any) {}
} }))
vi.mock('../src/main/device-login', () => ({ DeviceLoginBoundary: class { receipt = vi.fn((value: any) => ({ ...value, projected: true })) } }))
vi.mock('../src/main/ipc', () => ({ registerIpc: (deps: any) => { m.deps = deps; m.register(deps) } }))
vi.mock('../src/main/release-notice', () => ({ ReleaseNoticeService: class { constructor(public version: any, public open: any) {} } }))
vi.mock('../src/main/autostart', () => ({ setAutostart: m.autostart, isAutostartEnabled: m.enabled }))
vi.mock('../src/main/native-notifications', () => ({ showNativeNotification: m.native }))
vi.mock('../src/main/tray', () => ({ detectTray: async () => m.trayDetection ?? m.trayAvailable, OdinTray: class {
  setStatus = vi.fn(); setTooltip = vi.fn(); destroy = vi.fn();
  constructor(public path: string, public actions: any) { m.trays.push(this) }
} }))
vi.mock('../src/main/session-logout', () => ({
  startSessionMonitor: (_launch: any, end: any) => { m.sessionEnd = end; return { close: m.monitorClose } },
  installKdeLogoutHook: () => ({ remove: m.hookRemove })
}))
vi.mock('../src/main/onboarding-smoke', () => ({ onboardingSmoke: m.onboarding }))
vi.mock('../src/main/real-core-smoke', () => ({ realCoreSmoke: m.realSmoke }))
vi.mock('../src/main/shutdown', async (original) => {
  const real = await original<any>();
  return { ...real, CleanupJournal: class {
    notice: any = null; warning: any = null; begin = vi.fn(); finish = vi.fn();
    markUnknown = vi.fn((reason: string, source?: string) => { this.notice = { id: 'notice1', reason, source }; this.warning = this.notice });
    acknowledge = vi.fn((id: string) => { if (id !== this.notice?.id) return false; this.notice = null; return true });
    constructor(public path: string) { m.journal = this }
  } }
})

beforeEach(() => {
  vi.resetModules(); vi.clearAllMocks(); vi.useFakeTimers();
  m.windows.length = 0; m.brokers.length = 0; m.supervisors.length = 0; m.trays.length = 0;
  m.packaged = false; m.lock = true; m.trayAvailable = true; m.trayDetection = null;
  m.initialLink = 'ready'; m.ready = Promise.resolve(); m.deps = null;
  m.app = Object.assign(new EventEmitter(), {
    isPackaged: false, requestSingleInstanceLock: vi.fn(() => m.lock), quit: vi.fn(), exit: vi.fn(),
    whenReady: vi.fn(() => m.ready), getAppPath: () => '/mock/app', getVersion: () => '0.1.0', getPath: () => '/mock/downloads',
    setName: vi.fn(), setPath: vi.fn(), commandLine: { getSwitchValue: vi.fn(() => 'x11') }
  });
  m.theme = Object.assign(new EventEmitter(), { themeSource: 'system', shouldUseDarkColors: true });
  m.power = new EventEmitter(); m.ipc = new EventEmitter();
  const display = { id: 1, workArea: { x: 0, y: 0, width: 1280, height: 800 } };
  m.screen = Object.assign(new EventEmitter(), { getAllDisplays: () => [display], getPrimaryDisplay: () => display });
  m.read.mockImplementation((path: string) => path.includes('token') ? ' token\n' : '{}');
  m.write.mockImplementation(() => undefined);
  m.coreCommand.mockReturnValue({ command: '/mock/python', args: ['-m', 'src'], env: {} });
  m.guardian = Object.assign(new EventEmitter(), { stdin: { end: vi.fn() } });
  m.acquire.mockResolvedValue(m.guardian); m.admit.mockResolvedValue(undefined); m.inspect.mockReturnValue(undefined);
  m.native.mockResolvedValue('shown'); m.onboarding.mockResolvedValue(undefined); m.realSmoke.mockResolvedValue(undefined);
  m.pick.mockResolvedValue({ canceled: false, filePaths: ['/mock/a'] });
  m.save.mockResolvedValue({ canceled: false, filePath: '/mock/saved' });
  m.menu.mockImplementation(template => template); m.enabled.mockReturnValue(false);
  vi.stubGlobal('__dirname', '/mock/main');
  Object.defineProperty(process, 'resourcesPath', { configurable: true, get: () => '/mock/resources' });
  vi.spyOn(process, 'argv', 'get').mockReturnValue(['node', 'fixture']);
  for (const key of ['ODIN_APP_E2E', 'ODIN_SMOKE_ONBOARDING', 'ODIN_SMOKE_REAL_CORE', 'ODIN_SMOKE_OUT', 'ODIN_SMOKE_SHOTS', 'ODIN_SMOKE_MESSAGE', 'APPIMAGE']) vi.stubEnv(key, '');
  vi.spyOn(process.stdout, 'write').mockReturnValue(true); vi.spyOn(process.stderr, 'write').mockReturnValue(true);
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.restoreAllMocks(); delete (globalThis as any).__odinE2E; delete (process as any).resourcesPath })
async function boot(argv: string[] = []) {
  vi.spyOn(process, 'argv', 'get').mockReturnValue(['node', 'fixture', ...argv]);
  await import('../src/main/index'); await flush();
  return { win: m.windows[0], broker: m.brokers[0], supervisor: m.supervisors[0], tray: m.trays[0], deps: m.deps }
}
async function flush() { for (let i = 0; i < 15; i++) await Promise.resolve() }
const prevent = () => ({ preventDefault: vi.fn() })

describe('inert main-process lifecycle wiring', () => {
  it('rejects false persistence receipts without adopting notification or native theme changes', async () => {
    const { deps, win } = await boot()
    const previous = structuredClone(deps.getSettings())
    m.write.mockImplementation(() => { throw new Error('mock durable write failed') })
    expect(() => deps.setNotifications({ previews: !previous.notifications.previews })).toThrow('could not be persisted')
    expect(deps.getSettings().notifications).toEqual(previous.notifications)
    expect(() => deps.setAppearance('light')).toThrow('could not be persisted')
    expect(deps.getSettings().appearance).toBe(previous.appearance)
    expect(m.theme.themeSource).toBe(previous.appearance)
    expect(win.setBackgroundColor).toHaveBeenCalledWith('#0E1115')
    m.write.mockImplementation(() => undefined)
    expect(deps.setAppearance('light').appearance).toBe('light')
    expect(deps.setNotifications({ previews: false }).notifications.previews).toBe(false)
    expect(JSON.parse(m.write.mock.calls.at(-1)![1])).toMatchObject({ appearance: 'light', notifications: { previews: false } })
  })
  it('rolls back explicit mute and unmute when the shared preference writer fails', async () => {
    const { deps } = await boot()
    const before = structuredClone(deps.getSettings().notifications)
    m.write.mockImplementation(() => { throw new Error('mock durable write failed') })
    expect(() => deps.setConversationMuted('private-chat', true)).toThrow('could not be persisted')
    expect(deps.getSettings().notifications).toEqual(before)
    m.write.mockImplementation(() => undefined)
    expect(deps.setConversationMuted('private-chat', true).notifications.muted).toContain('private-chat')
    const muted = structuredClone(deps.getSettings().notifications)
    m.write.mockImplementation(() => { throw new Error('mock durable write failed') })
    expect(() => deps.setConversationMuted('private-chat', false)).toThrow('could not be persisted')
    expect(deps.getSettings().notifications).toEqual(muted)
    m.write.mockImplementation(() => undefined)
    expect(deps.setConversationMuted('private-chat', false).notifications.muted).not.toContain('private-chat')
  })
  it('supplies whitelisted app metadata and opens only the active profile configDir', async () => {
    const { deps } = await boot()
    const info = deps.getDesktopInfo()
    expect(info).toEqual({ appVersion: '0.1.0', electronVersion: process.versions.electron,
      chromiumVersion: process.versions.chrome, nodeVersion: process.versions.node,
      platform: process.platform, architecture: process.arch, license: 'MIT', packaged: false })
    m.app.isPackaged = true
    expect(deps.getDesktopInfo().packaged).toBe(true)
    m.openPath.mockResolvedValueOnce('OS rejected /mock/config')
    expect(await deps.openSettingsFolder('/untrusted/path')).toBe('OS rejected /mock/config')
    expect(m.openPath).toHaveBeenCalledExactlyOnceWith('/mock/config')
    expect(m.open).not.toHaveBeenCalled()
  })
  it('schedules the existing bounded shutdown only after the exit callback returns', async () => {
    const { deps, broker, supervisor } = await boot()
    expect(deps.exitOdin()).toBeUndefined()
    // Multiple accepted clicks still reach the existing idempotent shutdown once.
    expect(deps.exitOdin()).toBeUndefined()
    expect(deps.admitting()).toBe(true)
    expect(broker.quiesce).not.toHaveBeenCalled()
    expect(m.app.exit).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(0)
    await flush()
    expect(deps.admitting()).toBe(false)
    expect(broker.quiesce).toHaveBeenCalledOnce()
    expect(broker.originalRequest).toHaveBeenCalledWith('runtime.shutdown', { reason: 'exit' })
    expect(supervisor.stop).toHaveBeenCalledOnce()
    expect(m.app.exit).toHaveBeenCalledExactlyOnceWith(0)
    expect(m.journal.finish).toHaveBeenCalledWith(expect.objectContaining({ shutdownAccepted: true, processOutcome: 'exited' }))
  })
  it('pins Chromium storage and the visible name before instance admission or readiness', async () => {
    await boot();
    expect(m.app.setName).toHaveBeenCalledExactlyOnceWith('Odin');
    expect(m.app.setPath).toHaveBeenCalledExactlyOnceWith('userData', '/mock/downloads/odin-desktop/electron');
    expect(m.app.setPath.mock.invocationCallOrder[0]).toBeLessThan(m.app.requestSingleInstanceLock.mock.invocationCallOrder[0]);
    expect(m.app.setPath.mock.invocationCallOrder[0]).toBeLessThan(m.app.whenReady.mock.invocationCallOrder[0]);
  })
  it('quits duplicate/exit-only launches before constructing the profile or core', async () => {
    m.lock = false; await boot(); expect(m.app.quit).toHaveBeenCalledOnce(); expect(m.brokers).toHaveLength(0);
    vi.resetModules(); m.lock = true; await boot(['--exit']); expect(m.app.quit).toHaveBeenCalledTimes(2); expect(m.supervisors).toHaveLength(0);
  })
  it('reports core-command failure without starting or creating a window', async () => {
    m.coreCommand.mockImplementation(() => { throw new Error('runtime absent') });
    await boot(); expect(m.errorBox).toHaveBeenCalledWith('Odin core unavailable', 'runtime absent');
    expect(m.app.exit).toHaveBeenCalledWith(1); expect(m.windows).toHaveLength(0);
  })
  it('admits packaged ownership before startup and fails closed on admission errors', async () => {
    m.app.isPackaged = true; const { supervisor } = await boot();
    expect(m.admit).toHaveBeenCalledWith(m.guardian); expect(supervisor.start).toHaveBeenCalledOnce();
    m.guardian.emit('exit'); expect(m.app.exit).toHaveBeenCalledWith(1);
    vi.resetModules(); m.admit.mockRejectedValueOnce(new Error('lease denied')); await boot();
    expect(m.guardian.stdin.end).toHaveBeenCalledOnce(); expect(m.errorBox).toHaveBeenCalledWith('Odin ownership unavailable', 'lease denied');
  })
  it('boots hardened hidden window and maps core events, settings and native adapters correctly', async () => {
    const { win, broker, supervisor, tray, deps } = await boot(['--hidden']);
    expect(win.options).toMatchObject({ show: false, webPreferences: { sandbox: true }, backgroundColor: '#0E1115' });
    expect(win.loadURL).toHaveBeenCalledWith('app://odin/index.html');
    expect(supervisor.start).toHaveBeenCalledOnce(); expect(broker.connect).toHaveBeenCalledOnce(); expect(broker.startEvents).toHaveBeenCalledOnce();
    expect(broker.options.readToken()).toBe('token'); expect(supervisor.options.restartAllowed()).toBe(false);
    broker.coreInstanceId = null; expect(supervisor.options.restartAllowed()).toBe(true); broker.coreInstanceId = 'core1';
    expect(deps.windowId()).toBe(8); expect(deps.mainFrame()).toBe(win.webContents.mainFrame); expect(deps.admitting()).toBe(true);
    expect(await deps.pickFiles()).toEqual(['/mock/a']); expect(await deps.chooseSavePath('a/b')).toBe('/mock/saved');
    expect(m.save).toHaveBeenCalledWith(win, expect.objectContaining({ defaultPath: '/mock/downloads/a_b' }));
    m.pick.mockResolvedValueOnce({ canceled: true, filePaths: ['/ignored'] }); m.save.mockResolvedValueOnce({ canceled: true });
    expect(await deps.pickFiles()).toEqual([]); expect(await deps.chooseSavePath('a')).toBeNull();
    deps.copyText('text'); await deps.openVerification('https://example.test'); await deps.releases.open('https://release.test');
    expect(m.clipboard).toHaveBeenCalledWith('text'); expect(m.open).toHaveBeenCalledWith('https://example.test');
    await deps.artifacts.native.openPath('/mock/a'); deps.artifacts.native.showItemInFolder('/mock/a');
    expect(m.openPath).toHaveBeenCalledWith('/mock/a'); expect(m.reveal).toHaveBeenCalledWith('/mock/a');
    deps.setAutostart(true); expect(m.autostart).toHaveBeenCalledWith(true, [process.execPath, '/mock/app']);
    deps.setNotifications({ previews: false }); deps.setConversationMuted('c1', true); deps.setAppearance('light');
    expect(deps.getSettings()).toMatchObject({ appearance: 'light', notifications: { previews: false, muted: ['c1'] } });
    m.theme.emit('updated'); expect(win.setBackgroundColor).toHaveBeenCalledWith('#0E1115');
    broker.originalRequest.mockImplementation(async (method: string) => method === 'status.get'
      ? { ok: true, result: { limits: { attachment_bytes: 123, chunk_bytes: 9e6 }, resource_cleanup: { reconciliation_required: true, state: 'unknown', resources: ['resource'] } } }
      : { ok: true, result: { items: [{ id: 'c1', title: 'Fixture', unread: 2 }], watermark: '2' } });
    broker.emit('welcome'); await flush();
    expect(deps.attachments.limits()).toEqual({ attachment_bytes: 123, chunk_bytes: 2 * 1024 * 1024 });
    expect(deps.artifacts.chunk()).toBe(2 * 1024 * 1024); expect(m.journal.markUnknown).toHaveBeenCalledWith(expect.stringContaining('unresolved'), expect.stringContaining('core-resource:'));
    expect(() => deps.acknowledgeCleanup('stale')).toThrow('Cleanup notice changed');
    expect(deps.acknowledgeCleanup('notice1').cleanupWarning).toBeNull();
    for (const [type, payload] of [
      ['conversation.created', { conversation: { id: 'c2', title: 'Second', unread: 1 } }],
      ['conversation.updated', { conversation: { id: 'c2', title: 'Changed', unread: 3 } }],
      ['artifact.unavailable', { ref: 'gone' }], ['conversation.deleted', { conversation_id: 'c1' }]
    ] as const) broker.emit('event', { type, payload, seq: 3, at: new Date().toISOString() });
    expect(deps.artifacts.forget).toHaveBeenCalledWith('gone'); expect(deps.getSettings().notifications.muted).toEqual([]);
    expect(tray.setTooltip).toHaveBeenLastCalledWith('Odin: 3 unread messages');
    broker.emit('receipt', { id: 'receipt' }); expect(win.webContents.send).toHaveBeenCalledWith(IPC.receipt, { id: 'receipt', projected: true });
    broker.emit('reset', { reason: 'gap' }); broker.emit('core-changed'); broker.emit('state');
    for (const [event, label] of [['restarting', 'Odin is restarting…'], ['failed', 'Odin stopped unexpectedly'], ['started', 'Odin is running']]) {
      supervisor.emit(event); expect(tray.setStatus).toHaveBeenLastCalledWith(label);
    }
    broker.linkState = 'reconnecting'; broker.emit('state'); expect(tray.setStatus).toHaveBeenLastCalledWith('Reconnecting…');
    broker.linkState = 'connecting'; broker.emit('state'); expect(tray.setStatus).toHaveBeenLastCalledWith('Starting…');
    deps.attachments.emit('progress', { id: 'upload' }); expect(win.webContents.send).toHaveBeenCalledWith(IPC.attachmentProgress, { id: 'upload' });
    win.emit('ready-to-show'); expect(win.show).not.toHaveBeenCalled();
    win.minimized = true; win.webContents.crashed = true; m.app.emit('second-instance', {}, []);
    expect(win.restore).toHaveBeenCalledOnce(); expect(win.focus).toHaveBeenCalledOnce(); expect(win.loadURL).toHaveBeenCalledTimes(2);
    tray.actions.onOpen(); expect(win.focus).toHaveBeenCalledTimes(2);
    win.webContents.emit('did-finish-load'); m.app.emit('window-all-closed'); expect(m.app.exit).not.toHaveBeenCalled();
    const menu = m.menu.mock.calls[0]![0]; menu[0].submenu[0].click(); expect(win.hide).toHaveBeenCalledOnce();
  })
  it('routes notification clicks only after the exact window frame declares readiness, and acknowledges outcome', async () => {
    const { win, broker } = await boot();
    const event = { type: 'notification.intent', seq: 1, at: new Date().toISOString(), payload: { conversation_id: 'c1', message_id: 'm1', category: 'reply', preview: 'hello', dedupe_key: 'key' } };
    broker.emit('event', event); await flush();
    expect(m.native).toHaveBeenCalledWith(expect.objectContaining({ body: 'hello' }), expect.any(Set), '/mock/app/resources/icon.png');
    m.native.mock.calls[0]![0].onClick(); expect(win.focus).toHaveBeenCalledOnce();
    expect(win.webContents.send).not.toHaveBeenCalledWith(IPC.openConversation, expect.anything());
    m.ipc.emit(IPC.notificationRouteReady, { sender: {}, senderFrame: win.webContents.mainFrame });
    m.ipc.emit(IPC.notificationRouteReady, { sender: win.webContents, senderFrame: { url: 'app://odin/index.html' } });
    win.webContents.mainFrame.url = 'https://invalid.test';
    m.ipc.emit(IPC.notificationRouteReady, { sender: win.webContents, senderFrame: win.webContents.mainFrame });
    expect(win.webContents.send).not.toHaveBeenCalledWith(IPC.openConversation, expect.anything());
    win.webContents.mainFrame.url = 'app://odin/index.html';
    m.ipc.emit(IPC.notificationRouteReady, { sender: win.webContents, senderFrame: win.webContents.mainFrame });
    expect(win.webContents.send).toHaveBeenCalledWith(IPC.openConversation, { conversationId: 'c1', messageId: 'm1' });
    expect(broker.originalRequest).toHaveBeenCalledWith('notifications.ack', { dedupe_key: 'key', outcome: 'shown' }, expect.stringMatching(/^[0-9a-f-]{36}$/));
    win.webContents.emit('did-start-navigation', {}, '', false, true);
    win.webContents.emit('render-process-gone', {}, { reason: 'crashed' });
    expect(supervised()).toBe(true);
    function supervised() { return m.supervisors[0].stop.mock.calls.length === 0 }
  })
  it('hides on close, persists the no-tray notice once, then shutdown quiesces, persists, releases and exits', async () => {
    m.trayAvailable = false; const { win, broker, supervisor, deps } = await boot();
    const close = prevent(); win.emit('close', close); win.emit('close', prevent());
    expect(close.preventDefault).toHaveBeenCalledOnce(); expect(win.hide).toHaveBeenCalledTimes(2); expect(m.native).toHaveBeenCalledOnce();
    m.native.mock.calls[0]![0].onClick(); expect(win.focus).toHaveBeenCalledOnce();
    const os = { close: vi.fn() }; m.native.mock.calls[0]![1].add(os);
    const quit = prevent(); m.app.emit('before-quit', quit); await flush();
    expect(quit.preventDefault).toHaveBeenCalledOnce(); expect(deps.admitting()).toBe(false);
    expect(deps.drafts.flush).toHaveBeenCalledOnce(); expect(broker.quiesce).toHaveBeenCalledOnce();
    expect(broker.originalRequest).toHaveBeenCalledWith('runtime.shutdown', { reason: 'exit' });
    expect(supervisor.stop).toHaveBeenCalledOnce(); expect(m.monitorClose).toHaveBeenCalledOnce(); expect(m.hookRemove).toHaveBeenCalledOnce(); expect(os.close).toHaveBeenCalledOnce();
    expect(m.journal.finish).toHaveBeenCalledWith(expect.objectContaining({ state: 'process-exited', shutdownAccepted: true })); expect(m.app.exit).toHaveBeenCalledWith(0);
    expect(await broker.request('conversations.list')).toMatchObject({ ok: false, error: { code: 'busy' } });
    broker.linkState = 'reconnecting'; broker.emit('state'); expect(broker.close).toHaveBeenCalledTimes(2);
    const closing = prevent(); win.emit('close', closing); expect(closing.preventDefault).not.toHaveBeenCalled();
    const again = prevent(); m.app.emit('before-quit', again); expect(again.preventDefault).not.toHaveBeenCalled();
    m.app.emit('second-instance', {}, []); expect(win.focus).toHaveBeenCalledOnce();
  })
  it.each(['accelerator', 'power', 'session', 'tray', 'menu', 'second'])('exits through bounded shutdown for %s', async source => {
    const { win, tray, supervisor } = await boot(); const event = prevent();
    if (source === 'accelerator') {
      win.webContents.emit('before-input-event', prevent(), { type: 'keyDown', control: true, alt: true, key: 'q' });
      expect(supervisor.stop).not.toHaveBeenCalled();
      win.webContents.emit('before-input-event', event, { type: 'keyDown', control: true, key: 'Q' });
      expect(event.preventDefault).toHaveBeenCalledOnce();
    } else if (source === 'power') { m.power.emit('suspend'); m.power.emit('shutdown', event); expect(event.preventDefault).toHaveBeenCalledOnce() }
    else if (source === 'session') m.sessionEnd(); else if (source === 'tray') tray.actions.onExit();
    else if (source === 'menu') m.menu.mock.calls[0]![0][0].submenu[2].click(); else m.app.emit('second-instance', {}, ['--exit']);
    await flush(); expect(supervisor.stop).toHaveBeenCalledOnce(); expect(tray.destroy).toHaveBeenCalledOnce(); expect(m.app.exit).toHaveBeenCalledWith(0);
  })
  it('reports explicit preference failure but cosmetic persistence does not make cleanup unknown', async () => {
    const { deps } = await boot(); m.write.mockImplementation(() => { throw new Error('disk full') });
    expect(() => deps.setNotifications({ previews: false })).toThrow('could not be persisted');
    expect(deps.getSettings().notifications.previews).toBe(true);
    expect(() => deps.setAppearance('light')).toThrow('could not be persisted');
    m.sessionEnd(); await flush();
    expect(m.journal.finish).toHaveBeenCalledWith(expect.objectContaining({ state: 'process-exited', unsaved: false }));
  })
  it('still records draft persistence failure as unknown cleanup', async () => {
    const { deps } = await boot(); deps.drafts.flush.mockImplementation(() => { throw new Error('draft disk full') });
    m.sessionEnd(); await flush();
    expect(m.journal.finish).toHaveBeenCalledWith(expect.objectContaining({ state: 'unknown', unsaved: true }));
  })
  it.each(['null', '[]', '{broken'])('damaged top-level app state %s cannot block launch', async content => {
    m.read.mockReturnValue(content); const { win, deps } = await boot();
    expect(win.options.width).toBe(1180); expect(deps.getSetupReminderHidden()).toBe(false);
  })
  it('one latest-state writer preserves dismissal, geometry, preferences and unknown fields', async () => {
    m.read.mockReturnValue(JSON.stringify({ setupReminderHidden: true, appearance: 'dark', extraFutureField: { value: 1 } }));
    const { win, deps } = await boot(); expect(deps.getSetupReminderHidden()).toBe(true);
    win.setBounds({ x: 100, width: 900 }); deps.setNotifications({ previews: false }); deps.setAppearance('light');
    deps.setSetupReminderHidden(false); win.emit('close', prevent());
    const saved = JSON.parse(m.write.mock.calls.filter(([path]) => path === '/mock/app.json').at(-1)![1]);
    expect(saved).toMatchObject({ setupReminderHidden: false, appearance: 'light', notifications: { previews: false },
      extraFutureField: { value: 1 }, windowState: { normalBounds: { x: 100, width: 900 } } });
    m.write.mockImplementation(() => { throw new Error('disk full') });
    expect(() => deps.setSetupReminderHidden(true)).toThrow('could not be persisted'); expect(deps.getSetupReminderHidden()).toBe(false);
  })
  it('does not create a window if exit arrives before app readiness', async () => {
    let resolve!: () => void; m.ready = new Promise<void>(r => { resolve = r });
    await boot(); m.sessionEnd(); resolve(); await flush(); expect(m.windows).toHaveLength(0); expect(m.app.exit).toHaveBeenCalledWith(0);
  })
  it.each(['onboarding', 'real'])('dispatches %s smoke only to its inert runner and exits on success or failure', async mode => {
    vi.stubEnv(mode === 'onboarding' ? 'ODIN_SMOKE_ONBOARDING' : 'ODIN_SMOKE_REAL_CORE', '1');
    const runner = mode === 'onboarding' ? m.onboarding : m.realSmoke;
    const { win, broker } = await boot(['--smoke-test']); expect(runner).toHaveBeenCalledWith(win, broker, ''); expect(m.app.exit).toHaveBeenCalledWith(0);
    vi.resetModules(); runner.mockRejectedValueOnce(new Error('smoke rejected')); await boot(['--smoke-test']);
    expect(m.app.exit).toHaveBeenLastCalledWith(1);
  })
  it('runs screenshot smoke orchestration and records every requested fixture shot without a display', async () => {
    vi.stubEnv('ODIN_SMOKE_OUT', '/mock/smoke.png'); vi.stubEnv('ODIN_SMOKE_SHOTS', 'fixture search');
    const { win, broker } = await boot(['--smoke-test']);
    await vi.runAllTimersAsync(); await flush();
    expect(m.write).toHaveBeenCalledWith('/mock/smoke.png', Buffer.from('mock PNG'));
    for (const name of ['search', 'jump', 'menu', 'dialog', 'palette', 'work', 'tool', 'resume', 'settings', 'settings-models', 'settings-image', 'settings-tools', 'settings-skills', 'settings-mcp', 'settings-hosts', 'settings-work', 'settings-personality', 'settings-state', 'settings-records', 'settings-schedule-form', 'settings-host-wizard', 'long']) {
      expect(m.write).toHaveBeenCalledWith(`/mock/smoke-${name}.png`, Buffer.from('mock PNG'));
    }
    expect(win.webContents.send).toHaveBeenCalledWith(IPC.openConversation, { conversationId: 'c1', messageId: 'message1' });
    expect(broker.originalRequest).toHaveBeenCalledWith('runtime.shutdown', { reason: 'exit' }); expect(m.app.exit).toHaveBeenCalledWith(0);
  })
  it('exports isolated-test hooks only after all isolation predicates and projects their state', async () => {
    vi.stubEnv('ODIN_APP_E2E', '1'); vi.stubEnv('ODIN_REAL_CORE_ROOT', '/mock/home'); vi.stubEnv('HOME', '/mock/home');
    vi.stubEnv('ODIN_REAL_CORE_OUTER_PID_NS', 'outer-ns'); vi.stubEnv('DISPLAY', ':88'); vi.stubEnv('DBUS_SESSION_BUS_ADDRESS', 'mock-bus');
    vi.spyOn(process, 'getuid').mockReturnValue(1001);
    const { win, broker } = await boot(); const hooks = (globalThis as any).__odinE2E;
    expect(hooks.snapshot()).toMatchObject({ corePid: 101, coreState: 'running', visible: false, windowId: 7, rendererPid: 100, cursor: 2 });
    expect(await hooks.request('fixture.read', { value: 1 }, 'fixture-id')).toEqual({ ok: true, result: {} });
    expect(broker.originalRequest).toHaveBeenCalledWith('fixture.read', { value: 1 }, 'fixture-id');
    expect(await hooks.notification({ conversation_id: 'c1', message_id: 'm1', category: 'reply', preview: 'test', dedupe_key: 'e2e' }, new Date().toISOString())).toBe('shown');
    await flush(); expect(hooks.notificationAcks).toEqual([expect.objectContaining({ dedupeKey: 'e2e', outcome: 'shown', settled: { ok: true, result: {} } })]);
    expect(hooks.windowSnapshot()).toMatchObject({ backend: 'x11', resolvedOzonePlatform: 'x11',
      bounds: win.getBounds(), normalBounds: win.getNormalBounds(), maximized: false, minimized: false,
      fullscreen: false, persisted: { version: 1, maximized: false } });
    hooks.windowBounds({ x: 100, y: 40, width: 900, height: 600 });
    expect(win.setBounds).toHaveBeenLastCalledWith({ x: 100, y: 40, width: 900, height: 600 });
    expect(hooks.windowSnapshot().persisted.normalBounds).toEqual({ x: 100, y: 40, width: 900, height: 600 });
    for (const mode of ['maximize', 'unmaximize', 'minimize', 'restore', 'fullscreen', 'normal']) hooks.windowMode(mode);
    expect(win.maximize).toHaveBeenCalledOnce(); expect(win.unmaximize).toHaveBeenCalledOnce();
    expect(win.minimize).toHaveBeenCalledOnce(); expect(win.restore).toHaveBeenCalledOnce();
    expect(win.setFullScreen.mock.calls).toEqual([[true], [false]]);
    hooks.windowMode('unrecognized'); expect(win.setFullScreen).toHaveBeenCalledTimes(2);
    hooks.close(); hooks.show(); hooks.rendererCrash(); expect(win.close).toHaveBeenCalledOnce(); expect(win.focus).toHaveBeenCalledOnce(); expect(win.webContents.forcefullyCrashRenderer).toHaveBeenCalledOnce();
    hooks.exit(); await flush(); expect(m.app.exit).toHaveBeenCalledWith(0);
  })
  it('uses an AppImage autostart command and tolerates absent saved preferences', async () => {
    vi.stubEnv('APPIMAGE', '/mock/Odin.AppImage'); m.read.mockImplementation(() => { throw new Error('missing') });
    const { deps } = await boot(); deps.setAutostart(true);
    expect(m.autostart).toHaveBeenCalledWith(true, ['/mock/Odin.AppImage']); expect(deps.getSettings().appearance).toBe('system');
  })
  it('waits for welcome and the matching committed reply before screenshot smoke exits', async () => {
    m.initialLink = 'reconnecting';
    // Seed the mock before construction without starting a real core.
    m.coreCommand.mockImplementation(() => { vi.stubEnv('ODIN_SMOKE_MESSAGE', 'fixture hello'); return { command: '/mock/python', args: ['-m', 'src'], env: {} } });
    const { win, broker } = await boot(['--smoke-test']);
    await vi.advanceTimersByTimeAsync(1500); expect(broker.originalRequest).not.toHaveBeenCalled();
    broker.linkState = 'ready'; broker.emit('welcome'); await flush();
    await vi.advanceTimersByTimeAsync(1500); expect(broker.originalRequest).toHaveBeenCalledWith('submission.send', expect.objectContaining({ text: 'fixture hello', conversation_id: 'c1' }), expect.any(String));
    expect(win.webContents.capturePage).not.toHaveBeenCalled(); broker.emit('event', { type: 'request.completed', payload: {}, at: new Date().toISOString() });
    await vi.advanceTimersByTimeAsync(1500); await flush(); expect(win.webContents.capturePage).toHaveBeenCalledOnce(); expect(m.app.exit).toHaveBeenCalledWith(0);
  })
  it('fails screenshot orchestration honestly when renderer execution rejects', async () => {
    vi.stubEnv('ODIN_SMOKE_OUT', '/mock/smoke.png'); vi.stubEnv('ODIN_SMOKE_SHOTS', 'fixture');
    const { win } = await boot(['--smoke-test']); win.webContents.executeJavaScript.mockRejectedValueOnce(new Error('renderer unavailable'));
    await vi.advanceTimersByTimeAsync(3000); await flush(); expect(m.app.exit).toHaveBeenCalledWith(1);
    expect(process.stderr.write).toHaveBeenCalledWith(expect.stringContaining('interface shots failed: Error: Error: renderer unavailable (script:'));
  })
  it('fails a stalled smoke exchange at the deadline without claiming a screenshot', async () => {
    vi.stubEnv('ODIN_SMOKE_MESSAGE', 'fixture hello'); const { win } = await boot(['--smoke-test']);
    await vi.advanceTimersByTimeAsync(45000); expect(m.app.exit).toHaveBeenCalledWith(1); expect(win.webContents.capturePage).not.toHaveBeenCalled();
  })
  it('does not stop the core if a no-tray notification fails', async () => {
    m.trayAvailable = false; m.native.mockRejectedValueOnce(new Error('notification unavailable'));
    const { win, supervisor } = await boot(); win.emit('close', prevent()); await flush();
    expect(win.hide).toHaveBeenCalledOnce(); expect(supervisor.stop).not.toHaveBeenCalled(); expect(m.app.exit).not.toHaveBeenCalled();
  })
  it('repairs geometry only for relevant display changes and releases display listeners on Exit', async () => {
    const { win, deps } = await boot();
    const smaller = { id: 2, workArea: { x: 300, y: 200, width: 800, height: 600 } };
    m.screen.getAllDisplays = () => [smaller]; m.screen.getPrimaryDisplay = () => smaller;
    m.screen.emit('display-metrics-changed', {}, smaller, ['rotation', 'colorSpace']);
    expect(win.setBounds).not.toHaveBeenCalled(); expect(win.setMinimumSize).not.toHaveBeenCalled();
    m.screen.emit('display-metrics-changed', {}, smaller, ['workArea']);
    expect(win.setBounds).toHaveBeenLastCalledWith({ x: 300, y: 200, width: 800, height: 600 });
    expect(win.setMinimumSize).toHaveBeenLastCalledWith(720, 480);
    m.screen.emit('display-removed', {}, smaller);
    await vi.advanceTimersByTimeAsync(250);
    expect(JSON.parse(m.write.mock.calls.at(-1)![1]).windowState.normalBounds)
      .toEqual({ x: 300, y: 200, width: 800, height: 600 });
    expect(deps.admitting()).toBe(true);
    m.sessionEnd(); await flush();
    expect(m.screen.listenerCount('display-removed')).toBe(0);
    expect(m.screen.listenerCount('display-metrics-changed')).toBe(0);
    const repairs = win.setBounds.mock.calls.length;
    m.screen.emit('display-removed'); m.screen.emit('display-metrics-changed', {}, smaller, ['bounds']);
    expect(win.setBounds).toHaveBeenCalledTimes(repairs);
    await vi.advanceTimersByTimeAsync(1000); expect(m.app.exit).toHaveBeenCalledExactlyOnceWith(0);
  })
  it('restores maximized hidden windows without replacing retained normal geometry', async () => {
    const normalBounds = { x: 80, y: 40, width: 900, height: 600 };
    m.read.mockReturnValue(JSON.stringify({ windowState: { version: 1, normalBounds, maximized: true } }));
    const { win, deps } = await boot(['--hidden']);
    expect(win.options).toMatchObject(normalBounds); expect(win.maximize).toHaveBeenCalledOnce();
    expect(win.show).not.toHaveBeenCalled();
    deps.setSetupReminderHidden(true);
    expect(JSON.parse(m.write.mock.calls.at(-1)![1])).toMatchObject({ setupReminderHidden: true,
      windowState: { version: 1, normalBounds, maximized: true } });
  })
  it('retains a pre-ready open request but exits safely while tray detection is unresolved', async () => {
    let ready!: () => void; let trayReady!: (value: boolean) => void;
    m.ready = new Promise<void>(resolve => { ready = resolve });
    m.trayDetection = new Promise<boolean>(resolve => { trayReady = resolve });
    await boot(['--hidden']); m.app.emit('second-instance', {}, []);
    expect(m.windows).toHaveLength(0);
    ready(); await flush(); expect(m.deps).not.toBeNull(); expect(m.windows).toHaveLength(0);
    expect(await m.deps.pickFiles()).toEqual([]); expect(await m.deps.chooseSavePath('ignored')).toBeNull();
    expect(m.pick).not.toHaveBeenCalled(); expect(m.save).not.toHaveBeenCalled();
    m.sessionEnd(); await flush(); trayReady(true); await flush();
    expect(m.windows).toHaveLength(0); expect(m.trays).toHaveLength(0);
    expect(m.supervisors[0].start).not.toHaveBeenCalled(); expect(m.app.exit).toHaveBeenCalledExactlyOnceWith(0);
  })
  it.each(['not-ready', 'rejected'])('does not claim accepted shutdown when the core is %s', async failure => {
    const { broker, supervisor } = await boot();
    if (failure === 'not-ready') broker.waitForShutdownReady.mockResolvedValue(false);
    else broker.originalRequest.mockResolvedValue({ ok: false, error: { code: 'unavailable' } });
    m.sessionEnd(); await flush();
    expect(broker.quiesce).toHaveBeenCalledOnce(); expect(supervisor.stop).toHaveBeenCalledOnce();
    if (failure === 'not-ready') expect(broker.originalRequest).not.toHaveBeenCalledWith('runtime.shutdown', expect.anything());
    expect(m.journal.finish).toHaveBeenCalledWith(expect.objectContaining({ state: 'unknown', shutdownAccepted: false }));
    expect(m.app.exit).toHaveBeenCalledExactlyOnceWith(0);
  })
  it('ignores failed welcome snapshots and never sends an unaddressed smoke submission', async () => {
    vi.stubEnv('ODIN_SMOKE_MESSAGE', 'fixture hello');
    const { broker, win } = await boot(['--smoke-test']);
    broker.originalRequest.mockResolvedValue({ ok: false, error: { code: 'unavailable' } });
    broker.emit('welcome'); await flush();
    await vi.advanceTimersByTimeAsync(3000); await flush();
    expect(broker.originalRequest).not.toHaveBeenCalledWith('submission.send', expect.anything(), expect.anything());
    expect(win.webContents.capturePage).toHaveBeenCalledOnce(); expect(m.app.exit).toHaveBeenCalledWith(0);
  })
  it('retains latest geometry after a cosmetic write failure without adopting failed preferences or making Exit unknown', async () => {
    const { win, deps } = await boot();
    deps.setSetupReminderHidden(true); deps.setNotifications({ previews: false });
    const previous = structuredClone(deps.getSettings());
    m.write.mockImplementation(() => { throw new Error('geometry disk full') });
    win.setBounds({ x: 70, y: 30, width: 850, height: 550 });
    await vi.advanceTimersByTimeAsync(250);
    expect(m.journal.markUnknown).not.toHaveBeenCalled(); expect(m.app.exit).not.toHaveBeenCalled();
    expect(() => deps.setSetupReminderHidden(false)).toThrow('could not be persisted');
    expect(deps.getSetupReminderHidden()).toBe(true);
    expect(() => deps.setNotifications({ previews: true })).toThrow('could not be persisted');
    expect(deps.getSettings()).toEqual(previous);
    m.write.mockImplementation(() => undefined); deps.setAppearance('light');
    expect(JSON.parse(m.write.mock.calls.at(-1)![1])).toMatchObject({ setupReminderHidden: true,
      appearance: 'light', notifications: { previews: false }, windowState: {
        normalBounds: { x: 70, y: 30, width: 850, height: 550 } } });
    m.write.mockImplementation(() => { throw new Error('shutdown geometry disk full') });
    m.sessionEnd(); await flush();
    expect(m.journal.finish).toHaveBeenCalledWith(expect.objectContaining({ state: 'process-exited', unsaved: false }));
    expect(m.app.exit).toHaveBeenCalledExactlyOnceWith(0);
  })
  it.each(['missing-conversation', 'too-short', 'missing-message', 'not-highlighted', 'not-at-start'])
    ('rejects dishonest notification screenshot evidence: %s', async failure => {
      vi.stubEnv('ODIN_SMOKE_OUT', '/mock/smoke.png'); vi.stubEnv('ODIN_SMOKE_SHOTS', 'fixture');
      const { win } = await boot(['--smoke-test']);
      const execute = win.webContents.executeJavaScript.getMockImplementation()!;
      win.webContents.executeJavaScript.mockImplementation(async (script: string) => {
        if (failure === 'missing-conversation' && script.includes('conv-title')) return 'Not listed';
        if (failure === 'too-short' && script.includes('Math.round(s.scrollHeight')) return 99;
        if (failure === 'missing-message' && script.includes('id?.slice')) return '';
        if (script.includes('JSON.stringify({ top:')) {
          if (failure === 'not-highlighted') return JSON.stringify({ top: 0, view: 800, height: 900, highlighted: false });
          if (failure === 'not-at-start') return JSON.stringify({ top: 50, view: 800, height: 900, highlighted: true });
        }
        return execute(script);
      });
      await vi.runAllTimersAsync(); await flush();
      const expected = { 'missing-conversation': 'no listed conversation', 'too-short': 'too short to scroll away',
        'missing-message': 'could not identify', 'not-highlighted': 'did not highlight', 'not-at-start': 'did not show' }[failure];
      expect(process.stderr.write).toHaveBeenCalledWith(expect.stringContaining(expected!));
      expect(process.stdout.write).not.toHaveBeenCalledWith(expect.stringContaining('smoke: ok'));
      expect(m.app.exit).toHaveBeenCalledWith(1);
    })
})
