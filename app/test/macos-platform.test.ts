// The app on macOS (phase 4). Logic runs on any system: paths against the vectors the engine reads too, and every
// macOS-only branch through its injected system or a modelled Electron.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

const electron = vi.hoisted(() => ({ app: { isPackaged: false }, shell: { openExternal: vi.fn(async () => undefined) } }))
vi.mock('electron', () => electron)

import { applicationMenu, isExitShortcut, type KeyInput } from '../src/main/app-menu'
import { coreCommand, packagedCoreCommand } from '../src/main/core-command'
import * as ownership from '../src/main/package-ownership'
import * as packageState from '../src/main/package-state'
import * as paths from '../src/main/paths'
import { currentPlatform } from '../src/main/platform'
import { AUTOSTART_UNAVAILABLE, macosPlatform } from '../src/main/platform/macos'
import { LOGIN_ITEMS_SETTINGS, macosAutostartEnabled, macosOpenedAtLogin, setMacosAutostart, type LoginItems }
  from '../src/main/platform/macos-autostart'
import { GUARDIAN_GRACE_SECONDS, GUARDIAN_TERM_SECONDS, macosPath, systemPaths, underGuardian, type PathFiles }
  from '../src/main/platform/macos-launch'
import { HOME_WITH_WHITESPACE, macosProfilePaths, SOCKET_PATH_LIMIT, userTempRoot, type TempRootSystem }
  from '../src/main/platform/macos-paths'
import { detectTray } from '../src/main/tray'

type Layout = Record<'home' | 'profile' | 'temp_root' | 'config' | 'data' | 'cache' | 'token' | 'app_state' | 'logs'
  | 'socket', string>
const VECTORS = JSON.parse(readFileSync(join(__dirname, '..', '..', 'tests', 'fixtures', 'macos-profile-vectors.json'),
  'utf8')) as {
  layouts: Layout[]
  refused_by_both: { home: string[]; profile: string[]; socket: Array<{ temp_root: string; profile: string }> }
  refused_by_the_app_only: { profile: string[] }
}

describe('the macOS profile, against the engine\'s vectors', () => {
  it.each(VECTORS.layouts)('lays the profile out as the engine does ($socket)', (layout) => {
    const profile = macosProfilePaths(layout.profile, { HOME: layout.home }, () => layout.temp_root)
    expect([profile.configDir, profile.dataDir, profile.cacheDir, profile.tokenPath, profile.appStatePath,
      profile.logDir, profile.socketPath])
      .toEqual([layout.config, layout.data, layout.cache, layout.token, layout.app_state, layout.logs, layout.socket])
    expect(profile.runtimeDir).toBe(join(layout.temp_root, 'odin-desktop', layout.profile))
    expect(Buffer.byteLength(profile.socketPath)).toBeLessThanOrEqual(SOCKET_PATH_LIMIT)
  })

  it('refuses what the engine refuses, and the app\'s narrower subset too', () => {
    const root = (): string => VECTORS.layouts[0]!.temp_root
    for (const home of VECTORS.refused_by_both.home) expect(() => macosProfilePaths('default', { HOME: home }, root)).toThrow()
    expect(() => macosProfilePaths('default', { HOME: '/Users/Ada Lovelace' }, root)).toThrow(HOME_WITH_WHITESPACE)
    for (const profile of [...VECTORS.refused_by_both.profile, ...VECTORS.refused_by_the_app_only.profile]) {
      expect(() => macosProfilePaths(profile, { HOME: '/Users/ada' }, root)).toThrow('invalid profile id')
    }
    for (const { temp_root: tempRoot, profile } of VECTORS.refused_by_both.socket) {
      expect(() => macosProfilePaths(profile, { HOME: '/Users/ada' }, () => tempRoot))
        .toThrow(`longer than macOS allows (${SOCKET_PATH_LIMIT} bytes)`)
    }
  })
})

describe('the per-user temporary folder', () => {
  const folder = (overrides: Partial<{ dir: boolean; uid: number; mode: number }> = {}) =>
    ({ isDirectory: () => overrides.dir ?? true, uid: overrides.uid ?? 501, mode: 0o40000 | (overrides.mode ?? 0o700) })
  const system = (named: string, info = folder()): TempRootSystem => ({
    named: () => named,
    real: (path) => path.replace(/^\/var\//, '/private/var/'),
    stat: () => info,
    uid: 501
  })

  it('is the real path of the folder macOS names, owned by this user with mode 0700', () => {
    expect(userTempRoot(system('/var/folders/ab/cd/T/'))).toBe('/private/var/folders/ab/cd/T/')
  })

  it('is refused when it is relative, escapes, or is not private to this user', () => {
    expect(() => userTempRoot(system('folders/T'))).toThrow('not an absolute local path')
    expect(() => userTempRoot(system('/var/../tmp'))).toThrow('not an absolute local path')
    expect(() => userTempRoot(system('/var/folders/T', folder({ uid: 0 })))).toThrow('not private to this user')
    expect(() => userTempRoot(system('/var/folders/T', folder({ mode: 0o755 })))).toThrow('not private to this user')
    expect(() => userTempRoot(system('/var/folders/T', folder({ dir: false })))).toThrow('not private to this user')
  })
})

/** Electron 44.5.1's macOS login items over one service status: openAtLogin is `enabled` (browser_mac.mm). */
function loginItems(packaged: boolean, status = 'not-registered', wasOpenedAtLogin = false) {
  const state = { status, registered: [] as boolean[] }
  const items: LoginItems = {
    isPackaged: packaged,
    getLoginItemSettings: () => ({ openAtLogin: state.status === 'enabled', wasOpenedAtLogin, status: state.status }),
    setLoginItemSettings: ({ openAtLogin }) => {
      state.registered.push(openAtLogin)
      if (state.status !== 'requires-approval' || !openAtLogin) state.status = openAtLogin ? 'enabled' : 'not-registered'
    }
  }
  return { items, state }
}

describe('start at login on macOS', () => {
  it('is unavailable from source', () => {
    const { items, state } = loginItems(false, 'enabled')
    expect(macosAutostartEnabled(items)).toBe(false)
    expect(() => setMacosAutostart(true, items)).toThrow(AUTOSTART_UNAVAILABLE)
    expect(state.registered).toEqual([])
    expect(macosOpenedAtLogin(loginItems(false, 'enabled', true).items)).toBe(false)
  })

  it('registers and removes the app as its own login item, reading only `enabled` as on', () => {
    const { items, state } = loginItems(true)
    const open = vi.fn(async () => undefined)
    expect(setMacosAutostart(true, items, open)).toBe(true)
    expect(macosAutostartEnabled(items)).toBe(true)
    expect(setMacosAutostart(false, items, open)).toBe(false)
    expect(state.registered).toEqual([true, false])
    expect(open).not.toHaveBeenCalled()
  })

  it('opens Login Items when turning it on still needs the user\'s approval, and reads it as off', () => {
    const { items } = loginItems(true, 'requires-approval')
    const open = vi.fn(async () => undefined)
    expect(setMacosAutostart(true, items, open)).toBe(false)
    expect(open).toHaveBeenCalledWith(LOGIN_ITEMS_SETTINGS)
    open.mockClear()
    setMacosAutostart(false, items, open)
    expect(open).not.toHaveBeenCalled()
  })

  it('opens Login Items through the system browser handler by default', () => {
    electron.shell.openExternal.mockClear()
    setMacosAutostart(true, loginItems(true, 'requires-approval').items)
    expect(electron.shell.openExternal).toHaveBeenCalledWith(LOGIN_ITEMS_SETTINGS)
  })

  it('keeps a login item\'s start hidden', () => {
    expect(macosOpenedAtLogin(loginItems(true, 'enabled', true).items)).toBe(true)
    expect(macosOpenedAtLogin(loginItems(true, 'enabled', false).items)).toBe(false)
  })
})

describe('the macOS platform', () => {
  it('is chosen on darwin, with the shared profile and package members', () => {
    expect(currentPlatform('darwin')).toBe(macosPlatform)
    expect(macosPlatform.name).toBe('macos')
    expect(macosPlatform.profilePaths).toBe(macosProfilePaths)
    expect(macosPlatform.ensureProfileDirs).toBe(paths.ensureProfileDirs)
    expect(macosPlatform.ensureToken).toBe(paths.ensureToken)
    expect(macosPlatform.inspectPackagedState).toBe(packageState.inspectPackagedState)
    expect(macosPlatform.acquirePackagedApp).toBe(ownership.acquirePackagedApp)
    expect(macosPlatform.admitPackagedApp).toBe(ownership.admitPackagedApp)
    expect(macosPlatform.trayIcon).toBe('trayTemplate.png')
    expect(macosPlatform.startRefusal).toBeUndefined()
    expect(macosPlatform.describeLinkRefusal).toBeUndefined()
    // Logout and shut down reach Exit through index.ts's powerMonitor handler: nothing else to watch.
    expect(macosPlatform.startSessionMonitor({ command: '', args: [], env: {} }, () => undefined)).toBeNull()
    expect(macosPlatform.installLogoutHook([])).toBeNull()
  })

  it('names why start at login is unavailable from source, and offers it once installed', () => {
    electron.app.isPackaged = false
    expect(macosPlatform.autostartUnavailable).toBe(AUTOSTART_UNAVAILABLE)
    expect(macosPlatform.isAutostartEnabled()).toBe(false)
    expect(() => macosPlatform.setAutostart(true, [])).toThrow(AUTOSTART_UNAVAILABLE)
    expect(macosPlatform.openedAtLogin?.()).toBe(false)
    electron.app.isPackaged = true
    try {
      expect(macosPlatform.autostartUnavailable).toBeUndefined()
    } finally {
      electron.app.isPackaged = false
    }
  })

  it('takes the menu bar as available', async () => {
    expect(await detectTray({}, 'darwin')).toBe(true)
  })
})

describe('the engine launch on an installed Mac', () => {
  const files = (entries: Record<string, string>, folder: string[] | null = []): PathFiles => ({
    read: (path) => {
      if (!(path in entries)) throw new Error('ENOENT')
      return entries[path]!
    },
    list: () => {
      if (folder === null) throw new Error('ENOENT')
      return folder
    }
  })

  it('reads path_helper\'s folders: /etc/paths, then /etc/paths.d in name order', () => {
    const read = files({ '/etc/paths': '/usr/local/bin\n/usr/bin\n\n/bin\n', '/etc/paths.d/b': '/opt/b\n',
      '/etc/paths.d/a': ' /opt/a \n' }, ['b', 'a', 'missing'])
    expect(systemPaths(read)).toEqual(['/usr/local/bin', '/usr/bin', '/bin', '/opt/a', '/opt/b'])
    expect(systemPaths(files({}, null))).toEqual([])
  })

  it('puts Homebrew first, keeps each absolute folder once, and drops anything relative', () => {
    const read = files({ '/etc/paths': '/usr/local/bin\n/usr/bin\n/bin\n/usr/sbin\n/sbin\n' })
    expect(macosPath('/usr/bin:/bin:relative::/Users/ada/bin:/opt/homebrew/bin', read))
      .toBe('/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Users/ada/bin')
    expect(macosPath(undefined, files({}))).toBe('/opt/homebrew/bin:/opt/homebrew/sbin')
  })

  it('runs the bundled engine under the guardian, whose grace ends before the supervisor\'s TERM', () => {
    const resources = '/Applications/Odin.app/Contents/Resources'
    const launch = { command: `${resources}/runtime/python/bin/python3`, args: ['-I', '-B', '-m', 'src', '--socket', 's'],
      env: { HOME: '/Users/ada', PATH: '/usr/bin:/bin', ODIN_DESKTOP_BUNDLE_ROOT: `${resources}/runtime` } }
    const guarded = underGuardian(resources, launch, files({ '/etc/paths': '/usr/bin\n/bin\n' }))
    expect(guarded).toEqual({
      command: `${resources}/runtime/odin-guardian`,
      args: ['--grace', '14', '--term', '4', '--', launch.command, ...launch.args],
      env: { ...launch.env, PATH: '/opt/homebrew/bin:/opt/homebrew/sbin:/usr/bin:/bin' }
    })
    // The supervisor sends TERM at 15 s and KILL at 20 s: the guardian is always terminating by then.
    expect(GUARDIAN_GRACE_SECONDS).toBeLessThan(15)
    expect(GUARDIAN_GRACE_SECONDS + GUARDIAN_TERM_SECONDS).toBeLessThan(20)
  })

  it('wraps only an installed Mac app\'s core launch', () => {
    const profile = macosProfilePaths('default', { HOME: '/Users/ada' }, () => VECTORS.layouts[0]!.temp_root)
    const resolvePackaged = (resources: string, args: string[], env: NodeJS.ProcessEnv) =>
      ({ command: `${resources}/runtime/python/bin/python3`, args, env })
    const context = { packaged: true, resourcesPath: '/R', appPath: '/A', env: { PATH: '/usr/bin' }, resolvePackaged }
    const mac = coreCommand(profile, { ...context, system: 'darwin' })
    expect(mac.command).toBe('/R/runtime/odin-guardian')
    expect(mac.args.slice(0, 6)).toEqual(['--grace', '14', '--term', '4', '--', '/R/runtime/python/bin/python3'])
    expect(mac.args).toContain(profile.socketPath)
    const linux = coreCommand(profile, { ...context, system: 'linux' })
    expect(linux.command).toBe('/R/runtime/python/bin/python3')
    expect(linux.env.PATH).toBe('/usr/bin')
  })

  it('refuses an installed Mac bundle without its guardian', () => {
    const present = (missing: string) => (path: string) => path !== missing
    expect(() => packagedCoreCommand('/R', [], {}, { system: 'darwin', exists: present('/R/runtime/odin-guardian') }))
      .toThrow('Odin bundled runtime is missing')
    expect(packagedCoreCommand('/R', [], {}, { system: 'darwin', exists: () => true }).command)
      .toBe('/R/runtime/python/bin/python3')
    expect(packagedCoreCommand('/R', [], {}, { system: 'linux', exists: present('/R/runtime/odin-guardian') }).command)
      .toBe('/R/runtime/python/bin/python3')
  })
})

describe('the macOS menu and Exit shortcut', () => {
  it('keeps Linux\'s and Windows\' menu as it was', () => {
    const actions = { closeWindow: vi.fn(), exit: vi.fn() }
    for (const system of ['linux', 'win32'] as const) {
      const menu = applicationMenu(system, actions)
      expect(menu.map((item) => item.label)).toEqual(['Odin', 'Edit', 'View'])
      const odin = menu[0]!.submenu as Electron.MenuItemConstructorOptions[]
      expect(odin.map((item) => [item.label, item.accelerator, item.type]))
        .toEqual([['Close Window', 'Ctrl+W', undefined], [undefined, undefined, 'separator'], ['Exit Odin', 'Ctrl+Q', undefined]])
    }
  })

  it('gives macOS its app menu, Quit ⌘Q through Exit, and a Window menu', () => {
    const actions = { closeWindow: vi.fn(), exit: vi.fn() }
    const menu = applicationMenu('darwin', actions)
    expect(menu.map((item) => item.label)).toEqual(['Odin', 'Edit', 'View', 'Window'])
    const odin = menu[0]!.submenu as Electron.MenuItemConstructorOptions[]
    expect(odin.map((item) => item.role ?? item.label ?? item.type))
      .toEqual(['about', 'separator', 'hide', 'hideOthers', 'unhide', 'separator', 'Quit Odin'])
    const quit = odin.at(-1)!
    expect(quit.accelerator).toBe('Cmd+Q')
    ;(quit.click as () => void)()
    expect(actions.exit).toHaveBeenCalledOnce()
    const window = menu[3]!.submenu as Electron.MenuItemConstructorOptions[]
    const close = window.at(-1)!
    expect([close.label, close.accelerator]).toEqual(['Close Window', 'Cmd+W'])
    ;(close.click as () => void)()
    expect(actions.closeWindow).toHaveBeenCalledOnce()
    expect(menu[1]).toEqual(applicationMenu('linux', actions)[1])
  })

  it('reads Ctrl+Q as Exit elsewhere and ⌘Q on macOS, never the other', () => {
    const key = (overrides: Partial<KeyInput>): KeyInput =>
      ({ type: 'keyDown', key: 'q', control: false, alt: false, meta: false, ...overrides })
    expect(isExitShortcut(key({ control: true }), 'linux')).toBe(true)
    expect(isExitShortcut(key({ control: true, key: 'Q' }), 'win32')).toBe(true)
    expect(isExitShortcut(key({ meta: true }), 'linux')).toBe(false)
    expect(isExitShortcut(key({ meta: true }), 'darwin')).toBe(true)
    expect(isExitShortcut(key({ control: true }), 'darwin')).toBe(false)
    expect(isExitShortcut(key({ meta: true, control: true }), 'darwin')).toBe(false)
    expect(isExitShortcut(key({ meta: true, alt: true }), 'darwin')).toBe(false)
    expect(isExitShortcut(key({ meta: true, type: 'keyUp' }), 'darwin')).toBe(false)
    expect(isExitShortcut(key({ meta: true, key: 'w' }), 'darwin')).toBe(false)
  })
})
