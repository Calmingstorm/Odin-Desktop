// The app on Windows from source (phase 3d). Logic runs on any system: Windows paths through path.win32 and the
// shared vectors, Windows-only branches through their injected system. The profile, token and display-profile
// rules use real folders here; on Windows CI the same tests touch real NTFS.
import { execFileSync } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { lstatSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { crc32, deflateSync } from 'node:zlib'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('electron', () => ({ app: new EventEmitter(), BrowserWindow: { getAllWindows: () => [] } }))

import { safeFileName } from '../src/main/artifacts'
import { acquirePackagedApp, admitPackagedApp } from '../src/main/package-ownership'
import { inspectPackagedState } from '../src/main/package-state'
import { coreCommand, packagedCoreCommand, WINDOWS_SOURCE_CORE_REQUIRED } from '../src/main/core-command'
import { DisplayProfileStore } from '../src/main/display-profile'
import { configureIdentity } from '../src/main/identity'
import type { ProfilePaths } from '../src/main/paths'
import { currentPlatform } from '../src/main/platform'
import { AUTOSTART_UNAVAILABLE, windowsPlatform, windowsSessionMonitor } from '../src/main/platform/windows'
import { setWindowsAutostart, windowsAutostartEnabled } from '../src/main/platform/windows-autostart'
import { ELEVATED_REFUSAL, elevatedStartRefusal, integrityLevel, UNCHECKED_REFUSAL }
  from '../src/main/platform/windows-elevation'
import { ensureWindowsProfileDirs, ensureWindowsToken, localAppData, parseWhoamiUser, pipeName,
  windowsProfilePaths } from '../src/main/platform/windows-paths'
import { CleanupJournal, type JournalFs } from '../src/main/shutdown'
import { detectTray } from '../src/main/tray'
import { honorsPosition, restoreWindowState, windowBackend, type WindowState } from '../src/main/window-state'

const VECTORS = JSON.parse(readFileSync(join(__dirname, '..', '..', 'tests', 'fixtures', 'windows-profile-vectors.json'),
  'utf8')) as {
  pipes: Array<{ profile: string; sid: string; name: string }>
  layouts: Array<Record<'localappdata' | 'profile' | 'config' | 'data' | 'cache' | 'token' | 'app_state' | 'logs', string>>
  refused_by_both: { localappdata: string[]; profile: string[] }
  refused_by_the_app_only: { localappdata: string[]; profile: string[] }
}
const SID = 'S-1-5-21-1004336348-1177238915-682003330-1001'
const dirs: string[] = []
afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true }) })

function root(): string {
  const dir = mkdtempSync(join(tmpdir(), 'odin-windows-'))
  dirs.push(dir)
  return dir
}

/** A real profile tree in this system's own path syntax, shaped as Windows lays it out. */
function profileAt(base: string): ProfilePaths {
  const top = join(base, 'odin-desktop', 'default')
  const config = join(top, 'config'), data = join(top, 'data'), cache = join(top, 'cache')
  return { profileId: 'default', configDir: config, dataDir: data, cacheDir: cache, runtimeDir: cache,
    socketPath: pipeName('default', SID), tokenPath: join(config, 'ipc.token'), appStatePath: join(config, 'app-state.json'),
    logDir: join(data, 'logs') }
}

/** A folder link: a junction on Windows (no privilege needed), a symlink elsewhere. */
function linkFolder(target: string, path: string): void {
  symlinkSync(target, path, process.platform === 'win32' ? 'junction' : 'dir')
}

describe('the Windows profile, against the engine\'s vectors', () => {
  it.each(VECTORS.pipes)('names the pipe as the engine does ($profile)', ({ profile, sid, name }) => {
    expect(pipeName(profile, sid)).toBe(name)
  })

  it.each(VECTORS.layouts)('lays the profile out as the engine does ($localappdata)', (layout) => {
    const paths = windowsProfilePaths(layout.profile, { LOCALAPPDATA: layout.localappdata }, () => SID)
    expect([paths.configDir, paths.dataDir, paths.cacheDir, paths.tokenPath, paths.appStatePath, paths.logDir])
      .toEqual([layout.config, layout.data, layout.cache, layout.token, layout.app_state, layout.logs])
    expect(paths.runtimeDir).toBe(paths.cacheDir)
    expect(paths.socketPath).toBe(pipeName(layout.profile, SID))
  })

  it('refuses what the engine refuses, and the app\'s narrower subset too', () => {
    const refused = [...VECTORS.refused_by_both.localappdata, ...VECTORS.refused_by_the_app_only.localappdata]
    for (const base of refused) expect(() => localAppData({ LOCALAPPDATA: base })).toThrow('LOCALAPPDATA must be set')
    expect(() => localAppData({})).toThrow('LOCALAPPDATA must be set')
    for (const profile of [...VECTORS.refused_by_both.profile, ...VECTORS.refused_by_the_app_only.profile]) {
      expect(() => windowsProfilePaths(profile, { LOCALAPPDATA: 'C:\\Users\\x\\AppData\\Local' }, () => SID))
        .toThrow('invalid profile id')
    }
  })
})

describe('the user SID from whoami', () => {
  it('reads the second CSV field, whatever the localized account name holds', () => {
    expect(parseWhoamiUser(`"LEGION\\Atcha","${SID}"\r\n`)).toBe(SID)
    expect(parseWhoamiUser(`"Dom,Ain\\Zoë ""Z""","${SID}"`)).toBe(SID)
  })

  it.each([
    ['nothing', ''],
    ['two records', `"a","${SID}"\n"b","${SID}"`],
    ['no SID', '"a","not-a-sid"'],
    ['one field', `"${SID}"`],
    ['three fields', `"a","${SID}","c"`],
    ['an unclosed quote', `"a,"${SID}`],
    ['a SID with junk', `"a","${SID}x"`]
  ])('refuses %s', (_name, output) => {
    expect(() => parseWhoamiUser(output)).toThrow('whoami gave an unexpected answer.')
  })

  it.runIf(process.platform === 'win32')('names the pipe the real engine serves, from the real whoami', async () => {
    const python = process.env.ODIN_ENGINE_PYTHON
    if (!python) throw new Error('Set ODIN_ENGINE_PYTHON to the checkout\'s engine interpreter for this Windows test.')
    vi.resetModules()
    const { userSid } = await import('../src/main/platform/windows-paths')
    const sid = userSid()
    expect(sid).toMatch(/^S-1-5-21-\d+-\d+-\d+-\d+$/)
    const engine = execFileSync(python, ['-I', '-B', '-c',
      'from src.desktop.platform.windows_ipc import pipe_name; print(pipe_name("default"))'], { encoding: 'utf8' }).trim()
    expect(pipeName('default', sid)).toBe(engine)
  })

  it('asks whoami once per process', async () => {
    vi.resetModules()
    const { userSid } = await import('../src/main/platform/windows-paths')
    const run = vi.fn(() => `"a","${SID}"`)
    expect([userSid(run), userSid(run)]).toEqual([SID, SID])
    expect(run).toHaveBeenCalledTimes(1)
  })
})

describe('creating the profile plainly', () => {
  it('makes the folders and a token of exactly 64 hex bytes, then reuses only such a token', () => {
    const paths = profileAt(root())
    ensureWindowsProfileDirs(paths)
    for (const dir of [paths.configDir, paths.dataDir, paths.cacheDir, paths.logDir]) expect(lstatSync(dir).isDirectory()).toBe(true)
    const token = ensureWindowsToken(paths)
    expect(token).toMatch(/^[0-9a-f]{64}$/)
    expect(readFileSync(paths.tokenPath, 'latin1')).toBe(token)
    expect(ensureWindowsToken(paths)).toBe(token)
    for (const damaged of [`${token}\n`, token.toUpperCase(), 'short', '']) {
      writeFileSync(paths.tokenPath, damaged)
      const replaced = ensureWindowsToken(paths)
      expect(replaced).toMatch(/^[0-9a-f]{64}$/)
      expect(readFileSync(paths.tokenPath, 'latin1')).toBe(replaced) // the engine reads exactly these bytes
    }
  })

  it('refuses a linked profile folder before writing anything into it', () => {
    const base = root()
    const elsewhere = join(base, 'elsewhere')
    mkdirSync(elsewhere)
    const paths = profileAt(base)
    mkdirSync(join(base, 'odin-desktop', 'default'), { recursive: true })
    linkFolder(elsewhere, paths.configDir)
    expect(() => ensureWindowsProfileDirs(paths)).toThrow('A link in Odin\'s profile is refused')
    expect(() => ensureWindowsToken(paths)).toThrow('A link in Odin\'s profile is refused')
    expect(readdirSync(elsewhere)).toEqual([])
  })

  it('refuses a linked token file', () => {
    const base = root()
    const paths = profileAt(base)
    ensureWindowsProfileDirs(paths)
    const outside = join(base, 'outside.token')
    writeFileSync(outside, 'a'.repeat(64))
    try {
      symlinkSync(outside, paths.tokenPath, 'file')
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'EPERM') return // a file symlink needs privilege on Windows
      throw error
    }
    expect(() => ensureWindowsToken(paths)).toThrow('A link in Odin\'s profile is refused')
    expect(readFileSync(outside, 'latin1')).toBe('a'.repeat(64))
  })
})

describe('session end', () => {
  class FakeWindow extends EventEmitter {
    destroyed = false
    isDestroyed(): boolean { return this.destroyed }
  }

  it('reaches Exit once from any window, forgets closed windows, and stops on close', () => {
    const existing = new FakeWindow()
    const fakeApp = new EventEmitter()
    const onEnd = vi.fn()
    const electron = { app: fakeApp, BrowserWindow: { getAllWindows: () => [existing] } }
    const monitor = windowsSessionMonitor({ command: 'core', args: [], env: {} }, onEnd, electron as never)
    const created = new FakeWindow()
    fakeApp.emit('browser-window-created', {}, created)
    fakeApp.emit('browser-window-created', {}, created) // subscribed once
    expect(created.listenerCount('session-end')).toBe(1)
    existing.emit('session-end')
    created.emit('session-end')
    expect(onEnd).toHaveBeenCalledTimes(1)
    existing.emit('closed')
    expect(existing.listenerCount('session-end')).toBe(0)
    monitor.close()
    expect(created.listenerCount('session-end')).toBe(0)
    expect(fakeApp.listenerCount('browser-window-created')).toBe(0)
    const later = new FakeWindow()
    fakeApp.emit('browser-window-created', {}, later)
    expect(later.listenerCount('session-end')).toBe(0)
  })

  it('skips a window already destroyed', () => {
    const gone = Object.assign(new FakeWindow(), { destroyed: true })
    const electron = { app: new EventEmitter(), BrowserWindow: { getAllWindows: () => [gone] } }
    windowsSessionMonitor({ command: 'core', args: [], env: {} }, vi.fn(), electron as never)
    expect(gone.listenerCount('session-end')).toBe(0)
  })
})

describe('the Windows platform from source', () => {
  it('is chosen on win32; from source it has no start at login, and the package members are the shared ones', () => {
    expect(currentPlatform('win32')).toBe(windowsPlatform)
    expect(windowsPlatform.name).toBe('windows')
    // This test's Electron app isn't packaged: a source run.
    expect(windowsPlatform.isAutostartEnabled()).toBe(false)
    expect(() => windowsPlatform.setAutostart(true, ['odin'])).toThrow(AUTOSTART_UNAVAILABLE)
    expect(windowsPlatform.autostartUnavailable).toBe(AUTOSTART_UNAVAILABLE)
    // The Linux modules pick Windows' interpreter and the nsis lease by the system they run on.
    expect(windowsPlatform.inspectPackagedState).toBe(inspectPackagedState)
    expect(windowsPlatform.acquirePackagedApp).toBe(acquirePackagedApp)
    expect(windowsPlatform.admitPackagedApp).toBe(admitPackagedApp)
    expect(windowsPlatform.installLogoutHook(['odin'])).toBeNull()
    expect(windowsPlatform.startSessionMonitor({ command: 'core', args: [], env: {} }, vi.fn())).not.toBeNull()
  })

  it('never falls back to the Linux fixture: a source run names its engine', () => {
    const paths = profileAt(root())
    const context = { packaged: false, resourcesPath: 'resources', appPath: 'app', system: 'win32' as const }
    expect(() => coreCommand(paths, { ...context, env: {} })).toThrow(WINDOWS_SOURCE_CORE_REQUIRED)
    const named = coreCommand(paths, { ...context,
      env: { ODIN_DESKTOP_CORE_CMD: '["C:\\\\checkout\\\\.venv\\\\Scripts\\\\python.exe","-I","-B","-m","src"]' } })
    expect(named.command).toBe('C:\\checkout\\.venv\\Scripts\\python.exe')
    expect(named.args.slice(0, 6)).toEqual(['-I', '-B', '-m', 'src', '--socket', paths.socketPath])
  })

  it('keeps the Chromium profile in local AppData and gives notifications an app ID', () => {
    const app = { setName: vi.fn(), getPath: vi.fn(), setPath: vi.fn(), setAppUserModelId: vi.fn() }
    const makeDir = vi.fn()
    configureIdentity(app, 'win32', { LOCALAPPDATA: 'C:\\Users\\x\\AppData\\Local' }, makeDir)
    const chromium = 'C:\\Users\\x\\AppData\\Local\\odin-desktop\\electron'
    expect(makeDir).toHaveBeenCalledExactlyOnceWith(chromium, { recursive: true })
    expect(app.setPath).toHaveBeenCalledExactlyOnceWith('userData', chromium)
    expect(app.setAppUserModelId).toHaveBeenCalledExactlyOnceWith(process.execPath)
    expect(app.getPath).not.toHaveBeenCalled()
    expect(() => configureIdentity(app, 'win32', {}, makeDir)).toThrow('LOCALAPPDATA must be set')
  })

  it('takes the tray as available, and restores window positions', async () => {
    await expect(detectTray({}, 'win32')).resolves.toBe(true)
    expect(windowBackend('win32', '')).toBe('win32')
    expect([honorsPosition('win32'), honorsPosition('x11'), honorsPosition('wayland'), honorsPosition('unknown')])
      .toEqual([true, true, false, false])
    const state: WindowState = { version: 1, normalBounds: { x: 50, y: 60, width: 900, height: 600 }, maximized: false }
    const primary = { id: 1, workArea: { x: 0, y: 30, width: 1280, height: 770 }, scaleFactor: 1.5 }
    expect(restoreWindowState(state, [primary], 1, 'win32').options)
      .toEqual(restoreWindowState(state, [primary], 1, 'x11').options)
  })
})

describe('artifact names on Windows', () => {
  it.each([
    ['a:b<c>|d?.txt', 'a_b_c__d_.txt'],
    ['report*"final".pdf', 'report__final_.pdf'],
    ['CON', '_CON'],
    ['con.txt', '_con.txt'],
    ['nul .log', '_nul .log'],
    ['LPT\u00b9.log', '_LPT\u00b9.log'],
    ['COM0', '_COM0'],
    ['conin$', '_conin$'],
    ['console.txt', 'console.txt'],
    ['notes. . ', 'notes'],
    ['...', 'file']
  ])('%j becomes %j', (name, safe) => {
    expect(safeFileName(name, 'win32')).toBe(safe)
  })

  it('leaves Linux names as they were', () => {
    expect(safeFileName('a:b<c>|d?.txt', 'linux')).toBe('a:b<c>|d?.txt')
    expect(safeFileName('CON', 'linux')).toBe('CON')
  })
})

describe('display profile on Windows', () => {
  function png(): Buffer {
    const chunk = (type: string, data: Buffer): Buffer => {
      const length = Buffer.alloc(4)
      length.writeUInt32BE(data.length)
      const body = Buffer.concat([Buffer.from(type, 'latin1'), data])
      const crc = Buffer.alloc(4)
      crc.writeUInt32BE(crc32(body))
      return Buffer.concat([length, body, crc])
    }
    const header = Buffer.alloc(13)
    header.writeUInt32BE(256, 0)
    header.writeUInt32BE(256, 4)
    Object.assign(header, { 8: 8, 9: 6, 12: 0 })
    const pixels = Buffer.alloc((1 + 256 * 4) * 256)
    return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', header),
      chunk('IDAT', deflateSync(pixels)), chunk('IEND', Buffer.alloc(0))])
  }

  it('sets, reads and removes a name and a picture in a real folder', () => {
    const store = new DisplayProfileStore(join(root(), 'display-profile'), 'win32')
    expect(store.setName('Ada').name).toBe('Ada')
    const picture = store.setPicture({ target: 'user' }, png().toString('base64'))
    expect(picture.user).not.toBeNull()
    expect(store.removePicture({ target: 'user' }).user).toBeNull()
    expect(store.read().name).toBe('Ada')
  })

  it('refuses a linked folder and a linked picture', () => {
    const base = root()
    const elsewhere = join(base, 'elsewhere')
    mkdirSync(elsewhere)
    const linkedDir = join(base, 'linked-profile')
    linkFolder(elsewhere, linkedDir)
    const linked = new DisplayProfileStore(linkedDir, 'win32')
    expect(() => linked.setName('Ada')).toThrow('not private')
    expect(linked.read()).toEqual({ name: '', user: null, personalities: [] })
    expect(readdirSync(elsewhere)).toEqual([])
    const store = new DisplayProfileStore(join(base, 'display-profile'), 'win32')
    store.setName('Ada')
    const outside = join(base, 'outside.png')
    writeFileSync(outside, png())
    try {
      symlinkSync(outside, join(base, 'display-profile', 'user.png'), 'file')
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'EPERM') return // a file symlink needs privilege on Windows
      throw error
    }
    expect(store.read().user).toBeNull()
  })
})

describe('the cleanup journal on Windows', () => {
  type Call = [string, ...unknown[]]
  function recording(fail?: string): { fs: JournalFs; calls: Call[] } {
    const calls: Call[] = []
    let next = 10
    const step = <T>(name: string, value: T) => (...args: unknown[]): T => {
      calls.push([name, ...args])
      if (name === fail) throw new Error(`${name} failed`)
      return value
    }
    const fs = {
      openSync: (path: string, flags: string) => { calls.push(['openSync', path, flags]); return next++ },
      writeFileSync: step('writeFileSync', undefined),
      fsyncSync: step('fsyncSync', undefined),
      closeSync: step('closeSync', undefined),
      renameSync: step('renameSync', undefined)
    } as unknown as JournalFs
    return { fs, calls }
  }

  it('flushes the file and renames it over the journal, with no folder flush', () => {
    const path = join(root(), 'cleanup.json')
    const { fs, calls } = recording()
    new CleanupJournal(path, { system: 'win32', fs }).begin()
    expect(calls.map(([name]) => name)).toEqual(['openSync', 'writeFileSync', 'fsyncSync', 'closeSync', 'renameSync'])
    expect(calls[0]).toEqual(['openSync', `${path}.pending`, 'w'])
    expect(calls[4]).toEqual(['renameSync', `${path}.pending`, path])
  })

  it.each(['writeFileSync', 'fsyncSync', 'renameSync'])('reports a failed %s, never swallowing it', (step) => {
    const path = join(root(), 'cleanup.json')
    const { fs, calls } = recording(step)
    expect(() => new CleanupJournal(path, { system: 'win32', fs }).begin()).toThrow(`${step} failed`)
    if (step !== 'renameSync') expect(calls.map(([name]) => name)).toContain('closeSync') // the handle is closed
  })

  it('keeps uncertainty across a restart through real files, without a folder flush', () => {
    const path = join(root(), 'cleanup.json')
    const first = new CleanupJournal(path, { system: 'win32' })
    first.begin()
    const restarted = new CleanupJournal(path, { system: 'win32' }) // the earlier lifetime never finished
    expect(restarted.warning?.state).toBe('unknown')
    restarted.begin()
    restarted.markUnknown('core cleanup unknown', 'core:1')
    restarted.finish({ version: 1, state: 'process-exited', at: new Date().toISOString(), reason: 'Exit' })
    const notice = restarted.notice!
    expect(restarted.acknowledge(notice.id)).toBe(true)
    const reread = new CleanupJournal(path, { system: 'win32' })
    expect(reread.notice).toBeNull()
    expect(reread.archived.map((row) => row.id)).toContain(notice.id)
  })
})

describe('an elevated start of the installed app', () => {
  // whoami /groups /fo csv /nh: each group's name, type, SID and attributes; the mandatory label is one row.
  const groups = (label: string): string => [
    '"Everyone","Well-known group","S-1-1-0","Mandatory group, Enabled by default, Enabled group"',
    '"BUILTIN\\Administrators","Alias","S-1-5-32-544","Group used for deny only"',
    `"Mandatory Label\\${label} Mandatory Level","Label","S-1-16-${{ Medium: 8192, High: 12288, System: 16384 }[label]}",""`
  ].join('\r\n')
  const answering = (stdout: string, status = 0) => vi.fn(() => ({ status, stdout }))
  const env = { SystemRoot: 'C:\\Windows' }

  it('reads the integrity level from whoami\'s mandatory label', () => {
    expect(integrityLevel(groups('Medium'))).toBe(8192)
    expect(integrityLevel(groups('High'))).toBe(12288)
    expect(integrityLevel('"Everyone","Well-known group","S-1-1-0",""')).toBeNull()
  })

  it('lets a normal token start, a filtered administrator\'s included, and refuses High or System', () => {
    const run = answering(groups('Medium'))
    expect(elevatedStartRefusal(env, run)).toBeNull()
    expect(run).toHaveBeenCalledWith('C:\\Windows\\System32\\whoami.exe', ['/groups', '/fo', 'csv', '/nh'],
      expect.objectContaining({ windowsHide: true, timeout: 5_000 }))
    expect(elevatedStartRefusal(env, answering(groups('High')))).toBe(ELEVATED_REFUSAL)
    expect(elevatedStartRefusal(env, answering(groups('System')))).toBe(ELEVATED_REFUSAL)
  })

  it('refuses when it can\'t tell, rather than starting on a guess', () => {
    expect(elevatedStartRefusal({}, answering(groups('Medium')))).toBe(UNCHECKED_REFUSAL)
    expect(elevatedStartRefusal(env, answering(groups('Medium'), 1))).toBe(UNCHECKED_REFUSAL)
    expect(elevatedStartRefusal(env, vi.fn(() => ({ status: null, error: new Error('timed out') })))).toBe(UNCHECKED_REFUSAL)
    expect(elevatedStartRefusal(env, answering('"Everyone","Well-known group","S-1-1-0",""'))).toBe(UNCHECKED_REFUSAL)
  })

  it('is the Windows platform\'s start refusal', () => {
    vi.stubEnv('SystemRoot', '')  // no whoami to ask, on any system: refused rather than guessed
    try {
      expect(windowsPlatform.startRefusal?.()).toBe(UNCHECKED_REFUSAL)
    } finally {
      vi.unstubAllEnvs()
    }
  })
})

describe('the installed app\'s runtime and start at login', () => {
  it('starts the bundled interpreter at the runtime\'s root and drops PYTHON variables whatever their case', () => {
    const exists = vi.fn(() => true)
    const launch = packagedCoreCommand('C:\\Programs\\Odin\\resources', ['--profile', 'default'],
      { PythonPath: 'C:\\elsewhere', PYTHONHOME: 'C:\\home', Path: 'C:\\Windows' }, { system: 'win32', exists })
    expect(launch.command).toBe('C:\\Programs\\Odin\\resources\\runtime\\python\\python.exe')
    expect(launch.args).toEqual(['-I', '-B', '-m', 'src', '--profile', 'default'])
    expect(launch.env).not.toHaveProperty('PythonPath')
    expect(launch.env).not.toHaveProperty('PYTHONHOME')
    expect(launch.env).toMatchObject({ Path: 'C:\\Windows',
      ODIN_DESKTOP_BUNDLE_ROOT: 'C:\\Programs\\Odin\\resources\\runtime',
      PLAYWRIGHT_BROWSERS_PATH: 'C:\\Programs\\Odin\\resources\\runtime\\browser' })
    expect(exists).toHaveBeenCalledWith('C:\\Programs\\Odin\\resources\\bundle-manifest.json')
    expect(() => packagedCoreCommand('C:\\Programs\\Odin\\resources', [], {}, { system: 'win32', exists: () => false }))
      .toThrow('bundled runtime is missing')
  })

  const items = (settings: { openAtLogin: boolean; executableWillLaunchAtLogin: boolean }, isPackaged = true) => ({
    isPackaged, execPath: 'C:\\Programs\\Odin\\Odin.exe',
    getLoginItemSettings: vi.fn(() => settings), setLoginItemSettings: vi.fn()
  }) as unknown as Parameters<typeof windowsAutostartEnabled>[2]

  it('reads on only for this exact entry, registered and not disabled', () => {
    const on = items({ openAtLogin: true, executableWillLaunchAtLogin: true })
    expect(windowsAutostartEnabled(undefined, undefined, on)).toBe(true)
    expect((on as any).getLoginItemSettings).toHaveBeenCalledWith({ path: 'C:\\Programs\\Odin\\Odin.exe', args: ['--hidden'] })
    // Disabled from Task Manager's Startup page, or registered with other arguments.
    expect(windowsAutostartEnabled(undefined, undefined, items({ openAtLogin: true, executableWillLaunchAtLogin: false }))).toBe(false)
    expect(windowsAutostartEnabled(undefined, undefined, items({ openAtLogin: false, executableWillLaunchAtLogin: true }))).toBe(false)
    expect(windowsAutostartEnabled(undefined, undefined, items({ openAtLogin: true, executableWillLaunchAtLogin: true }, false))).toBe(false)
  })

  it('registers and approves, or removes, the installed executable with --hidden, and refuses from source', () => {
    const fake = items({ openAtLogin: true, executableWillLaunchAtLogin: true })
    expect(setWindowsAutostart(true, ['ignored'], undefined, fake)).toBe(true)
    expect((fake as any).setLoginItemSettings).toHaveBeenCalledWith({ openAtLogin: true, enabled: true,
      path: 'C:\\Programs\\Odin\\Odin.exe', args: ['--hidden'] })
    setWindowsAutostart(false, [], undefined, fake)
    expect((fake as any).setLoginItemSettings).toHaveBeenLastCalledWith({ openAtLogin: false, enabled: false,
      path: 'C:\\Programs\\Odin\\Odin.exe', args: ['--hidden'] })
    expect(() => setWindowsAutostart(true, [], undefined, items({ openAtLogin: false, executableWillLaunchAtLogin: false }, false)))
      .toThrow(AUTOSTART_UNAVAILABLE)
  })
})
