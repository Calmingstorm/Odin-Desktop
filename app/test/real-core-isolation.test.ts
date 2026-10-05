// Every process, proc read, timeout and signal here is fake. These tests never launch sudo or a real namespace.
import { EventEmitter } from 'node:events'
import { join } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { createIsolationLauncher } from '../scripts/real-core-isolation.mjs'

const script = join(import.meta.dirname, '../scripts/real-core-isolation.mjs')
const root = '/tmp/odrc-fake'

function fixture(results: Array<number | Error | 'pending'> = [0, 0, 0]) {
  const host = Object.assign(new EventEmitter(), {
    platform: 'linux', getuid: () => 1001, geteuid: () => 1001, getgid: () => 1002, getegid: () => 1002,
    pid: 1, execPath: '/usr/bin/node', argv: ['/usr/bin/node', script, '--inside-run'],
    env: {
      HOME: root, ODIN_REAL_CORE_ROOT: root, ODIN_REAL_CORE_UID: '1001', ODIN_REAL_CORE_GID: '1002',
      ODIN_REAL_CORE_OUTER_PID_NS: 'pid:[outer]', XDG_CONFIG_HOME: `${root}/config`,
      XDG_DATA_HOME: `${root}/data`, XDG_CACHE_HOME: `${root}/cache`, XDG_RUNTIME_DIR: `${root}/run`,
      RUNNER_TRACKING_ID: 'runner-cleanup-tag', DISPLAY: ':0', SECRET_TOKEN: 'never-inherit'
    } as Record<string, string>,
    kill: vi.fn()
  })
  const files = {
    existsSync: vi.fn(() => true), mkdtempSync: vi.fn(() => root), chmodSync: vi.fn(), mkdirSync: vi.fn(), rmSync: vi.fn(),
    readlinkSync: vi.fn(() => 'pid:[private]'),
    readFileSync: vi.fn((path: string) => path === '/proc/1/cmdline'
      ? host.argv.join('\0') + '\0'
      : 'CapEff:\t0000000000000000\nCapBnd:\t0000000000000000\nNoNewPrivs:\t1\nGroups:\t\n'),
    lstatSync: vi.fn(() => ({ isDirectory: () => true, uid: 1001, gid: 1002, mode: 0o40700 }))
  }
  const children: Array<EventEmitter & { pid?: number; stdout: EventEmitter; stderr: EventEmitter }> = []
  const spawnChild = vi.fn(() => {
    const outcome = results[children.length] ?? 0
    const child = Object.assign(new EventEmitter(), {
      pid: outcome instanceof Error ? undefined : 31000 + children.length,
      stdout: new EventEmitter(), stderr: new EventEmitter()
    })
    children.push(child)
    if (outcome !== 'pending') queueMicrotask(() => {
      if (outcome instanceof Error) child.emit('error', outcome)
      else child.emit('exit', outcome, null)
    })
    return child
  })
  const timers = new Map<object, () => void>()
  const schedule = vi.fn((fn: () => void) => { const handle = {}; timers.set(handle, fn); return handle })
  const unschedule = vi.fn((handle: object) => timers.delete(handle))
  const launcher = createIsolationLauncher({ process: host, files, spawnChild, temporaryDirectory: () => '/tmp', schedule, unschedule })
  return { ...launcher, host, files, spawnChild, children, timers }
}

async function flush() { for (let i = 0; i < 12; i++) await Promise.resolve() }

function calls(f: ReturnType<typeof fixture>): Array<[string, string[], Record<string, unknown>]> {
  return f.spawnChild.mock.calls as unknown as Array<[string, string[], Record<string, unknown>]>
}

describe('real-core isolation launcher with fake child_process only', () => {
  it('permission-checks and probes the helper first, then starts once without nested sudo or setpriv', async () => {
    const f = fixture()
    await f.launchIsolated('vitest', ['run'])
    expect(calls(f)).toHaveLength(3)
    expect(calls(f)[0].slice(0, 2)).toEqual(['sudo', ['-n', '-l', '/usr/local/sbin/odin-desktop-isolate']])
    for (const [, args, options] of calls(f).slice(1)) {
      expect(args.slice(0, 4)).toEqual(['-n', '/usr/local/sbin/odin-desktop-isolate', 'env', '-i'])
      expect(args).not.toContain('setpriv')
      expect(args).not.toContain('sudo')
      expect(args).not.toContain('--user')
      expect(options.detached).toBe(true)
      expect(options.env).toEqual({ PATH: '/usr/local/bin:/usr/bin:/bin', LANG: 'C.UTF-8' })
      expect(args).toContain('RUNNER_TRACKING_ID=runner-cleanup-tag')
      expect(args).toContain('ODIN_REAL_CORE_UID=1001')
      expect(args).toContain('ODIN_REAL_CORE_GID=1002')
      expect(args).toContain(`HOME=${root}`)
      expect(args.join(' ')).not.toMatch(/DISPLAY=|SECRET_TOKEN=|never-inherit/)
    }
    expect(calls(f)[1][1].at(-1)).toBe('--inside-probe')
    expect(calls(f)[2][1]).toContain('--inside-run')
    expect(calls(f)[2][1].slice(-2)).toEqual(['vitest', 'run'])
    expect(f.files.rmSync).toHaveBeenCalledWith(root, { recursive: true, force: true })
    expect(f.host.kill).not.toHaveBeenCalled()
    expect(f.timers.size).toBe(0)
  })

  it.each([[1, 0, 0], [0, 1, 0, 0], [new Error('sudo unavailable'), 0, 0]])(
    'uses generic sudo unshare LAST only after helper permission/probe failure (%j)', async (...outcomes) => {
      const f = fixture(outcomes)
      await f.launchIsolated('vitest')
      const launches = calls(f).filter(([, args]) => args.includes('unshare'))
      expect(launches).toHaveLength(2)
      expect(launches[0][1]).toContain('--inside-probe')
      expect(launches[1][1]).toContain('--inside-run')
      expect(launches[1][1]).toEqual(expect.arrayContaining(['--reuid=1001', '--regid=1002', '--clear-groups',
        '--no-new-privs', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all']))
      expect(calls(f).flatMap(([, args]) => args)).not.toContain('--map-current-user')
    }
  )

  it('fails clearly before running tests when all capability probes fail', async () => {
    const f = fixture([0, 1, 1])
    await expect(f.launchIsolated('vitest')).rejects.toThrow(/no tests were started.*approved isolation helper.*generic sudo unshare/)
    expect(calls(f).some(([, args]) => args.includes('--inside-run'))).toBe(false)
    expect(f.files.rmSync).toHaveBeenCalledOnce()
  })

  it('does not retry a suite failure or launch error after selecting the helper', async () => {
    for (const outcome of [7, new Error('spawn failed')]) {
      const f = fixture([0, 0, outcome])
      await expect(f.launchIsolated('vitest')).rejects.toThrow()
      expect(calls(f)).toHaveLength(3)
      expect(calls(f).some(([, args]) => args.includes('unshare'))).toBe(false)
      expect(f.host.listenerCount('SIGTERM')).toBe(0)
      expect(f.timers.size).toBe(0)
      expect(f.files.rmSync).toHaveBeenCalledOnce()
    }
  })

  it.each(['SIGINT', 'SIGTERM', 'abort', 'timeout'])('kills the detached group as the user on %s, awaits exit, then restores handlers and HOME', async (reason) => {
    const f = fixture([0, 0, 'pending'])
    const previous = vi.fn()
    f.host.on('SIGTERM', previous)
    const controller = new AbortController()
    const promise = f.launchIsolated('vitest', [], { signal: controller.signal })
    const rejected = expect(promise).rejects.toThrow(/cancelled|timed out/)
    await flush()
    const child = f.children[2]
    if (reason === 'abort') controller.abort()
    else if (reason === 'timeout') [...f.timers.values()][0]()
    else f.host.emit(reason)
    expect(f.host.kill).toHaveBeenCalledExactlyOnceWith(-child.pid!, 'SIGKILL')
    expect(f.files.rmSync).not.toHaveBeenCalled()
    expect(f.host.listenerCount('SIGTERM')).toBe(2)
    child.emit('exit', null, 'SIGKILL')
    await rejected
    expect(f.host.listeners('SIGTERM')).toEqual([previous])
    expect(f.host.listenerCount('SIGINT')).toBe(0)
    expect(f.files.rmSync).toHaveBeenCalledOnce()
    expect(f.timers.size).toBe(0)
    expect(calls(f)).toHaveLength(3)
  })

  it('cancels an active capability probe without trying the fallback', async () => {
    const f = fixture([0, 'pending'])
    const promise = f.launchIsolated('vitest')
    const rejected = expect(promise).rejects.toThrow('cancelled')
    await flush()
    f.host.emit('SIGINT')
    expect(f.host.kill).toHaveBeenCalledWith(-f.children[1].pid!, 'SIGKILL')
    expect(f.files.rmSync).not.toHaveBeenCalled()
    f.children[1].emit('exit', null, 'SIGKILL')
    await rejected
    expect(calls(f)).toHaveLength(2)
  })

  it('waits for a timed-out probe to exit before any fallback starts', async () => {
    const f = fixture([0, 'pending', 0, 0])
    const promise = f.launchIsolated('vitest')
    await flush()
    ;[...f.timers.values()][0]()
    expect(calls(f)).toHaveLength(2)
    expect(f.files.rmSync).not.toHaveBeenCalled()
    f.children[1].emit('exit', null, 'SIGKILL')
    await promise
    expect(calls(f)).toHaveLength(4)
    expect(calls(f)[2][1]).toContain('unshare')
  })

  it('never tries privileged cleanup if group signaling fails', async () => {
    const f = fixture([0, 0, 'pending'])
    f.host.kill.mockImplementation(() => { throw Object.assign(new Error('denied'), { code: 'EPERM' }) })
    const promise = f.launchIsolated('vitest')
    const rejected = expect(promise).rejects.toThrow('Process-group cleanup failed: denied')
    await flush()
    f.host.emit('SIGTERM')
    expect(f.files.rmSync).not.toHaveBeenCalled()
    expect(calls(f)).toHaveLength(3)
    f.children[2].emit('exit', null, 'SIGKILL')
    await rejected
    expect(calls(f)).toHaveLength(3)
  })

  it('handles a raced ESRCH by awaiting exit, and never signals PID 0', async () => {
    const f = fixture([0, 0, 'pending'])
    f.host.kill.mockImplementation(() => { throw Object.assign(new Error('gone'), { code: 'ESRCH' }) })
    const promise = f.launchIsolated('vitest')
    const rejected = expect(promise).rejects.toThrow('cancelled')
    await flush()
    f.host.emit('SIGINT')
    expect(f.files.rmSync).not.toHaveBeenCalled()
    f.children[2].emit('exit', null, 'SIGKILL')
    await rejected
    expect(f.host.kill).toHaveBeenCalledWith(-31002, 'SIGKILL')
  })

  it('rejects already-aborted launches, unsafe env, root, and changed effective identity before any spawn', async () => {
    for (const mutate of [
      (f: ReturnType<typeof fixture>) => { f.host.getuid = () => 0 },
      (f: ReturnType<typeof fixture>) => { f.host.getgid = f.host.getegid = () => 0 },
      (f: ReturnType<typeof fixture>) => { f.host.geteuid = () => 0 },
      (f: ReturnType<typeof fixture>) => { f.host.getegid = () => 0 }
    ]) {
      const f = fixture(); mutate(f)
      await expect(f.launchIsolated('vitest')).rejects.toThrow('non-root')
      expect(f.spawnChild).not.toHaveBeenCalled()
    }
    const f = fixture()
    await expect(f.launchIsolated('vitest', [], { env: { HOME: '/real-home' } })).rejects.toThrow('env override')
    const controller = new AbortController(); controller.abort()
    await expect(f.launchIsolated('vitest', [], { signal: controller.signal })).rejects.toThrow('cancelled before launch')
    expect(f.spawnChild).not.toHaveBeenCalled()
    expect(f.files.mkdtempSync).not.toHaveBeenCalled()
  })

  it('cleans failed HOME setup without launching anything', async () => {
    const f = fixture()
    f.files.mkdirSync.mockImplementation(() => { throw new Error('mkdir failed') })
    await expect(f.launchIsolated('vitest')).rejects.toThrow('mkdir failed')
    expect(f.files.rmSync).toHaveBeenCalledOnce()
    expect(f.spawnChild).not.toHaveBeenCalled()
  })
})

describe('real-core capability assertions against fake proc and HOME', () => {
  it('verifies both probe and run with the exact runner, numeric caller and private HOME', () => {
    const f = fixture()
    f.assertRealCoreIsolation()
    f.host.argv[2] = '--inside-probe'
    f.assertRealCoreIsolation('--inside-probe')
  })

  it.each([
    ['root', (f: ReturnType<typeof fixture>) => { f.host.getuid = () => 0 }],
    ['root group', (f: ReturnType<typeof fixture>) => { f.host.getgid = f.host.getegid = () => 0 }],
    ['effective uid', (f: ReturnType<typeof fixture>) => { f.host.geteuid = () => 0 }],
    ['effective gid', (f: ReturnType<typeof fixture>) => { f.host.getegid = () => 0 }],
    ['wrong uid', (f: ReturnType<typeof fixture>) => { f.host.env.ODIN_REAL_CORE_UID = '1003' }],
    ['wrong gid', (f: ReturnType<typeof fixture>) => { f.host.env.ODIN_REAL_CORE_GID = '1003' }],
    ['nonnumeric uid', (f: ReturnType<typeof fixture>) => { f.host.env.ODIN_REAL_CORE_UID = '1e3' }],
    ['missing uid', (f: ReturnType<typeof fixture>) => { delete f.host.env.ODIN_REAL_CORE_UID }],
    ['not PID 1', (f: ReturnType<typeof fixture>) => { f.host.pid = 19 }],
    ['outer namespace', (f: ReturnType<typeof fixture>) => { f.host.env.ODIN_REAL_CORE_OUTER_PID_NS = 'pid:[private]' }],
    ['nonprivate proc', (f: ReturnType<typeof fixture>) => { f.files.readlinkSync.mockImplementation((path: string) => path === '/proc/1/ns/pid' ? 'pid:[outer]' : 'pid:[private]') }],
    ['wrong runner', (f: ReturnType<typeof fixture>) => { f.host.argv[1] = `/prefix${script}` }],
    ['wrong runner mode', (f: ReturnType<typeof fixture>) => { f.host.argv[2] = '--inside-probe' }],
    ['wrong interpreter', (f: ReturnType<typeof fixture>) => { f.host.argv[0] = '/other/node' }],
    ['different init', (f: ReturnType<typeof fixture>) => { f.files.readFileSync.mockImplementation(() => `sh\0${script}\0--inside-run\0`) }],
    ['ambient HOME', (f: ReturnType<typeof fixture>) => { f.host.env.HOME = '/home/user' }],
    ['nested HOME', (f: ReturnType<typeof fixture>) => { f.host.env.HOME = f.host.env.ODIN_REAL_CORE_ROOT = `${root}/nested` }],
    ['ambient XDG', (f: ReturnType<typeof fixture>) => { f.host.env.XDG_RUNTIME_DIR = '/run/user/1001' }],
    ['wrong owner', (f: ReturnType<typeof fixture>) => { f.files.lstatSync.mockReturnValue({ isDirectory: () => true, uid: 0, gid: 1002, mode: 0o40700 }) }],
    ['wrong group', (f: ReturnType<typeof fixture>) => { f.files.lstatSync.mockReturnValue({ isDirectory: () => true, uid: 1001, gid: 0, mode: 0o40700 }) }],
    ['world readable', (f: ReturnType<typeof fixture>) => { f.files.lstatSync.mockReturnValue({ isDirectory: () => true, uid: 1001, gid: 1002, mode: 0o40755 }) }],
    ['symlink HOME', (f: ReturnType<typeof fixture>) => { f.files.lstatSync.mockReturnValue({ isDirectory: () => false, uid: 1001, gid: 1002, mode: 0o40700 }) }]
  ])('refuses %s', (_name, mutate) => {
    const f = fixture(); mutate(f)
    expect(() => f.assertRealCoreIsolation()).toThrow()
  })

  it.each(['CapEff:\t0001', 'CapBnd:\t0001', 'NoNewPrivs:\t0', 'Groups:\t1002'])('refuses unsafe process privileges: %s', (line) => {
    const f = fixture()
    const safe = f.files.readFileSync('/proc/self/status')
    f.files.readFileSync.mockImplementation((path: string) => path === '/proc/self/status'
      ? safe.replace(new RegExp(`^${line.split(':')[0]}:.*$`, 'm'), line)
      : f.host.argv.join('\0') + '\0')
    expect(() => f.assertRealCoreIsolation()).toThrow('capabilities')
  })
})
