<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, useId, watch } from 'vue'
import type { WorkAction, WorkItem } from '../../../shared/api'
import { select, state } from '../store'
import { actionLabel, bySection, controlWork, isActive, kindLabel, loadWork, work, workKey } from '../stores/work'
import { changedWorkNotices, workAnnouncement, workName } from '../work-accessibility'

const panel = ref<HTMLElement | null>(null)
const refresh = ref<HTMLButtonElement | null>(null)
let opener: HTMLElement | null = null
const groups = computed(bySection)
const prefix = `work-panel-${useId()}`
const itemId = (item: WorkItem, suffix: string): string => `${prefix}-${encodeURIComponent(`${item.kind}:${item.id}`)}-${suffix}`
const steering = reactive<Record<string, boolean>>({})
const steerText = reactive<Record<string, string>>({})
const announcement = ref('')
const pending = new Map<string, string>()
let noticeTimer: ReturnType<typeof setTimeout> | undefined

function plainState(item: WorkItem): string {
  if (item.kind === 'process' && item.state === 'exited' && typeof details(item).exit_code === 'number' && details(item).exit_code !== 0) return 'Failed'
  const labels: Record<string, string> = {
    admitted: 'Starting', starting: 'Starting', running: 'Running', stopping: 'Stopping',
    completed: 'Done', done: 'Done', exited: 'Done', failed: 'Failed', error: 'Failed',
    timeout: 'Timed out', timed_out: 'Timed out', killed: 'Stopped', cancelled: 'Stopped',
    stopped: 'Stopped', interrupted: 'Interrupted', paused: 'Paused', scheduled: 'Scheduled',
    active: item.kind === 'schedule' ? 'Scheduled' : 'Running', unknown: 'Unknown'
  }
  return labels[item.state] ?? item.state.replaceAll('_', ' ').replace(/^./, (first) => first.toUpperCase())
}

function details(item: WorkItem): Record<string, unknown> {
  return typeof item.detail === 'string' ? {} : item.detail
}

/** Display only actual user-facing output, never recursively print the manager record. */
function output(item: WorkItem): Array<{ label: string; text: string }> {
  const detail = details(item)
  const text = (value: unknown): string => typeof value === 'string' && !['Not reported', 'None reported'].includes(value.trim()) ? value.trim() : ''
  const result = text(detail.result) || text(detail.last_result) || (typeof item.detail === 'string' ? text(item.detail) : '')
  const error = text(detail.last_error) || text(detail.error)
  return [...(result ? [{ label: 'Result', text: result }] : []), ...(error ? [{ label: 'Last error', text: error }] : [])]
}

/** ISO and retained-manager Unix seconds both become local short dates. Invalid dates are omitted. */
function shortTime(value: unknown): string {
  if ((typeof value !== 'string' && typeof value !== 'number') || value === '') return ''
  const millis = typeof value === 'number' ? value * 1000 : Date.parse(value)
  if (!Number.isFinite(millis)) return ''
  const date = new Date(millis)
  if (!Number.isFinite(date.getTime())) return ''
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  const day = date.toDateString() === today.toDateString() ? 'Today'
    : date.toDateString() === yesterday.toDateString() ? 'Yesterday'
      : date.toLocaleDateString([], { month: 'short', day: 'numeric', ...(date.getFullYear() === today.getFullYear() ? {} : { year: 'numeric' as const }) })
  return `${day} ${date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
}

function times(item: WorkItem): Array<{ label: string; text: string }> {
  const detail = details(item)
  const values: Array<{ label: string; value: unknown }> = [{ label: item.kind === 'schedule' ? 'Created' : 'Started', value: item.started_at }]
  if (item.kind === 'schedule') values.push({ label: 'Next run', value: detail.next_run }, { label: 'Last run', value: detail.last_run })
  return values.flatMap(({ label, value }) => {
    const text = shortTime(value)
    return text ? [{ label, text }] : []
  })
}

function unknownOutcome(item: WorkItem): boolean {
  const unconfirmed = (value: unknown): boolean => {
    if (!value || typeof value !== 'object') return false
    const settlement = value as Record<string, unknown>
    return settlement.state === 'unknown' || (!isActive(item) && ['unknown', 'unproven'].includes(String(settlement.resource_release)))
  }
  return item.state === 'unknown' || item.state === 'interrupted' || unconfirmed(item.settlement)
    || (item.kind === 'schedule' && (unconfirmed(item.settlement?.last_run) || unconfirmed(details(item).settlement)))
}

watch(() => groups.value.flatMap((group) => group.items.map((item) => ({
  key: `${item.kind}:${item.id}`, name: workName(item), state: item.state,
  busy: Boolean(work.busy[workKey(item)]), note: work.notes[workKey(item)] ?? ''
}))), (current, previous) => {
  for (const notice of changedWorkNotices(current, previous)) {
    const item = groups.value.flatMap((group) => group.items).find((item) => `${item.kind}:${item.id}` === notice.key)
    const lifecycle = item && notice.text === `${workName(item)}. ${item.state}.`
    pending.set(notice.key, lifecycle ? `${workName(item)}. ${plainState(item)}.` : notice.text)
  }
  if (!pending.size) return
  clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => {
    announcement.value = workAnnouncement([...pending.values()])
    pending.clear()
  }, 150)
})

// A completed row may move sections or lose its controls. Repair only focus owned by the removed row.
watch(() => groups.value.map((group) => `${group.kind}=` + group.items.map((item) => `${item.kind}:${item.id}:${item.actions.join(',')}`).join('|')).join('||'), async () => {
  const active = document.activeElement as HTMLElement | null
  const row = active?.closest?.<HTMLElement>('.work-item')
  if (!row?.id.startsWith(`${prefix}-`)) return
  await nextTick()
  if (!active?.isConnected && document.activeElement === document.body) document.getElementById(row.id)?.focus()
})

async function control(item: WorkItem, action: WorkAction, event: MouseEvent): Promise<void> {
  if (work.busy[workKey(item)]) return
  const initiating = event.currentTarget as HTMLElement
  const ownedFocus = document.activeElement === initiating
  await controlWork(item, action)
  await nextTick()
  if (ownedFocus && !initiating.isConnected && document.activeElement === document.body) document.getElementById(itemId(item, 'item'))?.focus()
}

async function showSteer(item: WorkItem): Promise<void> {
  if (work.busy[workKey(item)] || !item.actions.includes('steer') || item.kind !== 'agent') return
  steering[workKey(item)] = true
  await nextTick()
  document.getElementById(itemId(item, 'steer-text'))?.focus()
}

async function submitSteer(item: WorkItem): Promise<void> {
  const key = workKey(item)
  const text = steerText[key] ?? ''
  const accepted = await controlWork(item, 'steer', text)
  if (accepted && steerText[key] === text) steerText[key] = ''
}

function titleOf(conversationId: string): string | null {
  return state.conversations.find((conversation) => conversation.id === conversationId)?.title ?? null
}

async function open(conversationId: string, event: MouseEvent): Promise<void> {
  const initiating = event.currentTarget as HTMLElement
  const ownedFocus = document.activeElement === initiating
  state.view = 'chat'
  await select(conversationId)
  if (ownedFocus && state.activeId === conversationId && (document.activeElement === initiating || (!initiating.isConnected && document.activeElement === document.body))) {
    work.open = false
    await nextTick()
    document.getElementById('conversation-history')?.focus()
  }
}

onMounted(() => {
  opener = document.activeElement as HTMLElement | null
  refresh.value?.focus?.()
})

function restoreFocus(): void {
  if (opener?.isConnected && typeof opener.focus === 'function') opener.focus()
  else document.querySelector<HTMLButtonElement>('.work-toggle')?.focus()
}

function close(): void {
  work.open = false
  restoreFocus()
}

// An inline region, not a modal. Tab may leave it; the rest of chat stays available.
onBeforeUnmount(() => {
  clearTimeout(noticeTimer)
  if (panel.value?.contains?.(document.activeElement)) restoreFocus()
})
</script>

<template>
  <section ref="panel" class="work-panel" aria-label="Work" @keydown.esc.prevent.stop="close">
    <header class="work-head">
      <strong>Work</strong>
      <span class="work-hint">Agents, tasks, workflows, loops, processes and schedules started from your chats.</span>
      <button ref="refresh" class="ghost" aria-label="Refresh work" title="Fetch the list again" @click="loadWork">Refresh</button>
      <button class="ghost" aria-label="Close work" title="Close work" @click="close"><span aria-hidden="true">✕</span></button>
    </header>
    <p class="work-announcement" role="status" aria-live="polite" aria-atomic="true">{{ announcement }}</p>
    <p v-if="work.error" :class="work.unavailable ? 'capability-unavailable' : 'warn'" :role="work.unavailable ? 'status' : 'alert'">{{ work.error }}</p>
    <p v-else-if="work.loaded && !groups.length" class="work-empty">No work is listed.</p>
    <div v-for="group in groups" :key="group.kind" class="work-group">
      <h2>{{ group.label }} <span class="work-count">{{ group.items.length }}</span></h2>
      <article v-for="item in group.items" :id="itemId(item, 'item')" :key="`${item.kind}:${item.id}`" :class="['work-item', { done: !isActive(item) }]" tabindex="-1" :aria-labelledby="itemId(item, 'title')" :aria-describedby="itemId(item, 'state')">
        <div class="work-line">
          <span :id="itemId(item, 'state')" :class="['work-state', item.state]">{{ plainState(item) }}</span>
          <strong :id="itemId(item, 'title')" class="work-title">{{ item.title }}</strong>
          <span class="work-actions">
            <button v-for="action in item.actions" :key="action" class="ghost"
              :aria-disabled="Boolean(work.busy[workKey(item)])" :aria-label="`${actionLabel(action)} ${workName(item)}`"
              :aria-describedby="[itemId(item, 'state'), work.notes[workKey(item)] ? itemId(item, 'note') : ''].filter(Boolean).join(' ')"
              :aria-expanded="action === 'steer' ? Boolean(steering[workKey(item)]) : undefined"
              :aria-controls="action === 'steer' ? itemId(item, 'steer-form') : undefined"
              @click="action === 'steer' ? showSteer(item) : control(item, action, $event)">{{ actionLabel(action) }}</button>
          </span>
        </div>
        <div class="work-meta">
          <span class="work-kind">{{ kindLabel(item.kind) }}</span>
          <span v-for="time in times(item)" :key="time.label">{{ time.label }} {{ time.text }}</span>
          <button v-if="item.conversation_id && titleOf(item.conversation_id)" class="work-link" :aria-label="`Open conversation ${titleOf(item.conversation_id)} for ${workName(item)}`" @click="open(item.conversation_id, $event)">Open conversation {{ titleOf(item.conversation_id) }}</button>
        </div>
        <p v-for="value in output(item)" :key="value.label" class="work-output"><strong>{{ value.label }}:</strong> {{ value.text }}</p>
        <p v-if="unknownOutcome(item)" class="work-note">The outcome is not confirmed.</p>
        <form v-if="item.kind === 'agent' && item.actions.includes('steer') && steering[workKey(item)]" :id="itemId(item, 'steer-form')" class="work-steer" @submit.prevent="submitSteer(item)">
          <label :for="itemId(item, 'steer-text')">Steer {{ workName(item) }}</label>
          <textarea :id="itemId(item, 'steer-text')" v-model="steerText[workKey(item)]" rows="3" :readonly="Boolean(work.busy[workKey(item)])" :aria-describedby="itemId(item, 'steer-help')" />
          <p :id="itemId(item, 'steer-help')" class="work-note">Sent once to the agent inbox. Queued is not consumed. Unknown outcomes are not retried.</p>
          <button type="submit" class="ghost" :aria-label="`Send steer to ${workName(item)}`" :aria-disabled="Boolean(work.busy[workKey(item)]) || !(steerText[workKey(item)] ?? '')">Send steer</button>
        </form>
        <p v-if="work.notes[workKey(item)]" :id="itemId(item, 'note')" class="work-note">{{ work.notes[workKey(item)] }}</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.work-actions button[aria-disabled='true'] { opacity: 0.5; cursor: default; }
.work-output { white-space: pre-wrap; overflow-wrap: anywhere; }
.work-steer { display: grid; gap: 0.5rem; margin-top: 0.75rem; }
.work-steer textarea { width: 100%; resize: vertical; }
.work-steer button { justify-self: start; }
.work-steer button[aria-disabled='true'] { opacity: 0.5; cursor: default; }
.work-announcement {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}
</style>
