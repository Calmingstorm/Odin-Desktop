// Native VM source qualification only. Never a packaged debug capability.
import { _electron, expect } from '@playwright/test'
import { execFileSync, spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readlinkSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { createConnection } from 'node:net'
import { randomUUID } from 'node:crypto'

const repository = resolve(import.meta.dirname, '../..')
const options = Object.fromEntries(process.argv.slice(2).map((arg) => {
  const match = /^--([a-z-]+)=(.+)$/.exec(arg)
  if (!match) throw new Error('Use --core=real|notification-fixture --socket=PATH --out=PATH')
  return [match[1], match[2]]
}))
if (!['real', 'notification-fixture'].includes(options.core) || !options.socket || !options.out)
  throw new Error('Explicit --core, --socket and --out required')
execFileSync('/usr/bin/python3', ['-c', 'import runpy,sys; runpy.run_path(sys.argv[1])["guard"]()',
  join(repository, 'scripts/qualification/lab/guest/native-p33-probe.py')], { stdio: 'inherit' })
const root = process.env.ODIN_REAL_CORE_ROOT
if (!root?.startsWith('/tmp/odrc-') || process.env.HOME !== root || statSync(root).uid !== process.getuid()
  || resolve(root) !== root || readlinkSafe(root) || (statSync(root).mode & 0o077)
  || !process.env.ODIN_REAL_CORE_OUTER_PID_NS
  || readlinkSync('/proc/self/ns/pid') === process.env.ODIN_REAL_CORE_OUTER_PID_NS
  || !/^:\d+$/.test(process.env.DISPLAY ?? '')) throw new Error('Real guest PID isolation and source seam prerequisites missing')
if (dirname(resolve(options.socket)) !== root || !statSync(options.socket).isSocket()) throw new Error('Collector socket not in owned run root')
if (!resolve(options.out).startsWith(`${root}/`)) throw new Error('Evidence output must be inside owned run root')
if (!existsSync(join(repository, 'app/out/main/index.js'))) throw new Error('Build source app; no packaged fallback')

function readlinkSafe(path) { try { readlinkSync(path); return true } catch { return false } }

const report = { schema: 'native-p33-v1', core: options.core, productionDebugAuthority: false,
  fixtureOnly: options.core === 'notification-fixture', steps: [], failures: [],
  limitations: ['Source app only; parent separately qualifies AppImage and installed packages.',
    'No login session restart; autostart setting/entry is not proof of login launch.'] }
async function native(operation, params = {}) {
  return new Promise((done, reject) => {
    const socket = createConnection(options.socket)
    let data = ''
    socket.setTimeout(20_000, () => socket.destroy(new Error('Native collector timeout')))
    socket.on('error', reject)
    socket.on('connect', () => socket.write(JSON.stringify({ operation, ...params }) + '\n'))
    socket.on('data', (chunk) => {
      data += chunk
      if (data.includes('\n')) {
        socket.end()
        const response = JSON.parse(data.split('\n')[0])
        if (!response.ok) reject(new Error(response.error)); else done(response.result)
      }
    })
  })
}
function identity(pid) {
  const base = `/proc/${pid}`
  return { pid, startTicks: readFileSync(`${base}/stat`, 'utf8').split(') ').at(-1).split(' ')[19],
    uid: Number(/^Uid:\s+(\d+)/m.exec(readFileSync(`${base}/status`, 'utf8'))[1]),
    namespace: readlinkSync(`${base}/ns/pid`), executable: readlinkSync(`${base}/exe`) }
}
function alive(before) {
  try { return identity(before.pid).startTicks === before.startTicks
    && readFileSync(`/proc/${before.pid}/stat`, 'utf8').split(') ').at(-1).split(' ')[0] !== 'Z' } catch { return false }
}
async function step(name, work) {
  try { const evidence = await work(); report.steps.push({ name, passed: true, evidence }); return evidence }
  catch (error) { report.steps.push({ name, passed: false, error: String(error) }); report.failures.push(name); return null }
}
const env = {}
for (const name of ['PATH', 'LANG', 'HOME', 'DISPLAY', 'XAUTHORITY', 'WAYLAND_DISPLAY', 'XDG_SESSION_TYPE',
  'XDG_CURRENT_DESKTOP', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS', 'ODIN_REAL_CORE_ROOT',
  'ODIN_REAL_CORE_OUTER_PID_NS', 'ODIN_DESKTOP_ENGINE_PYTHON']) if (process.env[name]) env[name] = process.env[name]
Object.assign(env, { ODIN_APP_E2E: '1', PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1',
  XDG_CONFIG_HOME: join(root, 'config'), XDG_DATA_HOME: join(root, 'data'), XDG_CACHE_HOME: join(root, 'cache') })
for (const key of ['XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME']) mkdirSync(env[key], { recursive: true, mode: 0o700 })
const python = env.ODIN_DESKTOP_ENGINE_PYTHON
if (!python || !existsSync(python)) throw new Error('Explicit guest engine Python required; no fixture fallback')
env.ODIN_DESKTOP_CORE_CMD = JSON.stringify(options.core === 'real' ? [python, '-m', 'src']
  : [python, join(repository, 'tests/desktop_fixtures/notification_core.py')])
const executable = join(repository, 'app/node_modules/electron/dist/electron')
const args = [join(repository, 'app'), '--force-renderer-accessibility',
  ...(env.XDG_SESSION_TYPE === 'wayland' ? ['--ozone-platform=wayland'] : ['--ozone-platform=x11'])]
let app
let exited = false
let snapshot
let identities
try {
  report.nativeBefore = await native('inspect')
  if (!report.nativeBefore.owners['org.freedesktop.Notifications']) throw new Error('Real desktop notification owner absent')
  app = await _electron.launch({ executablePath: executable, args, cwd: repository, env,
    chromiumSandbox: true, timeout: 30_000 })
  app.on('close', () => { exited = true })
  snapshot = () => app.evaluate(() => globalThis.__odinE2E.snapshot())
  await expect.poll(async () => (await snapshot()).appState.link, { timeout: 30_000 }).toBe('ready')
  const page = await app.firstWindow()
  const started = await snapshot()
  if (options.core === 'real') {
    const status = await app.evaluate(() => globalThis.__odinE2E.request('status.get'))
    expect(status.ok).toBe(true)
    report.realCoreStatus = status
  }
  identities = { main: identity(started.pid), core: identity(started.corePid), renderer: identity(started.rendererPid) }
  report.started = { snapshot: started, processes: identities }
  report.sandbox = await app.evaluate(({ BrowserWindow }) => ({ arguments: process.argv,
    preferences: BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences() }))
  if (report.sandbox.arguments.some((arg) => arg.includes('--no-sandbox')) || !report.sandbox.preferences.sandbox
    || !report.sandbox.preferences.contextIsolation || report.sandbox.preferences.nodeIntegration) throw new Error('Sandbox evidence rejected')
  await step('autostart-renderer-api', async () => {
    const enabled = await page.evaluate(() => window.odin.setAutostart(true))
    expect(enabled).toMatchObject({ ok: true, result: { autostart: true } })
    const entry = readFileSync(join(env.XDG_CONFIG_HOME, 'autostart/odin-desktop.desktop'), 'utf8')
    expect(entry).toContain('--hidden')
    const disabled = await page.evaluate(() => window.odin.setAutostart(false))
    expect(disabled).toMatchObject({ ok: true, result: { autostart: false } })
    expect(existsSync(join(env.XDG_CONFIG_HOME, 'autostart/odin-desktop.desktop'))).toBe(false)
    return { enabled, entry, disabled, scope: 'throwaway config, no login restart' }
  })
  await step('close-keeps-core', async () => {
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
    await expect.poll(async () => (await snapshot()).visible).toBe(false)
    expect(alive(identities.main) && alive(identities.core)).toBe(true)
    return await snapshot()
  })
  if (!started.appState.noTray) {
    await step('native-tray-open', async () => {
      const menu = await native('tray-menu')
      const action = await native('tray-action', { label: 'Open Odin' })
      await expect.poll(async () => (await snapshot()).visible).toBe(true)
      expect(alive(identities.main) && alive(identities.core)).toBe(true)
      return { menu, action, after: await snapshot() }
    })
  } else {
    await step('no-tray-second-launch-reopens', async () => {
      const child = spawn(executable, args, { cwd: repository, env, stdio: 'ignore' })
      const result = await new Promise((done, reject) => {
        const timer = setTimeout(() => { child.kill(); reject(new Error('Second launch timeout')) }, 15_000)
        child.on('error', reject)
        child.on('exit', (code) => { clearTimeout(timer); done(code) })
      })
      expect(result).toBe(0)
      await expect.poll(async () => (await snapshot()).visible).toBe(true)
      const after = await snapshot()
      expect(after.pid).toBe(started.pid)
      expect(after.corePid).toBe(started.corePid)
      expect(after.noTrayNoticeShown).toBe(true)
      return { secondExitCode: result, after }
    })
  }
  if (options.core === 'notification-fixture') {
    await step('real-os-notification-exact-dom-click-fixture', async () => {
      const evidence = { scope: 'fixture conversation/ack, real native OS daemon and AT-SPI click' }
      report.notification = evidence
      await page.locator('.conv', { hasText: 'Other conversation' }).click()
      await expect(page.locator('#m-notify-other-119')).toBeVisible()
      await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].hide())
      const marker = `P33 native ${randomUUID()}`
      evidence.marker = marker
      const accepted = await app.evaluate((_electron, marker) => globalThis.__odinE2E.notification({
        conversation_id: 'notify-main', message_id: 'notify-main-3', category: 'reply',
        preview: marker, dedupe_key: marker }, new Date().toISOString()), marker)
      evidence.accepted = accepted
      expect(accepted).toBe('shown')
      const beforeActions = (await native('inspect')).actions.length
      const click = await native('notification-click', { text: marker })
      evidence.click = click
      await expect(page.locator('#m-notify-main-3')).toHaveClass(/highlight/)
      await expect(page.locator('.conv.active')).toContainText('Notification target')
      await expect(page.locator('#m-notify-main-3')).toBeInViewport()
      await expect(page.locator('.jump-banner')).toBeVisible()
      await expect.poll(async () => (await app.evaluate(() => globalThis.__odinE2E.notificationAcks))
        .find((ack) => ack.dedupeKey === marker)?.settled.ok).toBe(true)
      const daemon = await native('inspect')
      expect(daemon.actions.slice(beforeActions).some((action) => action.action === 'default')).toBe(true)
      return { scope: 'fixture conversation/ack, real native OS daemon and AT-SPI click', marker,
        accepted, click, daemon, visibleMessage: await page.locator('.msg.highlight').getAttribute('id'),
        acks: await app.evaluate(() => globalThis.__odinE2E.notificationAcks) }
    })
  }
  await step('native-exit-process-witness', async () => {
    let nativeAction
    if (started.appState.noTray) {
      await app.evaluate(({ BrowserWindow }) => { const win = BrowserWindow.getAllWindows()[0]; win.show(); win.focus() })
      await page.keyboard.press('Control+q')
      nativeAction = 'Electron input Ctrl+Q accelerator, not callback'
    } else {
      const menu = await native('tray-menu')
      const action = await native('tray-action', { label: 'Exit Odin' })
      nativeAction = { menu, action }
    }
    await expect.poll(() => exited, { timeout: 30_000 }).toBe(true)
    await expect.poll(() => alive(identities.core), { timeout: 10_000 }).toBe(false)
    expect(alive(identities.main)).toBe(false)
    const cleanup = JSON.parse(readFileSync(started.cleanupPath, 'utf8'))
    expect(cleanup.current ?? cleanup).toMatchObject({ state: 'process-exited', shutdownAccepted: true, unsaved: false, unreceipted: 0 })
    expect(existsSync(started.paths.socketPath)).toBe(false)
    return { nativeAction, exited, mainGone: !alive(identities.main), coreGone: !alive(identities.core), cleanup, socketRemoved: true }
  })
} catch (error) {
  report.failures.push('runner')
  report.error = String(error)
} finally {
  if (app && !exited) {
    try { await app.close(); report.fallbackCleanup = 'Playwright normal close, NOT native-exit proof' }
    catch (error) { report.fallbackCleanup = String(error) }
  }
  report.verdict = report.failures.length ? 'fail' : 'pass'
  writeFileSync(options.out, JSON.stringify(report, null, 2) + '\n', { mode: 0o600 })
  console.log(JSON.stringify({ verdict: report.verdict, failures: report.failures, evidence: options.out }))
  process.exitCode = report.failures.length ? 1 : 0
}
