<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { McpServer } from '../../../../shared/api'
import { blank, mcpBody, type Form } from '../../mcp-form'
import { ask } from '../../dialog'
import { settingsUnavailableText as unavailableText } from '../../capability'
import SettingsSection from '../../components/settings/SettingsSection.vue'
import SettingsRow from '../../components/settings/SettingsRow.vue'
import SettingsSwitch from '../../components/settings/SettingsSwitch.vue'
import McpMoreMenu from '../../components/settings/McpMoreMenu.vue'
import {
  deleteMcp,
  loadMcp,
  loadMcpTools,
  management,
  reconnectMcp,
  refreshMcpTools,
  saveMcp,
  setMcpEnabled,
  setMcpGlobal,
  setMcpLimits
} from '../../stores/management'

onMounted(loadMcp)

const shownTools = reactive<Record<string, boolean | undefined>>({})
const limits = reactive<{ perServer: string | number; global: string | number }>({ perServer: '', global: '' })
const limitsError = ref('')


const form = ref<Form | null>(null)
const editorDialog = ref<HTMLDialogElement | null>(null)
let opener: HTMLElement | null = null
const formBusy = computed(() => Boolean(form.value && management.busy[`mcp:${form.value.name}`]))
function edit(server?: McpServer): void {
  if (server && management.busy[`mcp:${server.name}`]) return
  opener = typeof HTMLElement !== 'undefined' && document.activeElement instanceof HTMLElement ? document.activeElement : null
  form.value = blank(server)
}
function cancel(): void { if (!formBusy.value) form.value = null }
watch(() => !!form.value, async (open) => {
  if (!open) editorDialog.value?.close?.()
  await nextTick()
  if (open) editorDialog.value?.showModal?.()
  else if (opener?.isConnected) { opener.focus(); opener = null }
})
onBeforeUnmount(() => { opener = null; editorDialog.value?.close?.(); form.value = null })
const formError = ref('')
watch(form, () => { formError.value = '' }, { deep: true })


function toggleTools(name: string): void {
  shownTools[name] = !shownTools[name]
  if (shownTools[name]) void loadMcpTools(name)
}


async function save(): Promise<void> {
  const f = form.value
  if (!f || formBusy.value) return
  formError.value = ''
  const change = mcpBody(f)
  if (typeof change === 'string') {
    formError.value = change
    return
  }
  // Closes only this form, and only if nothing was changed in it while the save was on its way.
  const sent = JSON.stringify(f)
  if ((await saveMcp(change)) && form.value === f && JSON.stringify(f) === sent) form.value = null
}

async function remove(server: McpServer): Promise<void> {
  if (management.busy[`mcp:${server.name}`]) return
  const confirmed = await ask({
    title: 'Remove this server?',
    message: `${server.name} is stopped and removed, and its tools are no longer offered to Odin.`,
    confirmLabel: 'Remove',
    danger: true
  })
  if (confirmed) await deleteMcp(server.name)
}

async function saveLimits(): Promise<void> {
  limitsError.value = ''
  if ([limits.perServer, limits.global].some((value) => String(value).trim() && (!Number.isInteger(Number(value)) || Number(value) < 0))) {
    limitsError.value = 'Use whole numbers, zero or more.'
    return
  }
  const change: { max_published_tools_per_server?: number; max_published_tools_global?: number } = {}
  if (String(limits.perServer).trim()) change.max_published_tools_per_server = Number(limits.perServer)
  if (String(limits.global).trim()) change.max_published_tools_global = Number(limits.global)
  if (!Object.keys(change).length) return
  const sent = { ...limits }
  await setMcpLimits(change)
  if (management.notes['mcp-limits'] === 'Saved.') {
    if (limits.perServer === sent.perServer) limits.perServer = ''
    if (limits.global === sent.global) limits.global = ''
  }
}
</script>

<template>
  <SettingsSection v-if="management.mcp && !management.unavailable.mcp" title="Availability" aria-label="MCP">
    <SettingsRow label="MCP servers" description="Make server tools available; each action still needs permission." control-id="mcp-enabled">
      <SettingsSwitch id="mcp-enabled" label="MCP servers" :checked="management.mcp.enabled" :disabled="management.busy.mcp" described-by="mcp-enabled-description" @change="setMcpGlobal" />
      <template #note><p class="manage-desc">{{ management.mcp.connected_count }} of {{ management.mcp.server_count }} servers connected · {{ management.mcp.published_tool_count }} tools available</p></template>
    </SettingsRow>
    <p v-if="management.notes.mcp" class="manage-note" role="status">{{ management.notes.mcp }}</p>
  </SettingsSection>

  <SettingsSection title="Servers" aria-label="MCP servers">
    <header class="panel-head">
      <button v-if="!management.unavailable.mcp" class="ghost" @click="edit()">Add server</button>
    </header>
    <p v-if="management.unavailable.mcp" class="capability-unavailable" role="status">{{ unavailableText('MCP management') }}</p>
    <p v-else-if="management.errors.mcp" class="warn">{{ management.errors.mcp }}</p>
    <p v-else-if="!management.mcp" class="manage-desc" role="status">Loading servers…</p>
    <p v-else-if="!management.mcp.servers.length" class="manage-desc">No servers yet. Add a server to connect its tools.</p>
    <p class="manage-desc">Enabling a local server runs its program on this computer.</p>
    <ul v-if="!management.unavailable.mcp" class="manage-list">
      <li v-for="server in management.mcp?.servers ?? []" :key="server.name" :class="['manage-row', server.state]">
        <div class="mcp-server-line">
          <div class="mcp-server-copy"><div class="manage-line">
          <label class="manage-name" :for="`mcp-enabled-${encodeURIComponent(server.name)}`">{{ server.name }}</label>
          <span :class="['state-chip', server.state]">{{ server.state }}</span>
          </div><p class="manage-desc">{{ server.transport }} · {{ server.published_count }} of {{ server.discovered_count }} tools offered<span v-if="server.url_display"> · {{ server.url_display }}</span></p></div>
          <div class="mcp-server-actions">
              <SettingsSwitch :id="`mcp-enabled-${encodeURIComponent(server.name)}`" :label="`${server.enabled ? 'Turn off' : 'Turn on'} ${server.name}`" :checked="server.enabled" :disabled="management.busy[`mcp:${server.name}`]" @change="setMcpEnabled(server.name, $event)" />
            <button class="ghost" :aria-label="`Edit ${server.name}`" :disabled="management.busy[`mcp:${server.name}`]" @click="edit(server)">Edit</button>
            <McpMoreMenu :name="server.name" :enabled="server.enabled" :busy="!!management.busy[`mcp:${server.name}`]" :shown-tools="!!shownTools[server.name]" @action="$event === 'reconnect' ? reconnectMcp(server.name) : $event === 'refresh' ? refreshMcpTools(server.name) : $event === 'tools' ? toggleTools(server.name) : remove(server)" />
          </div>
        </div>
        <p v-if="server.header_keys.length || server.env_keys.length" class="manage-desc">
          Saved securely: {{ [...server.header_keys, ...server.env_keys].join(', ') }}
        </p>
        <p v-if="server.last_error" class="warn">{{ server.last_error }}</p>
        <p v-if="server.blocked_reason" class="warn">{{ server.blocked_reason }}</p>
        <p v-if="server.credential_migration" class="manage-desc">{{ server.credential_migration }}</p>
        <div :id="`mcp-tools-${encodeURIComponent(server.name)}`"><ul v-if="shownTools[server.name]" class="mcp-tools">
          <li v-for="tool in management.mcpTools[server.name] ?? []" :key="tool.original_name">
            <code>{{ tool.published_name }}</code>
            <span class="manage-desc">{{ tool.excluded ? `excluded: ${tool.exclusion_reason}` : tool.description }}</span>
          </li>
        </ul></div>
        <p v-if="management.notes[`mcp:${server.name}`]" class="manage-note" role="status">{{ management.notes[`mcp:${server.name}`] }}</p>
      </li>
    </ul>
  </SettingsSection>

  <dialog v-if="form && !management.unavailable.mcp" ref="editorDialog" class="settings-form-dialog" :aria-label="form.create ? 'Add MCP server' : `Edit MCP server ${form.name}`" @cancel.prevent="cancel">
  <form class="settings-form" aria-label="MCP server form" @submit.prevent="save">
    <h3>{{ form.create ? 'Add a server' : `Edit ${form.name}` }}</h3>
    <p v-if="!form.create" class="panel-hint">Leave a field blank to keep what is stored.</p>
    <fieldset :disabled="formBusy">
    <label v-if="form.create" class="field-input">Name <input v-model="form.name" placeholder="Letters, digits, underscores" /></label>
    <label class="field-input">
      Transport
      <select v-model="form.transport">
        <option value="stdio">stdio: a program on this computer</option>
        <option value="http">http: a server at a URL</option>
      </select>
    </label>
    <template v-if="form.transport === 'stdio'">
      <label class="field-input">Executable <input v-model="form.command" placeholder="/usr/local/bin/my-mcp-server" /></label>
      <label class="field-input">Arguments, one per line <textarea v-model="form.args" rows="3" :disabled="form.clearArgs" /></label>
      <label v-if="!form.create" class="toggle-inline"><input v-model="form.clearArgs" type="checkbox" /> Clear its arguments</label>
    </template>
    <label v-else class="field-input">URL <input v-model="form.url" placeholder="https://…" /></label>
    <details class="settings-more-options">
      <summary>More options</summary>
      <label v-if="form.transport === 'stdio'" class="field-input">Working directory <input v-model="form.cwd" /></label>
    <label class="field-input">Timeout, in seconds <input :value="form.timeout" @input="form.timeout = ($event.target as HTMLInputElement).value" type="number" min="1" :aria-invalid="!!formError || undefined" :aria-describedby="formError ? 'mcp-timeout-error' : undefined" /></label>
    <label class="field-input">
      Only these tools, one per line ({{ form.create ? 'blank: all' : 'blank keeps the current list' }})
      <textarea v-model="form.allowlist" rows="3" :disabled="form.allTools" />
    </label>
    <label v-if="!form.create" class="toggle-inline"><input v-model="form.allTools" type="checkbox" /> Offer all its tools again</label>
    </details>
    <fieldset class="secret-set">
      <legend>Headers and environment</legend>
      <p class="panel-hint">Values are stored for the server and never read back. To change one, enter it again.</p>
      <label v-for="key in form.headerKeys" :key="`h-${key}`" class="toggle-inline">
        <input v-model="form.removeHeaders" type="checkbox" :value="key" /> Remove header {{ key }}
      </label>
      <label v-for="key in form.envKeys" :key="`e-${key}`" class="toggle-inline">
        <input v-model="form.removeEnv" type="checkbox" :value="key" /> Remove variable {{ key }}
      </label>
      <div v-for="(row, i) in form.headers" :key="`nh${i}`" class="field-input">
        <label>Header name {{ i + 1 }} <input v-model="row.key" placeholder="Header" /></label>
        <label>Header value {{ i + 1 }} <input v-model="row.value" type="password" placeholder="Value" autocomplete="off" /></label>
      </div>
      <div v-for="(row, i) in form.env" :key="`ne${i}`" class="field-input">
        <label>Variable name {{ i + 1 }} <input v-model="row.key" placeholder="Variable" /></label>
        <label>Variable value {{ i + 1 }} <input v-model="row.value" type="password" placeholder="Value" autocomplete="off" /></label>
      </div>
      <div class="panel-actions">
        <button type="button" class="ghost" @click="form.headers.push({ key: '', value: '' })">Add a header</button>
        <button type="button" class="ghost" @click="form.env.push({ key: '', value: '' })">Add a variable</button>
      </div>
    </fieldset>
    </fieldset>
    <p v-if="formError" id="mcp-timeout-error" class="warn" role="alert">{{ formError }}</p>
    <p v-else-if="management.notes[`mcp:${form.name}`]" class="manage-note" role="status">{{ management.notes[`mcp:${form.name}`] }}</p>
    <div class="settings-form-actions">
      <button type="button" class="ghost" aria-label="Cancel MCP server changes" :disabled="formBusy" @click="cancel">Cancel</button>
      <button type="button" class="primary" :disabled="formBusy" :aria-label="form.create ? 'Add server (MCP)' : `Save MCP server ${form.name}`" @click="save">{{ form.create ? 'Add server' : 'Save' }}</button>
    </div>
  </form>

  </dialog>
  <details v-if="management.mcp && !management.unavailable.mcp" class="settings-more-options">
    <summary>More options</summary>
    <SettingsSection title="Tool limits">
      <SettingsRow label="Maximum tools per server" control-id="mcp-limit-server">
        <input id="mcp-limit-server" v-model="limits.perServer" type="number" min="0" :placeholder="String(management.mcp.max_published_tools_per_server)" :aria-invalid="!!limitsError || undefined" :aria-describedby="limitsError ? 'mcp-limits-error' : undefined" />
      </SettingsRow>
      <SettingsRow label="Maximum tools in all" control-id="mcp-limit-global">
        <input id="mcp-limit-global" v-model="limits.global" type="number" min="0" :placeholder="String(management.mcp.max_published_tools_global)" :aria-invalid="!!limitsError || undefined" :aria-describedby="limitsError ? 'mcp-limits-error' : undefined" />
      </SettingsRow>
      <div class="panel-actions">
        <button class="ghost" :disabled="management.busy['mcp-limits']" @click="saveLimits">Save limits</button>
        <button class="ghost" @click="limits.perServer = ''; limits.global = ''; limitsError = ''">Cancel limits</button>
      </div>
      <p v-if="limitsError" id="mcp-limits-error" class="warn" role="status">{{ limitsError }}</p>
      <p v-else-if="management.notes['mcp-limits']" class="manage-note" role="status">{{ management.notes['mcp-limits'] }}</p>
    </SettingsSection>
  </details>
</template>

<style scoped>
.mcp-server-line { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; }
.mcp-server-copy { min-width: 0; }
.mcp-server-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
@container (max-width: 440px) { .mcp-server-line { grid-template-columns: minmax(0, 1fr); } }
</style>
