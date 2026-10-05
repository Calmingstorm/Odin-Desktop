// The composer's slash commands: Discord's /stop, /steer, /status, /usage and /reload, plus /new and /search.
// Each one says what it affects before it runs. Model and effort shortcuts come with the settings screens.
import { newConversation, runSearch, send, showPanel, state, stop } from './store'

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
    usage: '/usage',
    affects: 'Shows usage totals and the current quota. Changes nothing.',
    run: async () => {
      const result = await window.odin.usage('session')
      if (!result.ok) return note(result.error.message)
      showPanel('Usage', result.result.summary)
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
