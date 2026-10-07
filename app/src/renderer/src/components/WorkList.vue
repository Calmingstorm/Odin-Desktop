<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, useId, watch } from 'vue'
import type { WorkAction, WorkItem, WorkKind } from '../../../shared/api'
import { select, state } from '../store'
import { actionLabel, bySection, controlWork, grouped, isActive, kindLabel, work, workKey } from '../stores/work'
import { changedWorkNotices, workAnnouncement, workName } from '../work-accessibility'
import { detailFields, settlementFields, workStartedLabel } from '../work-format'

/** `sections`: running, scheduled and finished work, as the Work column shows it; otherwise grouped by kind. */
const props = defineProps<{ kinds?: WorkKind[]; emptyText?: string; sections?: boolean }>()

const groups = computed<Array<{ kind: string; label: string; items: WorkItem[] }>>(() => props.sections
  ? bySection()
  : grouped().filter((group) => !props.kinds || props.kinds.includes(group.kind)))
const prefix = `work-${useId()}`
// A shared schedule lock uses its manager ID, but rows remain distinct immutable work generations.
const itemId = (item: Parameters<typeof workKey>[0], suffix: string): string => `${prefix}-${encodeURIComponent(`${item.kind}:${item.id}`)}-${suffix}`
const announcement = ref('')
const steering = reactive<Record<string, boolean>>({})
const steerText = reactive<Record<string, string>>({})
const pending = new Map<string, string>()
let noticeTimer: ReturnType<typeof setTimeout> | undefined

watch(
  () => groups.value.flatMap((group) => group.items.map((item) => ({
    key: `${item.kind}:${item.id}`, name: workName(item), state: item.state,
    busy: Boolean(work.busy[workKey(item)]), note: work.notes[workKey(item)] ?? ''
  }))),
  (current, previous) => {
    for (const notice of changedWorkNotices(current, previous)) pending.set(notice.key, notice.text)
    if (!pending.size) return
    clearTimeout(noticeTimer)
    noticeTimer = setTimeout(() => {
      announcement.value = workAnnouncement([...pending.values()])
      pending.clear()
    }, 150)
  }
)
onBeforeUnmount(() => clearTimeout(noticeTimer))

// A later core event may remove a completed item's controls after the initial command receipt, or, in the Work
// column, move its whole row to another section (running to finished), which renders a new row. Save only this
// list's current focus, and repair it only when that exact node was removed. The section is part of the watched
// value: a move can leave every item's kind, id and actions unchanged.
watch(
  () => groups.value.map((group) => `${group.kind}=` + group.items.map((item) => `${item.kind}:${item.id}:${item.actions.join(',')}`).join('|')).join('||'),
  async () => {
    const active = document.activeElement as HTMLElement | null
    const row = active?.closest?.<HTMLElement>('.work-item')
    if (!row?.id.startsWith(`${prefix}-`)) return
    await nextTick()
    if (!active?.isConnected && document.activeElement === document.body) {
      document.getElementById(row.id)?.focus()
    }
  }
)

async function control(item: WorkItem, action: WorkAction, event: MouseEvent): Promise<void> {
  if (work.busy[workKey(item)]) return // existing store lock; keep the button focusable while awaiting its receipt
  const initiating = event.currentTarget as HTMLElement
  const ownedFocus = document.activeElement === initiating
  await controlWork(item, action)
  await nextTick()
  if (ownedFocus && !initiating.isConnected && document.activeElement === document.body) {
    document.getElementById(itemId(item, 'item'))?.focus()
  }
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
  // A queued receipt is delivery to the inbox, not proof the agent consumed it. Never replay on a missing receipt.
  if (accepted && steerText[key] === text) steerText[key] = ''
}

function titleOf(conversationId: string): string | null {
  return state.conversations.find((c) => c.id === conversationId)?.title ?? null
}

/** Opens the conversation the work belongs to, from the Work panel or the settings menu. */
async function open(conversationId: string, event: MouseEvent): Promise<void> {
  const initiating = event.currentTarget as HTMLElement
  const ownedFocus = document.activeElement === initiating
  state.view = 'chat'
  await select(conversationId)
  // Never take focus back from someone who moved on while the conversation loaded.
  if (ownedFocus && state.activeId === conversationId && (document.activeElement === initiating || (!initiating.isConnected && document.activeElement === document.body))) {
    work.open = false
    await nextTick()
    document.getElementById('conversation-history')?.focus()
  }
}
</script>

<template>
  <p class="work-announcement" role="status" aria-live="polite" aria-atomic="true">{{ announcement }}</p>
  <p v-if="work.error" :class="work.unavailable ? 'capability-unavailable' : 'warn'" :role="work.unavailable ? 'status' : 'alert'">{{ work.error }}</p>
  <p v-else-if="work.loaded && !groups.length" class="work-empty">{{ emptyText ?? 'No work is listed.' }}</p>
  <div v-for="group in groups" :key="group.kind" class="work-group">
    <h2>{{ group.label }} <span class="work-count">{{ group.items.length }}</span></h2>
    <article v-for="item in group.items" :id="itemId(item, 'item')" :key="`${item.kind}:${item.id}`" :class="['work-item', { done: !isActive(item) }]" tabindex="-1" :aria-labelledby="itemId(item, 'title')" :aria-describedby="itemId(item, 'state')">
      <div class="work-line">
        <span :id="itemId(item, 'state')" :class="['work-state', item.state]">{{ item.state }}</span>
        <strong :id="itemId(item, 'title')" class="work-title">{{ item.title }}</strong>
        <span class="work-actions">
          <button
            v-for="action in item.actions"
            :key="action"
            class="ghost"
            :aria-disabled="Boolean(work.busy[workKey(item)])"
            :aria-label="`${actionLabel(action)} ${workName(item)}`"
            :aria-describedby="[itemId(item, 'state'), work.notes[workKey(item)] ? itemId(item, 'note') : ''].filter(Boolean).join(' ')"
            :aria-expanded="action === 'steer' ? Boolean(steering[workKey(item)]) : undefined"
            :aria-controls="action === 'steer' ? itemId(item, 'steer-form') : undefined"
            @click="action === 'steer' ? showSteer(item) : control(item, action, $event)"
          >
            {{ actionLabel(action) }}
          </button>
        </span>
      </div>
      <div class="work-meta">
        <span v-if="sections" class="work-kind">{{ kindLabel(item.kind) }}</span>
        <span v-if="typeof item.detail === 'string' && item.detail">{{ item.detail }}</span>
        <span v-if="item.started_at != null">started {{ workStartedLabel(item.started_at) }}</span>
        <button v-if="item.conversation_id && titleOf(item.conversation_id)" class="work-link" :aria-label="`Open conversation ${titleOf(item.conversation_id)} for ${workName(item)}`" @click="open(item.conversation_id, $event)">
          Open conversation {{ titleOf(item.conversation_id) }}
        </button>
      </div>
      <dl v-if="detailFields(item).length" class="work-details" aria-label="Work details">
        <template v-for="field in detailFields(item)" :key="field.key">
          <dt>{{ field.label }}</dt><dd>{{ field.value }}</dd>
        </template>
      </dl>
      <div v-if="item.settlement" class="work-settlement">
        <strong>Settlement</strong>
        <dl class="work-details" aria-label="Work settlement">
          <template v-for="field in settlementFields(item.settlement)" :key="field.key">
            <dt>{{ field.label }}</dt><dd>{{ field.value }}</dd>
          </template>
        </dl>
        <p v-if="item.settlement.state === 'unknown' || ['unknown', 'unproven'].includes(item.settlement.resource_release ?? '')" class="work-note">Resource release is not confirmed. A finished or stopped label alone does not prove release.</p>
      </div>
      <form v-if="item.kind === 'agent' && item.actions.includes('steer') && steering[workKey(item)]" :id="itemId(item, 'steer-form')" class="work-steer" @submit.prevent="submitSteer(item)">
        <label :for="itemId(item, 'steer-text')">Steer {{ workName(item) }}</label>
        <textarea :id="itemId(item, 'steer-text')" v-model="steerText[workKey(item)]" rows="3" :readonly="Boolean(work.busy[workKey(item)])" :aria-describedby="itemId(item, 'steer-help')" />
        <p :id="itemId(item, 'steer-help')" class="work-note">Sent once to the agent inbox. Queued is not consumed. Unknown outcomes are not retried.</p>
        <button type="submit" class="ghost" :aria-label="`Send steer to ${workName(item)}`" :aria-disabled="Boolean(work.busy[workKey(item)]) || !(steerText[workKey(item)] ?? '')">Send steer</button>
      </form>
      <p v-if="work.notes[workKey(item)]" :id="itemId(item, 'note')" class="work-note">{{ work.notes[workKey(item)] }}</p>
    </article>
  </div>
</template>

<style scoped>
.work-actions button[aria-disabled='true'] {
  opacity: 0.5;
  cursor: default;
}
.work-details {
  display: grid;
  grid-template-columns: minmax(8rem, 1fr) minmax(0, 3fr);
  gap: 0.25rem 0.75rem;
  font-size: 0.85rem;
  margin: 0.5rem 0;
}
.work-details dt { color: var(--muted); }
.work-details dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.work-steer { display: grid; gap: 0.5rem; margin-top: 0.75rem; }
.work-steer textarea { width: 100%; resize: vertical; }
.work-steer button { justify-self: start; }
.work-steer button[aria-disabled='true'] { opacity: 0.5; cursor: default; }
.work-settlement { margin-top: 0.5rem; }
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
