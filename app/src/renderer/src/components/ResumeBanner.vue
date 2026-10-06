<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { canAct, resume, resumeKey, resumeTarget, state } from '../store'

const props = defineProps<{ conversationId: string }>()

const target = computed(() => resumeTarget(state.views[props.conversationId]))
const resumeButton = ref<HTMLButtonElement | null>(null)
const attempt = computed(() => (target.value ? state.resumes[resumeKey(target.value.outcome)] : undefined))
const what = computed(() => (target.value?.outcome.outcome === 'suspended' ? 'was suspended' : 'was interrupted'))
const disabled = computed(() => attempt.value?.status === 'sending' || attempt.value?.status === 'unknown' || !canAct(props.conversationId))
watch(() => Boolean(target.value && attempt.value?.status !== 'admitted' && !target.value.blocked), async (visible) => {
  if (visible || document.activeElement !== resumeButton.value) return
  await nextTick()
  if (document.activeElement === document.body) document.getElementById('conversation-history')?.focus()
})
async function resumeTask(event: MouseEvent): Promise<void> {
  if (disabled.value || !target.value) return
  const button = event.currentTarget as HTMLButtonElement
  const wasFocused = document.activeElement === button
  await resume(props.conversationId, target.value.outcome)
  await nextTick()
  if (wasFocused && !button.isConnected && document.activeElement === document.body) document.getElementById('conversation-history')?.focus()
}
</script>

<template>
  <div v-if="target && attempt?.status !== 'admitted'" class="resume-banner">
    <p v-if="target.blocked">The last task {{ what }}. {{ target.blocked }}</p>
    <p v-else>The last task {{ what }} before it finished. Odin kept its progress and can carry on from there.</p>
    <button
      v-if="!target.blocked"
      ref="resumeButton"
      class="ghost"
      aria-label="Resume the last task"
      :aria-disabled="disabled"
      @click="resumeTask"
    >
      {{ attempt?.status === 'sending' ? 'Resuming…' : 'Resume' }}
    </button>
    <p class="tool-note" role="status" aria-atomic="true">{{ attempt?.status === 'unknown' ? 'Resume outcome unknown. Waiting for Odin to confirm; it is never sent twice.' : attempt?.status === 'sending' ? 'Resuming the last task.' : '' }}</p>
    <p v-if="attempt?.status === 'rejected' || attempt?.status === 'failed'" class="warn" role="alert">{{ attempt.reason }}</p>
  </div>
</template>

<style scoped>
button:focus-visible { outline: 2px solid var(--accent, #91baff); outline-offset: 3px; }
button[aria-disabled="true"] { opacity: .65; }
</style>
