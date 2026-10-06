// Uses the existing PID-namespace + private Xvfb runner. No production fixture override is shipped.
import { test, expect, _electron as electron, type ElectronApplication, type Page } from '@playwright/test'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readlinkSync, readdirSync, rmSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import type { OdinApi } from '../../src/shared/api'

declare global { interface Window { odin: OdinApi } }

const appDir = resolve(__dirname, '../..')
let app: ElectronApplication | undefined
let page: Page
let root: string

function snapshot(directory: string): Record<string, string> {
  const files: Record<string, string> = {}
  function walk(path: string): void {
    for (const entry of readdirSync(path, { withFileTypes: true })) {
      const target = join(path, entry.name)
      if (entry.isDirectory()) walk(target)
      else if (entry.isFile()) files[target.slice(directory.length)] = createHash('sha256').update(readFileSync(target)).digest('hex')
    }
  }
  if (existsSync(directory)) walk(directory)
  return files
}

async function launch(real: boolean): Promise<void> {
  expect(process.env.ODIN_REAL_CORE_OUTER_PID_NS).toBeTruthy()
  expect(readlinkSync('/proc/self/ns/pid')).not.toBe(process.env.ODIN_REAL_CORE_OUTER_PID_NS)
  expect(readFileSync('/proc/1/cmdline', 'utf8').split('\0')).toContain(join(appDir, 'scripts/real-core-isolation.mjs'))
  root = mkdtempSync(join(tmpdir(), 'od-notice-'))
  for (const dir of ['config', 'data', 'cache', 'run']) mkdirSync(join(root, dir), { mode: 0o700 })
  const env: Record<string, string> = { PATH: '/usr/local/bin:/usr/bin:/bin', LANG: 'C.UTF-8', HOME: root,
    XDG_CONFIG_HOME: join(root, 'config'), XDG_DATA_HOME: join(root, 'data'), XDG_CACHE_HOME: join(root, 'cache'),
    XDG_RUNTIME_DIR: join(root, 'run'), DISPLAY: process.env.DISPLAY!, XAUTHORITY: process.env.XAUTHORITY!,
    PYTHONDONTWRITEBYTECODE: '1', PYTHONNOUSERSITE: '1',
    GH_TOKEN: 'notice-test-ambient-canary', GITHUB_TOKEN: 'notice-test-ambient-canary',
    HTTPS_PROXY: 'https://fixture-user:fixture-password@127.0.0.1:1' }
  if (real) env.ODIN_DESKTOP_CORE_CMD = JSON.stringify([process.env.ODIN_DESKTOP_ENGINE_PYTHON, '-B', '-P', '-m', 'src'])
  app = await electron.launch({ executablePath: require('electron'), args: [appDir, '--force-renderer-accessibility'],
    env, cwd: appDir, chromiumSandbox: true })
  page = await app.firstWindow()
  await expect(page.locator('.link.ready')).toContainText('Connected')
  expect(await app.evaluate(({ BrowserWindow }) => (BrowserWindow.getAllWindows()[0]!.webContents as any).getLastWebPreferences()))
    .toMatchObject({ sandbox: true, contextIsolation: true, nodeIntegration: false })
  await page.keyboard.press('Control+,')
  await expect(page.getByRole('region', { name: 'App version and updates' })).toBeVisible()
  await page.evaluate(readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8'))
  // Debugger-side injection into the actual transport used by the named IPC operation.
  await app.evaluate(({ shell }) => {
    const https: any = process.getBuiltinModule('node:https'), fs: any = process.getBuiltinModule('node:fs'), child: any = process.getBuiltinModule('node:child_process')
    const { EventEmitter } = process.getBuiltinModule('node:events')
    const audit: any = (globalThis as any).__noticeAudit = { fixture: { status: 404, body: '{}' }, requests: [], opens: [], writes: [], spawns: [] }
    https.request = (url: unknown, options: unknown, callback: (response: unknown) => void) => {
      audit.requests.push({ url, options })
      const request: any = new EventEmitter()
      request.end = () => queueMicrotask(() => {
        if (audit.fixture.offline) { request.emit('error', new Error('controlled offline')); request.emit('close'); return }
        const response: any = new EventEmitter()
        response.statusCode = audit.fixture.status
        response.headers = audit.fixture.headers ?? {}
        callback(response)
        response.emit('data', Buffer.from(audit.fixture.body))
        response.emit('end')
        request.emit('close')
      })
      request.destroy = (error: Error) => { request.emit('error', error); request.emit('close') }
      return request
    }
    shell.openExternal = async (url: string) => { audit.opens.push(url) }
    for (const method of ['writeFileSync', 'writeFile', 'appendFileSync', 'appendFile', 'renameSync', 'rename', 'copyFileSync', 'copyFile']) {
      const original = fs[method]
      fs[method] = (...args: unknown[]) => { audit.writes.push(method); return original(...args) }
    }
    for (const method of ['spawn', 'exec', 'execFile', 'spawnSync', 'execSync', 'execFileSync']) {
      const original = child[method]
      child[method] = (...args: unknown[]) => { audit.spawns.push(method); return original(...args) }
    }
  })
}

const release = (tag: string, extra = {}) => ({ tag_name: tag,
  html_url: `https://github.com/Calmingstorm/Odin-Desktop/releases/tag/${tag}`, draft: false, prerelease: false,
  published_at: '2026-10-05T00:00:00Z', ...extra })

async function fixture(value: unknown): Promise<void> {
  await app!.evaluate((_electron, fixture) => { (globalThis as any).__noticeAudit.fixture = fixture }, value)
}

async function keyboardActivate(name: string, role: 'button' | 'link' = 'button'): Promise<void> {
  const target = page.getByRole(role, { name, exact: true })
  for (let n = 0; n < 100; n++) {
    if (await target.evaluate((el) => el === document.activeElement)) {
      expect(await target.evaluate((el) => el.matches(':focus-visible'))).toBe(true)
      await page.keyboard.press('Enter')
      return
    }
    await page.keyboard.press('Tab')
  }
  throw new Error(`Not keyboard reachable: ${name}`)
}

test.afterEach(async () => {
  if (app) {
    const child = app.process()
    await app.close()
    expect(child.exitCode !== null || child.signalCode !== null).toBe(true)
    app = undefined
    rmSync(root, { recursive: true, force: true })
    await test.info().attach('notice-cleanup', { body: JSON.stringify({ electronPid: child.pid, exitCode: child.exitCode,
      profileRemoved: !existsSync(root), pidNamespace: readlinkSync('/proc/self/ns/pid') }), contentType: 'application/json' })
  }
})

for (const real of [false, true]) test(`${real ? 'real core' : 'fixture core'}: named anonymous operation, all states, read-only and accessible`, async () => {
  await launch(real)
  const dataBefore = snapshot(join(root, 'data')), configBefore = snapshot(join(root, 'config'))
  const coreBefore = await page.evaluate(() => window.odin.status())
  const noticeDispatches: string[] = []
  // Record actual registered notice-handler dispatch, not a renderer-only fake API.
  await app!.evaluate(({ ipcMain }) => {
    const audit = (globalThis as any).__noticeAudit
    audit.noticeChannels = []
    for (const channel of ['odin:check-releases', 'odin:open-release']) {
      const handlers = (ipcMain as any)._invokeHandlers
      const original = handlers.get(channel)
      handlers.set(channel, (...args: unknown[]) => { audit.noticeChannels.push(channel); return original(...args) })
    }
  })
  const childIds = () => app!.evaluate(() => process.getBuiltinModule('node:fs').readFileSync(`/proc/${process.pid}/task/${process.pid}/children`, 'utf8'))
  const childrenBefore = await childIds()
  // Exercise the registered sender/schema gate as well, not only typed preload arguments.
  const rejected = await app!.evaluate(async ({ ipcMain, BrowserWindow }) => {
    const handler = (ipcMain as any)._invokeHandlers.get('odin:check-releases')
    const contents = BrowserWindow.getAllWindows()[0]!.webContents
    return [await handler({ sender: contents, senderFrame: contents.mainFrame }, { url: 'https://example.com', token: 'fixture' }),
      await handler({ sender: { id: -1 }, senderFrame: { url: 'https://example.com' } }, {})]
  })
  expect(rejected).toMatchObject([{ ok: false, error: { code: 'bad_request' } }, { ok: false, error: { code: 'unauthorized' } }])
  const cases = [
    [{ status: 404, body: '{}' }, 'cannot-check-private', "Can't check for updates"],
    [{ status: 401, body: '{}' }, 'cannot-check-private', 'access is denied'],
    [{ status: 403, body: '{}' }, 'unavailable', 'unavailable'],
    [{ offline: true }, 'offline', 'Offline'],
    [{ status: 403, body: '{}', headers: { 'x-ratelimit-remaining': '0' } }, 'rate-limited', 'rate-limited'],
    [{ status: 429, body: '{}' }, 'rate-limited', 'rate-limited'],
    [{ status: 200, body: '{' }, 'malformed', 'invalid release metadata'],
    [{ status: 200, body: ' '.repeat(1024 * 1024 + 1) }, 'malformed', 'invalid release metadata'],
    [{ status: 200, body: '[]' }, 'no-release', 'No published stable release'],
    [{ status: 200, body: JSON.stringify([release('v0.1.0')]) }, 'equal', 'Up to date'],
    [{ status: 200, body: JSON.stringify([release('v0.0.9')]) }, 'older', 'This app is newer'],
    [{ status: 200, body: JSON.stringify([release('v1.0.0'), release('v9.0.0', { draft: true }), release('v8.0.0', { prerelease: true })]) }, 'newer', 'A new version is available'],
    [{ status: 200, body: JSON.stringify([release('v1.0.0', { html_url: 'https://example.com/' })]) }, 'malformed', 'invalid release metadata']
  ] as const
  for (const [response, state, text] of cases) {
    await fixture(response)
    await keyboardActivate('Check for updates')
    await expect(page.locator('#release-notice-status')).toContainText(text)
    expect(await page.evaluate(() => window.odin.checkReleases())).toMatchObject({ ok: true, result: { state } })
    if (state === 'newer') {
      const axe = await page.evaluate(async () => (window as any).axe.run(document))
      expect(axe.violations).toEqual([])
      await test.info().attach('axe-newer-with-release-link', { body: JSON.stringify({ violations: axe.violations, incomplete: axe.incomplete }), contentType: 'application/json' })
      await keyboardActivate('Open release page in browser', 'link')
      expect(await app!.evaluate(() => (globalThis as any).__noticeAudit.opens)).toEqual([release('v1.0.0').html_url])
    }
    if (!['equal', 'older', 'newer'].includes(state)) {
      expect((await page.evaluate(() => window.odin.openRelease())).ok).toBe(false)
      await expect(page.getByRole('link', { name: 'Open release page in browser' })).toHaveCount(0)
    }
  }
  expect((await page.evaluate(() => window.odin.openRelease())).ok).toBe(false)
  const coreAfter = await page.evaluate(() => window.odin.status())
  expect(coreAfter.ok && coreAfter.result.core_instance_id).toBe(coreBefore.ok && coreBefore.result.core_instance_id)
  expect(snapshot(join(root, 'data'))).toEqual(dataBefore)
  expect(snapshot(join(root, 'config'))).toEqual(configBefore)
  expect(await childIds()).toBe(childrenBefore)
  const audit = await app!.evaluate(() => (globalThis as any).__noticeAudit)
  expect(audit.writes).toEqual([])
  expect(audit.spawns).toEqual([])
  expect(audit.opens).toEqual([release('v1.0.0').html_url])
  noticeDispatches.push(...audit.noticeChannels)
  expect(noticeDispatches).toContain('odin:check-releases')
  expect(noticeDispatches).toContain('odin:open-release')
  for (const request of audit.requests) expect(request).toEqual({
    url: 'https://api.github.com/repos/Calmingstorm/Odin-Desktop/releases?per_page=100',
    options: { method: 'GET', agent: false, headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'Odin-Desktop-release-notice', 'X-GitHub-Api-Version': '2022-11-28' } }
  })
  await page.evaluate(readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8'))
  const axe = await page.evaluate(async () => (window as any).axe.run(document))
  expect(axe.violations).toEqual([])
  const cdp = await page.context().newCDPSession(page)
  const ax = await cdp.send('Accessibility.getFullAXTree')
  await cdp.detach()
  expect(JSON.stringify(ax)).toContain('App version and updates')
  expect(JSON.stringify(ax)).toContain('Check for updates')
  await test.info().attach('notice-safety-and-a11y', { body: JSON.stringify({ audit, coreBefore, coreAfter,
    filesUnchanged: true, childIdentityUnchanged: true, axe: { violations: axe.violations, incomplete: axe.incomplete }, ax }, null, 2), contentType: 'application/json' })
})

test('built app resources do not contain credential material or ambient canaries', () => {
  const signatures = [/(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})/, /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
    /notice-test-ambient-canary/, /fixture-user:fixture-password/]
  let scanned = 0
  function scan(directory: string): void {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) scan(path)
      else {
        const text = readFileSync(path).toString('utf8')
        for (const pattern of signatures) expect(pattern.test(text), `credential signature in built ${path}`).toBe(false)
        scanned++
      }
    }
  }
  scan(join(appDir, 'out'))
  expect(scanned).toBeGreaterThan(3)
})
