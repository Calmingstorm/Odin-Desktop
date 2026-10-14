import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CoreSupervisor } from '../src/main/core-supervisor'
import { boundedShutdown, CleanupJournal } from '../src/main/shutdown'
import { waitFor } from './fixture-harness'

const cleanups: Array<() => Promise<unknown> | void> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
})

function supervisor(script: string, extra: Partial<ConstructorParameters<typeof CoreSupervisor>[0]> = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'odin-supervisor-'))
  const s = new CoreSupervisor({
    command: process.execPath,
    args: ['-e', script],
    logFile: join(dir, 'core.log'),
    backoffMs: [20],
    ...extra
  })
  cleanups.push(async () => {
    await s.stop(200, 200)
    rmSync(dir, { recursive: true, force: true })
  })
  return s
}

// A child that exits cleanly when its stdin (the parent link) closes, like the real core.
const OBEDIENT = "process.stdin.on('end', () => process.exit(0)); process.stdin.resume(); setInterval(() => {}, 1000)"
// A child that ignores the parent link and SIGTERM.
const STUBBORN = "process.on('SIGTERM', () => {}); setInterval(() => {}, 1000)"

describe('core supervisor', () => {
  it('shares concurrent stops and refuses starts after shutdown', async () => {
    const s = supervisor(OBEDIENT)
    s.start()
    await waitFor(() => s.current === 'running')
    const first = s.stop(2_000, 1_000)
    expect(s.stop()).toBe(first)
    await first
    s.start()
    expect(s.pid).toBeUndefined()
    expect(s.current).toBe('stopped')
  })
  it('does not replace a core with unproven cleanup when its admission predicate refuses', async () => {
    const s = supervisor('process.exit(1)', { restartAllowed: () => false })
    const restarted = vi.fn()
    s.on('restarting', restarted)
    s.start()
    await waitFor(() => s.current === 'failed')
    expect(restarted).not.toHaveBeenCalled()
  })
  it('restarts a crashed core within its budget, then reports failure', async () => {
    const s = supervisor('process.exit(1)', { maxRestarts: 2, restartWindowMs: 60_000 })
    const restarts: number[] = []
    let failed = false
    s.on('restarting', ({ attempt }: { attempt: number }) => restarts.push(attempt))
    s.on('failed', () => (failed = true))
    s.start()
    await waitFor(() => failed, 5_000)
    expect(restarts).toEqual([1, 2])
    expect(s.current).toBe('failed')
  })

  it('stops in order by closing the parent link', async () => {
    const s = supervisor(OBEDIENT)
    s.start()
    await waitFor(() => s.current === 'running')
    expect(await s.stop(2_000, 1_000)).toBe('exited')
    expect(s.current).toBe('stopped')
  })

  it('escalates to SIGKILL when the core will not stop', async () => {
    const s = supervisor(STUBBORN)
    s.start()
    await waitFor(() => s.current === 'running')
    await new Promise((r) => setTimeout(r, 200))
    expect(await s.stop(150, 150)).toBe('killed')
  })

  it('never signals a guardian: it waits, and past the wait the outcome is unknown', async () => {
    const s = supervisor(STUBBORN, { guardianWaitMs: 300 })
    s.start()
    await waitFor(() => s.current === 'running')
    const pid = s.pid!
    await new Promise((r) => setTimeout(r, 100))
    const started = Date.now()
    expect(await s.stop(10, 10)).toBe('unknown')  // the stop's own TERM and KILL times are not used
    expect(Date.now() - started).toBeGreaterThanOrEqual(280)
    expect(() => process.kill(pid, 0)).not.toThrow()  // still alive: nothing signalled it
    process.kill(pid, 'SIGKILL')
  })

  it('takes no exit but a guardian\'s clean one as an orderly stop', async () => {
    // The guardian's status is the engine's when it reaped it: forced (a signal), failed (a code), or the
    // guardian killed before reaping (also a signal). None of them proves the engine stopped cleanly.
    for (const ending of ['process.exit(3)', "process.kill(process.pid, 'SIGKILL')",
      "process.kill(process.pid, 'SIGTERM')"]) {
      const s = supervisor(`process.stdin.on('end', () => ${ending}); process.stdin.resume(); setInterval(() => {}, 1000)`,
        { guardianWaitMs: 5_000 })
      s.start()
      await waitFor(() => s.current === 'running')
      expect(await s.stop()).toBe('unknown')
    }
    const plain = supervisor("process.stdin.on('end', () => process.exit(3)); process.stdin.resume(); setInterval(() => {}, 1000)")
    plain.start()
    await waitFor(() => plain.current === 'running')
    expect(await plain.stop()).toBe('exited') // without a guardian the app's own escalation decides, as before
  })

  it('records a forced or failed guardian stop as unknown cleanup, even after an accepted shutdown', async () => {
    for (const [ending, state, processOutcome] of [
      ["process.kill(process.pid, 'SIGKILL')", 'unknown', 'unknown'], ['process.exit(3)', 'unknown', 'unknown'],
      ['process.exit(0)', 'process-exited', 'exited']] as const) {
      const s = supervisor(`process.stdin.on('end', () => ${ending}); process.stdin.resume(); setInterval(() => {}, 1000)`,
        { guardianWaitMs: 5_000 })
      s.start()
      await waitFor(() => s.current === 'running')
      const record = await boundedShutdown({ stopAdmission: () => undefined, persist: () => undefined,
        requestShutdown: async () => true, stopCore: () => s.stop(), unreceipted: () => 0,
        finish: () => undefined, release: () => undefined, exit: () => undefined })()
      expect(record).toMatchObject({ state, processOutcome, shutdownAccepted: true })
    }
  })

  it('keeps a guardian\'s abnormal end that comes before Stop, as one during Stop', async () => {
    // Bounded shutdown's request is accepted, but the guardian already ended before stopCore: its status still
    // decides. The current journal record is what the next start reads.
    for (const [ending, outcome, state] of [['process.exit(3)', 'unknown', 'unknown'],
      ["process.kill(process.pid, 'SIGKILL')", 'unknown', 'unknown'],
      ['process.exit(0)', 'not-running', 'process-exited']] as const) {
      const dir = mkdtempSync(join(tmpdir(), 'odin-guardian-end-'))
      cleanups.push(() => rmSync(dir, { recursive: true, force: true }))
      const journal = new CleanupJournal(join(dir, 'cleanup.json'))
      const s = supervisor(`setTimeout(() => ${ending}, 50); setInterval(() => {}, 1000)`,
        { guardianWaitMs: 5_000, restartAllowed: () => false })
      s.start()
      await waitFor(() => s.current === 'failed')
      const record = await boundedShutdown({ stopAdmission: () => undefined, persist: () => undefined,
        requestShutdown: async () => true, stopCore: () => s.stop(), unreceipted: () => 0,
        finish: (value) => journal.finish(value), release: () => undefined, exit: () => undefined })()
      expect(record).toMatchObject({ processOutcome: outcome, state, shutdownAccepted: true })
      expect(JSON.parse(readFileSync(join(dir, 'cleanup.json'), 'utf8')).current.state).toBe(state)
    }
  })

  it('still calls a guardian that never started, or a plain child\'s abnormal end, not running', async () => {
    const never = new CoreSupervisor({ command: '/nonexistent/odin-guardian', args: [], guardianWaitMs: 5_000,
      logFile: join(mkdtempSync(join(tmpdir(), 'odin-never-')), 'core.log') })
    never.start()
    await waitFor(() => never.current !== 'starting')
    expect(await never.stop()).toBe('not-running')
    const plain = supervisor('setTimeout(() => process.exit(3), 50); setInterval(() => {}, 1000)',
      { restartAllowed: () => false })
    plain.start()
    await waitFor(() => plain.current === 'failed')
    expect(await plain.stop()).toBe('not-running') // Linux and Windows: unchanged
  })

  it('lets an obedient guardian exit on its own within the wait', async () => {
    const s = supervisor(OBEDIENT, { guardianWaitMs: 5_000 })
    s.start()
    await waitFor(() => s.current === 'running')
    expect(await s.stop()).toBe('exited')
  })

  it('does not restart a core that was stopped on purpose', async () => {
    const s = supervisor(OBEDIENT)
    let restarted = false
    s.on('restarting', () => (restarted = true))
    s.start()
    await waitFor(() => s.current === 'running')
    await s.stop(2_000, 1_000)
    await new Promise((r) => setTimeout(r, 100))
    expect(restarted).toBe(false)
  })
})

describe('core supervisor start failures', () => {
  function missing(extra: Partial<ConstructorParameters<typeof CoreSupervisor>[0]> = {}) {
    // A path that can't exist: spawning it fails with ENOENT and runs nothing.
    return supervisor('', { command: join(tmpdir(), `odin-missing-core-${process.pid}`, 'core'), args: [], ...extra })
  }

  it('treats a core that cannot start like a crash: bounded restarts, then failure, each start ended once', async () => {
    const s = missing({ maxRestarts: 2, restartWindowMs: 60_000 })
    const restarts: number[] = []
    let ended = 0
    let failed = false
    let started = false
    s.on('restarting', ({ attempt }: { attempt: number }) => restarts.push(attempt))
    s.on('exited', () => (ended += 1))
    s.on('failed', () => (failed = true))
    s.on('started', () => (started = true))
    s.start()
    await waitFor(() => failed, 5_000)
    await new Promise((r) => setTimeout(r, 100))
    expect(restarts).toEqual([1, 2])
    expect(ended).toBe(3)
    expect(started).toBe(false)
    expect(s.current).toBe('failed')
    expect(s.pid).toBeUndefined()
  })

  it('stops a core that never started at once, without restarting it', async () => {
    const s = missing()
    let restarted = false
    s.on('restarting', () => (restarted = true))
    s.start()
    expect(await s.stop(200, 200)).toBe('not-running')
    await new Promise((r) => setTimeout(r, 150))
    expect(restarted).toBe(false)
    expect(s.current).toBe('stopped')
  })
})
