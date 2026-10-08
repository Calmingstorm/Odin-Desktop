import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { state, stopPending } from './store'

/** Both Stop and the working line use the same invocation clock, never the request's age. */
export function useStoppingLabel() {
  const now = ref(Date.now())
  const running = computed(() => state.activeId ? state.views[state.activeId]?.running : null)
  const stopping = computed(() => Boolean(running.value && stopPending(running.value.request_id, running.value.generation)))
  const tool = computed(() => {
    const request = running.value
    if (!request || !state.activeId) return undefined
    return state.views[state.activeId]?.tools[request.request_id]?.find((entry) => !entry.outcome &&
      (entry.generation === undefined || entry.generation === request.generation))
  })
  let timer: ReturnType<typeof setInterval> | undefined
  watch(() => stopping.value && Boolean(tool.value), (active) => {
    if (timer !== undefined) clearInterval(timer)
    timer = undefined
    now.value = Date.now()
    if (active) timer = setInterval(() => { now.value = Date.now() }, 1000)
  }, { immediate: true })
  onBeforeUnmount(() => { if (timer !== undefined) clearInterval(timer) })
  const label = computed(() => {
    const entry = tool.value
    if (!entry) return 'Stopping…'
    const start = Date.parse(entry.started_at ?? '')
    const seconds = Math.max(0, Math.floor((now.value - start) / 1000))
    const elapsed = Number.isFinite(start) ? ` (${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')})` : ''
    return `Stopping… waiting for ${entry.tool} to finish${elapsed}`
  })
  return { stopping, label }
}
