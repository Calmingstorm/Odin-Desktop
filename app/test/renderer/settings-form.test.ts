import { describe, expect, it } from 'vitest'
import type { ConfigField } from '../../src/shared/api'
import {
  FieldDrafts,
  SecretDrafts,
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

  it('says when the running value differs, but stays silent for unknowns and secrets', () => {
    expect(differenceNote(field({ path: 'x.t', type: 'integer', desired: 900, effective: 600 }))).toBe('Saved: 900. Running: 600.')
    expect(differenceNote(field({ path: 'x.t', type: 'integer', desired: 900, effective: 900 }))).toBeNull()
    expect(differenceNote(field({ path: 'x.t', type: 'integer', apply_state: 'unknown', desired: 3, effective: null }))).toBeNull()
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
    expect(editableHere(owned('models.main.set', { path: 'llm_provider.active_provider' }))).toBe(false)
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
    const w = heldWrites(tz())
    w.form.edit(tz(), 'Europe/Paris')
    void w.form.save(tz())
    void w.form.save(tz()) // the blur right after Enter
    expect(w.sent).toEqual(['Europe/Paris'])
    w.form.edit(tz(), 'Asia/Tokyo')
    await w.land()
    expect(w.sent).toEqual(['Europe/Paris'])
    expect(w.form.current(w.record())).toBe('Asia/Tokyo')
  })

  it('clears the draft once what was sent is saved', async () => {
    const w = heldWrites(tz())
    w.form.edit(tz(), 'Europe/Paris')
    void w.form.save(tz())
    await w.land()
    expect(w.form.drafts.timezone).toBeUndefined()
  })
})

/** Writes held until the test lands them, one at a time, with the field's record after each saved write. */
function heldWrites(initial: ConfigField) {
  let record = initial
  const sent: unknown[] = []
  const landing: Array<(ok: boolean) => void> = []
  const write = (value: unknown) =>
    new Promise<boolean>((resolve) => {
      sent.push(value)
      landing.push((ok) => {
        if (ok) record = { ...record, desired: value === 'default' ? record.default : value, configured: value !== 'default' }
        resolve(ok)
      })
    })
  const form = new FieldDrafts({
    save: (_f, value) => write(value),
    reset: () => write('default'),
    latest: () => record
  })
  const land = async (ok = true): Promise<void> => {
    landing.shift()!(ok)
    for (let i = 0; i < 10; i++) await Promise.resolve()
  }
  return { form, sent, land, record: () => record }
}

describe('review round 4: a choice or value asked for during a write is never dropped', () => {
  const learning = () => field({ type: 'boolean', path: 'learning.enabled', desired: false })

  it('saves a second choice once the first lands (12.R4.1)', async () => {
    const w = heldWrites(learning())
    w.form.edit(learning(), true)
    void w.form.save(learning())
    w.form.edit(learning(), false)
    void w.form.save(learning())
    expect(w.sent).toEqual([true])
    await w.land()
    expect(w.sent).toEqual([true, false])
    await w.land()
    expect(w.record().desired).toBe(false)
    expect(w.form.current(w.record())).toBe(false)
    expect(w.form.drafts['learning.enabled']).toBeUndefined()
  })

  it('sends nothing more when the last choice is the one already on its way', async () => {
    const w = heldWrites(learning())
    w.form.edit(learning(), true)
    void w.form.save(learning())
    w.form.edit(learning(), false)
    void w.form.save(learning())
    w.form.edit(learning(), true)
    void w.form.save(learning())
    await w.land()
    expect(w.sent).toEqual([true])
    expect(w.record().desired).toBe(true)
  })

  it('still shows and keeps the second choice when the first write fails', async () => {
    const w = heldWrites(learning())
    w.form.edit(learning(), true)
    void w.form.save(learning())
    w.form.edit(learning(), false)
    void w.form.save(learning())
    await w.land(false)
    expect(w.sent).toEqual([true]) // nothing was saved, and the core still has what is shown
    expect(w.form.current(w.record())).toBe(false)
    expect(w.record().desired).toBe(false)
  })

  it('keeps a value typed while a reset is on its way, and saves it if asked to (12.2)', async () => {
    const tz = field({ type: 'string', path: 'timezone', desired: 'Europe/Paris', default: 'UTC', configured: true })
    const w = heldWrites(tz)
    void w.form.reset(tz)
    w.form.edit(tz, 'Asia/Tokyo')
    await w.land()
    expect(w.form.current(w.record())).toBe('Asia/Tokyo')
    expect(w.sent).toEqual(['default'])
    void w.form.save(w.record())
    await w.land()
    expect(w.record().desired).toBe('Asia/Tokyo')
  })

  it('sends the value asked for during a write, even if typing went on after', async () => {
    const tz = field({ type: 'string', path: 'timezone', desired: 'UTC' })
    const w = heldWrites(tz)
    w.form.edit(tz, 'Europe/Paris')
    void w.form.save(tz)
    w.form.edit(tz, 'Asia/Tokyo')
    void w.form.save(tz) // leaving the field with Tokyo in it
    w.form.edit(tz, 'Asia/Tokyo-2') // back in the field, still typing
    await w.land()
    expect(w.sent).toEqual(['Europe/Paris', 'Asia/Tokyo'])
    await w.land()
    expect(w.record().desired).toBe('Asia/Tokyo')
    expect(w.form.current(w.record())).toBe('Asia/Tokyo-2')
  })

  it('does nothing for a reset asked for while a save is on its way', async () => {
    const tz = field({ type: 'string', path: 'timezone', desired: 'UTC', configured: true })
    const w = heldWrites(tz)
    w.form.edit(tz, 'Europe/Paris')
    void w.form.save(tz)
    await w.form.reset(tz)
    expect(w.sent).toEqual(['Europe/Paris'])
  })

  it('drops an unsaved value when the reset it came before lands', async () => {
    const tz = field({ type: 'string', path: 'timezone', desired: 'Europe/Paris', default: 'UTC', configured: true })
    const w = heldWrites(tz)
    w.form.edit(tz, 'Asia/Tokyo')
    void w.form.reset(tz)
    await w.land()
    expect(w.form.current(w.record())).toBe('UTC')
  })
})

describe('review round 4: a secret is written once per value, and newer typing stays (12.2)', () => {
  function secretWrites() {
    const sent: string[] = []
    const landing: Array<(ok: boolean) => void> = []
    const secrets = new SecretDrafts((_path, value) => new Promise<boolean>((resolve) => (sent.push(value), landing.push(resolve))))
    const land = async (ok = true): Promise<void> => {
      landing.shift()!(ok)
      for (let i = 0; i < 10; i++) await Promise.resolve()
    }
    return { secrets, sent, land }
  }

  it('writes once for Enter followed by the Save button', async () => {
    const w = secretWrites()
    w.secrets.values.token = 'value-a'
    void w.secrets.save('token')
    void w.secrets.save('token')
    await w.land()
    expect(w.sent).toEqual(['value-a'])
    expect(w.secrets.values.token).toBeUndefined()
  })

  it('keeps a value typed during a write, and writes it after if asked', async () => {
    const w = secretWrites()
    w.secrets.values.token = 'value-a'
    void w.secrets.save('token')
    w.secrets.values.token = 'value-b'
    await w.land()
    expect(w.secrets.values.token).toBe('value-b')
    void w.secrets.save('token')
    w.secrets.values.token = 'value-c'
    void w.secrets.save('token') // asked for during the write of value-b
    await w.land()
    expect(w.sent).toEqual(['value-a', 'value-b', 'value-c'])
    await w.land()
    expect(w.secrets.values.token).toBeUndefined()
  })
})
