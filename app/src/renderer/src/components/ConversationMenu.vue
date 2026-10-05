<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import type { Conversation } from '../../../shared/api'
import { ask } from '../dialog'
import { deleteConversation, isMuted, renameConversation, resetContext, setArchived, setMuted, startThread } from '../store'

const props = defineProps<{ conversation: Conversation; top: number; left: number }>()
const MENU_WIDTH = 200
const position = computed(() => ({
  top: `${props.top}px`,
  left: `${Math.max(8, Math.min(props.left - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8))}px`
}))
const emit = defineEmits<{ close: [] }>()
const menu = ref<HTMLElement | null>(null)

onMounted(async () => {
  await nextTick()
  menu.value?.querySelector('button')?.focus()
})

async function rename(): Promise<void> {
  emit('close')
  const title = await ask({
    title: 'Rename conversation',
    message: '',
    confirmLabel: 'Rename',
    input: { value: props.conversation.title, label: 'Title', maxLength: 200 }
  })
  if (typeof title === 'string' && title.trim() && title.trim() !== props.conversation.title) {
    await renameConversation(props.conversation.id, title.trim())
  }
}

async function thread(): Promise<void> {
  emit('close')
  await startThread(props.conversation.id)
}

async function mute(): Promise<void> {
  emit('close')
  await setMuted(props.conversation.id, !isMuted(props.conversation.id))
}

async function archive(): Promise<void> {
  emit('close')
  await setArchived(props.conversation.id, !props.conversation.archived)
}

async function reset(): Promise<void> {
  emit('close')
  const confirmed = await ask({
    title: 'Reset context?',
    message:
      'Odin starts fresh in this conversation. Everything above stays visible; it just stops being part of what Odin remembers here.',
    confirmLabel: 'Reset context',
    danger: true
  })
  if (confirmed) await resetContext(props.conversation.id)
}

async function remove(): Promise<void> {
  emit('close')
  const confirmed = await ask({
    title: 'Delete conversation?',
    message: `“${props.conversation.title}” and its files will be deleted. This can't be undone.`,
    confirmLabel: 'Delete',
    danger: true
  })
  if (confirmed) await deleteConversation(props.conversation.id)
}
</script>

<template>
  <Teleport to="body">
    <div class="menu-backdrop" @click="emit('close')" />
    <div ref="menu" class="menu" role="menu" :style="position" @keydown.escape="emit('close')">
      <button role="menuitem" @click="rename">Rename…</button>
      <button role="menuitem" @click="thread">New thread from here</button>
      <button role="menuitem" @click="mute">{{ isMuted(conversation.id) ? 'Unmute notifications' : 'Mute notifications' }}</button>
      <button role="menuitem" @click="archive">{{ conversation.archived ? 'Unarchive' : 'Archive' }}</button>
      <button role="menuitem" @click="reset">Reset context…</button>
      <button role="menuitem" class="danger-item" @click="remove">Delete…</button>
    </div>
  </Teleport>
</template>
