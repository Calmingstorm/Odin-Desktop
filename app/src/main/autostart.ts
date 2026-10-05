// Start at login (R2) via an XDG autostart entry. The app starts minimized to the tray, and the app starts Odin.
import { existsSync, mkdirSync, unlinkSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'

type Env = Record<string, string | undefined>

export function autostartPath(env: Env = process.env): string {
  const configHome = env.XDG_CONFIG_HOME || join(env.HOME || homedir(), '.config')
  return join(configHome, 'autostart', 'odin-desktop.desktop')
}

/** Quotes one Exec argument per the Desktop Entry spec (reserved characters inside double quotes, `%` doubled). */
export function quoteExecArg(arg: string): string {
  const percentEscaped = arg.replace(/%/g, '%%')
  if (!/[\s"'\\><~|&;$*?#()`]/.test(percentEscaped)) return percentEscaped
  return `"${percentEscaped.replace(/(["`$\\])/g, '\\$1')}"`
}

export function autostartEntry(command: readonly string[]): string {
  if (command.length === 0) throw new Error('autostart command is empty')
  return [
    '[Desktop Entry]',
    'Type=Application',
    'Name=Odin',
    'Comment=Start Odin in the system tray',
    `Exec=${[...command, '--hidden'].map(quoteExecArg).join(' ')}`,
    'Icon=odin-desktop',
    'Terminal=false',
    'X-GNOME-Autostart-enabled=true',
    ''
  ].join('\n')
}

export function isAutostartEnabled(path: string = autostartPath()): boolean {
  return existsSync(path)
}

export function setAutostart(enabled: boolean, command: readonly string[], path: string = autostartPath()): boolean {
  if (enabled) {
    mkdirSync(dirname(path), { recursive: true })
    writeFileSync(path, autostartEntry(command), { mode: 0o644 })
  } else if (existsSync(path)) {
    unlinkSync(path)
  }
  return isAutostartEnabled(path)
}
