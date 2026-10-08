import { describe, expect, it } from 'vitest'
import { detailFields, settlementFields, workFields, workStartedLabel, workStartedMillis } from '../../src/renderer/src/work-format'

describe('real Work projection formatting', () => {
  it('preserves mixed retained arrays and empty nested objects without stringifying objects implicitly', () => {
    expect(workFields({ results: [{ text: 'Retained report' }, 'plain', 0, null], last_run: {} })).toEqual([
      { key: 'results', label: 'Results', value: '{"text":"Retained report"}, plain, 0, null' },
      { key: 'last_run', label: 'Last run', value: 'None reported' }
    ])
  })
  it('accepts real manager epoch seconds and legacy ISO timestamps without invalid dates', () => {
    expect(workStartedMillis(1791264600)).toBe(Date.parse('2026-10-06T05:30:00Z'))
    expect(workStartedMillis('2026-10-06T05:30:00Z')).toBe(1791264600000)
    expect(workStartedMillis(null)).toBe(0)
    expect(workStartedLabel('unavailable')).toBe('unavailable')
    expect(workStartedLabel(1791264600)).not.toContain('Invalid')
  })
  it('preserves structured values, nested run bindings, false and zero without inventing release', () => {
    const fields = detailFields({ kind: 'agent', id: 'work01', title: 'Check', state: 'completed', actions: [], detail: {
      iteration_count: 0, children_ids: [], last_consumed_sequence: 0, transport_unknown: false,
      run_binding: { run_id: 'run01', generation: 3 }, last_error: null
    } })
    expect(fields).toEqual([
      { key: 'iteration_count', label: 'Iteration count', value: '0' },
      { key: 'children_ids', label: 'Children ids', value: 'None reported' },
      { key: 'last_consumed_sequence', label: 'Last consumed sequence', value: '0' },
      { key: 'transport_unknown', label: 'Transport unknown', value: 'false' },
      { key: 'run_binding.run_id', label: 'Run binding / Run id', value: 'run01' },
      { key: 'run_binding.generation', label: 'Run binding / Generation', value: '3' },
      { key: 'last_error', label: 'Last error', value: 'Not reported' }
    ])
    expect(settlementFields({ state: 'unknown', resource_release: 'unknown', last_run: { resource_release: 'unproven' } }).map((f) => f.value)).toEqual(['unknown', 'unknown', 'unproven'])
    expect(settlementFields()).toEqual([])
    expect(detailFields({ kind: 'task', id: 'task01', title: 'Legacy', state: 'running', actions: [], detail: 'Legacy text' })).toEqual([])
  })
})
