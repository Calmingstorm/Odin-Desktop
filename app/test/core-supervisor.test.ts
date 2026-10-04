import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { CoreSupervisor } from '../src/main/core-supervisor'
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
