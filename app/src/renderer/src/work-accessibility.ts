import type { WorkItem } from '../../shared/api'

/** Qualify repeated controls and notices without replacing the visible action's name. */
export function workName(item: Pick<WorkItem, 'kind' | 'title'>): string {
  return `${item.kind}: ${item.title}`
}

export interface WorkNotice {
  key: string
  name: string
  state: string
  busy: boolean
  note: string
}

// Transient detail/progress changes are deliberately absent. Only lifecycle changes speak.
const ANNOUNCED_STATES = new Set(['running', 'completed', 'failed', 'stopped', 'cancelled', 'paused', 'active', 'queued', 'consumed', 'unknown', 'outcome_unknown', 'interrupted'])

export function changedWorkNotices(current: WorkNotice[], previous: WorkNotice[]): Array<{ key: string; text: string }> {
  const before = new Map(previous.map((item) => [item.key, item]))
  return current.flatMap((item) => {
    const old = before.get(item.key)
    if (item.note && (item.note !== old?.note || (old?.busy && !item.busy))) return [{ key: item.key, text: `${item.name}. ${item.note}` }]
    if (item.busy && !old?.busy) return [{ key: item.key, text: `${item.name}. Control pending.` }]
    if (old && old.state !== item.state && ANNOUNCED_STATES.has(item.state)) {
      return [{ key: item.key, text: `${item.name}. ${item.state}.` }]
    }
    return []
  })
}

export function workAnnouncement(notices: string[]): string {
  if (notices.length <= 3) return notices.join(' ')
  return `${notices.slice(0, 3).join(' ')} ${notices.length - 3} other work items changed.`
}
