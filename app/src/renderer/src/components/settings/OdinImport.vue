<script setup lang="ts">
import { computed, nextTick, reactive, ref } from 'vue'
import type { OdinImportCategory, OdinImportItem, OdinImportOutcome, OdinImportPick, OdinImportReport } from '../../../../shared/api'

const GROUPS: Array<{ category: OdinImportCategory; title: string }> = [
  { category: 'memory', title: 'Memory' },
  { category: 'skills', title: 'Skills' },
  { category: 'mcp', title: 'MCP servers' },
  { category: 'personality', title: 'Personality' },
  { category: 'hosts', title: 'Hosts' },
  { category: 'models', title: 'Settings' }
]
const STATUS_TITLES: Record<OdinImportOutcome['status'], string> = {
  needs_attention: 'Needs your attention',
  failed: "Couldn't import",
  imported: 'Imported',
  skipped: 'Already there'
}

const dialog = ref<HTMLDialogElement | null>(null)
// Rendered only while open, so its controls never mix with the page's own.
const shown = ref(false)
const step = ref<'connect' | 'choose' | 'results'>('connect')
const busy = ref(false)
const error = ref('')
const copied = ref('')
// The token lives only in this dialog, for this import, and is cleared when it closes.
const form = reactive({ url: 'http://localhost:3002', token: '' })
const items = ref<OdinImportItem[]>([])
const picked = ref<string[]>([])
const report = ref<OdinImportReport | null>(null)

const key = (item: { category: OdinImportCategory; id: string }): string => `${item.category}/${item.id}`
const groups = computed(() => GROUPS
  .map((group) => ({ ...group, items: items.value.filter((item) => item.category === group.category) }))
  .filter((group) => group.items.length))
const picks = computed<OdinImportPick[]>(() => items.value
  .filter((item) => !item.exists && picked.value.includes(key(item)))
  .map((item) => ({ category: item.category, id: item.id })))
const outcomeGroups = computed(() => (Object.keys(STATUS_TITLES) as Array<OdinImportOutcome['status']>)
  .map((status) => ({ status, title: STATUS_TITLES[status], outcomes: (report.value?.outcomes ?? []).filter((row) => row.status === status) }))
  .filter((group) => group.outcomes.length))
const retryHosts = computed<OdinImportPick[]>(() => (report.value?.outcomes ?? [])
  .filter((row) => row.category === 'hosts' && row.status === 'needs_attention')
  .map((row) => ({ category: row.category, id: row.id })))

async function open(): Promise<void> {
  step.value = 'connect'
  error.value = ''
  report.value = null
  shown.value = true
  await nextTick()
  dialog.value?.showModal?.()
}

function close(): void {
  form.token = ''
  items.value = []
  picked.value = []
  report.value = null
  error.value = ''
  copied.value = ''
  dialog.value?.close?.()
  shown.value = false
}

async function look(): Promise<void> {
  if (busy.value) return
  error.value = ''
  if (!form.url.trim() || !form.token.trim()) {
    error.value = "Enter Odin's address and an API token."
    return
  }
  busy.value = true
  try {
    const answer = await window.odin.odinImportPreview({ url: form.url.trim(), token: form.token.trim() })
    if (!answer.ok) {
      error.value = answer.error.message
      return
    }
    items.value = answer.result.items
    picked.value = answer.result.items.filter((item) => item.selected && !item.exists).map(key)
    step.value = 'choose'
  } catch {
    error.value = "Couldn't ask Odin. Try again."
  } finally {
    busy.value = false
  }
}

async function run(selection: OdinImportPick[]): Promise<void> {
  if (busy.value || !selection.length) return
  error.value = ''
  busy.value = true
  try {
    const answer = await window.odin.odinImportApply({ url: form.url.trim(), token: form.token.trim(), picks: selection })
    if (!answer.ok) {
      error.value = answer.error.message
      return
    }
    report.value = answer.result
    step.value = 'results'
  } catch {
    error.value = "The import didn't finish. Nothing more was changed."
  } finally {
    busy.value = false
  }
}

async function copyKey(): Promise<void> {
  const text = report.value?.public_key
  if (!text) return
  const answer = await window.odin.copyText(text)
  copied.value = answer.ok ? 'Copied.' : 'Copy failed. Select the key and copy it.'
}

defineExpose({ open })
</script>

<template>
  <button type="button" class="ghost" @click="open">Import from Odin</button>
  <dialog v-if="shown" ref="dialog" class="settings-form-dialog odin-import" aria-label="Import from Odin" @cancel.prevent="close">
    <form class="settings-form" aria-label="Import from Odin" @submit.prevent="step === 'connect' ? look() : step === 'choose' ? run(picks) : close()">
      <h3>Import from Odin</h3>

      <template v-if="step === 'connect'">
        <p class="panel-hint">Odin Desktop reads what your Odin has through Odin's API. Nothing in Odin changes.</p>
        <fieldset :disabled="busy">
          <label class="field-input">Odin's address <input v-model="form.url" type="url" autocomplete="off" placeholder="http://localhost:3002" /></label>
          <label class="field-input">
            Admin API token
            <input v-model="form.token" type="password" autocomplete="off" placeholder="From Odin's WebUI" />
          </label>
          <p class="panel-hint">Used for this import only and never saved.</p>
        </fieldset>
      </template>

      <template v-else-if="step === 'choose'">
        <p class="panel-hint">Pick what to bring over. Things Odin Desktop already has are left as they are.</p>
        <p v-if="!groups.length" class="panel-hint">Odin has nothing to import.</p>
        <fieldset v-for="group in groups" :key="group.category" class="odin-import-group" :disabled="busy">
          <legend>{{ group.title }}</legend>
          <label v-for="item in group.items" :key="key(item)" class="odin-import-item">
            <input v-model="picked" type="checkbox" :value="key(item)" :disabled="item.exists" />
            <span class="odin-import-copy">
              <span class="odin-import-label">{{ item.label }}</span>
              <span v-if="item.exists" class="odin-import-detail">Already in Odin Desktop</span>
              <span v-else-if="item.detail" class="odin-import-detail">{{ item.detail }}</span>
              <span v-for="note in item.notes" :key="note" class="odin-import-note">{{ note }}</span>
            </span>
          </label>
        </fieldset>
      </template>

      <template v-else>
        <section v-for="group in outcomeGroups" :key="group.status" class="odin-import-group" :aria-label="group.title">
          <h4>{{ group.title }}</h4>
          <ul class="odin-import-outcomes">
            <li v-for="row in group.outcomes" :key="key(row)">
              <span class="odin-import-label">{{ row.label }}</span>
              <span class="odin-import-detail">{{ row.message }}</span>
            </li>
          </ul>
        </section>
        <section v-if="report?.public_key" class="odin-import-group" aria-label="Odin Desktop's SSH key">
          <h4>Odin Desktop's SSH key</h4>
          <p class="panel-hint">Add this line to <code>~/.ssh/authorized_keys</code> for the user on each host above, then retry.</p>
          <textarea class="odin-import-key" readonly rows="3" :value="report.public_key" aria-label="Odin Desktop's SSH public key" />
          <div class="panel-actions">
            <button type="button" class="ghost" @click="copyKey">Copy key</button>
            <span v-if="copied" role="status">{{ copied }}</span>
          </div>
        </section>
      </template>

      <p v-if="error" class="warn" role="alert">{{ error }}</p>
      <p v-else-if="busy" class="manage-note" role="status">{{ step === 'connect' ? 'Looking in Odin…' : 'Importing…' }}</p>

      <div class="settings-form-actions">
        <template v-if="step === 'connect'">
          <button type="button" class="ghost" :disabled="busy" @click="close">Cancel</button>
          <button type="submit" class="primary" :disabled="busy">Look in Odin</button>
        </template>
        <template v-else-if="step === 'choose'">
          <button type="button" class="ghost" :disabled="busy" @click="step = 'connect'">Back</button>
          <button type="button" class="ghost" :disabled="busy" @click="close">Cancel</button>
          <button type="submit" class="primary" :disabled="busy || !picks.length">{{ picks.length ? `Import ${picks.length}` : 'Import' }}</button>
        </template>
        <template v-else>
          <button v-if="retryHosts.length" type="button" class="ghost" :disabled="busy" @click="run(retryHosts)">Retry hosts</button>
          <button type="submit" class="primary" :disabled="busy">Done</button>
        </template>
      </div>
    </form>
  </dialog>
</template>
