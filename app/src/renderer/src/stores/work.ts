// Background work: agents, tasks, loops, processes, schedules and workflows, as the core lists them, with the
// controls Odin offers for each one now. The list is the authority: a work.updated event patches the state at once,
// then the list is fetched again for the new controls and detail.
import { reactive } from 'vue'
import type { CoreEvent, WorkAction, WorkItem, WorkKind } from '../../../shared/api'
import { onCoreEvent, onReady } from '../store'

export const work = reactive({
  open: false,
  items: [] as WorkItem[],
  loaded: false,
  error: '',
  /** What the last control on an item did, by item id. */
  notes: {} as Record<string, string | undefined>,
  /** Items with a control on its way to the core. */
  busy: {} as Record<string, boolean | undefined>
})

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

/** Sends one control. The note says what the core answered; the list then shows the result. */
export async function controlWork(item: WorkItem, action: WorkAction): Promise<void> {
  if (work.busy[item.id]) return
  work.busy[item.id] = true
  const result = await window.odin.workControl({
    control_command_id: crypto.randomUUID(),
    kind: item.kind,
    id: item.id,
    action
  })
  work.busy[item.id] = false
  work.notes[item.id] = result.ok
    ? `${actionLabel(action)}: ${DISPOSITIONS[result.result.disposition] ?? result.result.disposition}`
    : result.error.message
  await loadWork()
}

onCoreEvent(applyWorkEvent)
onReady(() => void loadWork())
