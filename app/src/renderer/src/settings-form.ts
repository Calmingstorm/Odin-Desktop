// How the settings view presents Odin's settings: the menu section each belongs to, how a value is edited as text, and
// what an apply state means. Presentation only: the core owns values, validation and how each change applies.
import { reactive } from 'vue'
import { SETTINGS_SHAPED, type ApplyState, type ConfigField, type ImageLeaf, type SettingsShapedMethod } from '../../shared/api'

export interface NavSection {
  id: string
  title: string
  /** The top-level configuration sections this menu section shows. */
  prefixes: string[]
}

/** The settings menu (app v1 plan, step 6). A configuration section no entry claims appears under Other. */
export const NAV: NavSection[] = [
  { id: 'general', title: 'General', prefixes: ['timezone', 'learning', 'sessions', 'context', 'attachments'] },
  {
    id: 'models',
    title: 'Models and providers',
    prefixes: ['llm_provider', 'openai_codex', 'ollama', 'openai_compatible', 'kimi', 'agents', 'image', 'llm_recovery']
  },
  { id: 'personality', title: 'Personality', prefixes: ['personality'] },
  { id: 'tools', title: 'Tools', prefixes: ['tools', 'browser', 'computer', 'email'] },
  { id: 'skills', title: 'Skills', prefixes: [] },
  { id: 'mcp', title: 'MCP servers', prefixes: ['mcp'] },
  { id: 'hosts', title: 'Hosts and trust', prefixes: [] },
  { id: 'work', title: 'Scheduled and running work', prefixes: ['webhook', 'outbound_webhooks', 'turn_state'] },
  { id: 'state', title: 'State', prefixes: ['search'] },
  { id: 'records', title: 'Records', prefixes: ['logging', 'usage', 'observability', 'audit'] },
  { id: 'other', title: 'Other', prefixes: [] }
]

/** The dedicated desktop methods a field may name as its apply handler; anything else is saved with settings.set. */
export const DEDICATED = ['models.main.set', 'models.agents.set'] as const
export type DedicatedMethod = (typeof DEDICATED)[number]

export const STATE_LABELS: Record<ApplyState, string> = {
  applied: 'Applied',
  pending_restart: 'Applies after a restart',
  dormant: 'Not in use',
  invalid: 'Invalid',
  drift: 'Running value differs',
  unknown: 'Running value unknown'
}

/** Readable names for Odin's configuration sections; any other shows its own name, made readable. */
const SECTION_TITLES: Record<string, string> = {
  timezone: 'Time',
  learning: 'Learning',
  llm_provider: 'Main model',
  openai_codex: 'Codex',
  openai_compatible: 'OpenAI-compatible provider',
  ollama: 'Ollama',
  kimi: 'Kimi',
  agents: 'Agents',
  image: 'Images',
  llm_recovery: 'Recovery',
  tools: 'Tools',
  browser: 'Browser',
  computer: 'Computer use',
  email: 'Email',
  mcp: 'MCP',
  personality: 'Personality',
  search: 'Search',
  sessions: 'Sessions',
  context: 'Context',
  attachments: 'Attachments',
  logging: 'Logging',
  usage: 'Usage',
  observability: 'Observability',
  audit: 'Audit',
  webhook: 'Webhooks',
  outbound_webhooks: 'Outbound webhooks',
  turn_state: 'Turn state'
}

export function sectionTitle(section: string): string {
  const known = SECTION_TITLES[section]
  if (known) return known
  const words = section.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** Odin's two plain sentences, as one line: what saving does, then what the running core does now. */
export function effectText(field: ConfigField): string {
  return [field.save_effect, field.runtime_effect].filter(Boolean).join(' ')
}

export function topSection(path: string): string {
  return path.split('.')[0] ?? path
}

export function navOf(path: string): string {
  const top = topSection(path)
  return NAV.find((section) => section.prefixes.includes(top))?.id ?? 'other'
}

/** A menu section's fields, grouped by their configuration section, in the core's order. */
export function groupsFor(navId: string, fields: readonly ConfigField[]): Array<{ section: string; fields: ConfigField[] }> {
  const groups = new Map<string, ConfigField[]>()
  for (const field of fields) {
    if (navOf(field.path) !== navId) continue
    const section = topSection(field.path)
    groups.set(section, [...(groups.get(section) ?? []), field])
  }
  return [...groups].map(([section, list]) => ({ section, fields: list }))
}

export function isSecret(field: ConfigField): boolean {
  return field.sensitivity !== 'public'
}

/** The settings-shaped method that saves this field, if its owner has one: settings.set's params, its own transaction. */
export function settingsShapedMethod(field: ConfigField): SettingsShapedMethod | null {
  const handler = field.apply_handler ?? ''
  return Object.hasOwn(SETTINGS_SHAPED, handler) ? (handler as SettingsShapedMethod) : null
}

/** An image-model leaf, which follows Odin's shipped default until pinned. */
export function imageLeafOf(field: ConfigField): ImageLeaf | null {
  return field.path === 'image.openai.image_model' ? 'image_model' : field.path === 'image.openai.outer_model' ? 'outer_model' : null
}

/** False for a field a section's own controls change (for example tool timeouts): the form shows it, read-only. */
export function editableHere(field: ConfigField): boolean {
  const handler = field.apply_handler
  return isSecret(field) || !handler || handler === 'settings.set' || dedicatedMethod(field) !== null || settingsShapedMethod(field) !== null
}

export function dedicatedMethod(field: ConfigField): DedicatedMethod | null {
  return (DEDICATED as readonly string[]).includes(field.apply_handler ?? '') ? (field.apply_handler as DedicatedMethod) : null
}

/** An array of text is edited one item per line; any other structure as JSON. */
function isTextList(field: ConfigField): boolean {
  const sample = Array.isArray(field.desired) ? field.desired : Array.isArray(field.default) ? field.default : []
  return field.type === 'array' && sample.every((item) => typeof item === 'string')
}

/** A field's saved value, as the form edits it. */
export function toInput(field: ConfigField): string | boolean {
  const value = field.desired
  if (field.type === 'boolean') return value === true
  if (value === null || value === undefined) return ''
  if (isTextList(field)) return (value as string[]).join('\n')
  if (field.type === 'array' || field.type === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

export type Parsed = { ok: true; value: unknown } | { ok: false; error: string }

/** The form's input as the value to save, or why it can't be one. The core still validates it. */
export function fromInput(field: ConfigField, raw: string | boolean): Parsed {
  if (field.type === 'boolean') return { ok: true, value: raw === true }
  const text = typeof raw === 'string' ? raw : String(raw)
  if (text.trim() === '' && field.nullable) return { ok: true, value: null }
  if (field.type === 'integer' || field.type === 'number') {
    const value = Number(text.trim())
    if (text.trim() === '' || !Number.isFinite(value)) return { ok: false, error: 'Enter a number.' }
    if (field.type === 'integer' && !Number.isInteger(value)) return { ok: false, error: 'Enter a whole number.' }
    const { minimum, maximum } = field.constraints
    if (minimum !== undefined && value < minimum) return { ok: false, error: `The lowest is ${minimum}.` }
    if (maximum !== undefined && value > maximum) return { ok: false, error: `The highest is ${maximum}.` }
    return { ok: true, value }
  }
  if (field.type === 'array' && isTextList(field)) {
    return { ok: true, value: text.split('\n').map((line) => line.trim()).filter(Boolean) }
  }
  if (field.type === 'array' || field.type === 'object') {
    try {
      const value: unknown = JSON.parse(text)
      const fits = field.type === 'array' ? Array.isArray(value) : Boolean(value) && typeof value === 'object' && !Array.isArray(value)
      return fits ? { ok: true, value } : { ok: false, error: field.type === 'array' ? 'Enter a JSON list.' : 'Enter a JSON object.' }
    } catch {
      return { ok: false, error: 'That is not valid JSON.' }
    }
  }
  if (field.enum && !field.enum.includes(text)) return { ok: false, error: `Choose one of ${field.enum.join(', ')}.` }
  return { ok: true, value: text }
}

/** "Saved: X. Running: Y." when the running value differs from the saved one, or isn't known. */
export function differenceNote(field: ConfigField): string | null {
  if (isSecret(field)) return null
  if (field.apply_state === 'unknown') return 'The running value is not known.'
  if (JSON.stringify(field.desired) === JSON.stringify(field.effective)) return null
  return `Saved: ${JSON.stringify(field.desired)}. Running: ${JSON.stringify(field.effective)}.`
}

/** How the settings form writes a field, and finds the field's newest record once a write replaced it. */
export interface FieldWrites {
  save: (field: ConfigField, value: unknown) => Promise<boolean>
  reset: (field: ConfigField) => Promise<boolean>
  latest: (path: string) => ConfigField | undefined
}

/**
 * What the user typed or chose in the settings form, per field. One write runs per field at a time. A save asked for
 * while one is on its way sends the value asked for once that write lands, unless the core has it by then: Enter
 * followed by leaving the field writes once, and a second choice is never dropped. When a write lands, the draft goes
 * only if it is still what that write sent, so newer typing stays.
 */
export class FieldDrafts {
  readonly drafts = reactive<Record<string, string | boolean | undefined>>({})
  readonly errors = reactive<Record<string, string | undefined>>({})
  private readonly writing = new Set<string>()
  /** The value last asked for while a write was on its way, by field. */
  private readonly owed = new Map<string, string | boolean>()

  constructor(private readonly writes: FieldWrites) {}

  current(field: ConfigField): string | boolean {
    return this.drafts[field.path] ?? toInput(field)
  }

  edit(field: ConfigField, value: string | boolean): void {
    this.drafts[field.path] = value
    this.errors[field.path] = undefined
  }

  changed(field: ConfigField): boolean {
    return this.drafts[field.path] !== undefined && this.drafts[field.path] !== toInput(field)
  }

  async save(field: ConfigField): Promise<void> {
    const draft = this.drafts[field.path]
    if (draft === undefined) return
    if (this.writing.has(field.path)) this.owed.set(field.path, draft)
    else await this.send(field, draft)
  }

  /** Back to Odin's default. A value typed while that is on its way stays, to be saved or dropped. */
  async reset(field: ConfigField): Promise<void> {
    if (this.writing.has(field.path)) return
    await this.write(field, this.drafts[field.path], () => this.writes.reset(field))
  }

  private async send(field: ConfigField, value: string | boolean): Promise<void> {
    if (value === toInput(field)) return
    const parsed = fromInput(field, value)
    if (!parsed.ok) {
      this.errors[field.path] = parsed.error
      return
    }
    await this.write(field, value, () => this.writes.save(field, parsed.value))
  }

  private async write(field: ConfigField, sent: string | boolean | undefined, run: () => Promise<boolean>): Promise<void> {
    this.writing.add(field.path)
    try {
      if ((await run()) && this.drafts[field.path] === sent) this.drafts[field.path] = undefined
    } finally {
      this.writing.delete(field.path)
    }
    const next = this.owed.get(field.path)
    this.owed.delete(field.path)
    if (next !== undefined) await this.send(this.writes.latest(field.path) ?? field, next)
  }
}

/**
 * New secret values, per field. They are write-only, so the box is all there is: one write runs per field at a time,
 * a value asked for during one is written once it lands unless it is the value just written, and when a write lands
 * the box clears only if it still holds what was sent.
 */
export class SecretDrafts {
  readonly values = reactive<Record<string, string | undefined>>({})
  private readonly writing = new Set<string>()
  private readonly owed = new Map<string, string>()

  constructor(private readonly write: (path: string, value: string) => Promise<boolean>) {}

  async save(path: string): Promise<void> {
    const value = this.values[path]
    if (!value) return
    if (this.writing.has(path)) this.owed.set(path, value)
    else await this.send(path, value)
  }

  private async send(path: string, value: string): Promise<void> {
    this.writing.add(path)
    try {
      if ((await this.write(path, value)) && this.values[path] === value) this.values[path] = undefined
    } finally {
      this.writing.delete(path)
    }
    const next = this.owed.get(path)
    this.owed.delete(path)
    if (next !== undefined && next !== value) await this.send(path, next)
  }
}

