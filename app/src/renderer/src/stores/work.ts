// Background work: agents, tasks, loops, processes, schedules and workflows, as the core lists them, with the
// controls Odin offers for each one now. The list is the authority: a work.updated event patches the state at once,
// then the list is fetched again for the new controls and detail.
import { reactive } from 'vue'
import type { CoreEvent, Result, WorkAction, WorkItem, WorkKind } from '../../../shared/api'
import { isUnknownOutcome, onCoreEvent, onLateReceipt, onReady } from '../store'
import { busy } from './locks'

export const work = reactive({
  open: false,
  items: [] as WorkItem[],
  loaded: false,
  error: '',
  /** What the last control on an item did, by `workKey`. */
  notes: {} as Record<string, string | undefined>,
  /**
   * Items with a control on its way to the core, or not yet confirmed, by `workKey`. Shared with the settings menu,
   * whose schedules section runs and pauses the same schedules.
   */
  busy
})

/** An item's identity: its kind and id together, since items of different kinds may share an id. */
export function workKey(item: Pick<WorkItem, 'kind' | 'id'>): string {
  return `${item.kind}:${item.id}`
}

const ACTIVE = new Set(['running', 'starting', 'stopping'])

export const GROUPS: Array<{ kind: WorkKind; label: string }> = [
  { kind: 'agent', label: 'Agents' },
  { kind: 'task', label: 'Tasks' },
  { kind: 'loop', label: 'Loops' },
  { kind: 'process', label: 'Processes' },
  { kind: 'workflow', label: 'Workflows' },
  { kind: 'schedule', label: 'Schedules' }
]

const ACTION_LABELS: Record<WorkAction, string> = {
  stop: 'Stop',
  cancel: 'Cancel',
  restart: 'Restart',
  pause: 'Pause',
  resume: 'Resume',
  run_now: 'Run now'
}

const DISPOSITIONS: Record<string, string> = {
  requested: 'requested',
  done: 'done',
  not_available: 'no longer offered'
}

export function actionLabel(action: WorkAction): string {
  return ACTION_LABELS[action] ?? action
}

export function isActive(item: WorkItem): boolean {
  return ACTIVE.has(item.state)
}

/** How many items are running now, for the badge. */
export function activeCount(): number {
  return work.items.filter(isActive).length
}

/** The items of each kind, running ones first, then the most recently started. */
export function grouped(): Array<{ kind: WorkKind; label: string; items: WorkItem[] }> {
  return GROUPS.map((group) => ({
    ...group,
    items: work.items
      .filter((item) => item.kind === group.kind)
      .sort((a, b) => Number(isActive(b)) - Number(isActive(a)) || (b.started_at ?? '').localeCompare(a.started_at ?? ''))
  })).filter((group) => group.items.length > 0)
}

let latest = 0

export async function loadWork(): Promise<void> {
  const mine = ++latest
  const result = await window.odin.workList()
  if (mine !== latest) return // a newer load answers instead
  if (!result.ok) {
    work.error = result.error.message
    return
  }
  work.error = ''
  work.items = result.result.items
  work.loaded = true
}

let reloadTimer: ReturnType<typeof setTimeout> | null = null

function reloadSoon(): void {
  if (reloadTimer) return
  reloadTimer = setTimeout(() => {
    reloadTimer = null
    void loadWork()
  }, 200)
}

export function applyWorkEvent(event: CoreEvent): void {
  if (event.type !== 'work.updated') return
  const p = event.payload
  const item = work.items.find((i) => i.id === String(p.id) && i.kind === p.kind)
  if (item) item.state = String(p.state)
  reloadSoon()
}

function answerNote(action: WorkAction, result: Result<{ disposition: string }>): string {
  return result.ok ? `${actionLabel(action)}: ${DISPOSITIONS[result.result.disposition] ?? result.result.disposition}` : result.error.message
}

/** Controls with no answer yet, by command id. Each stays under its first command until its receipt settles it. */
const uncertain = new Map<string, { key: string; action: WorkAction }>()

/**
 * Sends one control. The note says what the core answered; the list then shows the result. With no answer, the item
 * takes no other control until the original command's receipt arrives, so nothing runs twice under two commands.
 */
export async function controlWork(item: WorkItem, action: WorkAction): Promise<void> {
  const key = workKey(item)
  if (work.busy[key]) return
  work.busy[key] = true
  const commandId = crypto.randomUUID()
  const result = await window.odin.workControl({ control_command_id: commandId, kind: item.kind, id: item.id, action })
  if (!result.ok && isUnknownOutcome(result.error)) {
    uncertain.set(commandId, { key, action })
    work.notes[key] = `${actionLabel(action)}: waiting for Odin to confirm. It is never sent twice.`
    return
  }
  work.busy[key] = false
  work.notes[key] = answerNote(action, result)
  await loadWork()
}

onLateReceipt((receipt) => {
  const pending = uncertain.get(receipt.id)
  if (!pending || (!receipt.settled.ok && isUnknownOutcome(receipt.settled.error))) return
  uncertain.delete(receipt.id)
  work.busy[pending.key] = false
  work.notes[pending.key] = answerNote(pending.action, receipt.settled as Result<{ disposition: string }>)
  void loadWork()
})

onCoreEvent(applyWorkEvent)
onReady(() => void loadWork())
