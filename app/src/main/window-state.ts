// App-owned DIP geometry. No renderer IPC or Chromium userData migration.
export interface Bounds { x: number; y: number; width: number; height: number }
export interface WindowState { version: 1; normalBounds: Bounds; maximized: boolean }
export interface DisplayArea { id: number; workArea: Bounds; scaleFactor?: number }
export type WindowBackend = 'x11' | 'wayland' | 'win32' | 'unknown'
const DEFAULT_SIZE = { width: 1180, height: 780 }
const MIN_SIZE = { width: 720, height: 480 }
const MAX_COORDINATE = 1_000_000

/** Electron 44/Chromium 152 resolves ozone-platform before ready. Read the native
 * command line AFTER ready: WAYLAND_DISPLAY and EGL displayType are not evidence.
 * Unknown backends deliberately receive no position instructions. */
export function windowBackend(platform: string, resolvedOzonePlatform: string): WindowBackend {
  if (platform === 'linux' && resolvedOzonePlatform === 'x11') return 'x11'
  if (platform === 'linux' && resolvedOzonePlatform === 'wayland') return 'wayland'
  if (platform === 'win32') return 'win32'
  return 'unknown'
}

/** Whether the window system honors a window's position: X11 and Windows do, Wayland doesn't. */
export function honorsPosition(backend: WindowBackend): boolean {
  return backend === 'x11' || backend === 'win32'
}

export function objectRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {}
}

export function validBounds(value: unknown): Bounds | null {
  const candidate = objectRecord(value)
  if (!['x', 'y', 'width', 'height'].every((key) => typeof candidate[key] === 'number'
    && Number.isFinite(candidate[key]) && Math.abs(candidate[key] as number) <= MAX_COORDINATE)) return null
  if ((candidate.width as number) < 1 || (candidate.height as number) < 1) return null
  return { x: Math.round(candidate.x as number), y: Math.round(candidate.y as number),
    width: Math.round(candidate.width as number), height: Math.round(candidate.height as number) }
}

export function loadWindowState(value: unknown): WindowState | null {
  const candidate = objectRecord(value)
  const normalBounds = validBounds(candidate.normalBounds)
  return candidate.version === 1 && typeof candidate.maximized === 'boolean' && normalBounds
    ? { version: 1, normalBounds, maximized: candidate.maximized } : null
}

function intersection(a: Bounds, b: Bounds): number {
  return Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x))
    * Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y))
}

/** A body-only intersection cannot drag a window back. Require a useful titlebar
 * strip, scaled down only for genuinely tiny work areas. Work areas are already DIP. */
export function reachableTitlebar(bounds: Bounds, workArea: Bounds): boolean {
  const title = { ...bounds, height: Math.min(32, bounds.height) }
  const width = Math.min(title.x + title.width, workArea.x + workArea.width) - Math.max(title.x, workArea.x)
  const height = Math.min(title.y + title.height, workArea.y + workArea.height) - Math.max(title.y, workArea.y)
  return width >= Math.min(120, bounds.width, workArea.width)
    && height >= Math.min(24, title.height, workArea.height)
}

export interface RestoredWindow {
  state: WindowState
  options: { x?: number; y?: number; width: number; height: number; minWidth: number; minHeight: number }
}

export function restoreWindowState(saved: unknown, displays: DisplayArea[], primaryId: number,
  backend: WindowBackend): RestoredWindow {
  const available = displays.flatMap((display) => {
    const workArea = validBounds(display.workArea)
    return workArea ? [{ ...display, workArea }] : []
  })
  // Electron guarantees a display after ready. A defensive fallback still makes
  // malformed injected display data harmless; it is not backend evidence.
  const primary = available.find((display) => display.id === primaryId) ?? available[0]
    ?? { id: primaryId, workArea: { x: 0, y: 0, width: 1280, height: 800 } }
  const state = loadWindowState(saved)
  const prior = state?.normalBounds
  const display = honorsPosition(backend) && prior
    ? available.filter((d) => reachableTitlebar(prior, d.workArea))
      .sort((a, b) => intersection(prior, b.workArea) - intersection(prior, a.workArea))[0] ?? primary
    : primary
  const area = display.workArea
  const minWidth = Math.min(MIN_SIZE.width, area.width)
  const minHeight = Math.min(MIN_SIZE.height, area.height)
  const width = Math.min(area.width, Math.max(minWidth, prior?.width ?? DEFAULT_SIZE.width))
  const height = Math.min(area.height, Math.max(minHeight, prior?.height ?? DEFAULT_SIZE.height))
  const keepPosition = honorsPosition(backend) && prior && reachableTitlebar(prior, area)
  const x = keepPosition ? Math.max(area.x, Math.min(prior.x, area.x + area.width - width))
    : area.x + Math.floor((area.width - width) / 2)
  const y = keepPosition ? Math.max(area.y, Math.min(prior.y, area.y + area.height - height))
    : area.y + Math.floor((area.height - height) / 2)
  return { state: { version: 1, normalBounds: { x, y, width, height }, maximized: state?.maximized ?? false },
    options: { ...(honorsPosition(backend) ? { x, y } : {}), width, height, minWidth, minHeight } }
}

export interface StateWindow {
  isDestroyed(): boolean
  isMinimized(): boolean
  isMaximized(): boolean
  isFullScreen(): boolean
  getNormalBounds(): Bounds
  setBounds(bounds: Bounds | { width: number; height: number }): void
  setMinimumSize(width: number, height: number): void
  on(event: string, listener: () => void): unknown
  removeListener(event: string, listener: () => void): unknown
}

/** Events update the retained state immediately; only disk writes are debounced.
 * The app's single writer reads snapshot(), preserving ALL latest preferences. */
export class WindowStateController {
  private state: WindowState
  private timer: ReturnType<typeof setTimeout> | undefined
  private disposed = false
  private pendingRepair = false
  private readonly changed = (): void => { this.capture(); this.schedule() }
  private readonly restored = (): void => {
    try {
      if (this.pendingRepair && !this.win.isDestroyed() && !this.win.isMinimized()
        && !this.win.isMaximized() && !this.win.isFullScreen()) {
        this.pendingRepair = false
        const { x, y, width, height } = this.state.normalBounds
        this.win.setBounds(honorsPosition(this.backend) ? { x, y, width, height } : { width, height })
      }
    } catch { /* Native window may be ending. Cosmetic repair cannot block Exit. */ }
    this.changed()
  }
  private readonly events = ['move', 'resize', 'maximize']
  private readonly restoreEvents = ['unmaximize', 'restore', 'leave-full-screen']
  constructor(private readonly win: StateWindow, initial: WindowState,
    private readonly save: () => unknown, private readonly backend: WindowBackend, private readonly delay = 250) {
    this.state = { ...initial, normalBounds: { ...initial.normalBounds } }
    // X11 WMs can expose maximized bounds as getNormalBounds during a hidden
    // startup maximize. Retain the known normal rectangle until unmaximize.
    this.pendingRepair = initial.maximized
    for (const event of this.events) win.on(event, this.changed)
    for (const event of this.restoreEvents) win.on(event, this.restored)
  }
  snapshot(): WindowState { return { ...this.state, normalBounds: { ...this.state.normalBounds } } }
  private capture(): void {
    try { this.captureNative() } catch { /* Native destruction races are cosmetic. */ }
  }
  private captureNative(): void {
    if (this.disposed || this.win.isDestroyed() || this.win.isMinimized() || this.win.isFullScreen()) return
    if (this.pendingRepair) return
    this.state.maximized = this.win.isMaximized()
    if (this.state.maximized) { this.pendingRepair = true; return }
    const bounds = validBounds(this.win.getNormalBounds())
    if (bounds) this.state = { version: 1, normalBounds: bounds, maximized: this.win.isMaximized() }
  }
  private schedule(): void {
    if (this.disposed) return
    if (this.timer !== undefined) clearTimeout(this.timer)
    this.timer = setTimeout(() => { this.timer = undefined; this.persist() }, this.delay)
  }
  private persist(): void { try { this.save() } catch { /* Cosmetic persistence never blocks lifecycle. */ } }
  flush(): void {
    if (this.disposed) return
    if (this.timer !== undefined) clearTimeout(this.timer)
    this.timer = undefined
    this.capture()
    this.persist()
  }
  repair(displays: DisplayArea[], primaryId: number): void {
    try { this.repairNative(displays, primaryId) } catch { /* UI repair remains best effort. */ }
  }
  private repairNative(displays: DisplayArea[], primaryId: number): void {
    if (this.disposed || this.win.isDestroyed()) return
    this.capture()
    const repaired = restoreWindowState(this.state, displays, primaryId, this.backend)
    this.state = repaired.state
    this.win.setMinimumSize(repaired.options.minWidth, repaired.options.minHeight)
    if (!this.win.isMinimized() && !this.win.isMaximized() && !this.win.isFullScreen()) {
      const { x, y, width, height } = repaired.options
      this.win.setBounds(x !== undefined && y !== undefined ? { x, y, width, height } : { width, height })
    } else this.pendingRepair = true
    this.schedule()
  }
  dispose(): void {
    this.flush()
    this.disposed = true
    for (const event of this.events) this.win.removeListener(event, this.changed)
    for (const event of this.restoreEvents) this.win.removeListener(event, this.restored)
  }
}
