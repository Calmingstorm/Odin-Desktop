<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { ask } from '../../dialog'
import { configValue } from '../../skill-config'
import { settingsUnavailableText as unavailableText } from '../../capability'
import { settingsFields } from '../../settings-presentation'
import { settings } from '../../stores/settings'
import SettingEditor from '../../components/settings/SettingEditor.vue'
import SettingsSection from '../../components/settings/SettingsSection.vue'
import SettingsSwitch from '../../components/settings/SettingsSwitch.vue'
import SettingsRow from '../../components/settings/SettingsRow.vue'
import {
  closeSkill,
  deleteSkill,
  loadSkills,
  management,
  newSkill,
  openSkill,
  saveSkill,
  saveSkillConfig,
  setSkillEnabled,
  testSkill,
  validateSkill
} from '../../stores/management'

onMounted(loadSkills)

const STATUS: Record<string, string> = { loaded: 'Loaded', disabled: 'Off', error: 'Failed to load' }
const TEMPLATE = `"""What this skill does."""
SKILL_DEFINITION = {
    "name": "my_skill",
    "description": "What Odin can use it for.",
    "input_schema": {"type": "object", "properties": {}},
}


async def execute(inp, context):
    return "done"
`

/** The editor lives in the store, so a save that lands, even late, finds the editor it belongs to. */
const editing = computed(() => management.editor)
const more = computed(() => settingsFields('skills', 'more-options').flatMap((entry) => {
  const field = settings.meta?.fields.find((field) => field.path === entry.key)
  return field ? [{ ...entry, field }] : []
}))

const configFields = computed(() =>
  Object.entries((management.skill?.metadata.config_schema?.properties ?? {}) as Record<string, Record<string, unknown>>)
)

async function remove(name: string): Promise<void> {
  const confirmed = await ask({
    title: 'Delete this skill?',
    message: `${name} is removed from Odin, with its code. This can't be undone.`,
    confirmLabel: 'Delete',
    danger: true
  })
  if (confirmed) await deleteSkill(name)
}

function setConfig(key: string, spec: Record<string, unknown>, raw: string | boolean, optionIndex?: number): void {
  management.skillConfig[key] = configValue(spec, raw, optionIndex)
}
</script>

<template>
  <SettingsSection title="Skills" aria-label="Skills">
    <template #actions>
      <button v-if="!management.unavailable.skills" class="ghost" @click="newSkill(TEMPLATE)">New skill</button>
    </template>
    <p v-if="management.unavailable.skills" class="capability-unavailable" role="status">{{ unavailableText('Skill management') }}</p>
    <p v-else-if="management.errors.skills" class="warn">{{ management.errors.skills }}</p>
    <p v-if="!management.unavailable.skills && management.skillTestUnavailable" class="capability-unavailable" role="status">Skill testing is unavailable.</p>
    <p v-if="!management.unavailable.skills && !management.skills.length && !management.errors.skills" class="manage-desc">No skills yet. Create a skill to add your own tools.</p>
    <ul v-if="!management.unavailable.skills" class="manage-list">
      <li v-for="skill in management.skills" :key="skill.name" :class="['manage-row', skill.status]">
        <div class="manage-line">
          <code class="manage-name">{{ skill.name }}</code>
          <span class="tag">{{ skill.version }}</span>
          <span :class="['state-chip', skill.status]">{{ STATUS[skill.status] ?? skill.status }}</span>
          <span class="manage-count">{{ skill.execution_count ?? skill.total_executions ?? 0 }} runs</span>
          <span class="manage-actions">
            <button v-if="skill.status !== 'error'" class="ghost" :aria-label="`Open ${skill.name}`" @click="openSkill(skill.name)">Open</button>
            <label v-if="skill.status !== 'error'" class="toggle-inline">Available
              <SettingsSwitch :id="`skill-enabled-${encodeURIComponent(skill.name)}`" :label="`${skill.status === 'loaded' ? 'Turn off' : 'Turn on'} ${skill.name}`" :checked="skill.status === 'loaded'" :disabled="management.busy[`skill:${skill.name}`]" @change="setSkillEnabled(skill.name, $event)" />
            </label>
            <button class="ghost" :aria-label="`Test ${skill.name}`" :disabled="management.skillTestUnavailable || skill.status !== 'loaded' || management.busy[`skill:${skill.name}`]" @click="testSkill(skill.name)">Test</button>
            <button class="ghost danger-item" :aria-label="`Delete ${skill.name}…`" @click="remove(skill.name)">Delete…</button>
          </span>
        </div>
        <p v-if="!(skill.diagnostics ?? []).some((d) => d.message === skill.description)" class="manage-desc">{{ skill.description }}</p>
        <p v-if="skill.dependencies?.length" class="manage-desc">Dependencies: {{ skill.dependencies.join(', ') }}</p>
        <p v-for="(d, i) in skill.diagnostics ?? []" :key="i" :class="d.level === 'error' ? 'warn' : 'manage-desc'">{{ d.message }}</p>
        <p v-if="management.notes[`skill:${skill.name}`]" class="manage-note" role="status">{{ management.notes[`skill:${skill.name}`] }}</p>
      </li>
    </ul>
  </SettingsSection>

  <SettingsSection v-if="editing && !management.unavailable.skills" :title="editing.create ? 'New skill' : editing.name" class="skill-editor" aria-label="Skill editor">
    <header class="panel-head">
      <span class="panel-hint">Validation compiles the code without running it. Saving loads it into Odin.</span>
      <button class="ghost" aria-label="Cancel skill changes" @click="closeSkill">Cancel</button>
    </header>
    <SettingsRow v-if="management.skill" label="Execution" :description="management.skill.handoff_to_codex ? 'This skill hands work to a coding session; its access rules still apply.' : 'This skill runs Python code; tool access and approvals still apply.'">
      <span>{{ management.skill.handoff_to_codex ? 'Coding session' : 'Python' }}</span>
    </SettingsRow>
    <SettingsRow v-if="management.skill?.metadata.dependencies?.length" label="Dependencies">
      <span>{{ management.skill.metadata.dependencies.join(', ') }}</span>
    </SettingsRow>
    <label v-if="editing.create" class="field-input">Name <input v-model="editing.name" maxlength="100" placeholder="my_skill" /></label>
    <label for="skill-code">Skill code</label>
    <textarea id="skill-code" v-model="editing.code" class="code-editor" rows="18" spellcheck="false" :aria-invalid="management.validation?.valid === false || undefined" :aria-describedby="management.validation ? 'skill-validation' : undefined" />
    <div class="panel-actions">
      <button class="ghost" :aria-label="`Validate skill ${editing.name || 'code'}`" @click="validateSkill(editing.code)">Validate</button>
      <button class="ghost" :aria-label="`${editing.create ? 'Create' : 'Save'} skill ${editing.name || 'code'}`" :disabled="!editing.name.trim() || management.busy[`skill:${editing.name.trim()}`]" @click="saveSkill">
        {{ editing.create ? 'Create' : 'Save' }}
      </button>
      <button v-if="!editing.create" class="ghost" :aria-label="`Test ${editing.name}`" :disabled="management.skillTestUnavailable || management.busy[`skill:${editing.name}`]" @click="testSkill(editing.name)">Test</button>
    </div>
    <div v-if="management.validation" id="skill-validation" class="validation" role="status">
      <p v-if="management.validation.valid" class="field-saved">Valid.</p>
      <p v-for="(e, i) in management.validation.errors" :key="`e${i}`" class="warn">{{ e }}</p>
      <p v-for="(w, i) in management.validation.warnings" :key="`w${i}`" class="manage-desc">{{ w }}</p>
    </div>
    <pre v-if="management.testResult" :class="['manage-json', { warn: management.testResult.is_error }]">{{ management.testResult.result }}</pre>
    <p v-if="management.notes[`skill:${editing.name}`]" class="manage-note" role="status">{{ management.notes[`skill:${editing.name}`] }}</p>

    <template v-if="management.skill && configFields.length">
      <h4 class="sub-head">Its settings</h4>
      <label v-for="[key, spec] in configFields" :key="key" class="field-input">
        <span class="config-key">{{ key }}</span>
        <select
          v-if="Array.isArray(spec.enum)"
          @change="setConfig(key, spec, ($event.target as HTMLSelectElement).value, ($event.target as HTMLSelectElement).selectedIndex)"
        >
          <option v-for="(option, index) in spec.enum as unknown[]" :key="index" :selected="management.skillConfig[key] === option">{{ String(option) }}</option>
        </select>
        <input
          v-else-if="spec.type === 'boolean'"
          type="checkbox"
          :checked="management.skillConfig[key] === true"
          @change="setConfig(key, spec, ($event.target as HTMLInputElement).checked)"
        />
        <input
          v-else
          :type="spec.type === 'integer' || spec.type === 'number' ? 'number' : 'text'"
          :min="spec.minimum as number | undefined"
          :max="spec.maximum as number | undefined"
          :value="management.skillConfig[key] as string | number | undefined"
          @input="setConfig(key, spec, ($event.target as HTMLInputElement).value)"
        />
      </label>
      <div class="panel-actions">
        <button class="ghost" :aria-label="`Save settings for ${management.skill.name}`" :disabled="management.busy[`skill-config:${management.skill.name}`]" @click="saveSkillConfig(management.skill!.name, { ...management.skillConfig })">
          Save settings
        </button>
      </div>
      <p v-if="management.notes[`skill-config:${management.skill.name}`]" class="manage-note" role="status">
        {{ management.notes[`skill-config:${management.skill.name}`] }}
      </p>
    </template>
  </SettingsSection>

  <details v-if="more.length" class="settings-more-options">
    <summary>More options</summary>
    <SettingsSection title="Network access">
      <SettingEditor v-for="entry in more" :key="entry.key" :field="entry.field" :label="entry.label" :help="entry.help" />
    </SettingsSection>
  </details>
</template>
