<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { ArtifactRef } from '../../../shared/api'
import { onCodeCopyClick } from '../code-copy'
import { renderMarkdown } from '../markdown'

const props = defineProps<{ artifact: ArtifactRef }>()
const page = ref(1)
const pages = ref(0)
const text = ref('')
const loading = ref(false)
const error = ref('')
const status = ref('')
const actionBusy = ref(false)
const requestedPage = ref(1)
const body = computed(() => renderMarkdown(text.value))
const previousUnavailable = computed(() => loading.value || actionBusy.value || !props.artifact.available || page.value <= 1)
const nextUnavailable = computed(() => loading.value || actionBusy.value || !props.artifact.available || page.value >= pages.value)

/** Reads a stored page. It never runs the check again. */
async function load(target: number): Promise<void> {
  if (loading.value || actionBusy.value || !props.artifact.available || target < 1 || (pages.value > 0 && target > pages.value)) return
  requestedPage.value = target
  loading.value = true
  error.value = ''
  status.value = `Loading page ${target} of ${props.artifact.name}…`
  try {
    const result = await window.odin.reportPage({ report_id: props.artifact.ref, page: target })
    if (!result.ok) {
      error.value = result.error.message
      status.value = `Could not load page ${target} of ${props.artifact.name}: ${result.error.message}`
      return
    }
    page.value = result.result.page
    pages.value = result.result.pages
    text.value = result.result.text
    status.value = `${props.artifact.name}: page ${page.value} of ${pages.value} loaded.`
  } catch {
    error.value = 'Could not load this page. Try again.'
    status.value = `Could not load page ${target} of ${props.artifact.name}. Try again.`
  } finally {
    loading.value = false
  }
}

async function act(kind: 'copy' | 'save'): Promise<void> {
  if (actionBusy.value || loading.value || !props.artifact.available || (kind === 'copy' && !pages.value)) return
  actionBusy.value = true
  const name = props.artifact.name
  const copiedPage = page.value
  status.value = kind === 'copy' ? `Copying page ${copiedPage} of ${name}…` : `Saving ${name}…`
  try {
    if (kind === 'copy') {
      const result = await window.odin.copyText(text.value)
      status.value = !result.ok ? `${name}: ${result.error.message}` : result.result.copied
        ? `Copied page ${copiedPage} of ${name}.` : `Could not copy page ${copiedPage} of ${name}.`
    } else {
      const result = await window.odin.saveArtifact({ ref: props.artifact.ref, name })
      status.value = !result.ok ? `${name}: ${result.error.message}` : result.result.saved
        ? `Saved ${name}.` : `Save cancelled for ${name}.`
    }
  } catch {
    status.value = `Could not ${kind} ${name}. Try again.`
  } finally {
    actionBusy.value = false
  }
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
        <button type="button" class="ghost" :aria-label="`Previous page of ${artifact.name}`" :aria-disabled="previousUnavailable" @click="!previousUnavailable && load(page - 1)">Previous</button>
        <button type="button" class="ghost" :aria-label="`Next page of ${artifact.name}`" :aria-disabled="nextUnavailable" @click="!nextUnavailable && load(page + 1)">Next</button>
        <button type="button" class="ghost" :aria-label="`Copy page of ${artifact.name}`" :aria-disabled="actionBusy || loading || !pages || !artifact.available" @click="act('copy')">Copy page</button>
        <button type="button" class="ghost" :aria-label="`Save ${artifact.name} as…`" :aria-disabled="actionBusy || loading || !artifact.available" @click="act('save')">Save as…</button>
        <button type="button" class="ghost" :aria-label="`Retry loading ${artifact.name}`" :aria-disabled="loading || actionBusy || !error || !artifact.available" @click="error && load(requestedPage)">Retry</button>
      </span>
    </header>
    <p v-if="!artifact.available" class="report-note">This report is no longer available.</p>
    <p class="report-note" role="status" aria-atomic="true">{{ status }}</p>
    <div class="md report-body" :aria-busy="loading" @click="onCodeCopyClick" v-html="body" />
  </section>
</template>
