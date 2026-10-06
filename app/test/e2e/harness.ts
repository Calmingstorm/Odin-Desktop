import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readlinkSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { _electron, type ElectronApplication } from '@playwright/test'

export const repository = resolve(__dirname, '../../..')
export interface MainSnapshot {
  pid: number; corePid?: number; coreState: string; visible: boolean; windowId?: number; rendererPid?: number
  noTrayNoticeShown: boolean
  appState: { link: string; coreInstanceId: string | null; noTray: boolean; unreceipted: number }
  cleanupUnknown: null | { state: string; reason: string; processOutcome?: string }
  cleanupPath: string
  paths: { configDir: string; dataDir: string; socketPath: string; tokenPath: string; appStatePath: string }
  cursor: string | null
}
export interface LaunchOptions { args?: string[]; env?: Record<string, string>; profile?: string; realCore?: boolean }
const environments = new WeakMap<ElectronApplication, Record<string, string>>()

export function assertIsolated(): void {
  const root = process.env.ODIN_REAL_CORE_ROOT
  if (process.env.ODIN_APP_E2E !== '1' || process.platform !== 'linux' || process.getuid?.() === 0
    || !root || process.env.HOME !== root || !process.env.ODIN_REAL_CORE_OUTER_PID_NS
    || readlinkSync('/proc/self/ns/pid') === process.env.ODIN_REAL_CORE_OUTER_PID_NS
    || !/^:\d+$/.test(process.env.DISPLAY ?? '') || !process.env.DBUS_SESSION_BUS_ADDRESS) {
    throw new Error('Electron E2E refused outside parent isolated nonroot PID/HOME/Xvfb/private D-Bus runner')
  }
  const init = readFileSync('/proc/1/cmdline', 'utf8').split('\0')
  if (!init.includes(join(repository, 'app/scripts/real-core-isolation.mjs')) || !init.includes('--inside-run')) {
    throw new Error('Electron E2E refused: PID 1 is not the repository isolation launcher')
  }
}

export function isolatedEnv(profile = 'default'): Record<string, string> {
  assertIsolated()
  if (!/^[a-z0-9_-]+$/.test(profile)) throw new Error('Unsafe test profile key')
  const root = join(process.env.ODIN_REAL_CORE_ROOT!, `app-${profile}`)
  const env: Record<string, string> = {}
  for (const key of ['PATH', 'LANG', 'DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'ODIN_REAL_CORE_ROOT',
    'ODIN_REAL_CORE_OUTER_PID_NS', 'ODIN_DESKTOP_ENGINE_PYTHON', 'ODIN_APP_E2E_OUT']) {
    if (process.env[key]) env[key] = process.env[key]!
  }
  Object.assign(env, { HOME: process.env.HOME!, ODIN_APP_E2E: '1', PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1',
    XDG_CONFIG_HOME: join(root, 'config'), XDG_DATA_HOME: join(root, 'data'), XDG_CACHE_HOME: join(root, 'cache'),
    XDG_RUNTIME_DIR: join(root, 'run') })
  for (const key of ['XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR']) mkdirSync(env[key]!, { recursive: true, mode: 0o700 })
  return env
}

export async function launchApp(options: LaunchOptions = {}): Promise<ElectronApplication> {
  const env = { ...isolatedEnv(options.profile), ...options.env }
  if (options.realCore !== false && !env.ODIN_DESKTOP_CORE_CMD) {
    const python = process.env.ODIN_DESKTOP_ENGINE_PYTHON ?? join(repository, '.venv/bin/python')
    if (!existsSync(python)) throw new Error('Real engine Python missing; no fixture fallback')
    env.ODIN_DESKTOP_CORE_CMD = JSON.stringify([python, '-m', 'src'])
  }
  const application = await _electron.launch({ executablePath: join(repository, 'app/node_modules/electron/dist/electron'),
    chromiumSandbox: true,
    args: [join(repository, 'app'), ...(options.args ?? [])], cwd: repository, env, timeout: 30_000 })
  const launchEvidence = await application.evaluate(({ BrowserWindow }) => {
    const contents = BrowserWindow.getAllWindows()[0]?.webContents as unknown as {
      getLastWebPreferences(): { sandbox: boolean; contextIsolation: boolean; nodeIntegration: boolean }
    } | undefined
    return { arguments: process.argv, preferences: contents?.getLastWebPreferences() }
  })
  if (launchEvidence.arguments.some((argument) => argument.includes('--no-sandbox'))
    || (launchEvidence.preferences && (!launchEvidence.preferences.sandbox
      || !launchEvidence.preferences.contextIsolation || launchEvidence.preferences.nodeIntegration))) {
    await application.close()
    throw new Error('Qualification refused: Electron renderer sandbox/isolation was disabled')
  }
  environments.set(application, env)
  return application
}
export async function snapshot(application: ElectronApplication): Promise<MainSnapshot> {
  return application.evaluate(() => (globalThis as unknown as { __odinE2E: { snapshot(): MainSnapshot } }).__odinE2E.snapshot())
}
export async function request(application: ElectronApplication, method: string, params: Record<string, unknown> = {}, id?: string): Promise<{ok: boolean; result?: unknown; error?: unknown}> {
  return application.evaluate((_electron, input) => (globalThis as unknown as {
    __odinE2E: { request(method: string, params: Record<string, unknown>, id?: string): Promise<{ok: boolean; result?: unknown; error?: unknown}> }
  }).__odinE2E.request(input.method, input.params, input.id), { method, params, id })
}
export async function waitForCore(application: ElectronApplication): Promise<{pid: number; instanceId: string}> {
  // Allow cold startup plus the unchanged 5s handshake/restart policy under load; bound observation, not product timing.
  const deadline = Date.now() + 45_000
  while (Date.now() < deadline) {
    const state = await snapshot(application)
    if (state.appState.link === 'ready' && state.corePid && state.appState.coreInstanceId) return { pid: state.corePid, instanceId: state.appState.coreInstanceId }
    if (state.coreState === 'failed') throw new Error(`Core failed: ${JSON.stringify(state)}`)
    await new Promise((done) => setTimeout(done, 50))
  }
  throw new Error(`Core not ready: ${JSON.stringify(await snapshot(application))}`)
}
export async function launchSecond(application: ElectronApplication, args: string[] = []): Promise<{code: number | null; stdout: string; stderr: string}> {
  const env = environments.get(application)
  if (!env) throw new Error('Application was not created by isolated harness')
  return launchRaw(env, args)
}
export async function launchRaw(env: Record<string, string>, args: string[] = []): Promise<{code: number | null; stdout: string; stderr: string}> {
  assertIsolated()
  const child = spawn(join(repository, 'app/node_modules/electron/dist/electron'), [join(repository, 'app'), ...args],
    { cwd: repository, env, stdio: ['ignore', 'pipe', 'pipe'] })
  let stdout = '', stderr = ''
  child.stdout.on('data', (data: Buffer) => { stdout += data.toString() })
  child.stderr.on('data', (data: Buffer) => { stderr += data.toString() })
  return new Promise((done, reject) => {
    const timeout = setTimeout(() => { child.kill('SIGKILL'); reject(new Error('Second/exit-only Electron timed out')) }, 15_000)
    child.once('error', (error) => { clearTimeout(timeout); reject(error) })
    child.once('exit', (code) => { clearTimeout(timeout); done({ code, stdout, stderr }) })
  })
}
export async function exitApp(application: ElectronApplication): Promise<void> {
  const closed = application.waitForEvent('close', { timeout: 30_000 })
  await application.evaluate(() => { (globalThis as unknown as { __odinE2E: { exit(): void } }).__odinE2E.exit() })
  await closed
}
