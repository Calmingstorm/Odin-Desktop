<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { Message } from '../../../shared/api'
import { images, showsInline, type ImageHandle } from '../artifacts'
import { onCodeCopyClick } from '../code-copy'
import { plainTextOf, renderMarkdown } from '../markdown'
import { startThread, type ToolEntry } from '../store'
import FileCard from './FileCard.vue'
import Icon from './Icon.vue'
import ReportViewer from './ReportViewer.vue'
import ToolActivity from './ToolActivity.vue'
import appIcon from '../../../../resources/icon.svg'

const props = defineProps<{
  message: Message
  conversationId: string
  tools?: ToolEntry[]
  highlight?: boolean
  /** Copy and thread actions; off in the view around a search result. */
  actions?: boolean
}>()

const copyOpen = ref(false)
const copied = ref('')
const copyButton = ref<HTMLButtonElement | null>(null)
const copyChoices = ref<HTMLElement | null>(null)
// Tool publications retain their notice transcript role (they are not a guarded model reply).
// Present their known producer, without relabelling genuine notices or user attachments.
const displayRole = computed(() => props.message.role === 'notice' && props.message.author === 'odin' &&
  props.message.request_id && props.message.artifacts?.length ? 'assistant' : props.message.role)
const messageLabel = computed(() => `${who(displayRole.value)} message at ${time(props.message.created_at)}`)
const avatar = computed(() => displayRole.value === 'user' ? 'person' : 'info')
watch(copyOpen, async (open) => {
  await nextTick()
  if (open) copyChoices.value?.querySelector<HTMLButtonElement>('button')?.focus()
})
function closeCopy(): void {
  copyOpen.value = false
  copyButton.value?.focus()
}
/** blob: URLs for inline images; null once an image can't be shown, so it falls back to a file card. */
const sources = reactive<Record<string, string | null | undefined>>({})

const artifacts = computed(() => props.message.artifacts ?? [])
const inline = computed(() => artifacts.value.filter((a) => showsInline(a) && sources[a.ref] !== null))
const files = computed(() => artifacts.value.filter((a) => a.kind !== 'report' && (!showsInline(a) || sources[a.ref] === null)))
const reports = computed(() => artifacts.value.filter((a) => a.kind === 'report'))
const html = computed(() => renderMarkdown(props.message.text))

const held = new Map<string, ImageHandle>()

function loadImages(): void {
  for (const artifact of artifacts.value) {
    if (!showsInline(artifact) || held.has(artifact.ref)) continue
    const handle = images.acquire(artifact)
    held.set(artifact.ref, handle)
    sources[artifact.ref] = undefined
    void handle.url.then((url) => (sources[artifact.ref] = url))
  }
}
onMounted(loadImages)
watch(artifacts, loadImages)
onBeforeUnmount(() => {
  for (const handle of held.values()) handle.release()
  held.clear()
})

function who(role: string): string {
  return role === 'user' ? 'You' : role === 'assistant' ? 'Odin' : 'Notice'
}

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function copy(kind: 'markdown' | 'plain'): Promise<void> {
  closeCopy()
  const text = kind === 'markdown' ? props.message.text : plainTextOf(props.message.text)
  const result = await window.odin.copyText(text)
  copied.value = result.ok ? 'Copied' : "Couldn't copy"
  setTimeout(() => (copied.value = ''), 1500)
}

/** An image the window can't decode (a TIFF, say) is offered as a file instead. */
function onImageError(ref: string): void {
  sources[ref] = null
}
</script>

<template>
  <article :id="`m-${message.id}`" :class="['msg', displayRole, { highlight }]" tabindex="-1" :aria-label="messageLabel">
    <span class="avatar" aria-hidden="true">
      <img v-if="displayRole === 'assistant'" class="app-icon" :src="appIcon" width="36" height="36" alt="" />
      <Icon v-else :name="avatar" :size="18" />
    </span>
    <div class="meta">
      <span class="who">{{ who(displayRole) }}</span>
      <time :datetime="message.created_at">{{ time(message.created_at) }}</time>
      <span v-if="actions" class="msg-actions">
        <span class="copied" role="status" aria-atomic="true">{{ copied }}</span>
        <button ref="copyButton" class="msg-action" :aria-label="`Copy ${messageLabel}`" :aria-expanded="copyOpen" :aria-controls="`copy-${message.id}`" @click="copyOpen = !copyOpen">Copy</button>
        <button
          class="msg-action"
          :aria-label="`Thread from here: ${messageLabel}`"
          title="Start a new thread that carries this conversation's context up to here"
          @click="startThread(conversationId, message.id)"
        >
          Thread from here
        </button>
      </span>
    </div>
    <ToolActivity v-if="message.role === 'assistant' && tools?.length" :entries="tools" :request-id="message.request_id" />
    <div v-if="copyOpen" :id="`copy-${message.id}`" ref="copyChoices" class="copy-choices" @keydown.esc.prevent.stop="closeCopy">
      <button class="ghost" @click="copy('markdown')">Copy as Markdown</button>
      <button class="ghost" @click="copy('plain')">Copy as plain text</button>
    </div>
    <div v-if="message.text" class="body md" @click="onCodeCopyClick" v-html="html" />
    <ul v-if="message.attachments?.length" class="msg-attachments" aria-label="Attachments">
      <li v-for="a in message.attachments" :key="a.ref">{{ a.name }} · {{ fileSize(a.size) }}</li>
    </ul>
    <div v-if="inline.length" class="artifact-images">
      <figure v-for="a in inline" :key="a.ref" class="artifact-image">
        <img v-if="sources[a.ref]" :src="sources[a.ref] ?? undefined" :alt="a.name" @error="onImageError(a.ref)" />
        <span v-else class="image-loading">Loading {{ a.name }}…</span>
        <figcaption>{{ a.name }}</figcaption>
        <FileCard :artifact="a" actions-only />
      </figure>
    </div>
    <FileCard v-for="a in files" :key="a.ref" :artifact="a" />
    <ReportViewer v-for="a in reports" :key="a.ref" :artifact="a" />
  </article>
</template>

<style scoped>
article:focus-visible, button:focus-visible, .md :deep(button:focus-visible), .md :deep(a:focus-visible) { outline: 2px solid var(--accent, #91baff); outline-offset: 3px; }
article:focus-within { content-visibility: visible; }
.msg.assistant > .avatar { background: transparent; border-radius: 0; }
.app-icon { display: block; width: 100%; height: 100%; }
</style>
