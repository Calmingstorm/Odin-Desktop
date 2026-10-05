// The composer's slash commands: Discord's /stop, /steer, /status, /usage and /reload, plus /new and /search.
// Each one says what it affects before it runs. Model and effort shortcuts come with the settings screens.
import { newConversation, runSearch, send, showPanel, state, stop } from './store'
import { attachmentsFor } from './stores/composer'

/** Odin's /usage ranges; 7d when none is given, as in Odin. */
export const USAGE_RANGES = ['24h', '7d', '30d', 'all'] as const

export interface PaletteCommand {
  name: string
  usage: string
  /** What running it changes, shown before it runs. */
  affects: string
  /** Resolves false when the typed text should stay in the composer (for example, a steer that wasn't delivered). */
  run: (arg: string) => Promise<boolean | void> | boolean | void
}

function note(text: string): void {
  state.notice = text
}

export const COMMANDS: PaletteCommand[] = [
  {
    name: 'stop',
    usage: '/stop',
    affects: 'Stops the task running in this conversation. Work already done stays done.',
    run: () => stop()
  },
  {
    name: 'steer',
    usage: '/steer <guidance>',
    affects: 'Adds guidance to the task running in this conversation, which reads it at its next step.',
    run: async (arg) => {
      const running = state.activeId ? state.views[state.activeId]?.running : null
      if (!running) {
        note('Nothing is running here to steer.')
        return false
      }
      if (!arg) {
        note('Add the guidance after /steer.')
        return false
      }
      if (attachmentsFor(state.activeId).length) {
        note('Attachments go with a message, not a steer. Choose Queue to send them as a follow-up.')
        return false
      }
      return send(arg, 'steer')
    }
  },
  {
    name: 'status',
    usage: '/status',
    affects: "Shows Odin's runtime configuration and health. Changes nothing.",
    run: async () => {
      const result = await window.odin.status()
      if (!result.ok) return note(result.error.message)
      showPanel('Status', result.result.summary ?? `Core ${result.result.core_instance_id}: ${result.result.phase}`)
    }
  },
  {
    name: 'usage',
    usage: '/usage [24h | 7d | 30d | all]',
    affects: 'Shows usage totals and the current quota for a range, 7d by default. Changes nothing.',
    run: async (arg) => {
      const range = (arg.trim() || '7d') as (typeof USAGE_RANGES)[number]
      if (!USAGE_RANGES.includes(range)) {
        note(`Usage ranges are ${USAGE_RANGES.join(', ')}.`)
        return false
      }
      const result = await window.odin.usage(range)
      if (!result.ok) return note(result.error.message)
      showPanel(`Usage, ${range}`, result.result.summary)
    }
  },
  {
    name: 'reload',
    usage: '/reload',
    affects: "Reloads Odin's context files and shows what is in context.",
    run: async () => {
      const result = await window.odin.reload('context')
      if (!result.ok) return note(result.error.message)
      showPanel('Reload', result.result.summary)
    }
  },
  {
    name: 'new',
    usage: '/new',
    affects: 'Starts a new conversation.',
    run: () => newConversation()
  },
  {
    name: 'search',
    usage: '/search <words>',
    affects: 'Searches all conversations. Changes nothing.',
    run: async (arg) => {
      state.search.open = true
      if (arg) await runSearch(arg)
    }
  }
]

/** The commands matching what was typed after the slash. */
let inFlight: string | null = null

/** Runs one command at a time, like a send: a second press while one runs makes no second call. */
export async function dispatch(command: PaletteCommand, arg: string): Promise<boolean | void> {
  if (inFlight) {
    note(`/${inFlight} is still running.`)
    return false
  }
  inFlight = command.name
  try {
    return await command.run(arg)
  } finally {
    inFlight = null
  }
}

export function matchCommands(line: string): PaletteCommand[] {
  const name = line.replace(/^\//, '').split(/\s/, 1)[0]?.toLowerCase() ?? ''
  return COMMANDS.filter((c) => c.name.startsWith(name))
}

/** Splits "/steer use the other host" into the command name and its argument. */
export function parseCommand(line: string): { name: string; arg: string } {
  const body = line.replace(/^\//, '')
  const space = body.search(/\s/)
  return space < 0 ? { name: body.toLowerCase(), arg: '' } : { name: body.slice(0, space).toLowerCase(), arg: body.slice(space).trim() }
}
