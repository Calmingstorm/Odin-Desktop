<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import type { McpServer } from '../../../../shared/api'
import { blank, mcpBody, type Form } from '../../mcp-form'
import { ask } from '../../dialog'
import { unavailableText } from '../../capability'
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
const limits = reactive({ perServer: '', global: '' })


const form = ref<Form | null>(null)
const formError = ref('')
watch(form, () => { formError.value = '' }, { deep: true })


function toggleTools(name: string): void {
  shownTools[name] = !shownTools[name]
  if (shownTools[name]) void loadMcpTools(name)
}


async function save(): Promise<void> {
  const f = form.value
  if (!f) return
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
  const confirmed = await ask({
    title: 'Remove this server?',
    message: `${server.name} is stopped and removed, and its tools are no longer offered to Odin.`,
    confirmLabel: 'Remove',
    danger: true
  })
  if (confirmed) await deleteMcp(server.name)
}

async function saveLimits(): Promise<void> {
  const change: { max_published_tools_per_server?: number; max_published_tools_global?: number } = {}
  if (limits.perServer.trim()) change.max_published_tools_per_server = Number(limits.perServer)
  if (limits.global.trim()) change.max_published_tools_global = Number(limits.global)
  await setMcpLimits(change)
}
</script>

<template>
  <section v-if="management.mcp && !management.unavailable.mcp" class="panel" aria-label="MCP">
    <header class="panel-head">
      <h3>MCP</h3>
      <span class="panel-hint">
        {{ management.mcp.connected_count }} of {{ management.mcp.server_count }} servers connected,
        {{ management.mcp.published_tool_count }} tools offered to Odin.
      </span>
      <label class="toggle-inline">
        <input type="checkbox" :checked="management.mcp.enabled" @change="setMcpGlobal(($event.target as HTMLInputElement).checked)" />
        MCP on
      </label>
    </header>
    <div class="limits">
      <span class="panel-hint">Most tools offered to Odin:</span>
      <label class="limit">Maximum tools per server <input v-model="limits.perServer" type="number" min="0" :placeholder="String(management.mcp.max_published_tools_per_server)" /></label>
      <label class="limit">Maximum tools in all <input v-model="limits.global" type="number" min="0" :placeholder="String(management.mcp.max_published_tools_global)" /></label>
      <button class="ghost" @click="saveLimits">Save limits</button>
    </div>
    <p v-if="management.notes.mcp || management.notes['mcp-limits']" class="manage-note" role="status">
      {{ management.notes.mcp ?? management.notes['mcp-limits'] }}
    </p>
  </section>

  <section class="panel" aria-label="MCP servers">
    <header class="panel-head">
      <h3>Servers</h3>
      <button v-if="!management.unavailable.mcp" class="ghost" @click="form = blank()">Add server</button>
    </header>
    <p v-if="management.unavailable.mcp" class="capability-unavailable" role="status">{{ unavailableText('MCP management') }}</p>
    <p v-else-if="management.errors.mcp" class="warn">{{ management.errors.mcp }}</p>
    <ul v-if="!management.unavailable.mcp" class="manage-list">
      <li v-for="server in management.mcp?.servers ?? []" :key="server.name" :class="['manage-row', server.state]">
        <div class="manage-line">
          <code class="manage-name">{{ server.name }}</code>
          <span class="tag">{{ server.transport }}</span>
          <span :class="['state-chip', server.state]">{{ server.state }}</span>
          <span class="manage-count">{{ server.published_count }} of {{ server.discovered_count }} tools offered</span>
          <span class="manage-actions">
            <button class="ghost" :aria-label="`${server.enabled ? 'Turn off' : 'Turn on'} ${server.name}`" :disabled="management.busy[`mcp:${server.name}`]" @click="setMcpEnabled(server.name, !server.enabled)">
              {{ server.enabled ? 'Turn off' : 'Turn on' }}
            </button>
            <button class="ghost" :aria-label="`Reconnect ${server.name}`" :disabled="!server.enabled || management.busy[`mcp:${server.name}`]" @click="reconnectMcp(server.name)">Reconnect</button>
            <button class="ghost" :aria-label="`Refresh tools for ${server.name}`" :disabled="!server.enabled || management.busy[`mcp:${server.name}`]" @click="refreshMcpTools(server.name)">Refresh tools</button>
            <button class="ghost" :aria-label="`${shownTools[server.name] ? 'Hide tools' : 'Tools'} for ${server.name}`" :aria-expanded="!!shownTools[server.name]" :aria-controls="`mcp-tools-${encodeURIComponent(server.name)}`" @click="toggleTools(server.name)">{{ shownTools[server.name] ? 'Hide tools' : 'Tools' }}</button>
            <button class="ghost" :aria-label="`Edit ${server.name}`" @click="form = blank(server)">Edit</button>
            <button class="ghost danger-item" :aria-label="`Remove ${server.name}…`" @click="remove(server)">Remove…</button>
          </span>
        </div>
        <p v-if="server.url_display" class="manage-desc">{{ server.url_display }}</p>
        <p v-if="server.header_keys.length || server.env_keys.length" class="manage-desc">
          Stored, never shown: {{ [...server.header_keys.map((k) => `header ${k}`), ...server.env_keys.map((k) => `env ${k}`)].join(', ') }}
        </p>
        <p v-if="server.last_error" class="warn">{{ server.last_error }}</p>
        <p v-if="server.blocked_reason" class="warn">{{ server.blocked_reason }}</p>
        <div :id="`mcp-tools-${encodeURIComponent(server.name)}`"><ul v-if="shownTools[server.name]" class="mcp-tools">
          <li v-for="tool in management.mcpTools[server.name] ?? []" :key="tool.original_name">
            <code>{{ tool.published_name }}</code>
            <span class="manage-desc">{{ tool.excluded ? `excluded: ${tool.exclusion_reason}` : tool.description }}</span>
          </li>
        </ul></div>
        <p v-if="management.notes[`mcp:${server.name}`]" class="manage-note" role="status">{{ management.notes[`mcp:${server.name}`] }}</p>
      </li>
    </ul>
  </section>

  <section v-if="form && !management.unavailable.mcp" class="panel" aria-label="MCP server form">
    <header class="panel-head">
      <h3>{{ form.create ? 'Add a server' : `Edit ${form.name}` }}</h3>
      <span v-if="!form.create" class="panel-hint">Leave a field blank to keep what is stored.</span>
      <button class="ghost" aria-label="Close MCP server form" @click="form = null">Close</button>
    </header>
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
      <label class="field-input">Working directory <input v-model="form.cwd" /></label>
    </template>
    <label v-else class="field-input">URL <input v-model="form.url" placeholder="https://…" /></label>
    <label class="field-input">Timeout, in seconds <input :value="form.timeout" @input="form.timeout = ($event.target as HTMLInputElement).value" type="number" min="1" :aria-invalid="!!formError || undefined" :aria-describedby="formError ? 'mcp-timeout-error' : undefined" /></label>
    <label class="field-input">
      Only these tools, one per line ({{ form.create ? 'blank: all' : 'blank keeps the current list' }})
      <textarea v-model="form.allowlist" rows="3" :disabled="form.allTools" />
    </label>
    <label v-if="!form.create" class="toggle-inline"><input v-model="form.allTools" type="checkbox" /> Offer all its tools again</label>
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
        <button class="ghost" @click="form.headers.push({ key: '', value: '' })">Add a header</button>
        <button class="ghost" @click="form.env.push({ key: '', value: '' })">Add a variable</button>
      </div>
    </fieldset>
    <div class="panel-actions">
      <button class="ghost" :aria-label="form.create ? 'Add MCP server' : `Save MCP server ${form.name}`" @click="save">{{ form.create ? 'Add' : 'Save' }}</button>
    </div>
    <p v-if="formError" id="mcp-timeout-error" class="warn" role="alert">{{ formError }}</p>
    <p v-else-if="management.notes[`mcp:${form.name}`]" class="manage-note" role="status">{{ management.notes[`mcp:${form.name}`] }}</p>
  </section>
</template>
