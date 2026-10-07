// Round-5 editor ownership: real compiled Skills controls and store actions over a held bridge.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result, SkillDetail, SkillValidation } from '../../src/shared/api'
import { flush, Host, mount, type Mounted } from './component-host'

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const unknown = (id: string): Result<never> => ({
  ok: false,
  error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: id }
})
function deferred<T>() {
  let resolve!: (answer: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
const valid: SkillValidation = { valid: true, errors: [], warnings: [], metadata: null, definition_keys: [] }
const detail = (name: string, code = `${name}-core`, units = 'metric'): SkillDetail => ({
  name, code, description: '', loaded_at: '', status: 'loaded', version: '1', input_schema: {}, file_path: `${name}.py`,
  handoff_to_codex: false, config: { units },
  metadata: { version: '1', has_config: true, config_schema: { properties: { units: { type: 'string' } } } }
})

let store: typeof import('../../src/renderer/src/stores/management')
let mounted: Mounted | undefined
let stored: Record<string, SkillDetail>
let rootNodeDescriptor: PropertyDescriptor | undefined
const bridge = {
  skillsList: vi.fn(async () => ok(Object.keys(stored).map((name) => ({ name, status: 'loaded', version: '1', description: '' })))),
  skillsGet: vi.fn(async ({ name }: { name: string }) => ok(stored[name]!)),
  skillsValidate: vi.fn(async (_params: { code: string }): Promise<Result<SkillValidation>> => ok(valid)),
  skillsSave: vi.fn(async ({ name, code }: { name: string; code: string; create: boolean }): Promise<Result<{ result: string }>> => {
    stored[name] = detail(name, code)
    return ok({ result: 'Saved.' })
  }),
  skillsConfigSet: vi.fn(async ({ name, config }: { name: string; config: Record<string, unknown> }): Promise<Result<{ config: Record<string, unknown> }>> => {
    stored[name] = { ...stored[name]!, config: { ...config } }
    return ok({ config: { ...config } })
  })
}

beforeEach(async () => {
  vi.resetModules()
  vi.mocked(bridge.skillsList).mockClear()
  vi.mocked(bridge.skillsGet).mockReset().mockImplementation(async ({ name }) => ok(stored[name]!))
  vi.mocked(bridge.skillsValidate).mockReset().mockResolvedValue(ok(valid))
  vi.mocked(bridge.skillsSave).mockReset().mockImplementation(async ({ name, code }) => {
    stored[name] = detail(name, code)
    return ok({ result: 'Saved.' })
  })
  vi.mocked(bridge.skillsConfigSet).mockReset().mockImplementation(async ({ name, config }) => {
    stored[name] = { ...stored[name]!, config: { ...config } }
    return ok({ config: { ...config } })
  })
  stored = { a: detail('a'), b: detail('b') }
  vi.stubGlobal('window', { odin: bridge })
  vi.stubGlobal('document', { activeElement: null })
  // Vue's value-changing v-model update asks for DOM identity. Keep this host-only supplement local to this file.
  vi.stubGlobal('Document', class Document {})
  vi.stubGlobal('ShadowRoot', class ShadowRoot {})
  rootNodeDescriptor = Object.getOwnPropertyDescriptor(Host.prototype, 'getRootNode')
  Object.defineProperty(Host.prototype, 'getRootNode', { configurable: true, value: () => document })
  store = await import('../../src/renderer/src/stores/management')
})
afterEach(() => {
  mounted?.unmount()
  mounted = undefined
  if (rootNodeDescriptor) Object.defineProperty(Host.prototype, 'getRootNode', rootNodeDescriptor)
  else Reflect.deleteProperty(Host.prototype, 'getRootNode')
  vi.unstubAllGlobals()
})

async function skills() {
  mounted = mount((await import('../../src/renderer/src/views/settings/Skills.vue')).default)
  await flush()
}
const textarea = () => mounted!.root.findAll((host) => host.tag === 'textarea')[0]!
const editorSection = () => mounted!.root.findAll((host) => host.props['aria-label'] === 'Skill editor')[0]!
function draft(name = 'fresh', code = 'as sent') {
  store.newSkill(code)
  store.management.editor!.name = name
}
async function newDraft() {
  await skills()
  mounted!.root.button('New skill').fire('click')
  await flush()
  mounted!.root.findAll((host) => host.tag === 'input' && host.props.placeholder === 'my_skill')[0]!.type('fresh')
  textarea().type('as sent')
  await flush()
}
async function receipt(id: string, answer: Result<unknown>) {
  ;(await import('../../src/renderer/src/store')).applyReceipt({ id, settled: answer })
  await flush()
}
function holdSave() {
  const answer = deferred<Result<{ result: string }>>()
  bridge.skillsSave.mockImplementation(({ name, code }) => {
    stored[name] = detail(name, code)
    return answer.promise
  })
  return answer
}

describe('13.R5.1: validation and create share one admitted action', () => {
  for (const late of [false, true]) {
    it(`mounted Create is busy during validation and keeps later Python after ${late ? 'a late receipt' : 'success'}`, async () => {
      const validating = deferred<Result<SkillValidation>>()
      bridge.skillsValidate.mockImplementation(() => validating.promise)
      const saving = holdSave()
      await newDraft()
      mounted!.root.button('Create').fire('click')
      await flush()
      textarea().type('newer Python')
      await flush()
      // The original repro clicked this enabled control a second time here. A disabled control cannot be clicked.
      expect(mounted!.root.button('Create').props.disabled).toBe(true)
      expect(bridge.skillsValidate).toHaveBeenCalledExactlyOnceWith({ code: 'as sent' })
      expect(bridge.skillsSave).not.toHaveBeenCalled()
      validating.resolve(ok(valid))
      await flush()
      expect(bridge.skillsSave).toHaveBeenCalledExactlyOnceWith({ name: 'fresh', code: 'as sent', create: true })
      expect(mounted!.root.button('Create').props.disabled).toBe(true)
      saving.resolve(late ? unknown('create-r5') : ok({ result: 'Created.' }))
      await flush()
      if (late) {
        expect(mounted!.root.button('Create').props.disabled).toBe(true)
        expect(store.management.editor?.create).toBe(true)
        await receipt('create-r5', ok({ result: 'Created.' }))
      }
      expect(store.management.editor).toMatchObject({ name: 'fresh', code: 'newer Python', create: false })
      expect(textarea().value).toBe('newer Python')
      expect(editorSection().find('h3')?.textContent()).toBe('fresh')
      expect(editorSection().button('Save').props.disabled).toBe(false)
      expect(bridge.skillsGet).toHaveBeenCalledExactlyOnceWith({ name: 'fresh' })
    })

    it(`refuses a second store save before validation and after ${late ? 'an unknown outcome' : 'dispatch'}, without lending its baseline`, async () => {
      const validating = deferred<Result<SkillValidation>>()
      bridge.skillsValidate.mockImplementation(() => validating.promise)
      const saving = holdSave()
      draft()
      const first = store.saveSkill()
      store.management.editor!.code = 'newer Python'
      expect(await store.saveSkill()).toBe(false)
      expect(bridge.skillsValidate).toHaveBeenCalledTimes(1)
      validating.resolve(ok(valid))
      await flush()
      if (late) {
        saving.resolve(unknown('busy-create-r5'))
        expect(await first).toBe(false)
      }
      expect(await store.saveSkill()).toBe(false)
      expect(bridge.skillsValidate).toHaveBeenCalledTimes(1)
      expect(bridge.skillsSave).toHaveBeenCalledTimes(1)
      if (late) await receipt('busy-create-r5', ok({ result: 'Created.' }))
      else {
        saving.resolve(ok({ result: 'Created.' }))
        expect(await first).toBe(true)
        await flush()
      }
      expect(store.management.editor).toMatchObject({ name: 'fresh', code: 'newer Python', create: false })
      expect(store.management.busy['skill:fresh']).toBe(false)
    })
  }

  it('a refused create does not establish a loaded baseline, even when its validation would be valid', async () => {
    stored.fresh = detail('fresh', 'authoritative Python')
    draft('fresh', 'never sent')
    const pending = deferred<Result<string>>()
    const busy = store.act('skill:fresh', () => pending.promise, (answer) => answer)
    expect(await store.saveSkill()).toBe(false)
    expect(bridge.skillsValidate).not.toHaveBeenCalled()
    expect(bridge.skillsSave).not.toHaveBeenCalled()
    store.management.editor!.code = 'typed after refusal'
    pending.resolve(ok('Done.'))
    await busy
    await store.openSkill('fresh')
    // Explicitly opening an existing skill adopts its code; an unsent create did not become its loaded editor.
    expect(store.management.editor).toEqual({ name: 'fresh', code: 'authoritative Python', create: false })
  })

  for (const failedBridge of [false, true]) {
    it(`releases admission after ${failedBridge ? 'a validation route failure' : 'invalid Python'} and allows a corrected retry`, async () => {
      bridge.skillsValidate.mockResolvedValueOnce(failedBridge
        ? { ok: false, error: { code: 'unavailable', message: 'Validation unavailable.' } }
        : ok({ ...valid, valid: false, errors: ['execute() is missing.'] }))
      draft()
      expect(await store.saveSkill()).toBe(false)
      expect(bridge.skillsSave).not.toHaveBeenCalled()
      expect(store.management.validation?.valid).toBe(false)
      const message = failedBridge ? 'Validation unavailable.' : 'execute() is missing.'
      expect(store.management.validation?.errors).toEqual([message])
      expect(store.management.notes['skill:fresh']).toBe(message)
      expect(store.management.busy['skill:fresh']).toBe(false)
      store.management.editor!.code = 'corrected Python'
      expect(await store.saveSkill()).toBe(true)
      await flush()
      expect(bridge.skillsValidate).toHaveBeenCalledTimes(2)
      expect(bridge.skillsSave).toHaveBeenCalledExactlyOnceWith({ name: 'fresh', code: 'corrected Python', create: true })
      expect(store.management.editor).toMatchObject({ name: 'fresh', code: 'corrected Python', create: false })
    })
  }

  it('a create whose editor was closed and replaced while validating does not lend that editor its baseline', async () => {
    const validating = deferred<Result<SkillValidation>>()
    bridge.skillsValidate.mockImplementation(() => validating.promise)
    draft()
    const saving = store.saveSkill()
    store.closeSkill()
    draft('fresh', 'replacement draft')
    const expected = { ...store.management.editor! }
    validating.resolve(ok(valid))
    expect(await saving).toBe(true)
    await flush()
    // The already requested write is allowed to finish. Navigation is not cancellation.
    expect(bridge.skillsSave).toHaveBeenCalledExactlyOnceWith({ name: 'fresh', code: 'as sent', create: true })
    expect(bridge.skillsGet).not.toHaveBeenCalled()
    expect(store.management.editor).toEqual(expected)
    store.management.editor!.name = 'fresh'
    await store.openSkill('fresh')
    expect(store.management.editor).toEqual({ name: 'fresh', code: 'as sent', create: false })
  })

  it('an admitted create retains its sent baseline after renaming away during validation and back before success', async () => {
    const validating = deferred<Result<SkillValidation>>()
    bridge.skillsValidate.mockImplementation(() => validating.promise)
    const answer = holdSave()
    draft()
    const saving = store.saveSkill()
    store.management.editor!.name = 'other'
    store.management.editor!.code = 'newer Python'
    validating.resolve(ok(valid))
    await flush()
    expect(bridge.skillsSave).toHaveBeenCalledExactlyOnceWith({ name: 'fresh', code: 'as sent', create: true })
    store.management.editor!.name = 'fresh'
    answer.resolve(ok({ result: 'Created.' }))
    expect(await saving).toBe(true)
    await flush()
    expect(store.management.editor).toEqual({ name: 'fresh', code: 'newer Python', create: false })
    expect(bridge.skillsGet).toHaveBeenCalledExactlyOnceWith({ name: 'fresh' })
  })

  it('serializes per skill, not globally, so another draft can validate and create while the first waits', async () => {
    const validating = deferred<Result<SkillValidation>>()
    bridge.skillsValidate.mockImplementationOnce(() => validating.promise)
    draft('first', 'first Python')
    const first = store.saveSkill()
    draft('second', 'second Python')
    expect(await store.saveSkill()).toBe(true)
    await flush()
    expect(store.management.editor).toMatchObject({ name: 'second', code: 'second Python', create: false })
    validating.resolve(ok(valid))
    expect(await first).toBe(true)
    await flush()
    expect(bridge.skillsSave.mock.calls.map(([params]) => params.name)).toEqual(['second', 'first'])
    expect(store.management.editor?.name).toBe('second')
  })

  it('after create readback, an existing-code save still reads back its saved detail', async () => {
    draft()
    expect(await store.saveSkill()).toBe(true)
    await flush()
    expect(store.management.editor?.create).toBe(false)
    store.management.editor!.code = 'second write'
    expect(await store.saveSkill()).toBe(true)
    await flush()
    expect(bridge.skillsSave.mock.calls.map(([params]) => params.create)).toEqual([true, false])
    expect(bridge.skillsGet).toHaveBeenCalledTimes(2)
    expect(store.management.skill?.code).toBe('second write')
  })

  it('an existing-code save from visible A while Open B is pending cannot replace the newer detail request', async () => {
    const openingB = deferred<Result<SkillDetail>>()
    bridge.skillsGet.mockImplementation(({ name }) => name === 'b' ? openingB.promise : Promise.resolve(ok(stored[name]!)))
    await store.openSkill('a')
    const opening = store.openSkill('b')
    store.management.editor!.code = 'saved A code'
    expect(await store.saveSkill()).toBe(true)
    await flush()
    expect(bridge.skillsGet.mock.calls.map(([params]) => params.name)).toEqual(['a', 'b'])
    openingB.resolve(ok(stored.b!))
    await opening
    expect(store.management.editor).toEqual({ name: 'b', code: 'b-core', create: false })
  })
})

describe('13.R5.2: a settings answer owns both the editor epoch and skill name', () => {
  for (const late of [false, true]) {
    for (const configFirst of [false, true]) {
    it(`mounted Open B, then visible Save A settings, leaves B intact when ${late ? 'a late receipt' : 'success'} lands ${configFirst ? 'before' : 'after'} B detail`, async () => {
      const openingB = deferred<Result<SkillDetail>>()
      const savingA = deferred<Result<{ config: Record<string, unknown> }>>()
      bridge.skillsGet.mockImplementation(({ name }) => name === 'b' ? openingB.promise : Promise.resolve(ok(stored[name]!)))
      bridge.skillsConfigSet.mockImplementation(() => savingA.promise)
      await skills()
      mounted!.root.findAll((host) => host.tag === 'button' && host.textContent() === 'Open')[0]!.fire('click')
      await flush()
      const settings = mounted!.root.findAll((host) => host.tag === 'input' && host.props.type === 'text')[0]!
      settings.type('imperial')
      mounted!.root.findAll((host) => host.tag === 'button' && host.textContent() === 'Open')[1]!.fire('click')
      await flush()
      expect(store.management.editor?.name).toBe('a')
      expect(mounted!.root.button('Save settings').props.disabled).toBeFalsy()
      mounted!.root.button('Save settings').fire('click')
      await flush()
      expect(bridge.skillsConfigSet).toHaveBeenCalledExactlyOnceWith({ name: 'a', config: { units: 'imperial' } })
      const settleConfig = async () => {
        savingA.resolve(late ? unknown('config-a-r5') : ok({ config: { units: 'imperial' } }))
        await flush()
        if (late) {
          expect(store.management.busy['skill-config:a']).toBe(true)
          await receipt('config-a-r5', ok({ config: { units: 'imperial' } }))
        }
      }
      if (configFirst) {
        await settleConfig()
        expect(bridge.skillsGet.mock.calls.map(([params]) => params.name)).toEqual(['a', 'b'])
      }
      openingB.resolve(ok(stored.b!))
      await flush()
      textarea().type('unsent B code')
      await flush()
      if (!configFirst) await settleConfig()
      expect(bridge.skillsGet.mock.calls.map(([params]) => params.name)).toEqual(['a', 'b'])
      expect(store.management.editor).toEqual({ name: 'b', code: 'unsent B code', create: false })
      expect(store.management.skill?.name).toBe('b')
      expect(store.management.skillConfig).toEqual({ units: 'metric' })
      expect(textarea().value).toBe('unsent B code')
      expect(editorSection().find('h3')?.textContent()).toBe('b')
      expect(store.management.busy['skill-config:a']).toBe(false)
      expect(store.management.notes['skill-config:a']).toBe('Saved.')
    })
    }

    it(`does not refresh a newly opened same-name editor from an older ${late ? 'late' : 'ordinary'} settings save`, async () => {
      const saving = deferred<Result<{ config: Record<string, unknown> }>>()
      bridge.skillsConfigSet.mockImplementation(() => saving.promise)
      await store.openSkill('a')
      const pending = store.saveSkillConfig('a', { units: 'imperial' })
      store.closeSkill()
      await store.openSkill('a')
      store.management.editor!.code = 'new epoch code'
      store.management.skillConfig.units = 'new epoch config'
      saving.resolve(late ? unknown('config-epoch-r5') : ok({ config: { units: 'imperial' } }))
      expect(await pending).toBe(!late)
      if (late) await receipt('config-epoch-r5', ok({ config: { units: 'imperial' } }))
      await flush()
      expect(bridge.skillsGet).toHaveBeenCalledTimes(2)
      expect(store.management.editor?.code).toBe('new epoch code')
      expect(store.management.skillConfig.units).toBe('new epoch config')
    })

    it(`still refreshes its own editor after ${late ? 'a late receipt' : 'success'}, preserving unsent Python`, async () => {
      const saving = deferred<Result<{ config: Record<string, unknown> }>>()
      bridge.skillsConfigSet.mockImplementation(() => saving.promise)
      await store.openSkill('a')
      store.management.editor!.code = 'unsent A code'
      const pending = store.saveSkillConfig('a', { units: 'imperial' })
      stored.a = detail('a', 'a-core', 'imperial')
      saving.resolve(late ? unknown('config-own-r5') : ok({ config: { units: 'imperial' } }))
      expect(await pending).toBe(!late)
      if (late) await receipt('config-own-r5', ok({ config: { units: 'imperial' } }))
      await flush()
      expect(bridge.skillsGet).toHaveBeenCalledTimes(2)
      expect(store.management.editor).toMatchObject({ name: 'a', code: 'unsent A code', create: false })
      expect(store.management.skillConfig).toEqual({ units: 'imperial' })
    })
  }
})
