// The composer's slash commands: Discord's /stop, /steer, /status, /usage and /reload, plus /new, /search, and the
// /model and /effort shortcuts. Each one says what it affects before it runs.
import { newConversation, runSearch, send, showPanel, state, stop } from './store'
import { attachmentsFor } from './stores/composer'
import { loadSettings, saveField, settings } from './stores/settings'
import { resultMessage } from './capability'

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
      if (!result.ok) return note(resultMessage(result, 'Core status'))
      const core = result.result
      showPanel('Status', core.summary ?? `Core ${core.core_instance_id}\nVersion: ${core.version}\nPhase: ${core.phase}\nCapabilities: ${core.capabilities.join(', ')}`, core.summary !== undefined)
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
      if (!result.ok) return note(resultMessage(result, 'Usage'))
      showPanel(`Usage, ${range}`, result.result.summary, true)
    }
  },
  {
    name: 'reload',
    usage: '/reload',
    affects: "Reloads Odin's context files and shows what is in context.",
    run: async () => {
      const result = await window.odin.reload('context')
      if (!result.ok) return note(resultMessage(result, 'Context reload'))
      showPanel('Reload', result.result.summary, true)
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

/** A shortcut for one setting: with no argument it shows the current value and choices; otherwise it saves the choice
 *  exactly as the settings menu does, through the field's own apply path. */
async function settingShortcut(path: string, title: string, arg: string): Promise<boolean | void> {
  await loadSettings()
  if (settings.unavailable) return note(`${title} is unavailable in this core.`)
  const field = settings.meta?.fields.find((f) => f.path === path)
  if (!field) return note(`${title} isn't available here.`)
  const choice = arg.trim()
  if (!choice) {
    showPanel(title, `${title}: ${String(field.desired)}.` + (field.enum ? ` Choices: ${field.enum.join(', ')}.` : ''))
    return
  }
  if (field.enum && !field.enum.includes(choice)) {
    note(`Choose one of ${field.enum.join(', ')}.`)
    return false
  }
  const saved = await saveField(field, choice)
  if (!saved) return note(settings.fields[path]?.message ?? `${title} wasn't changed.`)
  note(`${title} is now ${choice}.`)
}

COMMANDS.push(
  {
    name: 'model',
    usage: '/model [name]',
    affects: "Shows or switches Odin's main model, the one that serves chat. A switch applies from the next turn.",
    run: (arg) => settingShortcut('llm_provider.model', 'Main model', arg)
  },
  {
    name: 'effort',
    usage: '/effort [level]',
    affects: "Shows or sets the main model's reasoning effort.",
    run: (arg) => settingShortcut('openai_codex.reasoning_effort', 'Reasoning effort', arg)
  }
)

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
