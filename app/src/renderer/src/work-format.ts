import type { WorkItem, WorkSettlement } from '../../shared/api'

export interface WorkField {
  key: string
  label: string
  value: string
}

const LABELS: Record<string, string> = {
  resource_release: 'Resource release',
  remote_effects: 'Remote effects',
  last_consumed_sequence: 'Last consumed sequence',
  inbox_sequence: 'Inbox sequence',
  unsettled_descendants: 'Unsettled descendants'
}

function label(key: string): string {
  return LABELS[key] ?? key.replaceAll('_', ' ').replace(/^./, (first) => first.toUpperCase())
}

/** Preserve each measured value, including false, zero, null and unknown. No inferred settlement. */
export function workFields(value: Record<string, unknown>, prefix = ''): WorkField[] {
  return Object.entries(value).flatMap(([key, entry]) => {
    const path = prefix ? `${prefix}.${key}` : key
    const name = prefix ? `${prefix.split('.').map(label).join(' / ')} / ${label(key)}` : label(key)
    if (entry && typeof entry === 'object' && !Array.isArray(entry)) {
      const nested = workFields(entry as Record<string, unknown>, path)
      return nested.length ? nested : [{ key: path, label: name, value: 'None reported' }]
    }
    const text = entry == null ? 'Not reported' : Array.isArray(entry)
      ? entry.length ? entry.map((item) => typeof item === 'object' && item !== null ? JSON.stringify(item) : String(item)).join(', ') : 'None reported'
      : String(entry)
    return [{ key: path, label: name, value: text }]
  })
}

export function detailFields(item: WorkItem): WorkField[] {
  return typeof item.detail === 'string' ? [] : workFields(item.detail)
}

export function settlementFields(settlement?: WorkSettlement): WorkField[] {
  return settlement ? workFields(settlement) : []
}

/** Real managers use Unix seconds, while fixture/scheduler dates are ISO strings. */
export function workStartedMillis(value: WorkItem['started_at']): number {
  const time = typeof value === 'number' ? value * 1000 : value ? Date.parse(value) : NaN
  return Number.isFinite(time) ? time : 0
}

export function workStartedLabel(value: NonNullable<WorkItem['started_at']>): string {
  const time = workStartedMillis(value)
  return time ? new Date(time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : String(value)
}
