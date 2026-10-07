// Plasma's post-cancellation shutdown scripts run before graphical-session.target
// stops and KWin quits. Unlike early portal/XSMP queries, this is an actual end.
import { constants, closeSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { spawn } from 'node:child_process'
import type { CoreLaunch } from './core-command'

export function sessionMonitorCommand(launch: CoreLaunch): CoreLaunch | null {
  const module = launch.args.indexOf('-m')
  if (module < 0 || launch.args[module + 1] !== 'src') return null
  return { ...launch, args: [...launch.args.slice(0, module), '-m', 'src.desktop.session_end'] }
}

/** App-owned sibling, not the core: its bus client survives core cleanup until
 * the app's own clean/unknown receipt is fsynced. No renderer/replay surface. */
export function startSessionMonitor(launch: CoreLaunch, onEnd: () => void): { close(): void } | null {
  const command = sessionMonitorCommand(launch)
  if (!command || !command.env.DBUS_SESSION_BUS_ADDRESS) return null
  try {
    const child = spawn(command.command, command.args, { env: command.env, stdio: ['pipe', 'pipe', 'ignore'] })
    let buffer = '', ending = false
    child.on('error', () => undefined)
    child.stdin.on('error', () => undefined)
    child.stdout.on('data', (data: Buffer) => {
      buffer = (buffer + data.toString()).slice(-128)
      if (!ending && buffer.includes('session-ending\n')) { ending = true; onEnd() }
    })
    return { close: () => { child.stdin.end() } }
  } catch { return null }
}

const marker = '# Odin Desktop bounded logout hook v1'
function shellArg(value: string): string {
  if (/[\0\r\n]/.test(value)) throw new Error('Invalid logout launcher argument')
  return `'${value.replace(/'/g, "'\\''")}'`
}

export function kdeLogoutHook(command: readonly string[], pid: number, startTicks = ''): string {
  if (!command.length || !Number.isSafeInteger(pid) || pid <= 1) throw new Error('Invalid logout owner')
  if (startTicks && !/^\d+$/.test(startTicks)) throw new Error('Invalid logout owner identity')
  // A second-instance --exit only enqueues Exit. Keep Plasma here until this app
  // disappears, but at most eight seconds even if the app/launcher is wedged.
  // Before launching --exit, reject stale hooks and reused PIDs. /proc's comm
  // can contain spaces: strip through the final ')' before reading field 22.
  const alive = startTicks
    ? `owner_alive() { stat=$(cat /proc/${pid}/stat 2>/dev/null) || return 1; stat=\${stat##*) }; set -- $stat; shift 19; test "$1" = ${startTicks}; }; owner_alive || exit 0; `
    : ''
  const check = startTicks ? 'owner_alive' : `kill -0 ${pid} 2>/dev/null`
  const body = `${alive}${[...command, '--exit'].map(shellArg).join(' ')}; while ${check}; do sleep 0.1; done`
  return `#!/bin/sh\n${marker}\n# No inhibition and no replay; timeout bounds the entire handoff.\ntimeout -k 1s 8s /bin/sh -c ${shellArg(body)}\nexit 0\n`
}

export function installKdeLogoutHook(command: readonly string[], env: NodeJS.ProcessEnv = process.env,
  pid = process.pid): { path: string; remove(): void } | null {
  if (!(env.XDG_CURRENT_DESKTOP ?? '').split(':').some((part) => part.toUpperCase() === 'KDE')) return null
  if (!env.HOME && !env.XDG_CONFIG_HOME) return null
  const directory = join(env.XDG_CONFIG_HOME || join(env.HOME!, '.config'), 'plasma-workspace', 'shutdown')
  const path = join(directory, 'odin-desktop.sh')
  try {
    try {
      if (!lstatSync(path).isFile()) return null
      if (!readFileSync(path, 'utf8').startsWith(`#!/bin/sh\n${marker}\n`)) return null
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') return null }
    const startTicks = pid === process.pid
      ? readFileSync(`/proc/${pid}/stat`, 'utf8').split(') ').at(-1)!.split(' ')[19]! : ''
    const body = kdeLogoutHook(command, pid, startTicks)
    mkdirSync(directory, { recursive: true })
    const fd = openSync(path, constants.O_WRONLY | constants.O_CREAT | constants.O_TRUNC | constants.O_NOFOLLOW, 0o700)
    try { writeFileSync(fd, body); fsyncSync(fd) } finally { closeSync(fd) }
    return { path, remove: () => {
      try { if (lstatSync(path).isFile() && readFileSync(path, 'utf8') === body) unlinkSync(path) } catch { /* Optional hook, fail open. */ }
    } }
  } catch { return null }
}
