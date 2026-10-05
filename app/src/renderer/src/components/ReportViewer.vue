<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { ArtifactRef } from '../../../shared/api'
import { onCodeCopyClick } from '../code-copy'
import { renderMarkdown } from '../markdown'

const props = defineProps<{ artifact: ArtifactRef }>()
const page = ref(1)
const pages = ref(0)
const text = ref('')
const loading = ref(false)
const error = ref('')

/** Reads a stored page. It never runs the check again. */
async function load(target: number): Promise<void> {
  loading.value = true
  error.value = ''
  const result = await window.odin.reportPage({ report_id: props.artifact.ref, page: target })
  loading.value = false
  if (!result.ok) {
    error.value = result.error.message
    return
  }
  page.value = result.result.page
  pages.value = result.result.pages
  text.value = result.result.text
}

onMounted(() => {
  if (props.artifact.available) void load(1)
})
</script>

<template>
  <section class="report" :aria-label="artifact.name">
    <header class="report-head">
      <strong>{{ artifact.name }}</strong>
      <span v-if="pages" class="report-pages">Page {{ page }} of {{ pages }}</span>
      <span class="report-nav" title="Pages are the stored result; paging never runs the check again.">
        <button class="ghost" :disabled="loading || page <= 1" @click="load(page - 1)">Previous</button>
        <button class="ghost" :disabled="loading || page >= pages" @click="load(page + 1)">Next</button>
      </span>
    </header>
    <p v-if="!artifact.available" class="report-note">This report is no longer available.</p>
    <p v-else-if="error" class="report-note warn">{{ error }}</p>
    <p v-else-if="loading && !text" class="report-note">Loading…</p>
    <div v-else class="md report-body" @click="onCodeCopyClick" v-html="renderMarkdown(text)" />
  </section>
</template>
