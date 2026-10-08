import { expect, it } from 'vitest'
import type { ConfigField } from '../src/shared/api'
import { advancedPresentation as presentation, assertAdvancedInventory as assertInventory, assertAdvancedScrollCoverage } from '../src/main/advanced-capture-contract'
const ADVANCED_FIELDS = presentation.fields, ADVANCED_CATEGORIES = presentation.categories
const assertAdvancedInventory = (fields: ConfigField[], paths: string[], categories: string[]) => assertInventory(fields, paths, categories, presentation)

it('uses the single explicit presentation manifest without duplicating renderer metadata', () => {
  expect(presentation.fields).toHaveLength(55)
  expect(presentation.categories).toHaveLength(5)
})

// Harmless unit metadata, explicitly not real-core evidence.
const fields = ADVANCED_FIELDS.map(({ path }) => ({ path, sensitivity: 'public', secret_route: null })) as ConfigField[]
const paths = ADVANCED_FIELDS.map(({ path }) => path)
it('requires every real-schema Advanced owner, all categories, and no missing/extra/duplicate/secret rows', () => {
  expect(() => assertAdvancedInventory(fields, paths, [...ADVANCED_CATEGORIES])).not.toThrow()
  expect(() => assertAdvancedInventory(fields.slice(1), paths, [...ADVANCED_CATEGORIES])).toThrow('REAL engine schema')
  expect(() => assertAdvancedInventory(fields, paths.slice(1), [...ADVANCED_CATEGORIES])).toThrow('full rendered Advanced inventory')
  expect(() => assertAdvancedInventory(fields, [...paths, paths[0]!], [...ADVANCED_CATEGORIES])).toThrow('exactly once')
  expect(() => assertAdvancedInventory(fields, [...paths, 'unexpected'], [...ADVANCED_CATEGORIES])).toThrow('full rendered Advanced inventory')
  expect(() => assertAdvancedInventory(fields, paths, [])).toThrow('every Advanced category')
  expect(() => assertAdvancedInventory([{ ...fields[0]!, sensitivity: 'sensitive' }, ...fields.slice(1)], paths, [...ADVANCED_CATEGORIES])).toThrow('must not expose secrets')
  expect(() => assertAdvancedInventory([{ ...fields[0]!, secret_route: 'secrets.set' }, ...fields.slice(1)], paths, [...ADVANCED_CATEGORIES])).toThrow('must not expose secrets')
})
it('accounts for real nested schema members through one container owner', () => {
  const nested = fields.filter((field) => field.path !== 'openai_compatible.model_profiles')
  nested.push({ path: 'openai_compatible.model_profiles.context_window', sensitivity: 'public' } as ConfigField)
  expect(() => assertAdvancedInventory(nested, paths, [...ADVANCED_CATEGORIES])).not.toThrow()
})
it('requires stable contiguous scroll coverage and visible evidence for every owner', () => {
  const make = () => [{ top: 0, client: 100, height: 180, path: '/external/top.png', visibleOwners: paths.slice(0, 20) },
    { top: 80, client: 100, height: 180, path: '/external/bottom.png', visibleOwners: paths.slice(20) }]
  expect(() => assertAdvancedScrollCoverage(make(), paths)).not.toThrow()
  const check = (change: (frames: ReturnType<typeof make>) => void) => { const frames = make(); change(frames); return () => assertAdvancedScrollCoverage(frames, paths) }
  expect(check((frames) => { frames.pop() })).toThrow('multiple scroll frames')
  expect(check((frames) => { frames[0]!.top = 1 })).toThrow('begin at the top')
  expect(check((frames) => { frames[1]!.top = 101 })).toThrow('without gaps')
  expect(check((frames) => { frames[1]!.top = 50 })).toThrow('reach the bottom')
  expect(check((frames) => { frames[1]!.height = 190 })).toThrow('height must remain stable')
  expect(check((frames) => { frames[1]!.visibleOwners = [] })).toThrow('every Advanced owner')
  expect(check((frames) => { frames[1]!.path = '' })).toThrow('needs a screenshot')
  expect(check((frames) => { frames[1]!.client = Number.NaN })).toThrow('invalid scroll dimensions')
})
