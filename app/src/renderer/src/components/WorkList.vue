<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import type { WorkAction, WorkItem, WorkKind } from '../../../shared/api'
import { select, state } from '../store'
import { actionLabel, controlWork, grouped, isActive, work, workKey } from '../stores/work'
import { changedWorkNotices, workAnnouncement, workName } from '../work-accessibility'

const props = defineProps<{ kinds?: WorkKind[]; emptyText?: string }>()

const groups = computed(() => grouped().filter((group) => !props.kinds || props.kinds.includes(group.kind)))
const prefix = `work-${useId()}`
const itemId = (item: Parameters<typeof workKey>[0], suffix: string): string => `${prefix}-${encodeURIComponent(workKey(item))}-${suffix}`
const announcement = ref('')
const pending = new Map<string, string>()
let noticeTimer: ReturnType<typeof setTimeout> | undefined

watch(
  () => groups.value.flatMap((group) => group.items.map((item) => ({
    key: workKey(item), name: workName(item), state: item.state,
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

// A later core event may remove a completed item's controls after the initial command receipt.
// Save only this list's current focus, and repair it only when that exact node was removed.
watch(
  () => groups.value.map((group) => group.items.map((item) => `${workKey(item)}:${item.actions.join(',')}`).join('|')).join('|'),
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

function titleOf(conversationId: string): string | null {
  return state.conversations.find((c) => c.id === conversationId)?.title ?? null
}

function started(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
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
  <p v-else-if="work.loaded && !groups.length" class="work-empty">{{ emptyText ?? 'Nothing is running.' }}</p>
  <div v-for="group in groups" :key="group.kind" class="work-group">
    <h3>{{ group.label }} <span class="work-count">{{ group.items.length }}</span></h3>
    <article v-for="item in group.items" :id="itemId(item, 'item')" :key="workKey(item)" :class="['work-item', { done: !isActive(item) }]" tabindex="-1" :aria-labelledby="itemId(item, 'title')" :aria-describedby="itemId(item, 'state')">
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
            @click="control(item, action, $event)"
          >
            {{ actionLabel(action) }}
          </button>
        </span>
      </div>
      <div class="work-meta">
        <span v-if="item.detail">{{ item.detail }}</span>
        <span v-if="item.started_at">started {{ started(item.started_at) }}</span>
        <button v-if="item.conversation_id && titleOf(item.conversation_id)" class="work-link" :aria-label="`Open conversation ${titleOf(item.conversation_id)} for ${workName(item)}`" @click="open(item.conversation_id, $event)">
          Open conversation {{ titleOf(item.conversation_id) }}
        </button>
      </div>
      <p v-if="work.notes[workKey(item)]" :id="itemId(item, 'note')" class="work-note">{{ work.notes[workKey(item)] }}</p>
    </article>
  </div>
</template>

<style scoped>
.work-actions button[aria-disabled='true'] {
  opacity: 0.5;
  cursor: default;
}
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
