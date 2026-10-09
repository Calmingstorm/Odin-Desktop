// Structural evidence only; real focus/keyboard/axe is the separate Electron gate.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Host, type Mounted } from './component-host'

let views: Mounted[]
beforeEach(() => {
  vi.resetModules()
  views = []
  const unavailable = { ok: false, error: { code: 'offline', message: 'Fixture read failed', disposition: 'not_dispatched' } }
  ;(globalThis as unknown as { window: unknown }).window = { odin: new Proxy({}, { get: () => async () => unavailable }) }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
})
afterEach(() => views.forEach((v) => v.unmount()))
async function view(name: string): Promise<Mounted> {
  const component = (await import(`../../src/renderer/src/views/settings/${name}.vue`)).default
  const v = mount(component)
  views.push(v)
  await flush()
  return v
}
function named(root: Host, name: string): Host {
  const matches = root.findAll((n) => n.props['aria-label'] === name)
  expect(matches).toHaveLength(1)
  return matches[0]!
}
function visibleLabels(root: Host): void {
  for (const control of root.findAll((n) => ['input', 'textarea', 'select'].includes(n.tag))) {
    let label = control.parent
    while (label && label.tag !== 'label') label = label.parent
    const explicit = root.findAll((n) => n.tag === 'label' && n.props.for === control.props.id && !!control.props.id)[0]
    expect((label ?? explicit)?.textContent().trim(), `${control.tag} needs a visible label`).toBeTruthy()
  }
}

describe('P3.4 settings work/hosts/state/records structural accessibility', () => {
  it('names repeated schedule actions and exposes history disclosure state', async () => {
    const v = await view('Work')
    const { schedules } = await import('../../src/renderer/src/stores/schedules')
    schedules.list = [{ id: 'disk', description: 'Disk report', action: 'reminder', channel_id: 'c1', paused: false, created_at: '' }]
    await flush()
    expect(named(v.root, 'Pause schedule Disk report').tag).toBe('button')
    expect(named(v.root, 'Edit schedule Disk report').tag).toBe('button')
    const disclosure = named(v.root, 'Runs for schedule Disk report')
    expect(disclosure.props['aria-expanded']).toBe(false)
    disclosure.fire('click')
    await flush()
    expect(named(v.root, 'Hide runs for schedule Disk report').props['aria-expanded']).toBe(true)
    expect(v.root.findAll((n) => n.props.id === disclosure.props['aria-controls'])).toHaveLength(1)
  })
  it('links schedule validation to only the identified field', async () => {
    const v = await view('Work')
    v.root.button('New schedule').fire('click')
    await flush()
    visibleLabels(v.root)
    v.root.button('Create').fire('click')
    await flush()
    const invalid = v.root.findAll((n) => n.props['aria-invalid'] === 'true')
    expect(invalid).toHaveLength(1)
    expect(invalid[0]!.parent!.textContent().trim()).toBe('Description')
    expect(invalid[0]!.props['aria-describedby']).toBe('schedule-form-error')
    expect(v.root.findAll((n) => n.props.id === 'schedule-form-error')[0]!.props.role).toBe('alert')
  })
  it('links server cron errors without invalidating unrelated fields', async () => {
    const v = await view('Work')
    v.root.button('New schedule').fire('click')
    await flush()
    const { schedules } = await import('../../src/renderer/src/stores/schedules')
    const editing = v.setup.editing as { form: { cron: string } }
    editing.form.cron = 'bad cron'
    schedules.cron = { expression: 'bad cron', timezone: '', error: 'Invalid cron', next_runs: [] }
    await flush()
    const invalid = v.root.findAll((n) => n.props['aria-invalid'] === 'true')
    expect(invalid).toHaveLength(1)
    expect(invalid[0]!.props['aria-describedby']).toBe('schedule-cron-error')
  })
  it('maps validation messages precisely and leaves non-field save outcomes unmarked', async () => {
    const v = await view('Work')
    const fieldError = v.setup.fieldError as (field: string) => Record<string, string | undefined>
    const cases = [
      ['Choose the conversation it reports to.', 'channel_id'],
      ['That run time is not a valid date.', 'run_at'],
      ['That time happens twice here: choose which one.', 'occurrence'],
      ['The tool input is a JSON object.', 'tool_input'],
      ['Steps are a JSON list of {tool_name, tool_input}.', 'steps'],
      ['Headers are a JSON object.', 'webhook_headers'],
      ['Expected statuses are HTTP codes, separated by commas.', 'webhook_expected'],
      ['Retries are a whole number, 0 or more.', 'max_retries'],
      ['The wait between retries is a whole number of seconds, at least 1.', 'retry_backoff_seconds']
    ]
    for (const [message, field] of cases) {
      v.setup.formError = message
      expect(fieldError(field!)).toEqual({ 'aria-invalid': 'true', 'aria-describedby': 'schedule-form-error' })
      expect(fieldError('description')['aria-invalid']).toBeUndefined()
    }
    v.setup.formError = 'Nothing changed.'
    expect(fieldError('description')['aria-invalid']).toBeUndefined()
  })
  it('visibly labels fingerprint input, links malformed input and identifies current enrollment step', async () => {
    const v = await view('Hosts')
    v.root.button('Add host').fire('click')
    await flush()
    visibleLabels(v.root)
    const { hosts } = await import('../../src/renderer/src/stores/hosts')
    hosts.enrollment!.step = 3
    hosts.enrollment!.note = 'bad is not a fingerprint. One looks like SHA256:…'
    await flush()
    visibleLabels(v.root)
    const fingerprints = v.root.find('textarea')!
    expect(fingerprints.parent!.textContent().trim()).toBe('Expected fingerprints')
    expect(fingerprints.props['aria-invalid']).toBe('true')
    expect(fingerprints.props['aria-describedby']).toBe('host-enrollment-note')
    expect(v.root.findAll((n) => n.props['aria-current'] === 'step')).toHaveLength(1)
  })
  it('visibly labels memory editors and exposes contextual scope/list/version disclosures', async () => {
    const v = await view('State')
    const { stateStore } = await import('../../src/renderer/src/stores/state')
    stateStore.memory = { global: { count: 1, keys: ['greeting'] } }
    stateStore.memoryEntries.global = { greeting: 'hello' }
    stateStore.lists = [{ name: 'Shopping list', count: 1, updated_at: '' }]
    stateStore.listItems['Shopping list'] = ['bread']
    stateStore.knowledge = [{ source: 'runbook.md', chunks: 1, ingested_at: '', uploader: '', content_hash: '' }]
    stateStore.versions['runbook.md'] = []
    await flush()
    named(v.root, 'Add Everywhere memory entry').fire('click')
    await flush()
    visibleLabels(v.root)
    expect(named(v.root, 'Key in Everywhere memory').tag).toBe('input')
    expect(named(v.root, 'Edit greeting in Everywhere memory').tag).toBe('button')
    for (const label of ['Close Everywhere memory', 'Close list Shopping list', 'Hide versions for runbook.md']) {
      const disclosure = named(v.root, label)
      expect(disclosure.tag).toBe('button')
      expect(disclosure.props['aria-expanded']).toBe(true)
      expect(v.root.findAll((n) => n.props.id === disclosure.props['aria-controls'])).toHaveLength(1)
    }
  })
  it('labels record filters and describes read errors without blaming valid input', async () => {
    const v = await view('Records')
    visibleLabels(v.root)
    expect(named(v.root, 'Refresh preserved work').tag).toBe('button')
    expect(named(v.root, 'Refresh computer use').tag).toBe('button')
    const described = v.root.findAll((n) => ['input', 'select'].includes(n.tag) && Boolean(n.props['aria-describedby']))
    expect(described).toHaveLength(5)
    for (const n of described) {
      expect(n.props['aria-invalid']).toBeUndefined()
      expect(v.root.findAll((error) => error.props.id === n.props['aria-describedby'])).toHaveLength(1)
    }
    expect(v.root.findAll((n) => n.props.role === 'tab')).toHaveLength(0)
  })
})
