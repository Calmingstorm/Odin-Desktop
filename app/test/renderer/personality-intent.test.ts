// residual 16.R4.2: input history, not equality to a historical value, owns the draft.
// Real compiled SFC + real stores; only bridge I/O is held. Edits go through the host's DOM listeners.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Personality, PersonalitySet, Result } from '../../src/shared/api'
import { flush, mount, type Host, type Mounted } from './component-host'

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const failed = { ok: false, error: { code: 'unavailable', message: 'not dispatched', disposition: 'not_dispatched' } } as const
const customFields = ['custom_name', 'custom_identity', 'custom_voice'] as const
type CustomField = (typeof customFields)[number]
type Phase = 'write' | 'readback'

function personality(fields: Partial<Personality> = {}): Personality {
  return {
    preset: 'odin', custom_name: 'loaded name', custom_identity: 'loaded identity', custom_voice: 'loaded voice',
    builtin_presets: ['odin', 'professional'], user_presets: [],
    presets: { odin: { name: 'Odin', identity: 'old identity', voice: 'old voice' }, professional: { name: 'Professional', identity: 'professional identity', voice: 'professional voice' } },
    ...fields
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

let mounted: Mounted | undefined
let loaded: Personality
let get: ReturnType<typeof vi.fn<() => Promise<Result<Personality>>>>
let set: ReturnType<typeof vi.fn<(change: PersonalitySet) => Promise<Result<{ status: string; preset: string }>>>>

beforeEach(() => {
  vi.resetModules()
  loaded = personality()
  get = vi.fn(async () => ok(loaded))
  set = vi.fn(async (change: PersonalitySet) => ok({ status: 'updated', preset: change.preset }))
  vi.stubGlobal('window', { odin: { personalityGet: get, personalitySet: set } })
  vi.stubGlobal('document', { activeElement: null })
})

afterEach(() => {
  mounted?.unmount()
  mounted = undefined
  vi.unstubAllGlobals()
})

async function view(initial = personality()): Promise<Mounted> {
  loaded = initial
  const component = (await import('../../src/renderer/src/views/settings/Personality.vue')).default
  mounted = mount(component)
  await flush()
  expect(get).toHaveBeenCalledTimes(1)
  return mounted
}

function panel(v: Mounted): Host {
  const result = v.root.findAll((node) => node.props['aria-label'] === 'Personality')[0]
  if (!result) throw new Error('Personality did not render')
  return result
}

function select(v: Mounted): Host { return panel(v).find('select')! }

async function choose(v: Mounted, preset: string): Promise<void> {
  const control = select(v)
  const index = control.options.findIndex((option) => option.props.value === preset)
  expect(index).toBeGreaterThanOrEqual(0)
  expect(control.props.disabled).not.toBe(true)
  control.choose(index)
  await flush()
}

function selected(v: Mounted): unknown {
  const control = select(v)
  return control.options[control.selectedIndex]?.props.value
}

function field(v: Mounted, key: CustomField): Host {
  const label = { custom_name: 'Name', custom_identity: 'Identity', custom_voice: 'Voice' }[key]
  const row = panel(v).findAll((node) => node.tag === 'label' && node.textContent().trim() === label)[0]
  const control = row?.find(key === 'custom_name' ? 'input' : 'textarea')
  if (!control) throw new Error(`Missing editable ${key}`)
  return control
}

async function type(v: Mounted, key: CustomField, text: string): Promise<void> {
  const control = field(v, key)
  expect(control.props.disabled).not.toBe(true)
  control.type(text)
  await flush()
  expect(field(v, key).value).toBe(text)
}

async function refresh(next: Personality): Promise<void> {
  loaded = next
  const { loadPersonality } = await import('../../src/renderer/src/stores/state')
  await loadPersonality()
  await flush()
}

async function holdSave(v: Mounted, phase: Phase) {
  const getBefore = get.mock.calls.length
  const receipt = deferred<Awaited<ReturnType<typeof set>>>()
  const readback = deferred<Result<Personality>>()
  set.mockReturnValueOnce(receipt.promise)
  get.mockReturnValueOnce(readback.promise)
  const saving = Promise.resolve(panel(v).button('Save').fire('click'))
  await flush()
  expect(set).toHaveBeenCalledTimes(1)
  expect(panel(v).button('Save').props.disabled).toBe(true)
  expect(get).toHaveBeenCalledTimes(getBefore)
  const deliverReceipt = async () => {
    receipt.resolve(ok({ status: 'updated', preset: set.mock.calls[0]![0].preset }))
    await flush()
    expect(get).toHaveBeenCalledTimes(getBefore + 1)
  }
  if (phase === 'readback') await deliverReceipt()
  return {
    async finish(authoritative: Personality) {
      if (phase === 'write') await deliverReceipt()
      loaded = authoritative
      readback.resolve(ok(authoritative))
      await saving
      await flush()
      expect(panel(v).button('Save').props.disabled).toBe(false)
    }
  }
}

async function nextSave(v: Mounted): Promise<PersonalitySet> {
  await Promise.resolve(panel(v).button('Save').fire('click'))
  await flush()
  expect(set).toHaveBeenCalledTimes(2)
  return set.mock.calls[1]![0]
}

describe('residual 16.R4.2: Personality field edit intent', () => {
  it('keeps persisted custom text when the real core replaces all fields on a built-in preset switch', async () => {
    const initial = personality({ preset: 'custom' })
    const v = await view(initial)
    await type(v, 'custom_identity', 'unsaved hidden identity')
    await choose(v, 'professional')
    set.mockImplementationOnce(async (change) => {
      // ModelSettingsService._personality_set defaults omitted custom fields to empty strings.
      loaded = personality({ preset: change.preset, custom_name: change.custom_name ?? '', custom_identity: change.custom_identity ?? '', custom_voice: change.custom_voice ?? '' })
      return ok({ status: 'updated', preset: loaded.preset })
    })
    await Promise.resolve(panel(v).button('Save').fire('click'))
    await flush()
    expect(loaded.custom_identity).toBe(initial.custom_identity)
    await choose(v, 'custom')
    expect(field(v, 'custom_identity').value).toBe('unsaved hidden identity')
  })

  for (const phase of ['write', 'readback'] as const) {
    it(`keeps Odin chosen again during ${phase}, including the next Save payload`, async () => {
      const v = await view()
      expect(selected(v)).toBe('odin')
      await choose(v, 'professional')
      const pending = await holdSave(v, phase)
      expect(set.mock.calls[0]![0]).toEqual({ preset: 'professional', custom_name: 'loaded name', custom_identity: 'loaded identity', custom_voice: 'loaded voice' })
      await choose(v, 'odin')
      await pending.finish(personality({ preset: 'professional' }))
      expect(selected(v)).toBe('odin')
      expect(await nextSave(v)).toEqual({ preset: 'odin', custom_name: 'loaded name', custom_identity: 'loaded identity', custom_voice: 'loaded voice' })
    })

    it(`records a same-as-submitted select change during ${phase}`, async () => {
      const v = await view()
      await choose(v, 'professional')
      const pending = await holdSave(v, phase)
      // A change event is intent even when v-model's resulting value is unchanged.
      await choose(v, 'professional')
      await pending.finish(personality({ preset: 'odin' }))
      expect(selected(v)).toBe('professional')
      expect(await nextSave(v)).toEqual({ preset: 'professional', custom_name: 'loaded name', custom_identity: 'loaded identity', custom_voice: 'loaded voice' })
    })

    for (const key of customFields) {
      it(`keeps ${key} re-entered with the submitted value during ${phase} despite canonical readback`, async () => {
        const v = await view(personality({ preset: 'custom' }))
        await type(v, key, 'submitted text')
        const pending = await holdSave(v, phase)
        expect(set.mock.calls[0]![0][key]).toBe('submitted text')
        await type(v, key, 'submitted text')
        const canonical = personality({ preset: 'custom', custom_name: 'canonical name', custom_identity: 'canonical identity', custom_voice: 'canonical voice' })
        await pending.finish(canonical)
        for (const fieldKey of customFields) expect(field(v, fieldKey).value).toBe(fieldKey === key ? 'submitted text' : canonical[fieldKey])
        expect(await nextSave(v)).toEqual({ preset: 'custom', custom_name: canonical.custom_name, custom_identity: canonical.custom_identity, custom_voice: canonical.custom_voice, [key]: 'submitted text' })
      })

      it(`keeps ${key} edited away and back to the loaded baseline during ${phase}`, async () => {
        const initial = personality({ preset: 'custom' })
        const v = await view(initial)
        await type(v, key, 'submitted text')
        const pending = await holdSave(v, phase)
        await type(v, key, 'temporary newer text')
        await type(v, key, initial[key])
        const canonical = personality({ preset: 'custom', [key]: 'canonical submitted text' })
        await pending.finish(canonical)
        expect(field(v, key).value).toBe(initial[key])
        expect((await nextSave(v))[key]).toBe(initial[key])
      })
    }
  }

  it('adopts canonical fields edited before submission but untouched after dispatch, then follows future refreshes', async () => {
    const v = await view(personality({ preset: 'custom' }))
    for (const key of customFields) await type(v, key, `submitted ${key}`)
    const pending = await holdSave(v, 'write')
    const canonical = personality({ preset: 'custom', custom_name: 'canonical name', custom_identity: 'canonical identity', custom_voice: 'canonical voice' })
    await pending.finish(canonical)
    for (const key of customFields) expect(field(v, key).value).toBe(canonical[key])
    const later = personality({ preset: 'custom', custom_name: 'later name', custom_identity: 'later identity', custom_voice: 'later voice' })
    await refresh(later)
    for (const key of customFields) expect(field(v, key).value).toBe(later[key])
  })

  it('advances untouched preset baseline after dispatch and adoption so later reads are followed', async () => {
    const v = await view()
    await choose(v, 'professional')
    const pending = await holdSave(v, 'write')
    await pending.finish(personality({ preset: 'professional' }))
    expect(selected(v)).toBe('professional')
    await refresh(personality({ preset: 'odin' }))
    expect(selected(v)).toBe('odin')
    await refresh(personality({ preset: 'professional' }))
    expect(selected(v)).toBe('professional')
  })

  for (const key of customFields) {
    it(`a ${key} away/back edit outside a save stays owned, while genuinely untouched fields follow two reads`, async () => {
      const initial = personality({ preset: 'custom' })
      const v = await view(initial)
      await type(v, key, 'temporary edit')
      await type(v, key, initial[key])
      for (const prefix of ['remote', 'later']) {
        const incoming = personality({ preset: 'custom', custom_name: `${prefix} name`, custom_identity: `${prefix} identity`, custom_voice: `${prefix} voice` })
        await refresh(incoming)
        for (const fieldKey of customFields) expect(field(v, fieldKey).value).toBe(fieldKey === key ? initial[key] : incoming[fieldKey])
      }
    })
  }

  it('an explicit return to the loaded preset stays owned through refresh, then successful Save releases it to follow', async () => {
    const v = await view()
    await choose(v, 'professional')
    await choose(v, 'odin')
    await refresh(personality({ preset: 'professional' }))
    expect(selected(v)).toBe('odin')
    const pending = await holdSave(v, 'write')
    await pending.finish(personality({ preset: 'odin' }))
    await refresh(personality({ preset: 'professional' }))
    expect(selected(v)).toBe('professional')
  })

  it('does not release a dirty field baseline when a save was not dispatched', async () => {
    const initial = personality({ preset: 'custom' })
    const v = await view(initial)
    await type(v, 'custom_name', 'temporary edit')
    await type(v, 'custom_name', initial.custom_name)
    set.mockResolvedValueOnce(failed)
    await Promise.resolve(panel(v).button('Save').fire('click'))
    await flush()
    await refresh(personality({ preset: 'custom', custom_name: 'remote name' }))
    expect(field(v, 'custom_name').value).toBe(initial.custom_name)
  })

  for (const key of customFields) {
    it(`does not accept an unsent dirty ${key} when saving only a built-in preset`, async () => {
      const initial = personality({ preset: 'custom' })
      const v = await view(initial)
      await type(v, key, 'temporary edit')
      await type(v, key, initial[key])
      await choose(v, 'professional')
      const pending = await holdSave(v, 'write')
      expect(set.mock.calls[0]![0]).toEqual({ preset: 'professional', custom_name: initial.custom_name, custom_identity: initial.custom_identity, custom_voice: initial.custom_voice })
      const canonical = personality({ preset: 'professional', [key]: 'remote unsent field' })
      await pending.finish(canonical)
      await choose(v, 'custom')
      expect(field(v, key).value).toBe(initial[key])
    })
  }

  it('a successful write releases submitted fields even when readback fails, so a later read can adopt', async () => {
    const v = await view(personality({ preset: 'custom' }))
    for (const key of customFields) await type(v, key, `submitted ${key}`)
    get.mockResolvedValueOnce(failed)
    await Promise.resolve(panel(v).button('Save').fire('click'))
    await flush()
    expect(set).toHaveBeenCalledTimes(1)
    for (const key of customFields) expect(field(v, key).value).toBe(`submitted ${key}`)
    const canonical = personality({ preset: 'custom', custom_name: 'later name', custom_identity: 'later identity', custom_voice: 'later voice' })
    await refresh(canonical)
    for (const key of customFields) expect(field(v, key).value).toBe(canonical[key])
  })

  for (const phase of ['write', 'readback'] as const) {
    for (const key of customFields) {
      it(`late success keeps newer ${key} intent during ${phase} and adopts the untouched submitted fields`, async () => {
        const v = await view(personality({ preset: 'custom' }))
        for (const fieldKey of customFields) await type(v, fieldKey, `submitted ${fieldKey}`)
        const unknown = { ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: 'personality-command' } } as const
        set.mockResolvedValueOnce(unknown)
        await Promise.resolve(panel(v).button('Save').fire('click'))
        await flush()
        expect(panel(v).button('Save').props.disabled).toBe(true)
        expect(get).toHaveBeenCalledTimes(1)
        const readback = deferred<Result<Personality>>()
        get.mockReturnValueOnce(readback.promise)
        if (phase === 'write') await type(v, key, `submitted ${key}`)
        const { applyReceipt } = await import('../../src/renderer/src/store')
        applyReceipt({ id: 'personality-command', settled: ok({ status: 'updated', preset: 'custom' }) })
        await flush()
        expect(get).toHaveBeenCalledTimes(2)
        if (phase === 'readback') await type(v, key, `submitted ${key}`)
        const canonical = personality({ preset: 'custom', custom_name: 'canonical name', custom_identity: 'canonical identity', custom_voice: 'canonical voice' })
        loaded = canonical
        readback.resolve(ok(canonical))
        await flush()
        for (const fieldKey of customFields) expect(field(v, fieldKey).value).toBe(fieldKey === key ? `submitted ${key}` : canonical[fieldKey])
        expect((await nextSave(v))[key]).toBe(`submitted ${key}`)
      })
    }
  }

  it('a failed late receipt does not accept edits as saved', async () => {
    const initial = personality({ preset: 'custom' })
    const v = await view(initial)
    await type(v, 'custom_name', 'temporary edit')
    await type(v, 'custom_name', initial.custom_name)
    const unknown = { ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: 'personality-command' } } as const
    set.mockResolvedValueOnce(unknown)
    await Promise.resolve(panel(v).button('Save').fire('click'))
    await flush()
    loaded = personality({ preset: 'custom', custom_name: 'remote name' })
    const { applyReceipt } = await import('../../src/renderer/src/store')
    applyReceipt({ id: 'personality-command', settled: failed })
    await flush()
    expect(field(v, 'custom_name').value).toBe(initial.custom_name)
  })

  it('a late Professional receipt keeps the newer return to Odin and the next Save sends Odin', async () => {
    const v = await view()
    await choose(v, 'professional')
    const unknown = { ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: 'personality-command' } } as const
    set.mockResolvedValueOnce(unknown)
    await Promise.resolve(panel(v).button('Save').fire('click'))
    await flush()
    expect(panel(v).button('Save').props.disabled).toBe(true)
    await choose(v, 'odin')
    loaded = personality({ preset: 'professional' })
    const { applyReceipt } = await import('../../src/renderer/src/store')
    applyReceipt({ id: 'personality-command', settled: ok({ status: 'updated', preset: 'professional' }) })
    await flush()
    expect(selected(v)).toBe('odin')
    expect(await nextSave(v)).toEqual({ preset: 'odin', custom_name: 'loaded name', custom_identity: 'loaded identity', custom_voice: 'loaded voice' })
  })

  it('an older held readback cannot replace the newer second Save readback', async () => {
    const v = await view()
    await choose(v, 'professional')
    const first = await holdSave(v, 'readback')
    // act releases the write lock after its receipt, while its readback can still be in flight.
    expect(panel(v).button('Save').props.disabled).toBe(false)
    await choose(v, 'odin')
    loaded = personality({ preset: 'odin' })
    expect(await nextSave(v)).toEqual({ preset: 'odin', custom_name: 'loaded name', custom_identity: 'loaded identity', custom_voice: 'loaded voice' })
    expect(selected(v)).toBe('odin')
    await first.finish(personality({ preset: 'professional' }))
    expect(selected(v)).toBe('odin')
    const { stateStore } = await import('../../src/renderer/src/stores/state')
    expect(stateStore.personality?.preset).toBe('odin')
  })

  it('a successful save with failed readback still protects a newer same-value input on the later read', async () => {
    const v = await view(personality({ preset: 'custom' }))
    await type(v, 'custom_name', 'submitted name')
    const receipt = deferred<Awaited<ReturnType<typeof set>>>()
    set.mockReturnValueOnce(receipt.promise)
    get.mockResolvedValueOnce(failed)
    const saving = Promise.resolve(panel(v).button('Save').fire('click'))
    await flush()
    await type(v, 'custom_name', 'submitted name')
    receipt.resolve(ok({ status: 'updated', preset: 'custom' }))
    await saving
    await flush()
    await refresh(personality({ preset: 'custom', custom_name: 'canonical name', custom_identity: 'canonical identity' }))
    expect(field(v, 'custom_name').value).toBe('submitted name')
    expect(field(v, 'custom_identity').value).toBe('canonical identity')
  })
})
