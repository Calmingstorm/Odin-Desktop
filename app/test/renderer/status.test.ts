// The status bar's facts, driven through a fake bridge: a refresh started later always answers instead.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CoreStatus, Result, UsageResult } from '../../src/shared/api'

type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void }
function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

let statuses: Array<Deferred<Result<CoreStatus>>>
let usages: Array<Deferred<Result<UsageResult>>>

const core = (version: string): Result<CoreStatus> => ({ ok: true, result: { phase: 'ready', core_instance_id: 'core-1', version, capabilities: [] } as CoreStatus })
const usage = (tokens: number): Result<UsageResult> => ({ ok: true, result: { period: '24h', tokens: { total: tokens } } as unknown as UsageResult })

beforeEach(() => {
  vi.resetModules()
  statuses = []
  usages = []
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      status: () => {
        const next = deferred<Result<CoreStatus>>()
        statuses.push(next)
        return next.promise
      },
      usage: () => {
        const next = deferred<Result<UsageResult>>()
        usages.push(next)
        return next.promise
      }
    }
  }
})

describe('review round 2: status refreshes', () => {
  it('never lets an older refresh that answers late replace a newer one', async () => {
    const { refreshStatus, status } = await import('../../src/renderer/src/stores/status')
    const older = refreshStatus()
    const newer = refreshStatus()
    statuses[1]!.resolve(core('new'))
    usages[1]!.resolve(usage(20))
    await newer
    statuses[0]!.resolve(core('old'))
    usages[0]!.resolve(usage(10))
    await older
    expect(status.core?.version).toBe('new')
    expect((status.usage as unknown as { tokens: { total: number } }).tokens.total).toBe(20)
  })
})
