<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { menuKey } from '../../conversation-menu-keys'
const props = defineProps<{ name: string; enabled: boolean; busy: boolean; shownTools: boolean }>()
const emit = defineEmits<{ action: [action: 'reconnect' | 'refresh' | 'tools' | 'remove'] }>()
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const open = ref(false)
const position = ref({ top: '0px', left: '0px' })
const id = `mcp-more-${encodeURIComponent(props.name)}`
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
  if (rect) position.value = { top: `${Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - 180))}px`, left: `${Math.max(8, Math.min(rect.right - 200, window.innerWidth - 208))}px` }
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
async function choose(action: 'reconnect' | 'refresh' | 'tools' | 'remove'): Promise<void> {
  if (props.busy || (['reconnect', 'refresh'].includes(action) && !props.enabled)) return
  // Restore the real row opener before the next dialog captures focus.
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
  <div :id="id" ref="menu" class="mcp-more-menu" popover="auto" role="menu" :aria-label="`More actions for ${name}`" :style="position" @keydown="onKey" @toggle="open = $event.newState === 'open'">
    <button type="button" role="menuitem" tabindex="-1" :aria-label="`Reconnect ${name}`" :disabled="!enabled || busy" @click="choose('reconnect')">Reconnect</button>
    <button type="button" role="menuitem" tabindex="-1" :aria-label="`Refresh tools for ${name}`" :disabled="!enabled || busy" @click="choose('refresh')">Refresh tools</button>
    <button type="button" role="menuitem" tabindex="-1" :aria-label="`${shownTools ? 'Hide tools' : 'Tools'} for ${name}`" :aria-expanded="shownTools" :aria-controls="`mcp-tools-${encodeURIComponent(name)}`" :disabled="busy" @click="choose('tools')">{{ shownTools ? 'Hide tools' : 'Tools' }}</button>
    <button type="button" role="menuitem" tabindex="-1" class="danger-item" :aria-label="`Remove ${name}…`" :disabled="busy" @click="choose('remove')">Remove…</button>
  </div>
</template>
<style scoped>
.mcp-more-menu { position: fixed; inset: auto; width: 200px; max-width: calc(100vw - 16px); max-height: calc(100vh - 16px); overflow: auto; margin: 0; padding: 4px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--fg); box-shadow: 0 4px 20px rgb(0 0 0 / 30%); }
.mcp-more-menu button { display: block; width: 100%; text-align: left; padding: 8px 12px; background: transparent; color: inherit; border: 0; border-radius: 4px; }
.mcp-more-menu button:hover, .mcp-more-menu button:focus-visible { background: var(--raise); }
.mcp-more-menu button:disabled { opacity: .5; }
.mcp-more-menu .danger-item { color: var(--bad); }
</style>
