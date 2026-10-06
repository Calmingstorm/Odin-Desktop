import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { acquirePackagedApp, admitPackagedApp } from '../src/main/package-ownership'

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
    const pending = acquirePackagedApp(paths, '/opt/Odin/resources', {
      ODIN_DESKTOP_OWNERSHIP_KIND: 'appimage'
    })
    process.stdout.write('READY\n')
    await pending
    expect(mocked.spawn.mock.calls[0]![1]).toContain('deb')
    process.stdin.end()
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
