<script setup lang="ts">
import { computed, ref } from 'vue'
import State from './State.vue'
import Records from './Records.vue'
import SettingEditor from '../../components/settings/SettingEditor.vue'
import SettingsSection from '../../components/settings/SettingsSection.vue'
import SettingsRow from '../../components/settings/SettingsRow.vue'
import { settingsFields } from '../../settings-presentation'
import { settings } from '../../stores/settings'
import { deleteConversation, select, setArchived, state } from '../../store'
import { ask } from '../../dialog'
const active = ref('memory')
const primary = computed(() => settingsFields('data').map((entry) => ({ ...entry, field: settings.meta?.fields.find((field) => field.path === entry.key) })).filter((entry) => entry.field))
const more = computed(() => settingsFields('data', 'more-options').map((entry) => ({ ...entry, field: settings.meta?.fields.find((field) => field.path === entry.key) })).filter((entry) => entry.field))
async function openConversation(id: string): Promise<void> {
  await select(id)
  if (state.activeId === id) state.view = 'chat'
}
async function removeConversation(id: string, title: string): Promise<void> {
  if (await ask({ title: 'Delete this conversation?', message: `“${title}” and its messages are permanently deleted. Other conversations are not changed.`, confirmLabel: 'Delete', danger: true })) await deleteConversation(id)
}
</script>
<template>
  <nav class="settings-subnav" aria-label="Data and privacy subsections">
    <button class="ghost" :aria-pressed="active === 'memory'" :aria-current="active === 'memory' ? 'page' : undefined" @click="active = 'memory'">Memory and knowledge</button>
    <button class="ghost" :aria-pressed="active === 'conversations'" :aria-current="active === 'conversations' ? 'page' : undefined" @click="active = 'conversations'">Conversations</button>
    <button class="ghost" :aria-pressed="active === 'records'" :aria-current="active === 'records' ? 'page' : undefined" @click="active = 'records'">Usage, logs and audit</button>
  </nav>
  <template v-if="active === 'memory'">
    <SettingsSection v-if="primary.length" title="Learning and search">
      <SettingEditor v-for="entry in primary" :key="entry.key" :field="entry.field!" :label="entry.label" :help="entry.help" />
    </SettingsSection>
    <State />
  </template>
  <SettingsSection v-else-if="active === 'conversations'" title="Conversations">
    <SettingsRow v-for="conversation in state.conversations" :key="conversation.id" :label="conversation.title" :description="conversation.archived ? 'Archived conversation.' : 'Saved conversation.'">
      <button class="ghost" :aria-label="`Open conversation ${conversation.title}`" @click="openConversation(conversation.id)">Open</button>
      <button class="ghost" :aria-label="`${conversation.archived ? 'Restore' : 'Archive'} conversation ${conversation.title}`" :disabled="Boolean(state.busy[conversation.id]?.length)" @click="setArchived(conversation.id, !conversation.archived)">{{ conversation.archived ? 'Restore' : 'Archive' }}</button>
      <button class="ghost danger-item" :aria-label="`Delete conversation ${conversation.title}…`" :disabled="Boolean(state.busy[conversation.id]?.length)" @click="removeConversation(conversation.id, conversation.title)">Delete…</button>
    </SettingsRow>
    <p v-if="!state.conversations.length" role="status">No conversations to show. Start a conversation in chat.</p>
    <p v-if="state.notice" role="status">{{ state.notice }}</p>
  </SettingsSection>
  <Records v-else />
  <details v-if="more.length" class="settings-more"><summary>More options</summary>
    <SettingsSection title="Privacy and disk use">
      <SettingEditor v-for="entry in more" :key="entry.key" :field="entry.field!" :label="entry.label" :help="entry.help" />
    </SettingsSection>
  </details>
</template>
