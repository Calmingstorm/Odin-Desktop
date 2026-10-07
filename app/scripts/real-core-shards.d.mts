import type { launchIsolated } from './real-core-isolation.mjs'
export const REAL_CORE_SHARDS: readonly (readonly string[])[]
export const REAL_CORE_FILES: readonly string[]
export const SHARD_TIMEOUT_MS: number
export const AGGREGATE_TIMEOUT_MS: number
export function selectRealCoreFiles(shard?: string): string[]
export function runRealCoreShards(options: {
  launch: typeof launchIsolated
  command: string
  args: string[]
  extraArgs?: string[]
  config: string
  cwd: string
  host?: Pick<NodeJS.Process, 'on' | 'off'>
  schedule?: typeof setTimeout
  unschedule?: typeof clearTimeout
  now?: () => number
  report?: (message: string) => void
  shardTimeoutMs?: number
  aggregateTimeoutMs?: number
}): Promise<void>
