// Actual Vue/store and schedule-form behavior, without a browser or live core.
// These restore UI semantics, not the removed raw JavaScript source spelling.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import type { ConfigField, HostRow, ScheduleRow } from '../../src/shared/api'
import { blankForm, buildSave, formFor } from '../../src/renderer/src/schedule-form'
import { fromInput } from '../../src/renderer/src/settings-form'
import { flush, mount, type Mounted } from './component-host'

const ok = <T>(result: T) => ({ ok: true as const, result })
const utc = { offsetMinutes: () => 0 }
const field = (path: string, extra: Partial<ConfigField> = {}): ConfigField => ({
  path, label: path, description: '', type: 'string', enum: null, constraints: {}, default: null, nullable: false,
  sensitivity: 'public', apply_mode: 'live_read', apply_handler: null, restart_reason: null, activation_policy: null,
  consumers: [], save_effect: '', runtime_effect: null, desired: null, effective: null, configured: true,
  pending_restart: false, apply_state: 'applied', ...extra
})
let mounted: Mounted | undefined
beforeEach(() => { vi.resetModules(); vi.stubGlobal('document', { activeElement: null }) })
afterEach(() => { mounted?.unmount(); mounted = undefined; vi.unstubAllGlobals() })

describe('step8-part5 hosts delete references', () => {
  it('renders every structured blocking kind and location and never deletes a referenced host', async () => {
    const row: HostRow = {
      alias: 'build', host_id: 'h', address: '192.0.2.10', ssh_user: 'odin', port: 22, os: 'linux', description: '',
      enabled: true, active: true, targetable: true, trust_mode: 'pinned', trust_state: 'pinned', last_test: null,
      diagnostic: null, draining: false, generation: 1
    }
    const references = [
      { kind: 'schedule', location: 'schedule report-1' },
      { kind: 'workflow', location: 'workflow step 2 host' }
    ]
    const hostsDelete = vi.fn(async () => ok({ result: 'saved' }))
    vi.stubGlobal('window', { odin: {
      hostsList: async () => ok({ hosts: [row], default_host: '', generation: 1, tofu_enabled: false }),
      hostsPublicKey: async () => ok(null),
      hostsReferences: async () => ok({ alias: 'build', references }), hostsDelete
    } })
    mounted = mount((await import('../../src/renderer/src/views/settings/Hosts.vue')).default)
    await flush()
    const store = await import('../../src/renderer/src/stores/hosts')
    expect(await store.deleteHost('build')).toBe('blocked')
    await flush()
    expect(mounted.root.textContent()).toContain('Not deleted: these still name build.')
    for (const item of references) expect(mounted.root.textContent()).toContain(`${item.kind}: ${item.location}`)
    expect(hostsDelete).not.toHaveBeenCalled()
  })
})

describe('step8-part5 report format parity', () => {
  it('creates reads back edits and explicitly clears the same report format literal', () => {
    const created = buildSave({ ...blankForm(), action: 'check', description: 'Report', channel_id: 'c', cron: '0 9 * * *',
      tool_name: 'run_command', tool_input: '{"command":"uptime"}', report_format: 'paginated_embed_v1' }, undefined, utc)
    expect(created).toMatchObject({ report_format: 'paginated_embed_v1' })
    if (typeof created === 'string') throw new Error(created)
    const row = { id: 's', ...created, timezone: 'UTC' } as ScheduleRow
    const edit = formFor(row, utc)
    expect(edit.report_format).toBe('paginated_embed_v1')
    expect(buildSave(edit, row, utc)).toBe('Nothing changed.')
    edit.description = 'Updated report'
    expect(buildSave(edit, row, utc)).toEqual({ id: 's', description: 'Updated report' })
    edit.report_format = ''
    expect(buildSave(edit, row, utc)).toEqual({ id: 's', description: 'Updated report', report_format: '' })
    expect(formFor({ ...row, report_format: null }, utc).report_format).toBe('')
  })
})

describe('step8-part5 restart notice', () => {
  it.each(['applied', 'unknown', 'invalid'] as const)('keeps pending restart truth independent of provider %s state', async (providerState) => {
    const fields = ['timezone', 'tools.hosts', 'browser.enabled'].map((path) => field(path, {
      desired: 'saved', effective: 'running', pending_restart: true, apply_state: 'pending_restart',
      save_effect: 'Saved to this profile.', runtime_effect: `Restart Odin to apply ${path}.`
    }))
    fields.push(field('openai_codex.enabled', { apply_state: providerState }))
    vi.stubGlobal('window', { odin: {} })
    const SchemaForm = (await import('../../src/renderer/src/components/SchemaForm.vue')).default
    mounted = mount({ render: () => h(SchemaForm, { fields }) })
    await flush()
    for (const path of ['timezone', 'tools.hosts', 'browser.enabled']) {
      expect(mounted.root.textContent()).toContain(`Restart Odin to apply ${path}.`)
    }
    expect(mounted.root.textContent()).toContain('Saved: "saved". Running: "running".')
  })
})

describe('step8-part5 core supplied choices', () => {
  it('renders the supplied neutral vocabulary without extending it and rejects an unlisted effort', async () => {
    const levels = ['none', 'low', 'medium', 'high', 'xhigh', 'max']
    const effort = field('openai_compatible.reasoning_effort', { enum: levels, desired: 'high' })
    vi.stubGlobal('window', { odin: {} })
    const SchemaForm = (await import('../../src/renderer/src/components/SchemaForm.vue')).default
    mounted = mount({ render: () => h(SchemaForm, { fields: [effort] }) })
    await flush()
    expect(mounted.root.findAll((node) => node.tag === 'option').map((node) => node.props.value)).toEqual(levels)
    expect(fromInput(effort, 'ultra')).toEqual({ ok: false, error: 'Choose one of none, low, medium, high, xhigh, max.' })
  })
})
