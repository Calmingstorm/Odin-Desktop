import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { boundedShutdown, CleanupJournal, resourceCleanupSource, type CleanupRecord, type ShutdownDeps } from '../src/main/shutdown'

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
  it('identifies the same core evidence after sorted-key persistence and distinguishes a later unknown count', () => {
    const first = { previous: { state: 'running', at: '2026-10-05T20:00:00Z',
      resources: { computer: { state: 'unknown', unresolved_sessions: ['retained'] }, processes: { state: 'released' } } }, count: 1 }
    const persisted = { count: 1, previous: { at: first.previous.at,
      resources: { processes: { state: 'released' }, computer: { unresolved_sessions: ['retained'], state: 'unknown' } }, state: 'running' } }
    expect(resourceCleanupSource(first)).toBe(resourceCleanupSource(persisted))
    expect(resourceCleanupSource(first)).not.toBe(resourceCleanupSource({ ...persisted, count: 2 }))
  })
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
  it('archives acknowledgment durably without a release claim and stays quiet after a normal restart', () => {
    const { path, journal: first } = journal()
    first.begin()
    first.markUnknown('Native cleanup unverified', 'native-receipt-1')
    const notice = first.notice!
    expect(first.acknowledge(notice.id)).toBe(true)
    expect(first.notice).toBeNull()
    const archive = JSON.parse(readFileSync(path, 'utf8')).archived
    expect(archive[0]).toMatchObject({ id: notice.id, records: [{ state: 'unknown', reason: 'Native cleanup unverified' }] })
    expect(Number.isFinite(Date.parse(archive[0].acknowledgedAt))).toBe(true)
    first.finish({ version: 1, state: 'process-exited', at: new Date().toISOString(), reason: 'Core process exit only' })
    const restarted = new CleanupJournal(path)
    restarted.begin()
    restarted.markUnknown('Same retained core report', 'native-receipt-1')
    expect(restarted.notice).toBeNull()
    expect(restarted.archived).toEqual(archive)
    restarted.markUnknown('A later unknown event', 'native-receipt-2')
    expect(restarted.notice?.id).not.toBe(notice.id)
    expect(restarted.notice?.records).toMatchObject([{ reason: 'A later unknown event' }])
    expect(new CleanupJournal(path).archived).toEqual(archive)
  })
  it('does not let a stale acknowledgment archive a later unknown event', () => {
    const { journal: first } = journal()
    first.begin()
    first.markUnknown('First event')
    const firstId = first.notice!.id
    first.markUnknown('Second event')
    expect(first.acknowledge(firstId)).toBe(false)
    expect(first.notice?.records.map((row) => row.reason)).toEqual(['First event', 'Second event'])
    expect(first.archived).toEqual([])
  })
  it('acknowledgment never hides a new interrupted lifetime', () => {
    const { path, journal: first } = journal()
    first.begin()
    first.markUnknown('Old event')
    expect(first.acknowledge(first.notice!.id)).toBe(true)
    // No finish receipt: the acknowledged notice is archived, but this new
    // interrupted app lifetime must still warn on restart.
    const restarted = new CleanupJournal(path)
    expect(restarted.notice?.records[0]?.reason).toContain('without a shutdown receipt')
    expect(restarted.archived[0]?.records[0]?.reason).toBe('Old event')
  })
  it('retains the notice when acknowledgment cannot persist its archive', () => {
    const { path, journal: first } = journal()
    first.begin()
    first.markUnknown('Unverified cleanup')
    const notice = first.notice!
    rmSync(path)
    rmSync(join(path, '..'), { recursive: true })
    expect(() => first.acknowledge(notice.id)).toThrow()
    expect(first.notice).toEqual(notice)
    expect(first.archived).toEqual([])
  })
  it('migrates the legacy single unknown receipt and preserves every evidence field', () => {
    const { path } = journal()
    const record: CleanupRecord = { version: 1, state: 'unknown', at: '2026-10-05T20:00:00Z',
      reason: 'Legacy cleanup unknown', processOutcome: 'killed', shutdownAccepted: false, unreceipted: 2 }
    writeFileSync(path, JSON.stringify(record))
    const migrated = new CleanupJournal(path)
    migrated.begin()
    expect(migrated.acknowledge(migrated.notice!.id)).toBe(true)
    expect(new CleanupJournal(path).archived[0]?.records).toEqual([record])
  })
})
