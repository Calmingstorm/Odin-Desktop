import { describe, expect, it } from 'vitest'
import type { ConfigField } from '../../src/shared/api'
import {
  FieldDrafts,
  dedicatedMethod,
  editableHere,
  differenceNote,
  effectText,
  fromInput,
  groupsFor,
  imageLeafOf,
  navOf,
  sectionTitle,
  settingsShapedMethod,
  toInput
} from '../../src/renderer/src/settings-form'

function field(fields: Partial<ConfigField> & Pick<ConfigField, 'path' | 'type'>): ConfigField {
  return {
    label: fields.path,
    description: '',
    enum: null,
    constraints: {},
    default: null,
    nullable: false,
    sensitivity: 'public',
    apply_mode: 'live_read',
    apply_handler: null,
    restart_reason: null,
    activation_policy: null,
    consumers: [],
    save_effect: '',
    runtime_effect: null,
    desired: null,
    effective: null,
    configured: false,
    pending_restart: false,
    apply_state: 'applied',
    ...fields
  }
}

describe('where a setting appears', () => {
  it("maps Odin's sections into the menu, and anything unclaimed into Other", () => {
    expect(navOf('openai_codex.reasoning_effort')).toBe('models')
    expect(navOf('timezone')).toBe('general')
    expect(navOf('tools.tool_timeouts')).toBe('tools')
    expect(navOf('graceful_degradation.enabled')).toBe('other')
    expect(navOf('a_section_from_a_newer_odin.flag')).toBe('other')
  })

  it("groups a menu section's fields by configuration section, in the core's order", () => {
    const fields = [
      field({ path: 'agents.model', type: 'string' }),
      field({ path: 'openai_codex.reasoning_effort', type: 'string' }),
      field({ path: 'agents.max_concurrent_agents', type: 'integer' }),
      field({ path: 'timezone', type: 'string' })
    ]
    expect(groupsFor('models', fields).map((g) => [g.section, g.fields.map((f) => f.path)])).toEqual([
      ['agents', ['agents.model', 'agents.max_concurrent_agents']],
      ['openai_codex', ['openai_codex.reasoning_effort']]
    ])
  })
})

describe('editing a value', () => {
  it('checks whole numbers against their bounds', () => {
    const f = field({ path: 'x.n', type: 'integer', constraints: { minimum: 30, maximum: 100 } })
    expect(fromInput(f, '60')).toEqual({ ok: true, value: 60 })
    expect(fromInput(f, '20')).toEqual({ ok: false, error: 'The lowest is 30.' })
    expect(fromInput(f, '6.5')).toEqual({ ok: false, error: 'Enter a whole number.' })
    expect(fromInput(f, 'many')).toEqual({ ok: false, error: 'Enter a number.' })
  })

  it('offers only the listed choices, and lets an empty nullable value mean none', () => {
    expect(fromInput(field({ path: 'x.e', type: 'string', enum: ['a', 'b'] }), 'c')).toEqual({ ok: false, error: 'Choose one of a, b.' })
    expect(fromInput(field({ path: 'x.s', type: 'string', nullable: true }), '  ')).toEqual({ ok: true, value: null })
  })

  it('edits a list of text one item per line, and other structures as JSON', () => {
    const list = field({ path: 'agents.auto_model_allowlist', type: 'array', desired: ['gpt-6-sol', 'gpt-6-luna'] })
    expect(toInput(list)).toBe('gpt-6-sol\ngpt-6-luna')
    expect(fromInput(list, 'gpt-6-sol\n\n gpt-6.1-sol \n')).toEqual({ ok: true, value: ['gpt-6-sol', 'gpt-6.1-sol'] })
    const map = field({ path: 'tools.tool_timeouts', type: 'object', desired: { run_command: 900 } })
    expect(toInput(map)).toBe('{\n  "run_command": 900\n}')
    expect(fromInput(map, '{"generate_video": 600}')).toEqual({ ok: true, value: { generate_video: 600 } })
    expect(fromInput(map, '[1]')).toEqual({ ok: false, error: 'Enter a JSON object.' })
    expect(fromInput(map, '{oops')).toEqual({ ok: false, error: 'That is not valid JSON.' })
  })

  it('says when the running value differs from the saved one, or is unknown, but never for a secret', () => {
    expect(differenceNote(field({ path: 'x.t', type: 'integer', desired: 900, effective: 600 }))).toBe('Saved: 900. Running: 600.')
    expect(differenceNote(field({ path: 'x.t', type: 'integer', desired: 900, effective: 900 }))).toBeNull()
    expect(differenceNote(field({ path: 'x.t', type: 'integer', apply_state: 'unknown' }))).toBe('The running value is not known.')
    expect(differenceNote(field({ path: 'x.k', type: 'string', sensitivity: 'sensitive', desired: '••••', effective: null }))).toBeNull()
  })

  it('routes only known dedicated methods; anything else saves through settings.set', () => {
    expect(dedicatedMethod(field({ path: 'llm_provider.model', type: 'string', apply_handler: 'models.main.set' }))).toBe('models.main.set')
    expect(dedicatedMethod(field({ path: 'x.y', type: 'string', apply_handler: 'settings.set' }))).toBeNull()
    expect(dedicatedMethod(field({ path: 'x.y', type: 'string', apply_handler: 'PUT /api/llm/codex/config' }))).toBeNull()
  })
})

describe('how a setting reads', () => {
  it("names Odin's sections readably, and any newer one by its own name", () => {
    expect(sectionTitle('llm_provider')).toBe('Main model')
    expect(sectionTitle('a_newer_section')).toBe('A newer section')
  })

  it("joins Odin's two sentences with a space", () => {
    expect(effectText(field({ path: 'x', type: 'string', save_effect: 'Saved.', runtime_effect: 'Read on next use.' }))).toBe('Saved. Read on next use.')
    expect(effectText(field({ path: 'x', type: 'string', save_effect: 'Saved.' }))).toBe('Saved.')
  })
})

describe('review round 2: which method saves a field', () => {
  it("names a provider or computer field's settings-shaped method, and nothing for the rest", () => {
    expect(settingsShapedMethod(field({ type: 'string', path: 'ollama.base_url', apply_handler: 'providers.ollama.set' }))).toBe('providers.ollama.set')
    expect(settingsShapedMethod(field({ type: 'string', path: 'computer.enabled', apply_handler: 'computer.activation.set' }))).toBe('computer.activation.set')
    expect(settingsShapedMethod(field({ type: 'string', path: 'timezone', apply_handler: 'settings.set' }))).toBeNull()
    expect(settingsShapedMethod(field({ type: 'string', path: 'llm_provider.model', apply_handler: 'models.main.set' }))).toBeNull()
    expect(settingsShapedMethod(field({ type: 'string', path: 'x', apply_handler: 'toString' }))).toBeNull() // only the protocol's own names
  })

  it('knows the two image-model leaves, which follow or pin', () => {
    expect(imageLeafOf(field({ type: 'string', path: 'image.openai.image_model' }))).toBe('image_model')
    expect(imageLeafOf(field({ type: 'string', path: 'image.openai.outer_model' }))).toBe('outer_model')
    expect(imageLeafOf(field({ type: 'string', path: 'image.openai.quality' }))).toBeNull()
  })
})

describe('what the form edits in place', () => {
  const owned = (apply_handler: string | null, extra: Partial<ConfigField> = {}) =>
    field({ type: 'string', path: 'x.y', apply_handler, ...extra })

  it('edits generic, secret, leaf-editor and settings-shaped fields, and shows section-owned ones read-only', () => {
    expect(editableHere(owned(null))).toBe(true)
    expect(editableHere(owned('settings.set'))).toBe(true)
    expect(editableHere(owned('providers.compat.set', { sensitivity: 'sensitive' }))).toBe(true) // a secret: set, never shown
    expect(editableHere(owned('models.main.set'))).toBe(true)
    expect(editableHere(owned('providers.ollama.set'))).toBe(true)
    expect(editableHere(owned('computer.activation.set'))).toBe(true)
    expect(editableHere(owned('tools.timeouts.set'))).toBe(false) // the Tools section's own controls change it
    expect(editableHere(owned('mcp.set_limits'))).toBe(false)
  })
})

describe('review round 3: a field saves once at a time, and keeps newer typing', () => {
  const tz = () => field({ type: 'string', path: 'timezone', desired: 'UTC' })

  it('sends one save for Enter followed by leaving the field, and keeps what was typed during it', async () => {
    const form = new FieldDrafts()
    const sent: unknown[] = []
    let land!: (ok: boolean) => void
    const saver = (_f: ConfigField, value: unknown) => (sent.push(value), new Promise<boolean>((resolve) => (land = resolve)))
    form.edit(tz(), 'Europe/Paris')
    const first = form.save(tz(), saver)
    await form.save(tz(), saver) // the blur right after Enter
    expect(sent).toEqual(['Europe/Paris'])
    form.edit(tz(), 'Asia/Tokyo')
    land(true)
    await first
    expect(form.current(tz())).toBe('Asia/Tokyo')
  })

  it('clears the draft once what was sent is saved', async () => {
    const form = new FieldDrafts()
    form.edit(tz(), 'Europe/Paris')
    await form.save(tz(), async () => true)
    expect(form.drafts.timezone).toBeUndefined()
  })
})

