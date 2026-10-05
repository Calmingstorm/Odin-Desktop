<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { ask } from '../../dialog'
import { configValue } from '../../skill-config'
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
  <section class="panel" aria-label="Skills">
    <header class="panel-head">
      <h3>Skills</h3>
      <span class="panel-hint">Tools written as Python files that Odin loads alongside his own.</span>
      <button class="ghost" @click="newSkill(TEMPLATE)">New skill</button>
    </header>
    <p v-if="management.error" class="warn">{{ management.error }}</p>
    <ul class="manage-list">
      <li v-for="skill in management.skills" :key="skill.name" :class="['manage-row', skill.status]">
        <div class="manage-line">
          <code class="manage-name">{{ skill.name }}</code>
          <span class="tag">{{ skill.version }}</span>
          <span :class="['state-chip', skill.status]">{{ STATUS[skill.status] ?? skill.status }}</span>
          <span class="manage-count">{{ skill.execution_count ?? skill.total_executions ?? 0 }} runs</span>
          <span class="manage-actions">
            <button v-if="skill.status !== 'error'" class="ghost" @click="openSkill(skill.name)">Open</button>
            <button v-if="skill.status !== 'error'" class="ghost" :disabled="management.busy[`skill:${skill.name}`]" @click="setSkillEnabled(skill.name, skill.status !== 'loaded')">
              {{ skill.status === 'loaded' ? 'Turn off' : 'Turn on' }}
            </button>
            <button class="ghost" :disabled="skill.status !== 'loaded' || management.busy[`skill:${skill.name}`]" @click="testSkill(skill.name)">Test</button>
            <button class="ghost danger-item" @click="remove(skill.name)">Delete…</button>
          </span>
        </div>
        <p v-if="!(skill.diagnostics ?? []).some((d) => d.message === skill.description)" class="manage-desc">{{ skill.description }}</p>
        <p v-for="(d, i) in skill.diagnostics ?? []" :key="i" :class="d.level === 'error' ? 'warn' : 'manage-desc'">{{ d.message }}</p>
        <p v-if="management.notes[`skill:${skill.name}`]" class="manage-note" role="status">{{ management.notes[`skill:${skill.name}`] }}</p>
      </li>
    </ul>
  </section>

  <section v-if="editing" class="panel skill-editor" aria-label="Skill editor">
    <header class="panel-head">
      <h3>{{ editing.create ? 'New skill' : editing.name }}</h3>
      <span class="panel-hint">Validation compiles the code without running it. Saving loads it into Odin.</span>
      <button class="ghost" @click="closeSkill">Close</button>
    </header>
    <label v-if="editing.create" class="field-input">Name <input v-model="editing.name" maxlength="100" placeholder="my_skill" /></label>
    <textarea v-model="editing.code" class="code-editor" rows="18" spellcheck="false" aria-label="Skill code" />
    <div class="panel-actions">
      <button class="ghost" @click="validateSkill(editing.code)">Validate</button>
      <button class="ghost" :disabled="!editing.name.trim() || management.busy[`skill:${editing.name.trim()}`]" @click="saveSkill">
        {{ editing.create ? 'Create' : 'Save' }}
      </button>
      <button v-if="!editing.create" class="ghost" @click="testSkill(editing.name)">Test</button>
    </div>
    <div v-if="management.validation" class="validation" role="status">
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
        <button class="ghost" :disabled="management.busy[`skill-config:${management.skill.name}`]" @click="saveSkillConfig(management.skill!.name, { ...management.skillConfig })">
          Save its settings
        </button>
      </div>
      <p v-if="management.notes[`skill-config:${management.skill.name}`]" class="manage-note" role="status">
        {{ management.notes[`skill-config:${management.skill.name}`] }}
      </p>
    </template>
  </section>
</template>
