// Odin Desktop: app main process.
//
// Odin runs while the app runs (D3). Closing the window keeps Odin working in the tray; Exit (tray, window menu,
// Ctrl+Q, or the launcher's "Exit Odin" action) shuts Odin down in order and then quits the app.
import { randomUUID } from 'node:crypto'
import { readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { BrowserWindow, Menu, Notification, app, clipboard, dialog, ipcMain, shell } from 'electron'
import { IPC, type AppState, type CoreEvent, type LinkState, type NotificationSettings, type Settings } from '../shared/api'
import { ArtifactStore, safeFileName } from './artifacts'
import { AttachmentManager, type AttachmentLimits } from './attachments'
import { isAutostartEnabled, setAutostart } from './autostart'
import { Broker } from './broker'
import { coreCommand, type CoreLaunch } from './core-command'
import { CoreSupervisor } from './core-supervisor'
import { DraftStore } from './drafts'
import { registerIpc } from './ipc'
import { decideSecondInstance, decideWindowClose, parseLaunchFlags, type LifecycleState } from './lifecycle'
import { ConversationIndex, Notifier, loadSettings, mergeSettings, setMuted, type NotificationIntent } from './notifications'
import { ensureProfileDirs, ensureToken, profilePaths } from './paths'
import { realCoreSmoke } from './real-core-smoke'
import { hardenedWebPreferences, installGuards, registerAppScheme, serveAppScheme } from './security'
import { APP_ORIGIN } from './security-policy'
import { OdinTray, detectTray } from './tray'
import { boundedShutdown, CleanupJournal } from './shutdown'
import { showNativeNotification } from './native-notifications'

registerAppScheme()

const flags = parseLaunchFlags(process.argv)

if (!app.requestSingleInstanceLock()) {
  // Another Odin is running: it receives our argv through 'second-instance' (focus, or exit for --exit).
  app.quit()
} else if (flags.exit) {
  // No running app: Exit is a no-op, before profile/core construction.
  app.quit()
} else {
  run()
}

function run(): void {
  const paths = profilePaths()
  ensureProfileDirs(paths)
  ensureToken(paths)

  const appStateFile = paths.appStatePath
  // Separate app-owned evidence from the engine's identity-checked bootstrap profile.
  const cleanupPath = join(paths.configDir, '..', `${paths.profileId}-cleanup-state.json`)
  const cleanup = new CleanupJournal(cleanupPath)
  cleanup.begin()
  const persisted = readPersisted(appStateFile)
  const lifecycle: LifecycleState = {
    quitting: false,
    trayAvailable: false,
    noTrayNoticeShown: persisted.noTrayNoticeShown === true
  }
  let notificationSettings = loadSettings(persisted.notifications)
  const savePersisted = (): boolean =>
    writePersisted(appStateFile, { noTrayNoticeShown: lifecycle.noTrayNoticeShown, notifications: notificationSettings })

  const resources = join(app.getAppPath(), 'resources')
  const iconPath = join(resources, 'icon.png')
  const trayIconPath = join(resources, 'tray.png')
  const preloadPath = join(__dirname, '../preload/index.js')
  const rendererDir = join(__dirname, '../renderer')

  let win: BrowserWindow | null = null
  let tray: OdinTray | null = null
  const cleanupNotice = new AbortController()
  let supervisorLink: LinkState | null = null
  let pendingOpen = !flags.hidden
  let notificationRouteReady = false
  let pendingNotificationTarget: { conversationId: string; messageId: string } | null = null
  const drainNotificationTarget = (): void => {
    if (!notificationRouteReady || !win || !pendingNotificationTarget || lifecycle.quitting) return
    win.webContents.send(IPC.openConversation, pendingNotificationTarget)
    pendingNotificationTarget = null
  }

  let launch: CoreLaunch
  try {
    launch = coreCommand(paths, {
      packaged: app.isPackaged,
      resourcesPath: process.resourcesPath,
      appPath: app.getAppPath(),
      env: process.env
    })
  } catch (error) {
    void app.whenReady().then(() => {
      dialog.showErrorBox('Odin core unavailable', (error as Error).message)
      app.exit(1)
    })
    return
  }
  const supervisor = new CoreSupervisor({ ...launch, logFile: join(paths.logDir, 'core.log'),
    // A ready core's unexpected loss cannot prove effect/input cleanup. Do not replace it automatically.
    restartAllowed: () => broker.coreInstanceId === null })
  const broker = new Broker({
    socketPath: paths.socketPath,
    readToken: () => readFileSync(paths.tokenPath, 'utf8').trim(),
    profileId: paths.profileId,
    clientVersion: app.getVersion()
  })
  const coreRequest = broker.request.bind(broker)
  broker.request = (method, params, id) => lifecycle.quitting
    ? Promise.resolve({ ok: false, error: { code: 'busy', message: 'Odin is exiting' } })
    : coreRequest(method, params, id)

  // Titles and unread counts for notifications and the tray. Cosmetic: the window keeps the authoritative view.
  const conversations = new ConversationIndex()
  const refreshTray = (): void => tray?.setTooltip(conversations.tooltip())
  const listConversations = (): void => {
    void broker.request('conversations.list').then((listed) => {
      if (!listed.ok) return
      const { items, watermark } = listed.result as { items: Array<{ id: string; title: string; unread: number }>; watermark: string }
      conversations.reset(items, Number(watermark) || 0)
      refreshTray()
    })
  }
  const liveNotifications = new Set<Notification>()
  const notificationAcks: Array<Record<string, unknown>> = []
  const notifier = new Notifier({
    settings: () => notificationSettings,
    windowFocused: () => Boolean(win?.isVisible() && win.isFocused()),
    titleOf: (id) => conversations.titleOf(id),
    show: (notification) => showNativeNotification(notification, liveNotifications, iconPath),
    open: (id, messageId) => {
      pendingNotificationTarget = { conversationId: id, messageId }
      showWindow()
      drainNotificationTarget()
    },
    ack: (dedupeKey, outcome) => {
      const id = randomUUID()
      void broker.request('notifications.ack', { dedupe_key: dedupeKey, outcome }, id).then((settled) => {
        if (process.env.ODIN_APP_E2E === '1') notificationAcks.push({ dedupeKey, outcome, id, settled })
      })
    },
    now: () => new Date()
  })
  const onCoreEvent = (event: CoreEvent): void => {
    const p = event.payload
    switch (event.type) {
      case 'notification.intent':
        void notifier.handle(p as unknown as NotificationIntent, new Date(event.at))
        return
      case 'conversation.created':
      case 'conversation.updated':
        conversations.upsert(p.conversation as { id: string; title: string; unread: number }, event.seq)
        refreshTray()
        return
      case 'artifact.unavailable':
        // A file the core no longer has leaves the private cache too.
        void artifacts.forget(String(p.ref))
        return
      case 'conversation.deleted': {
        const id = String(p.conversation_id)
        conversations.remove(id, event.seq)
        if (notificationSettings.muted.includes(id)) {
          notificationSettings = setMuted(notificationSettings, id, false)
          savePersisted()
        }
        refreshTray()
      }
    }
  }

  const drafts = new DraftStore(join(paths.dataDir, 'drafts.json'))
  // Until the core announces its own limits. A chunk stays well inside one frame after base64.
  let limits: AttachmentLimits = { attachment_bytes: 25 * 1024 * 1024, chunk_bytes: 512 * 1024 }
  const attachments = new AttachmentManager(broker, () => limits)
  attachments.on('progress', (progress) => win?.webContents.send(IPC.attachmentProgress, progress))
  const artifacts = new ArtifactStore(broker, paths.cacheDir, () => limits.chunk_bytes, {
    openPath: (path) => shell.openPath(path),
    showItemInFolder: (path) => shell.showItemInFolder(path)
  })
  broker.on('welcome', () => {
    listConversations()
    void broker.request('status.get').then((status) => {
      const announced = status.ok ? (status.result as { limits?: Partial<AttachmentLimits> }).limits : undefined
      if (announced?.attachment_bytes && announced.chunk_bytes) {
        limits = { attachment_bytes: announced.attachment_bytes, chunk_bytes: Math.min(announced.chunk_bytes, 2 * 1024 * 1024) }
      }
    })
  })

  const appState = (): AppState => ({
    link: supervisorLink ?? broker.linkState,
    coreInstanceId: broker.coreInstanceId,
    noTray: !lifecycle.trayAvailable,
    unreceipted: broker.unreceiptedCount
  })

  const publishAppState = (): void => {
    const state = appState()
    win?.webContents.send(IPC.appState, state)
    tray?.setStatus(statusLabel(state.link))
  }

  broker.on('state', () => {
    // Existing pending receipts may settle, but Exit must never reconnect/re-send uncertain commands.
    if (lifecycle.quitting && broker.linkState !== 'ready') broker.close()
    publishAppState()
  })
  // A new incarnation rebuilds the cosmetic index. The Broker retains the
  // profile's durable sequence/cursor across core restarts.
  broker.on('core-changed', () => conversations.restart())
  broker.on('event', (event) => {
    win?.webContents.send(IPC.event, event)
    onCoreEvent(event)
  })
  broker.on('receipt', (receipt) => {
    win?.webContents.send(IPC.receipt, receipt)
    publishAppState()
  })
  // The interval since our cursor is unknown: the window rebuilds every view from fresh snapshots.
  broker.on('reset', (reset) => {
    win?.webContents.send(IPC.reset, reset)
    listConversations()
  })

  supervisor.on('restarting', () => {
    cleanup.markUnknown('Core stopped unexpectedly. Cleanup unknown; replacement must acquire the real profile lock. No work is replayed.')
    supervisorLink = 'core-restarting'
    publishAppState()
  })
  supervisor.on('started', () => {
    supervisorLink = null
    publishAppState()
  })
  supervisor.on('failed', () => {
    cleanup.markUnknown('Core stopped unexpectedly or could not start. Cleanup unknown; no work is replayed.')
    supervisorLink = 'core-failed'
    publishAppState()
  })

  const showWindow = (): void => {
    if (lifecycle.quitting) return
    pendingOpen = true
    if (!win) return
    if (win.webContents.isCrashed()) void win.loadURL(`${APP_ORIGIN}/index.html`)
    if (win.isMinimized()) win.restore()
    win.show()
    win.focus()
  }

  const settings = (): Settings => ({ autostart: isAutostartEnabled(), notifications: notificationSettings })

  const shutdown = boundedShutdown({
    stopAdmission: () => { lifecycle.quitting = true; cleanupNotice.abort(); broker.quiesce(); tray?.setStatus('Stopping Odin…') },
    persist: () => { drafts.flush(); if (!savePersisted()) throw new Error('App preferences were not persisted') },
    requestShutdown: async () => broker.linkState === 'ready'
      && (await coreRequest('runtime.shutdown', { reason: 'exit' })).ok,
    stopCore: () => {
      // No reconnect or command reconciliation during Exit.
      broker.close()
      return supervisor.stop()
    },
    unreceipted: () => broker.unreceiptedCount,
    finish: (record) => cleanup.finish(record),
    release: () => {
      for (const os of liveNotifications) os.close()
      liveNotifications.clear()
      tray?.destroy()
      tray = null
    },
    exit: (code) => app.exit(code)
  })
  const exitOdin = async (code = 0): Promise<void> => { await shutdown(code) }

  // Main-only hooks; not exposed through IPC/preload. The E2E runner enforces isolation before launch.
  if (!app.isPackaged && process.env.ODIN_APP_E2E === '1'
    && process.getuid?.() !== 0 && process.env.ODIN_REAL_CORE_ROOT
    && process.env.HOME === process.env.ODIN_REAL_CORE_ROOT
    && process.env.ODIN_REAL_CORE_OUTER_PID_NS
    && readlinkSync('/proc/self/ns/pid') !== process.env.ODIN_REAL_CORE_OUTER_PID_NS
    && /^:\d+$/.test(process.env.DISPLAY ?? '') && process.env.DBUS_SESSION_BUS_ADDRESS) {
    Object.assign(globalThis, { __odinE2E: {
      snapshot: () => ({ pid: process.pid, corePid: supervisor.pid, coreState: supervisor.current,
        appState: appState(), visible: win?.isVisible() ?? false, windowId: win?.id,
        rendererPid: win?.webContents.getOSProcessId(), noTrayNoticeShown: lifecycle.noTrayNoticeShown,
        cleanupUnknown: cleanup.warning, cleanupPath, paths, cursor: broker.cursor }),
      request: (method: string, params?: Record<string, unknown>, id?: string) => broker.request(method, params, id),
      notification: (intent: NotificationIntent, emittedAt: string) => notifier.handle(intent, new Date(emittedAt)),
      notificationAcks,
      close: () => win?.close(), show: showWindow,
      rendererCrash: () => win?.webContents.forcefullyCrashRenderer(),
      exit: () => { void exitOdin() }
    } })
  }

  app.on('second-instance', (_event, argv) => {
    if (decideSecondInstance(argv) === 'exit') void exitOdin()
    else showWindow()
  })

  // Closing every window must never stop Odin (D3); only Exit does.
  app.on('window-all-closed', () => undefined)
  app.on('before-quit', (event) => {
    if (!lifecycle.quitting) {
      event.preventDefault()
      void exitOdin()
    }
  })

  void app.whenReady().then(async () => {
    if (lifecycle.quitting) return
    installGuards()
    serveAppScheme(rendererDir)
    registerIpc({
      admitting: () => !lifecycle.quitting,
      broker,
      windowId: () => win?.webContents.id ?? null,
      drafts,
      attachments,
      pickFiles: async () => {
        const chosen = win
          ? await dialog.showOpenDialog(win, { properties: ['openFile', 'multiSelections'], title: 'Attach files' })
          : { canceled: true, filePaths: [] }
        return chosen.canceled ? [] : chosen.filePaths
      },
      artifacts,
      chooseSavePath: async (name) => {
        const chosen = win
          ? await dialog.showSaveDialog(win, {
              defaultPath: join(app.getPath('downloads'), safeFileName(name)),
              title: 'Save file',
              properties: ['showOverwriteConfirmation', 'createDirectory']
            })
          : { canceled: true, filePath: undefined }
        return chosen.canceled || !chosen.filePath ? null : chosen.filePath
      },
      copyText: (text) => clipboard.writeText(text),
      mainFrame: () => win?.webContents.mainFrame ?? null,
      getSettings: settings,
      setAutostart: (enabled) => {
        setAutostart(enabled, launchCommand())
        return settings()
      },
      setNotifications: (change) => {
        notificationSettings = mergeSettings(notificationSettings, change)
        savePersisted()
        return settings()
      },
      setConversationMuted: (conversationId, muted) => {
        notificationSettings = setMuted(notificationSettings, conversationId, muted)
        savePersisted()
        return settings()
      },
      appState
    })

    lifecycle.trayAvailable = flags.smokeTest ? false : await detectTray()
    if (lifecycle.quitting) return
    if (lifecycle.trayAvailable) {
      tray = new OdinTray(trayIconPath, { onOpen: showWindow, onExit: () => void exitOdin() })
      refreshTray()
    }

    Menu.setApplicationMenu(
      Menu.buildFromTemplate([
        {
          label: 'Odin',
          submenu: [
            { label: 'Close Window', accelerator: 'Ctrl+W', click: () => win?.close() },
            { type: 'separator' },
            { label: 'Exit Odin', accelerator: 'Ctrl+Q', click: () => void exitOdin() }
          ]
        },
        { label: 'Edit', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
        { label: 'View', submenu: [{ role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { type: 'separator' }, { role: 'togglefullscreen' }] }
      ])
    )

    win = new BrowserWindow({
      width: 1180,
      height: 780,
      minWidth: 720,
      minHeight: 480,
      show: false,
      title: 'Odin',
      icon: iconPath,
      backgroundColor: '#07090d',
      autoHideMenuBar: true,
      webPreferences: hardenedWebPreferences(preloadPath)
    })
    win.on('close', (event) => {
      const decision = decideWindowClose(lifecycle)
      if (decision.action === 'allow') return
      event.preventDefault()
      win?.hide()
      if (decision.showNoTrayNotice) {
        lifecycle.noTrayNoticeShown = true
        savePersisted()
        void showNativeNotification({
          title: 'Odin is still running',
          body: 'Reopen Odin from your app launcher. To stop Odin, choose Exit Odin in the window menu (Ctrl+Q) or in the launcher’s menu.',
          onClick: showWindow
        }, liveNotifications, iconPath).catch(() => undefined)
      }
    })
    win.webContents.on('did-finish-load', publishAppState)
    // Keep the no-tray Exit accelerator available even while the renderer is loading or unresponsive.
    win.webContents.on('before-input-event', (event, input) => {
      if (input.type === 'keyDown' && input.control && !input.alt && !input.meta && input.key.toLowerCase() === 'q') {
        event.preventDefault()
        void exitOdin()
      }
    })
    ipcMain.on(IPC.notificationRouteReady, (event) => {
      if (!win || lifecycle.quitting || event.sender !== win.webContents
        || event.senderFrame !== win.webContents.mainFrame
        || !event.senderFrame.url.startsWith(`${APP_ORIGIN}/`)) return
      notificationRouteReady = true
      drainNotificationTarget()
    })
    win.webContents.on('did-start-navigation', (_event, _url, _inPlace, mainFrame) => {
      if (mainFrame) notificationRouteReady = false
    })
    win.once('ready-to-show', () => {
      if (pendingOpen && !lifecycle.quitting) win?.show()
    })
    win.webContents.on('render-process-gone', (_event, details) => {
      notificationRouteReady = false
      process.stderr.write(`renderer ended reason=${details.reason}; core remains supervised\n`)
    })
    void win.loadURL(`${APP_ORIGIN}/index.html`)

    supervisor.start()
    broker.connect()
    broker.startEvents()
    if (cleanup.warning) {
      void dialog.showMessageBox(win, { type: 'warning', title: 'Odin cleanup unknown',
        message: 'Previous cleanup is unknown',
        detail: `${cleanup.warning.reason}\nNo effects are labelled undone. No work is replayed. This warning remains on future starts.`,
        buttons: ['Continue'], noLink: true, signal: cleanupNotice.signal })
    }

    if (flags.smokeTest && process.env.ODIN_SMOKE_REAL_CORE === '1') {
      void realCoreSmoke(win, broker, process.env.ODIN_SMOKE_OUT ?? '').then(
        () => exitOdin(),
        (error: unknown) => {
          process.stderr.write(`real-core-smoke: failed: ${String(error)}\n`)
          return exitOdin(1)
        }
      )
    } else if (flags.smokeTest) runSmokeTest(win, broker, exitOdin)
  })
}

/** The command the autostart entry runs: the AppImage, the packaged binary, or Electron plus this app in development. */
function launchCommand(): string[] {
  if (process.env.APPIMAGE) return [process.env.APPIMAGE]
  if (app.isPackaged) return [process.execPath]
  return [process.execPath, app.getAppPath()]
}

function statusLabel(link: LinkState): string {
  switch (link) {
    case 'ready':
      return 'Odin is running'
    case 'core-restarting':
      return 'Odin is restarting…'
    case 'core-failed':
      return 'Odin stopped unexpectedly'
    case 'reconnecting':
      return 'Reconnecting…'
    default:
      return 'Starting…'
  }
}

interface PersistedState {
  noTrayNoticeShown: boolean
  notifications: NotificationSettings
}

function readPersisted(path: string): { noTrayNoticeShown?: boolean; notifications?: unknown } {
  try {
    return JSON.parse(readFileSync(path, 'utf8')) as { noTrayNoticeShown?: boolean; notifications?: unknown }
  } catch {
    return {}
  }
}

/** Writes the whole state every time, so saving one setting never drops another. */
function writePersisted(path: string, state: PersistedState): boolean {
  try {
    writeFileSync(path, JSON.stringify(state), { mode: 0o600 })
    return true
  } catch {
    // Exit records failed persistence as unknown rather than silently declaring
    // completed clean shutdown. Ordinary UI callers remain available.
    return false
  }
}

/**
 * Development smoke test, run in an isolated virtual display (xvfb), never on a real desktop: waits until the core
 * handshake completes and the page has rendered, saves a screenshot, then exits through the normal Exit path.
 */
function runSmokeTest(win: BrowserWindow, broker: Broker, exitOdin: () => Promise<void>): void {
  const out = process.env.ODIN_SMOKE_OUT
  const deadline = setTimeout(() => {
    process.stderr.write('smoke: timed out\n')
    app.exit(1)
  }, 45_000)
  const capture = (): void => {
    void exchange().then(() => setTimeout(async () => {
      const image = await win.webContents.capturePage()
      if (out) writeFileSync(out, image.toPNG())
      if (out && process.env.ODIN_SMOKE_SHOTS) {
        try {
          await interfaceShots(win, out, broker)
        } catch (error) {
          process.stderr.write(`smoke: interface shots failed: ${String(error)}\n`)
          app.exit(1)
          return
        }
      }
      process.stdout.write(`smoke: ok link=${broker.linkState} core=${broker.coreInstanceId}\n`)
      clearTimeout(deadline)
      await exitOdin()
    }, 1_500))
  }
  // With ODIN_SMOKE_MESSAGE set, send one message as the user would and wait for the committed reply, so the
  // screenshot shows the full path: submission, tool activity, guarded reply.
  const exchange = async (): Promise<void> => {
    const text = process.env.ODIN_SMOKE_MESSAGE
    await new Promise((resolve) => setTimeout(resolve, 1_500))
    if (!text) return
    const listed = await broker.request('conversations.list')
    const items = listed.ok ? (listed.result as { items: Array<{ id: string }> }).items : []
    const conversationId = items[0]?.id
    if (!conversationId) return
    const done = new Promise<void>((resolve) => {
      const onEvent = (event: { type: string }): void => {
        if (event.type === 'request.completed') {
          broker.off('event', onEvent)
          resolve()
        }
      }
      broker.on('event', onEvent)
    })
    const id = randomUUID()
    await broker.request('submission.send', { client_submission_id: id, conversation_id: conversationId, text }, id)
    await done
  }
  if (broker.linkState === 'ready') capture()
  else broker.once('welcome', capture)
}

/**
 * With ODIN_SMOKE_SHOTS set, the smoke run also opens the search panel, a search result, a conversation menu, the
 * rename dialog and the command menu, and asks for a very long reply, saving a screenshot of each next to the main one
 * so layout can be checked by eye, and printing how quickly the long reply renders. Test tooling only.
 */
async function interfaceShots(win: BrowserWindow, out: string, broker: Broker): Promise<void> {
  const pause = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))
  const run = (script: string): Promise<unknown> =>
    win.webContents.executeJavaScript(script, true).catch((error: unknown) => {
      throw new Error(`${String(error)} (script: ${script.trim().slice(0, 90)})`)
    })
  const shoot = async (name: string): Promise<void> => {
    const image = await win.webContents.capturePage()
    writeFileSync(out.replace(/\.png$/, `-${name}.png`), image.toPNG())
  }
  await run(`document.querySelector('.head-actions button').click()`)
  await pause(300)
  await run(`(() => {
    const input = document.querySelector('.search-form input')
    input.value = ${JSON.stringify(process.env.ODIN_SMOKE_SHOTS)}
    input.dispatchEvent(new Event('input'))
    input.form.requestSubmit()
  })()`)
  await pause(700)
  await shoot('search')
  await run(`document.querySelector('.hit').click()`)
  await pause(700)
  await shoot('jump')
  await run(`document.querySelector('.jump-banner .ghost')?.click()`) // only when the hit was outside the loaded page
  await pause(300)
  await run(`document.querySelector('.search-form .ghost').click()`)
  await run(`document.querySelector('.conv-more').click()`)
  await pause(300)
  await shoot('menu')
  await run(`document.querySelector('.menu button').click()`)
  await pause(300)
  await shoot('dialog')
  await run(`document.querySelector('.dialog .ghost').click()`)
  await run(`(() => {
    const box = document.querySelector('.composer-form textarea')
    box.value = '/'
    box.dispatchEvent(new Event('input'))
  })()`)
  await pause(300)
  await shoot('palette')
  await run(`(() => {
    const box = document.querySelector('.composer-form textarea')
    box.value = ''
    box.dispatchEvent(new Event('input'))
  })()`)
  // Running work, a tool call's details and retained output, and the resume banner.
  const sendAndWait = (text: string, ready: string): Promise<unknown> =>
    run(`(async () => {
      const box = document.querySelector('.composer-form textarea')
      box.value = ${JSON.stringify(text)}
      box.dispatchEvent(new Event('input'))
      box.form.requestSubmit()
      for (let i = 0; i < 250; i++) {
        await new Promise((r) => setTimeout(r, 20))
        if (${ready}) return true
      }
      throw new Error('never ready: ' + ${JSON.stringify(text)})
    })()`)
  await sendAndWait(
    'start an agent and a process, and show the output',
    `[...document.querySelectorAll('.msg.assistant .body')].some((b) => b.textContent.includes('start an agent'))`
  )
  await run(`document.querySelector('.work-toggle').click()`)
  await pause(500)
  await shoot('work')
  await run(`document.querySelector('.work-toggle').click()`)
  await run(`(async () => {
    const toggles = document.querySelectorAll('.msg.assistant .tools-toggle')
    toggles[toggles.length - 1].click()
    await new Promise((r) => setTimeout(r, 100))
    const rows = document.querySelectorAll('.msg.assistant .tool-row')
    rows[rows.length - 1].click()
    for (let i = 0; i < 100 && !document.querySelector('.tool-output button'); i++) await new Promise((r) => setTimeout(r, 20))
    document.querySelector('.tool-output button').click()
    for (let i = 0; i < 100 && !document.querySelector('.tool-output pre'); i++) await new Promise((r) => setTimeout(r, 20))
    document.querySelector('.tool-detail').scrollIntoView({ block: 'center' })
  })()`)
  await pause(300)
  await shoot('tool')
  await sendAndWait('please interrupt', `document.querySelector('.resume-banner')`)
  await run(`document.querySelector('.resume-banner').scrollIntoView({ block: 'end' })`)
  await pause(300)
  await shoot('resume')
  // The settings menu: General, then Models and providers with the Codex accounts.
  await run(`[...document.querySelectorAll('.topbar button')].find((b) => b.textContent.trim() === 'Settings').click()`)
  await pause(800)
  await shoot('settings')
  await run(`[...document.querySelectorAll('.settings-nav-item')].find((b) => b.textContent.includes('Models')).click()`)
  await pause(800)
  await shoot('settings-models')
  await run(`document.querySelector('.field-intent').scrollIntoView({ block: 'center' })`)
  await shoot('settings-image')
  const sections: Array<[string, string]> = [
    ['Tools', 'settings-tools'],
    ['Skills', 'settings-skills'],
    ['MCP servers', 'settings-mcp'],
    ['Hosts and trust', 'settings-hosts'],
    ['Scheduled and running work', 'settings-work'],
    ['Personality', 'settings-personality'],
    ['State', 'settings-state'],
    ['Records', 'settings-records']
  ]
  for (const [section, name] of sections) {
    await run(`[...document.querySelectorAll('.settings-nav-item')].find((b) => b.textContent.trim() === ${JSON.stringify(section)}).click()`)
    await pause(800)
    await shoot(name)
  }
  // The schedule form, then the host wizard's first step.
  await run(`[...document.querySelectorAll('.settings-nav-item')].find((b) => b.textContent.trim() === 'Scheduled and running work').click()`)
  await pause(600)
  await run(`[...document.querySelectorAll('.panel-head button')].find((b) => b.textContent.trim() === 'New schedule').click()`)
  await pause(500)
  await run(`document.querySelector('[aria-label="Schedule form"]').scrollIntoView({ block: 'start' })`)
  await shoot('settings-schedule-form')
  await run(`[...document.querySelectorAll('.settings-nav-item')].find((b) => b.textContent.trim() === 'Hosts and trust').click()`)
  await pause(600)
  await run(`[...document.querySelectorAll('.panel-head button')].find((b) => b.textContent.trim() === 'Add host').click()`)
  await pause(500)
  await run(`document.querySelector('[aria-label="Host enrollment"]').scrollIntoView({ block: 'start' })`)
  await shoot('settings-host-wizard')
  await run(`document.querySelector('.settings-nav .back').click()`)
  await pause(300)
  // A very long reply, as a regression signal: how long reopening its conversation takes (fetch, render, paint), and
  // how long narrowing it by a pixel takes to re-lay it out, as a window resize does.
  const timing = await run(`(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
    const painted = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))
    const longReply = () =>
      [...document.querySelectorAll('.msg.assistant .body')].find((b) => b.textContent.includes('log line 5000'))
    const box = document.querySelector('.composer-form textarea')
    box.value = 'a long reply please'
    box.dispatchEvent(new Event('input'))
    box.form.requestSubmit()
    for (let i = 0; i < 500 && !longReply(); i++) await sleep(20)
    if (!longReply()) return 'never rendered'
    await painted()
    const longButton = document.querySelector('.conversations .conv.active')
    document.querySelector('.head-actions button + button').click()
    await sleep(500)
    const reopened = []
    for (let i = 0; i < 3; i++) {
      ;[...document.querySelectorAll('.conversations .conv')].find((b) => b !== longButton).click()
      await sleep(400)
      if (longReply()) return 'stayed on the page while another conversation was open'
      const t = performance.now()
      longButton.click()
      for (let k = 0; k < 2500 && !longReply(); k++) await sleep(2)
      if (!longReply()) return 'never came back'
      await painted()
      reopened.push((performance.now() - t).toFixed(0))
    }
    const reply = longReply()
    const article = reply.closest('.msg')
    const scroller = document.querySelector('.message-scroll')
    const narrower = article.getBoundingClientRect().width - 1 + 'px'
    const relayouts = []
    for (let i = 0; i < 6; i++) {
      const t = performance.now()
      article.style.maxWidth = i % 2 ? '' : narrower
      void scroller.scrollHeight
      relayouts.push(performance.now() - t)
    }
    article.style.maxWidth = ''
    const relayout = (relayouts.reduce((a, b) => a + b) / relayouts.length).toFixed(1)
    return reply.children.length + ' blocks; reopened in ' + reopened.join('/') + ' ms; relayout ' + relayout + ' ms; ' +
      document.querySelectorAll('.code-copy').length + ' code copy buttons'
  })()`)
  process.stdout.write(`smoke: long reply ${String(timing)}\n`)
  await pause(300)
  await shoot('long')
  // A clicked notification for the open conversation shows its latest message, even after scrolling away from it.
  const listed = await broker.request('conversations.list')
  const openTitle = String(await run(`document.querySelector('.conversations .conv.active .conv-title')?.textContent?.trim() ?? ''`))
  const items = listed.ok ? (listed.result as { items: Array<{ id: string; title: string }> }).items : []
  const latest = items.find((c) => c.title === openTitle)?.id
  if (!latest) throw new Error(`no listed conversation is titled "${openTitle}"`)
  {
    await run(`document.querySelector('.message-scroll').scrollTop = 0`)
    await pause(200)
    const away = Number(await run(`(() => { const s = document.querySelector('.message-scroll'); return Math.round(s.scrollHeight - s.scrollTop - s.clientHeight) })()`))
    if (away < 100) throw new Error(`the conversation is too short to scroll away from its latest message (${away}px)`)
    const messageId = String(await run(`document.querySelector('.msg:last-of-type')?.id?.slice(2) ?? ''`))
    if (!messageId) throw new Error('notification smoke could not identify the latest real message')
    win.webContents.send(IPC.openConversation, { conversationId: latest, messageId })
    await pause(600)
    const gap = Number(await run(`(() => { const s = document.querySelector('.message-scroll'); return Math.round(s.scrollHeight - s.scrollTop - s.clientHeight) })()`))
    process.stdout.write(`smoke: a notification click left the view ${gap}px from the latest message\n`)
    if (gap > 4) throw new Error(`a notification click left the view ${gap}px from the latest message`)
  }
}
