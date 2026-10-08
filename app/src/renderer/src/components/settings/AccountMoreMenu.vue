<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { menuKey } from '../../conversation-menu-keys'
const props = defineProps<{ accountId: number; name: string; busy: boolean; refreshDisabled: boolean; canRename: boolean }>()
type Action = 'refresh' | 'rename' | 'remove'
const emit = defineEmits<{ action: [action: Action] }>()
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const open = ref(false)
const position = ref({ top: '0px', left: '0px' })
const id = `account-more-${props.accountId}`
function items(): HTMLButtonElement[] { return Array.from(menu.value?.querySelectorAll?.<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? []) }
async function close(restore = true): Promise<void> {
  open.value = false
  menu.value?.hidePopover?.()
  if (restore) trigger.value?.focus?.()
}
async function show(last = false): Promise<void> {
  if (props.busy) return
  if (open.value) { await close(); return }
  const rect = trigger.value?.getBoundingClientRect?.()
  if (rect) position.value = { top: `${Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - 150))}px`, left: `${Math.max(8, Math.min(rect.right - 200, window.innerWidth - 208))}px` }
  open.value = true
  await nextTick()
  menu.value?.showPopover?.()
  const controls = items()
  controls[last ? controls.length - 1 : 0]?.focus()
}
function onKey(event: KeyboardEvent): void {
  const controls = items()
  const action = menuKey(event.key, controls.indexOf(document.activeElement as HTMLButtonElement), controls.length)
  if (action === null) return
  if (event.key !== 'Tab') event.preventDefault()
  event.stopPropagation()
  if (action === 'close') void close()
  else controls[action]?.focus()
}
async function choose(action: Action): Promise<void> {
  if (props.busy || (action === 'refresh' && props.refreshDisabled) || (action === 'rename' && !props.canRename)) return
  // Restore the row opener before the account dialog captures focus.
  await close()
  await nextTick()
  emit('action', action)
}
function triggerKey(event: KeyboardEvent): void {
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
  event.preventDefault()
  void show(event.key === 'ArrowUp')
}
onBeforeUnmount(() => { menu.value?.hidePopover?.() })
</script>
<template>
  <button ref="trigger" type="button" class="ghost" :aria-label="`More actions for ${name}`" aria-haspopup="menu" :aria-expanded="open" :aria-controls="id" :disabled="busy" @click="show()" @keydown="triggerKey">More</button>
  <div :id="id" ref="menu" class="account-more-menu" popover="auto" role="menu" :aria-label="`More actions for ${name}`" :style="position" @keydown="onKey" @toggle="open = $event.newState === 'open'">
    <button type="button" role="menuitem" tabindex="-1" :aria-label="`Refresh sign-in: ${name}`" :disabled="busy || refreshDisabled" @click="choose('refresh')">Refresh sign-in</button>
    <button v-if="canRename" type="button" role="menuitem" tabindex="-1" :aria-label="`Rename ${name}`" :disabled="busy" @click="choose('rename')">Rename</button>
    <button type="button" role="menuitem" tabindex="-1" class="danger-item" :aria-label="`Remove ${name}`" :disabled="busy" @click="choose('remove')">Remove…</button>
  </div>
</template>
<style scoped>
.account-more-menu { position: fixed; inset: auto; width: 200px; max-width: calc(100vw - 16px); max-height: calc(100vh - 16px); overflow: auto; margin: 0; padding: 4px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--fg); box-shadow: 0 4px 20px rgb(0 0 0 / 30%); }
.account-more-menu button { display: block; width: 100%; text-align: left; padding: 8px 12px; background: transparent; color: inherit; border: 0; border-radius: 4px; }
.account-more-menu button:hover, .account-more-menu button:focus-visible { background: var(--raise); }
.account-more-menu button:disabled { opacity: .5; }
.account-more-menu .danger-item { color: var(--bad); }
</style>
