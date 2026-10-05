<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import type { Conversation } from '../../../shared/api'
import { ask } from '../dialog'
import { deleteConversation, isMuted, renameConversation, resetContext, setArchived, setMuted, startThread } from '../store'
import { menuKey } from '../conversation-menu-keys'

const props = defineProps<{ conversation: Conversation; top: number; left: number; id?: string }>()
const MENU_WIDTH = 200
const menuHeight = ref(0)
const position = computed(() => ({
  top: `${Math.max(8, Math.min(props.top, window.innerHeight - menuHeight.value - 8))}px`,
  left: `${Math.max(8, Math.min(props.left - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8))}px`,
  maxWidth: 'calc(100vw - 16px)',
  maxHeight: 'calc(100vh - 16px)',
  overflowY: 'auto' as const
}))
const emit = defineEmits<{ close: [] }>()
const menu = ref<HTMLElement | null>(null)

function onKey(event: KeyboardEvent): void {
  const items = Array.from(menu.value?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])
  const action = menuKey(event.key, items.indexOf(document.activeElement as HTMLButtonElement), items.length)
  if (action === null) return
  // Tab exits normally from the restored opener; a menu is not a focus-trapping dialog.
  if (event.key !== 'Tab') event.preventDefault()
  event.stopPropagation()
  if (action === 'close') emit('close')
  else items[action]?.focus()
}

onMounted(async () => {
  await nextTick()
  menuHeight.value = menu.value?.offsetHeight ?? 0
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
    <div :id="id" ref="menu" class="menu" role="menu" :aria-label="`Actions for ${conversation.title}`" :style="position" @keydown="onKey">
      <button role="menuitem" tabindex="-1" @click="rename">Rename…</button>
      <button role="menuitem" tabindex="-1" @click="thread">New thread from here</button>
      <button role="menuitem" tabindex="-1" @click="mute">{{ isMuted(conversation.id) ? 'Unmute notifications' : 'Mute notifications' }}</button>
      <button role="menuitem" tabindex="-1" @click="archive">{{ conversation.archived ? 'Unarchive' : 'Archive' }}</button>
      <button role="menuitem" tabindex="-1" @click="reset">Reset context…</button>
      <button role="menuitem" tabindex="-1" class="danger-item" @click="remove">Delete…</button>
    </div>
  </Teleport>
</template>
