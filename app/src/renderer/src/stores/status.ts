// What the status bar shows: the core's model, providers and health, and usage, quota and context as the core
// measured, estimated or doesn't know. Fetched when the link becomes ready, and again shortly after a request settles
// or the core reports a status change.
import { reactive } from 'vue'
import type { CoreEvent, CoreStatus, UsageResult } from '../../../shared/api'
import { onCoreEvent, onReady } from '../store'

export const status = reactive({
  core: null as CoreStatus | null,
  usage: null as UsageResult | null
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
  const [core, usage] = await Promise.all([window.odin.status(), window.odin.usage('24h')])
  if (mine !== latest) return
  if (core.ok) status.core = core.result
  if (usage.ok) status.usage = usage.result
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
