// Odin Desktop: app main process.
//
// Odin runs while the app runs (D3). Closing the window keeps Odin working in the tray; Exit (tray, window menu,
// Ctrl+Q, or the launcher's "Exit Odin" action) shuts Odin down in order and then quits the app.
import { randomUUID } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { BrowserWindow, Menu, Notification, app } from 'electron'
import { IPC, type AppState, type LinkState, type Settings } from '../shared/api'
import { isAutostartEnabled, setAutostart } from './autostart'
import { Broker } from './broker'
import { CoreSupervisor } from './core-supervisor'
import { registerIpc } from './ipc'
import { decideSecondInstance, decideWindowClose, parseLaunchFlags, type LifecycleState } from './lifecycle'
import { ensureProfileDirs, ensureToken, profilePaths } from './paths'
import { hardenedWebPreferences, installGuards, registerAppScheme, serveAppScheme } from './security'
import { APP_ORIGIN } from './security-policy'
import { OdinTray, detectTray } from './tray'

registerAppScheme()

const flags = parseLaunchFlags(process.argv)

if (!app.requestSingleInstanceLock()) {
  // Another Odin is running: it receives our argv through 'second-instance' (focus, or exit for --exit).
  app.quit()
} else {
  run()
}

function run(): void {
  const paths = profilePaths()
  ensureProfileDirs(paths)
  ensureToken(paths)

  const appStateFile = paths.appStatePath
  const persisted = readPersisted(appStateFile)
  const lifecycle: LifecycleState = {
    quitting: false,
    trayAvailable: false,
    noTrayNoticeShown: persisted.noTrayNoticeShown === true
  }

  const resources = join(app.getAppPath(), 'resources')
  const iconPath = join(resources, 'icon.png')
  const trayIconPath = join(resources, 'tray.png')
  const preloadPath = join(__dirname, '../preload/index.js')
  const rendererDir = join(__dirname, '../renderer')

  let win: BrowserWindow | null = null
  let tray: OdinTray | null = null
  let supervisorLink: LinkState | null = null

  const supervisor = new CoreSupervisor({ ...coreCommand(paths), logFile: join(paths.logDir, 'core.log') })
  const broker = new Broker({
    socketPath: paths.socketPath,
    readToken: () => readFileSync(paths.tokenPath, 'utf8').trim(),
    profileId: paths.profileId,
    clientVersion: app.getVersion()
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

  broker.on('state', publishAppState)
  broker.on('event', (event) => win?.webContents.send(IPC.event, event))
  broker.on('receipt', (receipt) => {
    win?.webContents.send(IPC.receipt, receipt)
    publishAppState()
  })
  // The interval since our cursor is unknown: the window rebuilds every view from fresh snapshots.
  broker.on('reset', (reset) => win?.webContents.send(IPC.reset, reset))

  supervisor.on('restarting', () => {
    supervisorLink = 'core-restarting'
    publishAppState()
  })
  supervisor.on('started', () => {
    supervisorLink = null
    publishAppState()
  })
  supervisor.on('failed', () => {
    supervisorLink = 'core-failed'
    publishAppState()
  })

  const showWindow = (): void => {
    if (!win) return
    if (win.isMinimized()) win.restore()
    win.show()
    win.focus()
  }

  const settings = (): Settings => ({ autostart: isAutostartEnabled() })

  let exiting: Promise<void> | null = null
  const exitOdin = (): Promise<void> => {
    if (exiting) return exiting
    lifecycle.quitting = true
    tray?.setStatus('Stopping Odin…')
    exiting = (async () => {
      if (broker.linkState === 'ready') {
        await Promise.race([
          broker.request('runtime.shutdown', { reason: 'exit' }),
          new Promise((resolve) => setTimeout(resolve, 5_000))
        ])
      }
      await supervisor.stop()
      broker.close()
      tray?.destroy()
      tray = null
      app.exit(0)
    })()
    return exiting
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
    installGuards()
    serveAppScheme(rendererDir)
    registerIpc({
      broker,
      windowId: () => win?.webContents.id ?? null,
      mainFrame: () => win?.webContents.mainFrame ?? null,
      getSettings: settings,
      setAutostart: (enabled) => {
        setAutostart(enabled, launchCommand())
        return settings()
      },
      appState
    })

    lifecycle.trayAvailable = flags.smokeTest ? false : await detectTray()
    if (lifecycle.trayAvailable) tray = new OdinTray(trayIconPath, { onOpen: showWindow, onExit: () => void exitOdin() })

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
        writePersisted(appStateFile, { noTrayNoticeShown: true })
        new Notification({
          title: 'Odin is still running',
          body: 'Reopen Odin from your app launcher. To stop Odin, choose Exit Odin in the window menu (Ctrl+Q) or in the launcher’s menu.'
        }).show()
      }
    })
    win.webContents.on('did-finish-load', publishAppState)
    win.once('ready-to-show', () => {
      if (!flags.hidden) win?.show()
    })
    void win.loadURL(`${APP_ORIGIN}/index.html`)

    supervisor.start()
    broker.connect()
    broker.startEvents()

    if (flags.smokeTest) runSmokeTest(win, broker, exitOdin)
  })
}

/** How to start the core. Phase 2 bundles the real engine; until then a development fixture stands in. */
function coreCommand(paths: ReturnType<typeof profilePaths>): { command: string; args: string[] } {
  const coreArgs = ['--socket', paths.socketPath, '--token-file', paths.tokenPath, '--profile', paths.profileId, '--data-dir', paths.dataDir]
  const override = process.env.ODIN_DESKTOP_CORE_CMD
  if (override) {
    const parts = JSON.parse(override) as string[]
    const [command, ...args] = parts
    if (!command) throw new Error('ODIN_DESKTOP_CORE_CMD is empty')
    return { command, args: [...args, ...coreArgs] }
  }
  return { command: 'python3', args: [join(app.getAppPath(), 'fixture-core', 'fixture_core.py'), ...coreArgs] }
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

function readPersisted(path: string): { noTrayNoticeShown?: boolean } {
  try {
    return JSON.parse(readFileSync(path, 'utf8')) as { noTrayNoticeShown?: boolean }
  } catch {
    return {}
  }
}

function writePersisted(path: string, state: { noTrayNoticeShown: boolean }): void {
  try {
    writeFileSync(path, JSON.stringify(state), { mode: 0o600 })
  } catch {
    /* a lost notice flag only means the notice may show once more */
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
      if (out && process.env.ODIN_SMOKE_SHOTS) await interfaceShots(win, out)
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
 * With ODIN_SMOKE_SHOTS set, the smoke run also opens the search panel, a conversation menu and the rename dialog,
 * saving a screenshot of each next to the main one, so layout can be checked by eye. Test tooling only.
 */
async function interfaceShots(win: BrowserWindow, out: string): Promise<void> {
  const pause = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))
  const run = (script: string): Promise<unknown> => win.webContents.executeJavaScript(script, true)
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
  await run(`document.querySelector('.search-form .ghost').click()`)
  await run(`document.querySelector('.conv-more').click()`)
  await pause(300)
  await shoot('menu')
  await run(`document.querySelector('.menu button').click()`)
  await pause(300)
  await shoot('dialog')
  await run(`document.querySelector('.dialog .ghost').click()`)
}
