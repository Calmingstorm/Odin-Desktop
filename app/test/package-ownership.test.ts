import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { acquirePackagedApp, admitPackagedApp, hasLine, INSTALL_UNFINISHED, MAC_START_REFUSALS, PENDING_EXIT,
  StartRefused } from '../src/main/package-ownership'

const mocked = vi.hoisted(() => ({ spawn: vi.fn(), read: vi.fn(), exists: vi.fn(() => true) }))
vi.mock('node:child_process', () => ({ spawn: mocked.spawn }))
vi.mock('node:fs', () => ({ readFileSync: mocked.read, existsSync: mocked.exists }))

const paths = { profileId: 'other', configDir: '/temporary/config/other',
  dataDir: '/temporary/data/other' } as Parameters<typeof acquirePackagedApp>[0]

function child() {
  return Object.assign(new EventEmitter(), {
    stdin: new PassThrough(), stdout: new PassThrough(), stderr: new PassThrough()
  })
}

describe('independent packaged app lifetime', () => {
  beforeEach(() => { mocked.spawn.mockReset(); mocked.read.mockReturnValue('deb\n') })

  it('holds the per-user nsis lease through the Windows runtime, without a console window', async () => {
    const process = child()
    mocked.spawn.mockReturnValue(process)
    const windowsPaths = { profileId: 'default', configDir: 'C:\\Users\\Ada\\AppData\\Local\\odin-desktop\\default\\config',
      dataDir: 'C:\\Users\\Ada\\AppData\\Local\\odin-desktop\\default\\data' } as Parameters<typeof acquirePackagedApp>[0]
    const pending = acquirePackagedApp(windowsPaths, 'C:\\Programs\\Odin\\resources', {}, 'win32')
    process.stdout.write('READY\n')
    expect(await pending).toBe(process)
    const [command, args, options] = mocked.spawn.mock.calls[0]!
    expect(command).toBe('C:\\Programs\\Odin\\resources\\runtime\\python\\python.exe')
    expect(args).toEqual([
      '-I', '-B', 'C:\\Programs\\Odin\\resources\\ownership.py', '--kind', 'nsis', '--role', 'app',
      '--app-cleanup', 'C:\\Users\\Ada\\AppData\\Local\\odin-desktop\\default\\default-cleanup-state.json',
      '--core-cleanup', 'C:\\Users\\Ada\\AppData\\Local\\odin-desktop\\default\\data\\resource-cleanup.json', 'hold'
    ])
    // Detached: otherwise Windows ends the guardian with the app, before it records the clean Exit.
    expect(options).toMatchObject({ windowsHide: true, detached: true })
    process.stdin.end()
  })

  it('holds the per-user macos lease through the Mac runtime, as a plain child', async () => {
    const process = child()
    mocked.spawn.mockReturnValue(process)
    const macPaths = { profileId: 'default', configDir: '/Users/ada/Library/odin-desktop/default/config',
      dataDir: '/Users/ada/Library/odin-desktop/default/data' } as Parameters<typeof acquirePackagedApp>[0]
    const resources = '/Applications/Odin.app/Contents/Resources'
    const pending = acquirePackagedApp(macPaths, resources, {}, 'darwin')
    process.stdout.write('READY\n')
    expect(await pending).toBe(process)
    const [command, args, options] = mocked.spawn.mock.calls[0]!
    expect(command).toBe(`${resources}/runtime/python/bin/python3`)
    expect(args).toEqual([
      '-I', '-B', `${resources}/ownership.py`, '--kind', 'macos', '--role', 'app',
      '--app-cleanup', '/Users/ada/Library/odin-desktop/default/default-cleanup-state.json',
      '--core-cleanup', '/Users/ada/Library/odin-desktop/default/data/resource-cleanup.json', 'hold'
    ])
    expect(options).not.toHaveProperty('detached')
    process.stdin.end()
  })

  it('keeps the Linux guardian a plain child, as before', async () => {
    const process = child()
    mocked.spawn.mockReturnValue(process)
    const pending = acquirePackagedApp(paths, '/candidate/resources', {}, 'linux')
    process.stdout.write('READY\n')
    expect(await pending).toBe(process)
    const options = mocked.spawn.mock.calls[0]![2]
    expect(options).not.toHaveProperty('detached')
    expect(options).not.toHaveProperty('windowsHide')
    process.stdin.end()
  })

  it('reads the guardian\'s lines whether they end in LF or CRLF, even split across chunks', async () => {
    expect(hasLine('READY\n', 'READY')).toBe(true)
    expect(hasLine('READY\r\n', 'READY')).toBe(true)
    expect(hasLine('noise\r\nADMITTED\r\n', 'ADMITTED')).toBe(true)
    expect(hasLine('NOT-READY\n', 'READY')).toBe(false)
    expect(hasLine('READY', 'READY')).toBe(false)
    const process = child()
    mocked.spawn.mockReturnValue(process)
    const pending = acquirePackagedApp(paths, '/candidate/resources', {})
    process.stdout.write('REA')
    process.stdout.write('DY\r')
    process.stdout.write('\n')
    expect(await pending).toBe(process)
    const admitted = admitPackagedApp(process as never)
    process.stdout.write('ADMITTED\r\n')
    await expect(admitted).resolves.toBeUndefined()
    process.stdin.end()
  })

  it('does not admit app startup until guardian confirms durable lifetime', async () => {
    const process = child()
    mocked.spawn.mockReturnValue(process)
    const pending = acquirePackagedApp(paths, '/candidate/resources', {})
    let admitted = false
    void pending.then(() => { admitted = true })
    await Promise.resolve()
    expect(admitted).toBe(false)
    process.stdout.write('READY\n')
    expect(await pending).toBe(process)
    expect(mocked.spawn.mock.calls[0]![1]).toEqual([
      '-I', '-B', '/candidate/resources/ownership.py', '--kind', 'appimage', '--role', 'app',
      '--app-cleanup', '/temporary/config/other-cleanup-state.json',
      '--core-cleanup', '/temporary/data/other/resource-cleanup.json', 'hold'
    ])
    expect(process.stdin.writableEnded).toBe(false)
    process.stdin.end()
  })

  it('managed deb root cannot be redirected by environment kind', async () => {
    const process = child()
    mocked.spawn.mockReturnValue(process)
    const pending = acquirePackagedApp(paths, '/opt/odin-desktop/resources', {
      ODIN_DESKTOP_OWNERSHIP_KIND: 'appimage'
    })
    process.stdout.write('READY\n')
    await pending
    expect(mocked.spawn.mock.calls[0]![1]).toContain('deb')
    process.stdin.end()
  })

  it.each(['/opt/Odin/resources', '/opt/odin/resources', '/opt/odin-desktop-copy/resources',
    '/tmp/.mount_odin-desktop/resources'])('does not classify %s as the managed deb root', async (resources) => {
    const process = child()
    mocked.spawn.mockReturnValue(process)
    const pending = acquirePackagedApp(paths, resources, { ODIN_DESKTOP_OWNERSHIP_KIND: 'deb' })
    process.stdout.write('READY\n')
    await pending
    const args = mocked.spawn.mock.calls[0]![1] as string[]
    expect(args[args.indexOf('--kind') + 1]).toBe('appimage')
    process.stdin.end()
  })

  it('names the remedy on Windows when an unfinished installer run fences the start', async () => {
    const windowsPaths = { profileId: 'default', configDir: 'C:\\Users\\Ada\\AppData\\Local\\odin-desktop\\default\\config',
      dataDir: 'C:\\Users\\Ada\\AppData\\Local\\odin-desktop\\default\\data' } as Parameters<typeof acquirePackagedApp>[0]
    for (const [system, code, message] of [['win32', PENDING_EXIT, INSTALL_UNFINISHED],
      ['win32', 1, 'ownership is unavailable'], ['linux', PENDING_EXIT, 'ownership is unavailable']] as const) {
      const process = child()
      mocked.spawn.mockReturnValue(process)
      const pending = acquirePackagedApp(system === 'win32' ? windowsPaths : paths,
        system === 'win32' ? 'C:\\Programs\\Odin\\resources' : '/candidate/resources', {}, system)
      process.emit('exit', code)
      await expect(pending).rejects.toThrow(message)
    }
  })

  it('words each refusal of the Mac start check with its remedy, and nothing else as one', async () => {
    const macPaths = { profileId: 'default', configDir: '/Users/ada/Library/odin-desktop/default/config',
      dataDir: '/Users/ada/Library/odin-desktop/default/data' } as Parameters<typeof acquirePackagedApp>[0]
    const resources = '/Applications/Odin.app/Contents/Resources'
    const remedies = { 80: 'Reinstall Odin from its disk image', 81: 'Wait a minute, then open Odin again',
      82: 'Restart the Mac, then open Odin', 83: 'remove the folder ~/Library/odin-desktop/.install-ownership' }
    expect(Object.keys(MAC_START_REFUSALS).map(Number)).toEqual([80, 81, 82, 83])
    for (const [code, remedy] of Object.entries(remedies)) {
      const process = child()
      mocked.spawn.mockReturnValue(process)
      const pending = acquirePackagedApp(macPaths, resources, {}, 'darwin')
      process.emit('exit', Number(code))
      const error = await pending.catch((caught: unknown) => caught)
      expect(error).toBeInstanceOf(StartRefused)
      expect((error as Error).message).toContain(remedy)
      expect((error as Error).message).toMatch(/Nothing was changed\.$/)
    }
    for (const [system, code] of [['darwin', 1], ['darwin', PENDING_EXIT], ['linux', 80], ['win32', 82]] as const) {
      const process = child()
      mocked.spawn.mockReturnValue(process)
      const pending = acquirePackagedApp(system === 'darwin' ? macPaths : paths, resources, {}, system)
      process.emit('exit', code)
      const error = await pending.catch((caught: unknown) => caught)
      expect(error).not.toBeInstanceOf(StartRefused)
      expect((error as Error).message).toContain('ownership is unavailable')
    }
  })

  it('gives the Mac\'s first full check a minute before READY, and others 15 seconds', async () => {
    vi.useFakeTimers()
    try {
      for (const [system, wait] of [['darwin', 60_000], ['linux', 15_000]] as const) {
        const process = child()
        mocked.spawn.mockReturnValue(process)
        const pending = acquirePackagedApp(paths, '/candidate/resources', {}, system)
        const settled = vi.fn()
        pending.then(settled, settled)
        await vi.advanceTimersByTimeAsync(wait - 1)
        expect(settled).not.toHaveBeenCalled()
        await vi.advanceTimersByTimeAsync(1)
        expect(settled).toHaveBeenCalledOnce()
      }
    } finally {
      vi.useRealTimers()
    }
  })

  it('guardian loss before readiness is not admission', async () => {
    const process = child()
    mocked.spawn.mockReturnValue(process)
    const pending = acquirePackagedApp(paths, '/candidate/resources', {})
    process.emit('exit', 1)
    await expect(pending).rejects.toThrow('ownership is unavailable')
    expect(process.stdin.writableEnded).toBe(true)
  })

  it('read-only readiness does not write ADMIT until compatibility succeeds', async () => {
    const process = child()
    mocked.spawn.mockReturnValue(process)
    const pending = acquirePackagedApp(paths, '/candidate/resources', {})
    process.stdout.write('READY\n')
    await pending
    expect(process.stdin.read()).toBeNull()
    const admitted = admitPackagedApp(process as never)
    expect(String(process.stdin.read())).toBe('ADMIT\n')
    process.stdout.write('ADMITTED\n')
    await admitted
    process.stdin.end()
  })
})
