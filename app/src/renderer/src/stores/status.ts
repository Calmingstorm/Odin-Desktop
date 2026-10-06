// What the status bar shows: the core's model, providers and health, and usage, quota and context as the core
// measured, estimated or doesn't know. Fetched when the link becomes ready, and again shortly after a request settles
// or the core reports a status change.
import { reactive, watch } from 'vue'
import type { CoreEvent, CoreStatus, UsageResult, Result } from '../../../shared/api'
import { onCoreEvent, onReady, state } from '../store'
import { isUnavailable, resultMessage } from '../capability'

export const status = reactive({
  core: null as CoreStatus | null,
  usage: null as UsageResult | null,
  coreError: '',
  epoch: -1,
  usageError: '',
  usageUnavailable: false
})

const REFRESH_ON = new Set([
  'runtime.status',
  'request.completed',
  'request.failed',
  'request.cancelled',
  'request.interrupted',
  'request.suspended'
])

let latest = 0

/** Fetches status and usage. A refresh started after this one, including one for a recovery, answers instead. */
export async function refreshStatus(): Promise<void> {
  const mine = ++latest
  const epoch = state.recoveryEpoch
  const instance = state.app.coreInstanceId
  const unavailable: Result<never> = { ok: false, error: { code: 'unavailable', message: 'The core could not be reached.' } }
  const read = async <T>(request: () => Promise<Result<T>>): Promise<Result<T>> => {
    try { return await request() } catch { return unavailable }
  }
  const [core, usage] = await Promise.all([read(() => window.odin.status()), read(() => window.odin.usage('24h'))])
  if (mine !== latest || epoch !== state.recoveryEpoch || instance !== state.app.coreInstanceId) return
  status.epoch = epoch
  status.core = core.ok ? core.result : null
  status.coreError = resultMessage(core, 'Core status')
  status.usage = usage.ok ? usage.result : null
  status.usageError = resultMessage(usage, 'Usage')
  status.usageUnavailable = !usage.ok && isUnavailable(usage.error)
}

let timer: ReturnType<typeof setTimeout> | null = null

export function applyStatusEvent(event: CoreEvent): void {
  if (!REFRESH_ON.has(event.type) || timer) return
  timer = setTimeout(() => {
    timer = null
    void refreshStatus()
  }, 1000)
}

onCoreEvent(applyStatusEvent)
onReady(() => void refreshStatus())

// Link recovery invalidates every previous provider verdict, including in-flight status reads.
watch(() => [state.app.link, state.app.coreInstanceId, state.recoveryEpoch], () => {
  latest += 1
  status.core = null
  status.coreError = ''
  status.epoch = -1
}, { flush: 'sync' })
