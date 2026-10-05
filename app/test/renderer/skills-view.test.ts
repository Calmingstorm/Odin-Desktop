// The skills section, mounted with its real code and the real management store over a fake bridge.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result } from '../../src/shared/api'
import { flush, mount, type Host } from './component-host'

const ok = <T>(result: T): Result<T> => ({ ok: true, result })

let root: Host
let skills: Record<string, string>
let landSave: Array<() => void>

beforeEach(async () => {
  vi.resetModules()
  skills = {}
  landSave = []
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      skillsList: async () => ok(Object.keys(skills).map((name) => ({ name, status: 'loaded', version: '1', description: '' }))),
      skillsGet: async (params: { name: string }) => ok({ name: params.name, code: skills[params.name], config: {}, metadata: { config_schema: {} } }),
      skillsValidate: async () => ok({ valid: true, errors: [], warnings: [], metadata: null, definition_keys: [] }),
      skillsSave: (params: { name: string; code: string }) => {
        skills[params.name] = params.code
        return new Promise((resolve) => landSave.push(() => resolve(ok({ result: 'created' }))))
      }
    }
  }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
  const Skills = (await import('../../src/renderer/src/views/settings/Skills.vue')).default
  root = mount(Skills).root
  await flush()
})

const editor = (): Host => root.findAll((host) => host.tag === 'textarea')[0]!

describe('review round 4: the skill editor', () => {
  it('keeps code typed while a new skill is created, and shows it as created (13.R4.2)', async () => {
    root.button('New skill').fire('click')
    await flush()
    root.findAll((host) => host.tag === 'input' && host.props.placeholder === 'my_skill')[0]!.type('fresh')
    editor().type('as sent')
    await flush()
    root.button('Create').fire('click')
    await flush()
    editor().type('typed during create')
    await flush()
    landSave.shift()!()
    await flush()
    expect(editor().value).toBe('typed during create')
    const section = root.findAll((host) => host.props['aria-label'] === 'Skill editor')[0]!
    expect(section.find('h3')?.textContent()).toBe('fresh')
    expect(section.button('Save')).toBeDefined() // an existing skill now: it saves rather than creates
  })
})
