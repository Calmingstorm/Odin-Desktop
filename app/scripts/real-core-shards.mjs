// One reviewed selection, shared by Vitest and the outer scheduler. Whole files
// stay intact: no test-name filters, retries, cache-dependent balancing or skips.
export const REAL_CORE_SHARDS = Object.freeze([
  Object.freeze(['test/real-core-contract.test.ts']),
  Object.freeze(['test/real-core-settings.test.ts', 'test/real-core-completion.test.ts']),
  Object.freeze(['test/real-core-services.test.ts', 'test/real-core-webhooks.test.ts', 'test/real-core-skills.test.ts', 'test/renderer/real-core-renderer-contract.test.ts']),
  Object.freeze(['test/real-core-work.test.ts'])
])
export const REAL_CORE_FILES = Object.freeze(REAL_CORE_SHARDS.flat())
export const SHARD_TIMEOUT_MS = 300_000
export const AGGREGATE_TIMEOUT_MS = 600_000

export function selectRealCoreFiles(shard) {
  if (shard === undefined) return [...REAL_CORE_FILES]
  if (!/^[1-4]\/4$/.test(shard)) throw new Error(`Invalid real-core shard: ${shard}; expected 1/4, 2/4, 3/4 or 4/4.`)
  return [...REAL_CORE_SHARDS[Number(shard[0]) - 1]]
}

// The scheduler never imports engine code or launches a child directly. Each
// call uses the unchanged verified namespace launcher and its own HOME/XDG/tmp.
// Abort requests cleanup; allSettled waits for actual launcher exit before the
// gate resolves. A failed shard is never replayed and cancels its siblings.
export async function runRealCoreShards({ launch, command, args, extraArgs = [], config, cwd, host = process,
  schedule = setTimeout, unschedule = clearTimeout, now = () => performance.now(), report = console.log,
  shardTimeoutMs = SHARD_TIMEOUT_MS, aggregateTimeoutMs = AGGREGATE_TIMEOUT_MS }) {
  for (const bound of [shardTimeoutMs, aggregateTimeoutMs]) {
    if (!Number.isFinite(bound) || bound < 1) throw new Error('Expected positive real-core bounds.')
  }
  // A second selector can silently run only a fraction of this already-sharded
  // suite. File reporters could also overwrite one another's output, including
  // their implicit default paths. Console output stays on the default reporter.
  // No filter is admitted by the full gate; focused tests can use an explicit
  // isolated launcher invocation instead of silently shrinking this selection.
  // Fail closed for flags: Vitest adds aliases and non-running commands (for
  // example --clearCache/listTags). A denylist cannot protect exact selection
  // and shared output against new CLI spelling. Only console presentation is
  // forwarded. Internal command args are separate from user-supplied CLI args.
  const safeFlag = /^(?:--no-color|--color(?:=(?:true|false))?|--silent(?:=(?:true|false|passed-only))?)$/
  if (extraArgs.some((arg) => !safeFlag.test(arg))) {
    throw new Error('Real-core selection/config is owned by the gate; nested selectors, shared output/cache and watch overrides are forbidden.')
  }
  const controller = new AbortController()
  const started = now()
  let failure
  const stop = (error) => {
    if (!failure) failure = error
    controller.abort()
  }
  const interrupt = () => stop(new Error('Real-core shards cancelled by SIGINT.'))
  const terminate = () => stop(new Error('Real-core shards cancelled by SIGTERM.'))
  host.on('SIGINT', interrupt)
  host.on('SIGTERM', terminate)
  const timer = schedule(() => stop(new Error(`Real-core aggregate deadline exceeded (${aggregateTimeoutMs}ms); cancelling all shards.`)), aggregateTimeoutMs)
  try {
    const runShard = async (index) => {
      const files = REAL_CORE_SHARDS[index]
      const shard = `${index + 1}/${REAL_CORE_SHARDS.length}`
      const shardStarted = now()
      report(`Real-core shard ${shard}: ${files.join(', ')}; bound ${shardTimeoutMs}ms`)
      try {
        await launch(command, [...args, ...extraArgs, '--config', config], { cwd, timeoutMs: shardTimeoutMs, signal: controller.signal,
          env: { ODIN_APP_REAL_CORE_SHARD: shard } })
        report(`Real-core shard ${shard} passed in ${Math.round(now() - shardStarted)}ms`)
      } catch (error) {
        stop(new Error(`Real-core shard ${shard} failed: ${error.message}`, { cause: error }))
        throw error
      }
    }
    // WorkProof imports/admits actual managers under a strict 12s test deadline.
    // Measurements show three parallel cold imports can starve that fixture.
    // Drain the first wave before admitting it; do not lengthen its deadline.
    await Promise.allSettled([0, 1, 2].map(runShard))
    if (failure) throw failure
    await Promise.allSettled([runShard(3)])
    if (failure) throw failure
    report(`Real-core: ${REAL_CORE_SHARDS.length} isolated shards passed in ${Math.round(now() - started)}ms; aggregate bound ${aggregateTimeoutMs}ms`)
  } finally {
    unschedule(timer)
    host.off('SIGINT', interrupt)
    host.off('SIGTERM', terminate)
  }
}
