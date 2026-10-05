import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { boundedShutdown, CleanupJournal, type CleanupRecord, type ShutdownDeps } from '../src/main/shutdown'

const roots: string[] = []
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }) })
function journal() {
  const root = mkdtempSync(join(tmpdir(), 'odin-cleanup-'))
  roots.push(root)
  const path = join(root, 'cleanup.json')
  return { path, journal: new CleanupJournal(path) }
}
function deps(extra: Partial<ShutdownDeps> = {}): ShutdownDeps {
  return { stopAdmission: vi.fn(), persist: vi.fn(), requestShutdown: vi.fn(async () => true),
    stopCore: vi.fn(async () => 'exited' as const), unreceipted: () => 0, finish: vi.fn(), release: vi.fn(), exit: vi.fn(), ...extra }
}
describe('bounded shared shutdown', () => {
  it('shares simultaneous Exit routes and preserves ordering', async () => {
    const order: string[] = []
    const d = deps({ stopAdmission: () => { order.push('admission') }, persist: () => { order.push('persist') },
      requestShutdown: async () => { order.push('request'); return true },
      stopCore: async () => { order.push('core'); return 'exited' },
      finish: () => { order.push('receipt') }, release: () => { order.push('release') }, exit: () => { order.push('exit') } })
    const exit = boundedShutdown(d)
    const first = exit()
    expect(exit(1)).toBe(first)
    expect((await first).state).toBe('process-exited')
    expect(order).toEqual(['admission', 'persist', 'request', 'core', 'receipt', 'release', 'exit'])
  })
  it('bounds request acceptance without retry and escalated exit stays unknown', async () => {
    const d = deps({ requestTimeoutMs: 10, requestShutdown: vi.fn(() => new Promise<boolean>(() => {})), stopCore: async () => 'killed' })
    expect(await boundedShutdown(d)()).toMatchObject({ state: 'unknown', processOutcome: 'killed', shutdownAccepted: false })
    expect(d.requestShutdown).toHaveBeenCalledTimes(1)
    expect(d.exit).toHaveBeenCalledWith(0)
  })
  it.each(['persist', 'requestShutdown', 'stopCore', 'finish'] as const)('still releases and exits when %s fails', async (key) => {
    const d = deps()
    Object.assign(d, { [key]: () => { throw new Error('harmless test failure') } })
    await boundedShutdown(d)()
    expect(d.release).toHaveBeenCalledTimes(1)
    expect(d.exit).toHaveBeenCalledTimes(1)
  })
  it('keeps unreceipted commands unknown', async () => {
    expect((await boundedShutdown(deps({ unreceipted: () => 1 }))()).state).toBe('unknown')
  })
})
describe('persistent cleanup evidence', () => {
  it('detects app loss and never clears it on a later clean exit', () => {
    const { path, journal: first } = journal()
    first.begin()
    const restarted = new CleanupJournal(path)
    expect(restarted.warning?.state).toBe('unknown')
    restarted.begin()
    restarted.finish({ version: 1, state: 'process-exited', at: new Date().toISOString(), reason: 'later clean exit' })
    expect(new CleanupJournal(path).warning?.state).toBe('unknown')
  })
  it('preserves full unknown evidence and records process receipt without a native-release claim', () => {
    const { path, journal: first } = journal()
    first.begin()
    first.finish({ version: 1, state: 'unknown', at: new Date().toISOString(), reason: 'unproven', processOutcome: 'killed' })
    expect(new CleanupJournal(path).warning?.processOutcome).toBe('killed')
    expect((JSON.parse(readFileSync(path, 'utf8')) as CleanupRecord).state).toBe('unknown')
  })
  it('fails visibly on unreadable previous evidence', () => {
    const { path } = journal()
    writeFileSync(path, 'not JSON')
    expect(new CleanupJournal(path).warning?.state).toBe('unknown')
  })
})
