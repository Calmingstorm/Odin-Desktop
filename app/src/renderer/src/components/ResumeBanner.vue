<script setup lang="ts">
import { computed } from 'vue'
import { canAct, resume, resumeKey, resumeTarget, state } from '../store'

const props = defineProps<{ conversationId: string }>()

const target = computed(() => resumeTarget(state.views[props.conversationId]))
const attempt = computed(() => (target.value ? state.resumes[resumeKey(target.value.outcome)] : undefined))
const what = computed(() => (target.value?.outcome.outcome === 'suspended' ? 'was suspended' : 'was interrupted'))
</script>

<template>
  <div v-if="target && attempt?.status !== 'admitted'" class="resume-banner" role="status">
    <p v-if="target.blocked">The last task {{ what }}. {{ target.blocked }}</p>
    <p v-else>The last task {{ what }} before it finished. Ask Odin to resume from any progress he preserved.</p>
    <button
      v-if="!target.blocked"
      class="ghost"
      :disabled="attempt?.status === 'sending' || attempt?.status === 'unknown' || !canAct(conversationId)"
      @click="resume(conversationId, target.outcome)"
    >
      {{ attempt?.status === 'sending' ? 'Resuming…' : 'Resume' }}
    </button>
    <p v-if="attempt?.status === 'unknown'" class="tool-note">Waiting for Odin to confirm the resume. It is never sent twice.</p>
    <p class="tool-note">Use Resume to carry on. Typing “continue” is an ordinary message in this core, not a resume control.</p>
    <p v-if="attempt?.status === 'rejected' || attempt?.status === 'failed'" class="warn">{{ attempt.reason }}</p>
  </div>
</template>
