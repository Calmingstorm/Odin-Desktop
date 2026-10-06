/** Only structural task state enters live speech. Never pass message, draft, steer or tool text here. */
export interface ChatAnnouncementState {
  running: string | null
  stopping: boolean
  terminal: string | null
  outcome: string | null
  queued: number
  consumed: string[]
  steerQueued: string[]
  unknown: string[]
}

export function chatAnnouncement(previous: ChatAnnouncementState | undefined, next: ChatAnnouncementState): string {
  const lines: string[] = []
  if (next.running && next.running !== previous?.running) lines.push('Odin is working.')
  if (next.stopping && !previous?.stopping) lines.push('Stopping the current task.')
  if (previous && next.terminal && next.terminal !== previous.terminal) {
    const outcomes: Record<string, string> = {
      completed: 'Task completed.', failed: 'Task failed.', cancelled: 'Task stopped.',
      interrupted: 'Task interrupted.', suspended: 'Task suspended. Resume is available when permitted by its state.'
    }
    lines.push(outcomes[next.outcome ?? ''] ?? 'Task ended.')
  }
  if (next.queued && next.queued !== previous?.queued) lines.push(`${next.queued} follow-up${next.queued === 1 ? '' : 's'} queued.`)
  if (next.steerQueued.some((id) => !previous?.steerQueued.includes(id))) lines.push('Steer queued for Odin to read.')
  if (previous && next.consumed.some((id) => !previous.consumed.includes(id))) lines.push('Odin has read the steer.')
  if (next.unknown.some((id) => !previous?.unknown.includes(id))) lines.push('An action has an unknown outcome. It will not be repeated.')
  return lines.join(' ')
}
