// Tray icon and menu (D3): Open, status, Exit. Exit is the way to stop Odin.
import { execFile } from 'node:child_process'
import { Menu, Tray, nativeImage } from 'electron'

type Env = Record<string, string | undefined>

const XEMBED_OR_SNI_DESKTOPS = /cinnamon|mate|xfce|lxqt|lxde|budgie|kde|plasma/i

/**
 * Best-effort check for a working tray. A StatusNotifierItem watcher on the session bus means yes. On X11, desktops
 * known to provide a tray mean yes. Otherwise no, and closing the window shows the one-time "still running" notice.
 */
export function detectTray(env: Env = process.env, system: NodeJS.Platform = process.platform): Promise<boolean> {
  // Windows always has a notification area; creating the tray is still checked where it's made.
  if (system === 'win32') return Promise.resolve(true)
  return new Promise((resolve) => {
    execFile(
      'gdbus',
      [
        'call', '--session', '--dest', 'org.freedesktop.DBus', '--object-path', '/org/freedesktop/DBus',
        '--method', 'org.freedesktop.DBus.NameHasOwner', 'org.kde.StatusNotifierWatcher'
      ],
      { timeout: 2000 },
      (error, stdout) => {
        if (!error && /true/.test(stdout)) return resolve(true)
        const x11 = (env.XDG_SESSION_TYPE || '').toLowerCase() === 'x11'
        resolve(x11 && XEMBED_OR_SNI_DESKTOPS.test(env.XDG_CURRENT_DESKTOP || ''))
      }
    )
  })
}

export interface TrayHandlers {
  onOpen: () => void
  onExit: () => void
}

export class OdinTray {
  private tray: Tray
  private status = 'Starting…'

  constructor(iconPath: string, private handlers: TrayHandlers) {
    this.tray = new Tray(nativeImage.createFromPath(iconPath))
    this.tray.setToolTip('Odin')
    this.tray.on('click', () => handlers.onOpen())
    this.render()
  }

  setStatus(status: string): void {
    this.status = status
    this.render()
  }

  /** Unread counts, so a glance at the tray says whether anything is waiting. */
  setTooltip(text: string): void {
    this.tray.setToolTip(text)
  }

  destroy(): void {
    this.tray.destroy()
  }

  private render(): void {
    this.tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: 'Open Odin', click: () => this.handlers.onOpen() },
        { label: this.status, enabled: false },
        { type: 'separator' },
        { label: 'Exit Odin', click: () => this.handlers.onExit() }
      ])
    )
  }
}
