// Shared by the production-entry smoke and isolated visual evidence lane.
// Expectations come from the explicit UI allowlist, metadata only from settings.schema.
import { strict as assert } from 'node:assert'
import type { ConfigField } from '../shared/api'
import { ADVANCED_CATEGORIES, ADVANCED_FIELDS } from '../renderer/src/settings-presentation'
export interface AdvancedEntry { path: string; label: string; help: string; category: string }
export interface AdvancedPresentation { fields: AdvancedEntry[]; categories: string[] }
// The single explicit presentation manifest is pure metadata, with no stores/UI imports.
export const advancedPresentation: AdvancedPresentation = { fields: [...ADVANCED_FIELDS], categories: [...ADVANCED_CATEGORIES] }
export function assertAdvancedInventory(fields: ConfigField[], paths: string[], categories: string[], presentation: AdvancedPresentation): void {
  assert.deepEqual(categories, presentation.categories, 'every Advanced category must render in reviewed order')
  const expected = presentation.fields.map((entry) => entry.path)
  assert(expected.length > 30, 'Advanced proof must cover the full allowlist, not a tiny fixture')
  assert.equal(new Set(paths).size, paths.length, 'each Advanced owner must render exactly once')
  assert.deepEqual([...paths].sort(), [...expected].sort(), 'full rendered Advanced inventory must equal the explicit allowlist')
  for (const entry of presentation.fields) {
    const owned = fields.filter((field) => field.path === entry.path || field.path.startsWith(`${entry.path}.`))
    assert(owned.length > 0, `${entry.path} must exist in the REAL engine schema`)
    assert(owned.every((field) => field.sensitivity === 'public' && !field.secret_route), `${entry.path} must not expose secrets`)
  }
  // Include nested record metadata in coverage, without inventing independent editors.
  const schemaInventory = fields.filter((field) => presentation.fields.some((entry) => field.path === entry.path || field.path.startsWith(`${entry.path}.`)))
  for (const field of schemaInventory) {
    assert.equal(presentation.fields.filter((entry) => field.path === entry.path || field.path.startsWith(`${entry.path}.`)).length, 1,
      `${field.path} must have exactly one Advanced presentation owner`)
  }
}

export interface ScrollFrame { top: number; client: number; height: number; path: string; visibleOwners: string[] }
export function assertAdvancedScrollCoverage(frames: ScrollFrame[], paths: string[]): void {
  assert(frames.length > 1, 'full Advanced requires multiple scroll frames')
  assert.equal(frames[0]!.top, 0, 'capture must begin at the top')
  const height = frames[0]!.height
  for (let index = 0; index < frames.length; index++) {
    const frame = frames[index]!
    assert.equal(frame.height, height, 'Advanced height must remain stable throughout capture')
    assert(Number.isFinite(frame.client) && Number.isFinite(frame.top) && Number.isFinite(height) && frame.client > 0 && frame.top >= 0 && frame.top <= height, 'invalid scroll dimensions')
    assert(frame.path.endsWith('.png'), 'every scroll frame needs a screenshot')
    if (index > 0) {
      const previous = frames[index - 1]!
      assert(frame.top > previous.top && frame.top <= previous.top + previous.client, 'scroll frames must advance without gaps')
    }
  }
  const last = frames.at(-1)!
  assert(last.top + last.client >= height - 1, 'capture must reach the bottom')
  const visible = new Set(frames.flatMap((frame) => frame.visibleOwners))
  assert.deepEqual([...visible].sort(), [...paths].sort(), 'every Advanced owner must be visible in captured frames')
}
