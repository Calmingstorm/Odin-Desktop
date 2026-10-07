import { EventEmitter } from 'node:events'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AGGREGATE_TIMEOUT_MS, REAL_CORE_FILES, REAL_CORE_SHARDS, runRealCoreShards,
  selectRealCoreFiles, SHARD_TIMEOUT_MS } from '../scripts/real-core-shards.mjs'

function fixture() {
  const host = new EventEmitter()
  const timers = new Map<object, () => void>()
  const schedule = vi.fn((callback: () => void) => {
    const handle = {}
    timers.set(handle, callback)
    return handle as NodeJS.Timeout
  }) as unknown as typeof setTimeout
  const unschedule = vi.fn((handle: unknown) => timers.delete(handle as object))
  const pending: Array<{ resolve: () => void; reject: (error: Error) => void }> = []
  const launch = vi.fn(() => new Promise<void>((resolve, reject) => pending.push({ resolve, reject })))
  const report = vi.fn()
  const options = { launch, host: host as unknown as NodeJS.Process, schedule, unschedule,
    command: '/usr/bin/node', args: ['/app/vitest.mjs', 'run'], config: '/app/vitest.real-core.config.ts', cwd: '/app', report }
  return { host, timers, pending, launch, report, options }
}

describe('real-core shard orchestration', () => {
  afterEach(() => { vi.unstubAllEnvs(); vi.resetModules() })

  it('the actual Vitest config selects every shard without changing case deadlines or sharing a cache', async () => {
    // This runtime gate config is outside the composite app TS project. Load
    // it through Vitest, not as a new production build input.
    const configPath = '../vitest.real-core.config'
    for (const shard of [undefined, '1/4', '2/4', '3/4', '4/4']) {
      vi.stubEnv('ODIN_APP_REAL_CORE_SHARD', shard)
      vi.resetModules()
      const config = (await import(configPath)).default
      expect(config.test).toMatchObject({ include: selectRealCoreFiles(shard), fileParallelism: false,
        cache: false, environment: 'node', testTimeout: 180_000, hookTimeout: 90_000 })
    }
    vi.stubEnv('ODIN_APP_REAL_CORE_SHARD', '5/4')
    vi.resetModules()
    await expect(import(configPath)).rejects.toThrow('Invalid real-core shard')
  })
  it('partitions the entire original reviewed eight-file selection exactly once', () => {
    const original = ['test/real-core-contract.test.ts', 'test/real-core-settings.test.ts',
      'test/real-core-completion.test.ts', 'test/real-core-services.test.ts', 'test/real-core-work.test.ts',
      'test/real-core-webhooks.test.ts', 'test/real-core-skills.test.ts', 'test/renderer/real-core-renderer-contract.test.ts']
    expect([...REAL_CORE_FILES].sort()).toEqual(original.sort())
    const selected = REAL_CORE_SHARDS.flatMap((_, index) => selectRealCoreFiles(`${index + 1}/4`))
    expect(selected.sort()).toEqual(original)
    expect(new Set(selected).size).toBe(original.length)
    expect(selectRealCoreFiles()).toEqual(REAL_CORE_FILES)
    const copy = selectRealCoreFiles('1/4')
    copy.pop()
    expect(selectRealCoreFiles('1/4')).toHaveLength(1)
  })

  it.each(['', '0/4', '5/4', '1/3', '01/4', '1/4extra'])('rejects invalid shard %j instead of running empty selection', (shard) => {
    expect(() => selectRealCoreFiles(shard)).toThrow('Invalid real-core shard')
  })

  it('starts three isolated shards, drains them, then admits work alone with separate selectors and bounded signals', async () => {
    const f = fixture()
    const running = runRealCoreShards({ ...f.options, extraArgs: ['--no-color', '--silent=passed-only'] })
    expect(f.pending).toHaveLength(3)
    expect(f.launch.mock.calls).toHaveLength(3)
    const calls = f.launch.mock.calls as unknown as Array<[string, string[], { cwd: string; timeoutMs: number; signal: AbortSignal; env: Record<string, string> }]>
    calls.forEach(([command, args, options], index) => {
      expect(command).toBe('/usr/bin/node')
      expect(args).toEqual(['/app/vitest.mjs', 'run', '--no-color', '--silent=passed-only', '--config', '/app/vitest.real-core.config.ts'])
      expect(options).toMatchObject({ cwd: '/app', timeoutMs: SHARD_TIMEOUT_MS, env: { ODIN_APP_REAL_CORE_SHARD: `${index + 1}/4` } })
      expect(options.signal.aborted).toBe(false)
    })
    expect(AGGREGATE_TIMEOUT_MS).toBe(600_000)
    f.pending[0]!.resolve()
    f.pending[1]!.resolve()
    for (let i = 0; i < 5; i++) await Promise.resolve()
    expect(f.pending).toHaveLength(3)
    f.pending[2]!.resolve()
    for (let i = 0; i < 5; i++) await Promise.resolve()
    expect(f.pending).toHaveLength(4)
    expect((f.launch.mock.calls as unknown as Array<[string, string[], { env: Record<string, string> }]>)[3]![2].env)
      .toEqual({ ODIN_APP_REAL_CORE_SHARD: '4/4' })
    f.pending[3]!.resolve()
    await running
    expect(f.report.mock.calls.at(-1)?.[0]).toContain('4 isolated shards passed')
    expect(f.timers.size).toBe(0)
    expect(f.host.listenerCount('SIGTERM')).toBe(0)
  })

  it('propagates first failure, aborts siblings, never retries and waits for every exit', async () => {
    const f = fixture()
    const running = runRealCoreShards(f.options)
    const rejected = expect(running).rejects.toThrow('shard 2/4 failed: real test failed')
    let finished = false
    void running.catch(() => { finished = true })
    f.pending[1]!.reject(new Error('real test failed'))
    await Promise.resolve()
    const options = (f.launch.mock.calls as unknown as Array<[string, string[], { signal: AbortSignal }]>)[0]![2]
    expect(options.signal.aborted).toBe(true)
    expect(finished).toBe(false)
    expect(f.timers.size).toBe(1)
    f.pending[0]!.reject(new Error('cancelled'))
    f.pending[2]!.resolve()
    await rejected
    expect(f.launch).toHaveBeenCalledTimes(3)
    expect(f.timers.size).toBe(0)
  })

  it.each(['deadline', 'SIGTERM', 'SIGINT'])('cancels all shards on %s and preserves existing handlers', async (cause) => {
    const f = fixture()
    const previous = vi.fn()
    f.host.on('SIGTERM', previous)
    const running = runRealCoreShards(f.options)
    const rejected = expect(running).rejects.toThrow(cause === 'deadline' ? 'aggregate deadline' : cause)
    if (cause === 'deadline') [...f.timers.values()][0]!()
    else f.host.emit(cause)
    f.pending.forEach((child) => child.reject(new Error('cancelled')))
    await rejected
    expect(f.host.listeners('SIGTERM')).toEqual([previous])
    expect(f.host.listenerCount('SIGINT')).toBe(0)
    expect(f.launch).toHaveBeenCalledTimes(3)
  })

  it('catches synchronous launcher failures and cancels before subsequent launchers can run tests', async () => {
    const f = fixture()
    f.launch.mockImplementation(() => { throw new Error('missing isolation capability') })
    await expect(runRealCoreShards(f.options)).rejects.toThrow('missing isolation capability')
    const calls = f.launch.mock.calls as unknown as Array<[string, string[], { signal: AbortSignal }]>
    expect(calls.every(([, , options]) => options.signal.aborted)).toBe(true)
    expect(f.timers.size).toBe(0)
  })

  it('keeps one aggregate timer across waves and propagates final-wave failure without replay', async () => {
    const f = fixture()
    const running = runRealCoreShards(f.options)
    const rejected = expect(running).rejects.toThrow('shard 4/4 failed: work admission failed')
    const originalTimer = [...f.timers.keys()][0]
    f.pending.forEach((child) => child.resolve())
    for (let i = 0; i < 5; i++) await Promise.resolve()
    expect(f.pending).toHaveLength(4)
    expect([...f.timers.keys()]).toEqual([originalTimer])
    f.pending[3]!.reject(new Error('work admission failed'))
    await rejected
    expect(f.launch).toHaveBeenCalledTimes(4)
    expect(f.timers.size).toBe(0)
  })

  it.each(['--shard=1/4', '--config', '--project=x', '--exclude=x', '--include=x', '-c',
    '--outputFile=x', '--outputFile.junit=x', '--reporter=junit', '--reporters=blob', '--coverage',
    '--coverage.reportsDirectory=coverage', '--mergeReports', '--cache=true', '--watch', '-w', '--clearCache',
    '--listTags', '--root=/elsewhere', '--passWithNoTests', '--retry=1', '-t', '--testNamePattern=x',
    'real-core-work', '--no-fileParallelism'])('refuses unsafe override %s before launch', async (arg) => {
    const f = fixture()
    await expect(runRealCoreShards({ ...f.options, extraArgs: [arg] })).rejects.toThrow('owned by the gate')
    expect(f.launch).not.toHaveBeenCalled()
    expect(f.timers.size).toBe(0)
  })

  it.each([0, -1, NaN, Infinity])('refuses invalid bounds %j without creating resources', async (bound) => {
    const f = fixture()
    await expect(runRealCoreShards({ ...f.options, shardTimeoutMs: bound })).rejects.toThrow('positive real-core bounds')
    await expect(runRealCoreShards({ ...f.options, aggregateTimeoutMs: bound })).rejects.toThrow('positive real-core bounds')
    expect(f.launch).not.toHaveBeenCalled()
  })
})
