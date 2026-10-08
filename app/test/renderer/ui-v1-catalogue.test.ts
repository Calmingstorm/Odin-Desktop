import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { ADVANCED_FIELDS, advancedMatches, isCuratedPath, presentationDestination, presentationFor, restartFields, settingsFields } from '../../src/renderer/src/settings-presentation'
import type { ConfigField } from '../../src/shared/api'

const inventory = new Map(readFileSync(new URL('../../../docs/design/ui-v1-core-inventory.tsv', import.meta.url), 'utf8').trim().split('\n').slice(1).map((line) => {
  const [path, disposition] = line.split('\t'); return [path!, disposition!]
}))
const pages = ['general', 'models', 'personality', 'tools', 'skills', 'mcp', 'hosts', 'work', 'data']
describe('explicit settings presentation catalogue', () => {
  it('contains only inventory-approved paths, placements and one visible owner', () => {
    const seen = new Set<string>()
    for (const page of pages) for (const placement of ['primary', 'more-options'] as const) {
      for (const field of settingsFields(page, placement)) {
        expect(inventory.get(field.path), field.path).toBe(placement)
        expect(field.key).toBe(field.path)
        expect(field.label).toBeTruthy(); expect(field.help).toBeTruthy()
        expect(seen.has(field.path), field.path).toBe(false)
        seen.add(field.path)
        expect(presentationDestination(field.path)).toBe(page)
        expect(presentationFor(field.path)?.label).toBe(field.label)
        expect(`${field.label} ${field.help}`).not.toMatch(/\b(core|owner|transaction|metadata|cleanup)\b/i)
      }
    }
    for (const field of ADVANCED_FIELDS) {
      expect(inventory.get(field.path), field.path).toBe('advanced')
      expect(seen.has(field.path)).toBe(false)
      expect(presentationDestination(field.path)).toBe('advanced')
    }
  })
  it('never discovers leftovers or duplicates managed controls', () => {
    expect(settingsFields('unknown', 'primary')).toEqual([])
    expect(settingsFields('mcp', 'primary')).toEqual([])
    expect(settingsFields('hosts', 'primary')).toEqual([])
    expect(settingsFields('work', 'primary')).toEqual([])
    expect(settingsFields('tools', 'more')).toEqual(settingsFields('tools', 'more-options'))
    expect(presentationFor('computer.storage_dir')).toBeUndefined()
    expect(presentationFor('logging.directory')).toBeUndefined()
    expect(presentationDestination('openai_compatible.model_profiles.custom.supported_efforts')).toBe('advanced')
    expect(presentationDestination('mcp.servers.example.cwd')).toBe('mcp')
    expect(presentationDestination('tools.hosts.example.address')).toBe('hosts')
  })
  it('consciously routes every visible inventory fact, including dedicated records', () => {
    for (const [path, disposition] of inventory) {
      if (!['primary', 'more-options', 'advanced'].includes(disposition)) continue
      expect(presentationFor(path), path).toBeDefined()
      expect(presentationDestination(path), path).toBeDefined()
    }
  })
  it('searches plain labels and detects curated records and restart state without schema fallbacks', () => {
    expect(isCuratedPath('sessions.context_budget_overrides.model')).toBe(true)
    expect(isCuratedPath('new.setting')).toBe(false)
    expect(advancedMatches(ADVANCED_FIELDS[0]!, ' codex budgets ')).toBe(true)
    expect(advancedMatches(ADVANCED_FIELDS[0]!, 'absent words')).toBe(false)
    expect(presentationDestination('unknown')).toBeUndefined()
    const fields = [{ path: 'a', pending_restart: true }, { path: 'b', apply_state: 'pending_restart' }, { path: 'c', apply_state: 'applied' }] as unknown as ConfigField[]
    expect(restartFields(fields).map((field) => field.path)).toEqual(['a', 'b'])
  })
})
