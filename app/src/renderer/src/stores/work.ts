// Background work: agents, tasks, loops, processes, schedules and workflows, as the core lists them, with the
// controls Odin offers for each one now. The list is the authority: a work.updated event patches the state at once,
// then the list is fetched again for the new controls and detail.
import { reactive } from 'vue'
import type { CoreEvent, Result, WorkAction, WorkControlParams, WorkControlReceipt, WorkItem, WorkKind } from '../../../shared/api'
import { isUnknownOutcome, onCoreEvent, onLateReceipt, onReady } from '../store'
import { busy } from './locks'
import { isUnavailable, resultMessage } from '../capability'
import { workStartedMillis } from '../work-format'

export const work = reactive({
  open: false,
  items: [] as WorkItem[],
  loaded: false,
  error: '',
  unavailable: false,
  /** What the last control on an item did, by `workKey`. */
  notes: {} as Record<string, string | undefined>,
  /**
   * Items with a control on its way to the core, or not yet confirmed, by `workKey`. Shared with the settings menu,
   * whose schedules section runs and pauses the same schedules.
   */
  busy
})

/** An item's identity: its kind and id together, since items of different kinds may share an id. */
export function workKey(item: Pick<WorkItem, 'kind' | 'id' | 'manager_id'>): string {
  return `${item.kind}:${item.kind === 'schedule' ? item.manager_id ?? item.id : item.id}`
}

const ACTIVE = new Set(['admitted', 'running', 'starting', 'stopping'])
/** The states the core gives a schedule its scheduler no longer holds. */
const ENDED_SCHEDULE = new Set(['completed', 'failed', 'cancelled', 'unknown'])

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
  run_now: 'Run now',
  steer: 'Steer'
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

const KIND_LABELS: Record<WorkKind, string> = {
  agent: 'Agent', task: 'Task', loop: 'Loop', process: 'Process', workflow: 'Workflow', schedule: 'Schedule'
}

export function kindLabel(kind: WorkKind): string {
  return KIND_LABELS[kind] ?? kind
}

/**
 * The Work column's view of the same items: what is running now, then the schedules, then finished work, each most
 * recently started first. Nothing is dropped; every item is in exactly one section.
 */
export function bySection(): Array<{ kind: string; label: string; items: WorkItem[] }> {
  const recent = (a: WorkItem, b: WorkItem): number => workStartedMillis(b.started_at) - workStartedMillis(a.started_at)
  // A schedule the scheduler no longer holds (a one-time run that finished, or a deleted one) is finished work.
  const scheduled = (item: WorkItem): boolean => item.kind === 'schedule' && !ENDED_SCHEDULE.has(item.state)
  return [
    { kind: 'running', label: 'Running now', items: work.items.filter((i) => !scheduled(i) && isActive(i)).sort(recent) },
    { kind: 'scheduled', label: 'Scheduled', items: work.items.filter(scheduled)
      .sort((a, b) => Number(isActive(b)) - Number(isActive(a)) || recent(a, b)) },
    { kind: 'finished', label: 'Finished', items: work.items.filter((i) => !scheduled(i) && !isActive(i)).sort(recent) }
  ].filter((section) => section.items.length > 0)
}

/** The items of each kind, running ones first, then the most recently started. */
export function grouped(): Array<{ kind: WorkKind; label: string; items: WorkItem[] }> {
  return GROUPS.map((group) => ({
    ...group,
    items: work.items
      .filter((item) => item.kind === group.kind)
      .sort((a, b) => Number(isActive(b)) - Number(isActive(a)) || workStartedMillis(b.started_at) - workStartedMillis(a.started_at))
  })).filter((group) => group.items.length > 0)
}

let latest = 0

export async function loadWork(): Promise<void> {
  const mine = ++latest
  const result = await window.odin.workList()
  if (mine !== latest) return // a newer load answers instead
  if (!result.ok) {
    work.unavailable = isUnavailable(result.error)
    work.error = resultMessage(result, 'Work (agents, tasks, loops, processes, workflows and schedules)')
    if (work.unavailable) {
      work.items = []
      work.loaded = true
    }
    return
  }
  work.unavailable = false
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
  if (item) {
    if (typeof p.state === 'string') item.state = p.state
    if (Array.isArray(p.actions)) item.actions = p.actions as WorkAction[]
    if (typeof p.detail === 'string' || (p.detail && typeof p.detail === 'object' && !Array.isArray(p.detail))) item.detail = p.detail as WorkItem['detail']
    if (p.settlement && typeof p.settlement === 'object') item.settlement = p.settlement as WorkItem['settlement']
  }
  reloadSoon()
}

function answerNote(action: WorkAction, result: Result<WorkControlReceipt>): string {
  if (!result.ok) return resultMessage(result, 'Work controls')
  const receipt = result.result
  if (action === 'steer' && receipt.disposition === 'queued') {
    return `Steer: queued${receipt.sequence === undefined ? '' : ` (sequence ${receipt.sequence})`}. Queued is not consumed.`
  }
  return `${actionLabel(action)}: ${DISPOSITIONS[receipt.disposition] ?? receipt.disposition}${receipt.reason ? ` (${receipt.reason})` : ''}`
}

/** Controls with no answer yet, by command id. Each stays under its first command until its receipt settles it. */
const uncertain = new Map<string, { key: string; action: WorkAction }>()

/**
 * Sends one control. The note says what the core answered; the list then shows the result. With no answer, the item
 * takes no other control until the original command's receipt arrives, so nothing runs twice under two commands.
 */
export async function controlWork(item: WorkItem, action: WorkAction, text?: string): Promise<boolean> {
  const key = workKey(item)
  if (work.busy[key] || !item.actions.includes(action)) return false
  if (action === 'steer' && (item.kind !== 'agent' || !text)) return false
  work.busy[key] = true
  const commandId = crypto.randomUUID()
  const params: WorkControlParams = { control_command_id: commandId, kind: item.kind, id: item.id, action }
  // Echo only bindings the core actually listed, preserving fixture compatibility. Never invent a generation.
  if (item.manager_generation !== undefined) params.manager_generation = item.manager_generation
  if (item.run_id !== undefined) params.run_id = item.run_id
  if (item.generation !== undefined) params.generation = item.generation
  if (item.conversation_id !== undefined) params.conversation_id = item.conversation_id
  if (item.kind === 'schedule' && typeof item.detail !== 'string' && typeof item.detail.revision === 'number') params.revision = item.detail.revision
  if (action === 'steer') params.text = text
  const result = await window.odin.workControl(params)
  if (!result.ok && isUnknownOutcome(result.error)) {
    uncertain.set(commandId, { key, action })
    work.notes[key] = `${actionLabel(action)}: waiting for Odin to confirm. It is never sent twice.`
    return false
  }
  work.busy[key] = false
  work.notes[key] = answerNote(action, result)
  await loadWork()
  return result.ok && ['queued', 'requested', 'done'].includes(result.result.disposition)
}

onLateReceipt((receipt) => {
  const pending = uncertain.get(receipt.id)
  if (!pending || (!receipt.settled.ok && isUnknownOutcome(receipt.settled.error))) return
  uncertain.delete(receipt.id)
  work.busy[pending.key] = false
  work.notes[pending.key] = answerNote(pending.action, receipt.settled as Result<WorkControlReceipt>)
  void loadWork()
})

onCoreEvent(applyWorkEvent)
onReady(() => void loadWork())
