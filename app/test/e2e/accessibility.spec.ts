import { test, expect, _electron as electron, type ElectronApplication, type Page, type Locator } from '@playwright/test'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readlinkSync, rmSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'

const appDir = resolve(__dirname, '../..')
const axePath = require.resolve('axe-core/axe.min.js')
let app: ElectronApplication
let page: Page
let root: string
let launchEvidence: unknown

test.beforeEach(async () => {
  // Fail closed even when somebody calls the Playwright CLI directly.
  expect(process.env.ODIN_REAL_CORE_OUTER_PID_NS).toBeTruthy()
  expect(readlinkSync('/proc/self/ns/pid')).not.toBe(process.env.ODIN_REAL_CORE_OUTER_PID_NS)
  const init = readFileSync('/proc/1/cmdline', 'utf8').split('\0')
  expect(init).toContain(join(appDir, 'scripts/real-core-isolation.mjs'))
  expect(init).toContain('--inside-run')
  expect(process.env.HOME).toBe(process.env.ODIN_REAL_CORE_ROOT)
  expect(process.env.HOME).toMatch(/^\/tmp\/odrc-/)
})

async function launch(real = false, scenario?: string): Promise<void> {
  root = mkdtempSync(join(tmpdir(), 'od-a11y-'))
  for (const dir of ['config', 'data', 'cache', 'run']) mkdirSync(join(root, dir), { mode: 0o700 })
  const env: Record<string, string> = {
    PATH: '/usr/local/bin:/usr/bin:/bin', LANG: 'C.UTF-8', HOME: root,
    XDG_CONFIG_HOME: join(root, 'config'), XDG_DATA_HOME: join(root, 'data'),
    XDG_CACHE_HOME: join(root, 'cache'), XDG_RUNTIME_DIR: join(root, 'run'),
    DISPLAY: process.env.DISPLAY!, XAUTHORITY: process.env.XAUTHORITY!,
    DBUS_SESSION_BUS_ADDRESS: process.env.DBUS_SESSION_BUS_ADDRESS!,
    PYTHONDONTWRITEBYTECODE: '1', PYTHONNOUSERSITE: '1'
  }
  if (real) {
    env.ODIN_DESKTOP_CORE_CMD = JSON.stringify([process.env.ODIN_DESKTOP_ENGINE_PYTHON, '-B', '-P', '-m', 'src'])
    // Native dialogs need the private bus in fixture lanes, but this fresh real-core lane must
    // report a missing vault rather than wait on an unqualified Secret Service unlock prompt.
    delete env.DBUS_SESSION_BUS_ADDRESS
  }
  else if (scenario) env.ODIN_DESKTOP_CORE_CMD = JSON.stringify(['/usr/bin/python3', '-B', join(appDir, 'test/e2e/accessibility-core.py'), scenario])
  app = await electron.launch({ executablePath: require('electron'), args: [appDir, '--force-renderer-accessibility'],
    cwd: appDir, env, chromiumSandbox: true })
  page = await app.firstWindow()
  await expect(page.locator('.link.ready')).toContainText('Connected')
  launchEvidence = await app.evaluate(({ BrowserWindow }) => {
    // Electron's diagnostic method exists at runtime but is absent from its public TypeScript surface.
    const contents = BrowserWindow.getAllWindows()[0]!.webContents as unknown as {
      getLastWebPreferences: () => { sandbox: boolean; contextIsolation: boolean; nodeIntegration: boolean }
    }
    const preferences = contents.getLastWebPreferences()
    return { sandbox: preferences.sandbox, contextIsolation: preferences.contextIsolation,
      nodeIntegration: preferences.nodeIntegration, arguments: process.argv }
  })
  expect(launchEvidence).toMatchObject({ sandbox: true, contextIsolation: true, nodeIntegration: false })
  expect(JSON.stringify(launchEvidence)).not.toContain('--no-sandbox')
  // Debugger-side evaluation for the audit, not a CSP exception in the app.
  await page.evaluate(readFileSync(axePath, 'utf8'))
}

test.afterEach(async () => {
  if (app) {
    const child = app.process()
    await app.close()
    await expect.poll(() => child.exitCode !== null || child.signalCode !== null).toBe(true)
    await test.info().attach('isolation-cleanup', { body: JSON.stringify({ launch: launchEvidence,
      pidNamespace: readlinkSync('/proc/self/ns/pid'), outerNamespace: process.env.ODIN_REAL_CORE_OUTER_PID_NS,
      display: process.env.DISPLAY, electronPid: child.pid, exitCode: child.exitCode, signal: child.signalCode,
      profileRemoved: root ? (rmSync(root, { recursive: true, force: true }), !existsSync(root)) : true }), contentType: 'application/json' })
  } else if (root) rmSync(root, { recursive: true, force: true })
})

async function audit(name: string): Promise<void> {
  const findings = await page.evaluate(async () => {
    const axe = (window as unknown as { axe: { run: (doc: Document) => Promise<{ violations: unknown[]; incomplete: unknown[] }> } }).axe
    const result = await axe.run(document)
    return { violations: result.violations, incomplete: result.incomplete }
  })
  await test.info().attach(`axe-${name}`, { body: JSON.stringify(findings, null, 2), contentType: 'application/json' })
  expect(findings.violations, `axe findings on ${name}`).toEqual([])
}

async function tabTo(target: Locator, reverse = false): Promise<void> {
  await expect(target).toBeVisible()
  for (let n = 0; n < 200; n++) {
    if (await target.evaluate((el) => el === document.activeElement)) {
      const focus = await target.evaluate((el) => {
        const s = getComputedStyle(el)
        return { visible: el.matches(':focus-visible'), outline: s.outlineStyle, width: s.outlineWidth }
      })
      expect(focus.visible).toBe(true)
      expect(focus.outline).not.toBe('none')
      expect(parseFloat(focus.width)).toBeGreaterThanOrEqual(2)
      return
    }
    await page.keyboard.press(reverse ? 'Shift+Tab' : 'Tab')
  }
  throw new Error(`Not keyboard reachable: ${await target.getAttribute('aria-label') ?? await target.textContent()}`)
}

async function activate(target: Locator): Promise<void> {
  await tabTo(target)
  await page.keyboard.press('Enter')
}

async function send(text: string): Promise<void> {
  const box = page.getByRole('textbox', { name: 'Message', exact: true })
  await tabTo(box)
  await page.keyboard.press('Control+a')
  await page.keyboard.insertText(text)
  await page.keyboard.press('Enter')
}

async function ax(name: string): Promise<string> {
  const session = await page.context().newCDPSession(page)
  await session.send('Accessibility.enable')
  const tree = await session.send('Accessibility.getFullAXTree')
  await session.detach()
  await test.info().attach(`ax-${name}`, { body: JSON.stringify(tree, null, 2), contentType: 'application/json' })
  const controls = new Set(['button', 'textbox', 'searchbox', 'combobox', 'checkbox', 'radio', 'spinbutton', 'menuitem', 'slider'])
  expect(tree.nodes.filter((node) => !node.ignored && controls.has(String(node.role?.value)) && !String(node.name?.value ?? '').trim()),
    `unnamed controls in real Chromium AX tree on ${name}`).toEqual([])
  return JSON.stringify(tree)
}

async function settingsSection(name: string): Promise<void> {
  await activate(page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name, exact: true }))
  await expect(page.locator('.settings-body')).toContainText(name)
}

async function typeField(field: Locator, value: string): Promise<void> {
  await tabTo(field)
  await page.keyboard.press('Control+a')
  await page.keyboard.insertText(value)
}

test('fixture baseline audit', async () => {
  await launch()
  await audit('chat')
  await page.keyboard.press('Control+,')
  await audit('general')
})

test('settings section audit inventory', async () => {
  await launch()
  await page.keyboard.press('Control+,')
  const nav = page.getByRole('navigation', { name: 'Settings sections' })
  const labels = await nav.locator('.settings-nav-item').allTextContents()
  const findings: Record<string, unknown> = {}
  for (const label of labels) {
    await activate(nav.getByRole('button', { name: label, exact: true }))
    await expect(page.locator('.settings-body')).toContainText(label)
    await page.waitForTimeout(200)
    findings[label] = await page.evaluate(async () => {
      const r = await (window as any).axe.run(document)
      return { violations: r.violations, incomplete: r.incomplete }
    })
    await ax(`settings-${label}`)
  }
  await test.info().attach('axe-settings-inventory', { body: JSON.stringify(findings, null, 2), contentType: 'application/json' })
  expect(Object.entries(findings).filter(([, v]) => (v as { violations: unknown[] }).violations.length)).toEqual([])
})

test('keyboard chat, code and results, native attach cancel and save', async () => {
  await launch()
  const first = page.getByRole('button', { name: 'New conversation', exact: true })
  await activate(first)
  await send('file report script keyboard result\n```text\nkeyboard-code\n```')
  await expect(page.locator('.msg.assistant')).toContainText('keyboard result')
  await audit('results')
  const results = await ax('results')
  expect(results).toContain('Echo:')
  await activate(page.locator('.msg.assistant').getByRole('button', { name: /^Copy Odin message/ }))
  await activate(page.locator('.msg.assistant').getByRole('button', { name: 'Copy as Markdown', exact: true }))
  await expect.poll(async () => app.evaluate(({ clipboard }) => clipboard.readText())).toContain('keyboard result')
  await activate(page.locator('.msg.assistant .code-copy').first())
  await expect.poll(async () => app.evaluate(({ clipboard }) => clipboard.readText())).toContain('keyboard-code')
  await activate(page.locator('.report').getByRole('button', { name: 'Next page of Health report', exact: true }))
  await expect(page.locator('.report')).toContainText('Page 2')
  await activate(page.locator('.report').getByRole('button', { name: 'Previous page of Health report', exact: true }))
  await expect(page.locator('.report')).toContainText('Page 1')
  await activate(page.locator('.report').getByRole('button', { name: 'Copy page of Health report', exact: true }))
  await expect.poll(async () => app.evaluate(({ clipboard }) => clipboard.readText())).toContain('Stored result, page 1 of 3')

  // Native dialogs run only on the namespace's Xvfb display/private bus. No dialog mock, mouse or workstation input.
  await activate(page.getByRole('button', { name: 'Attach files', exact: true }))
  await nativeKey('Escape', 'Attach files')
  await expect(page.locator('.attachments')).toHaveCount(0)
  const chosen = join(root, 'keyboard-attachment.txt')
  writeFileSync(chosen, 'keyboard-only attachment\n')
  await activate(page.getByRole('button', { name: 'Attach files', exact: true }))
  await nativeFile(chosen, 'Attach files')
  await expect(page.locator('.attachment')).toContainText('keyboard-attachment.txt')
  await activate(page.locator('.attachment').getByRole('button', { name: /Remove/ }))
  await expect(page.locator('.attachments')).toHaveCount(0)

  const file = page.locator('.file-card').filter({ hasText: 'notes.txt' })
  const saved = join(root, 'keyboard-saved.txt')
  await activate(file.getByRole('button', { name: /Save/ }))
  await nativeFile(saved, 'Save file')
  await expect.poll(() => existsSync(saved)).toBe(true)
  expect(readFileSync(saved, 'utf8')).toContain('Generated notes')
})

async function nativeWindow(title: string): Promise<string> {
  let id = ''
  await expect.poll(() => {
    try {
      id = execFileSync('xdotool', ['search', '--onlyvisible', '--name', `^${title}$`], { encoding: 'utf8' }).trim().split('\n')[0] ?? ''
      return Boolean(id)
    } catch { return false }
  }).toBe(true)
  return id
}

async function nativeKey(key: string, title: string): Promise<void> {
  const id = await nativeWindow(title)
  execFileSync('xdotool', ['windowfocus', '--sync', id])
  execFileSync('xdotool', ['key', '--clearmodifiers', key])
}

async function nativeFile(path: string, title: string): Promise<void> {
  await nativeKey('ctrl+l', title)
  execFileSync('xdotool', ['key', '--clearmodifiers', 'ctrl+a'])
  if (title === 'Save file') {
    execFileSync('xdotool', ['type', '--clearmodifiers', '--delay', '1', dirname(path)])
    execFileSync('xdotool', ['key', '--clearmodifiers', 'Return'])
    await page.waitForTimeout(200)
    execFileSync('xdotool', ['key', '--clearmodifiers', 'alt+n', 'ctrl+a'])
    execFileSync('xdotool', ['type', '--clearmodifiers', '--delay', '1', basename(path)])
    execFileSync('xdotool', ['key', '--clearmodifiers', 'Return'])
    return
  }
  execFileSync('xdotool', ['type', '--clearmodifiers', '--delay', '1', path])
  execFileSync('xdotool', ['key', '--clearmodifiers', 'Return'])
}

test('keyboard menus, modal trapping, restored focus and conversation children', async () => {
  await launch()
  await activate(page.getByRole('button', { name: 'New conversation', exact: true }))
  const opener = page.getByRole('button', { name: /Actions for/ }).last()
  await activate(opener)
  const menu = page.getByRole('menu')
  await expect(menu.getByRole('menuitem', { name: 'Rename…' })).toBeFocused()
  await page.keyboard.press('End')
  await expect(menu.getByRole('menuitem', { name: 'Delete…' })).toBeFocused()
  await page.keyboard.press('Home')
  await expect(menu.getByRole('menuitem', { name: 'Rename…' })).toBeFocused()
  await page.keyboard.press('Enter')
  const modal = page.getByRole('dialog', { name: 'Rename conversation' })
  await expect(modal.getByRole('textbox', { name: 'Title' })).toBeFocused()
  await page.keyboard.press('Control+,')
  await expect(modal.getByRole('textbox', { name: 'Title' })).toBeFocused()
  await expect(page.getByRole('main', { name: 'Settings', exact: true })).toHaveCount(0)
  for (let n = 0; n < 8; n++) {
    await page.keyboard.press('Tab')
    expect(await modal.evaluate((el) => el.contains(document.activeElement))).toBe(true)
  }
  for (let n = 0; n < 5; n++) {
    await page.keyboard.press('Shift+Tab')
    expect(await modal.evaluate((el) => el.contains(document.activeElement))).toBe(true)
  }
  const modalTree = JSON.parse(await ax('rename-modal'))
  expect(modalTree.nodes.some((n: any) => !n.ignored && n.role?.value === 'dialog')).toBe(true)
  expect(modalTree.nodes.some((n: any) => !n.ignored && n.name?.value === 'Attach files')).toBe(false)
  await audit('rename-modal')
  await page.keyboard.press('Escape')
  await expect(modal).toHaveCount(0)
  await expect(opener).toBeFocused()
  await page.keyboard.press('Enter')
  await page.keyboard.press('Escape')
  await expect(opener).toBeFocused()
  await page.keyboard.press('Enter')
  await page.keyboard.press('ArrowDown')
  await expect(menu.getByRole('menuitem', { name: 'New thread from here' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('.inherited')).toContainText('continued from')
  await activate(page.getByRole('button', { name: 'Open the original', exact: true }))
  await expect(page.locator('.inherited')).toHaveCount(0)
})

test('keyboard running task steer queue stop and guarded resume', async () => {
  await launch()
  await page.evaluate(() => {
    (window as any).taskAnnouncements = []
    new MutationObserver(() => (window as any).taskAnnouncements.push(document.querySelector('.chat-announcement')?.textContent))
      .observe(document.querySelector('.chat-announcement')!, { childList: true, subtree: true, characterData: true })
  })
  await send('slow keyboard task')
  await expect(page.locator('.working')).toBeVisible()
  await send('keyboard steer')
  await expect(page.locator('.steer-state')).toContainText('Odin has read it')
  const queue = page.getByRole('radio', { name: 'Queue as a follow-up' })
  await tabTo(page.getByRole('radio', { name: 'Steer the current task' }))
  await page.keyboard.press('ArrowRight')
  await expect(queue).toBeChecked()
  await send('queued keyboard follow up')
  await expect(page.locator('.queued')).toBeVisible()
  await audit('busy-queued')
  await ax('busy-queued-consumed')
  await activate(page.getByRole('button', { name: 'Stop the current task', exact: true }))
  await expect(page.locator('.msg.assistant')).toContainText('queued keyboard follow up')
  await expect(page.locator('.working')).toHaveCount(0)
  await send('interrupt keyboard task')
  await expect(page.locator('.resume-banner')).toBeVisible()
  await expect(page.locator('.resume-banner')).toContainText('continue')
  await expect(page.locator('.resume-banner')).toContainText('resume')
  await audit('suspended-resume-banner')
  expect(await ax('suspended-resume-banner')).toContain('continue')
  await activate(page.locator('.resume-banner').getByRole('button', { name: /Resume/ }))
  await expect(page.locator('.resume-banner')).toHaveCount(0)
  await expect(page.locator('.msg.assistant').last()).toContainText('interrupt keyboard task')
  await send('unknown keyboard effect')
  await expect(page.locator('.resume-banner')).toContainText('reconciled')
  expect(await ax('unknown-outcome')).toContain('unknown')
  const announcements = await page.evaluate(() => (window as any).taskAnnouncements as string[])
  expect(announcements.join('\n')).toContain('queued')
  expect(announcements.join('\n')).toContain('Odin has read the steer')
  expect(announcements.join('\n')).toContain('unknown outcome')
  await test.info().attach('queued-consumed-unknown-announcements', { body: JSON.stringify(announcements), contentType: 'application/json' })
})

test('search remains navigable while loading and opens the current message', async () => {
  await launch()
  await send('searchable keyboard anchor')
  await expect(page.locator('.msg.assistant')).toContainText('searchable keyboard anchor')
  await page.keyboard.press('Control+Shift+f')
  const search = page.getByRole('searchbox', { name: 'Search all conversations', exact: true })
  await expect(search).toBeFocused()
  await page.keyboard.type('searchable')
  await page.keyboard.press('Enter')
  await expect(page.locator('.search-hits .hit')).toHaveCount(2)
  await audit('search-results')
  await activate(page.locator('.search-hits .hit').first())
  await expect(page.locator('.msg.highlight')).toContainText('searchable')
  await ax('search-highlight')
})

test('200 percent zoom reflow, reduced motion and keyboard view menu', async () => {
  await launch()
  await send('slow reflow keyboard')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expect(page.locator('.spinner')).toBeVisible()
  expect(await page.locator('.spinner').evaluate((el) => getComputedStyle(el).animationName)).toBe('none')
  await nativeKey('ctrl+0', 'Odin')
  await nativeKey('ctrl+plus', 'Odin')
  await expect.poll(async () => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.webContents.getZoomFactor())).toBeGreaterThan(1)
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.webContents.setZoomFactor(2))
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await audit('zoom-chat')
  const zoomChat = join(appDir, 'test-results/zoom-chat-200.png')
  execFileSync('import', ['-window', 'root', zoomChat])
  await test.info().attach('zoom-chat-200', { path: zoomChat, contentType: 'image/png' })
  await page.keyboard.press('Control+,')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await audit('zoom-settings')
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.webContents.setZoomFactor(4))
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await audit('zoom-settings-400')
  await tabTo(page.locator('.settings-body'))
  expect(await page.locator('.settings-body').evaluate((el) => el.clientHeight)).toBeGreaterThan(25)
  await tabTo(page.locator('.statusbar'))
  const zoomSettings = join(appDir, 'test-results/zoom-settings-400.png')
  execFileSync('import', ['-window', 'root', zoomSettings])
  await test.info().attach('zoom-settings-400', { path: zoomSettings, contentType: 'image/png' })
  await activate(page.getByRole('button', { name: /Back to chat/ }))
  await nativeKey('ctrl+0', 'Odin')
  await expect.poll(async () => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.webContents.getZoomFactor())).toBe(1)
})

test('real core keyboard status usage and every real settings or unavailable service panel', async () => {
  await launch(true)
  const skillCode = readFileSync(join(appDir, 'test/harmless-skill.py'), 'utf8')
  const saved = await page.evaluate(async (code) => (window as any).odin.skillsSave({ name: 'slice4_constant', code, create: true }), skillCode)
  expect(saved.ok).toBe(true)
  await send('/status')
  await expect(page.getByRole('region', { name: 'Status', exact: true }).locator('.panel-text')).toContainText('Odin v0.1.0.dev1')
  await send('/usage')
  await expect(page.getByRole('region', { name: 'Usage, 7d', exact: true }).locator('.panel-text')).toContainText('history unavailable (usage history not enabled)')
  await expect(page.locator('.statusbar')).not.toContainText('Usage is unavailable in this core')
  await audit('real-core-chat')
  expect(await ax('real-core-chat')).not.toContain('Echo:')
  await page.keyboard.press('Control+,')
  const nav = page.getByRole('navigation', { name: 'Settings sections' })
  // Schema loading adds Other. Do not race enumeration and silently omit its accessibility audit.
  await expect(nav.getByRole('button', { name: 'Other', exact: true })).toBeVisible()
  const labels = await nav.locator('.settings-nav-item').allTextContents()
  expect(labels).toHaveLength(11)
  for (const label of labels) {
    // Real Tools has the full catalog, potentially hundreds of controls. Walk
    // backwards from its first status control to the settings navigation rather
    // than treating a >200-tab forward circuit as proof of inaccessible nav.
    const section = nav.getByRole('button', { name: label, exact: true })
    await tabTo(section, label === 'Skills')
    await page.keyboard.press('Enter')
    await expect(page.locator('.settings-body')).toContainText(label)
    await page.waitForTimeout(200)
    if (label === 'Skills') {
      const panel = page.getByRole('region', { name: 'Skills', exact: true })
      await expect(panel).toContainText('slice4_constant')
      await expect(panel).not.toContainText('Skills is unavailable in this core')
      await activate(panel.getByRole('button', { name: 'Open slice4_constant', exact: true }))
      await tabTo(page.getByRole('textbox', { name: 'Skill code', exact: true }))
      await expect(panel).not.toContainText('Test is unavailable in this core.')
      const editor = page.getByRole('region', { name: 'Skill editor', exact: true })
      const testSkill = editor.getByRole('button', { name: 'Test slice4_constant', exact: true })
      await expect(testSkill).toBeEnabled()
      await activate(testSkill)
      await expect(editor.locator('.manage-json')).toHaveText('harmless constant')
      await expect(editor.locator('.manage-json')).not.toHaveClass(/warn/)
      await expect(panel.locator('.manage-count')).toHaveText('1 runs')
    }
    if (label === 'MCP servers') {
      const panel = page.getByRole('region', { name: 'MCP servers', exact: true })
      await expect(panel.locator('.manage-row')).toHaveCount(0)
      await expect(panel).not.toContainText('MCP is unavailable in this core')
      await activate(panel.getByRole('button', { name: 'Add server', exact: true }))
      await tabTo(page.getByRole('textbox', { name: 'Executable', exact: true }))
    }
    if (label === 'Tools') {
      // D17 fresh settings enable the browser; this source-tree profile has no qualified bundle.
      const browser = page.getByRole('region', { name: 'Browser runtime', exact: true })
      await expect(browser).toContainText('State: unavailable')
      await expect(browser).toContainText('Not ready')
      await activate(browser.getByRole('button', { name: 'Refresh status for browser', exact: true }))
      await expect(browser).toContainText('State: unavailable')
    }
    if (label === 'Records') {
      const computer = page.getByRole('region', { name: 'Computer use', exact: true })
      await expect(computer).toContainText('No computer-use session is reported by this status')
      await expect(computer).toContainText('Native input is not qualified or supported')
      await expect(computer.getByRole('button', { name: 'Reconcile', exact: true })).toHaveCount(0)
      const usage = page.getByRole('region', { name: 'Usage', exact: true })
      await expect(usage.getByRole('combobox', { name: 'Period', exact: true })).toBeVisible()
      await expect(usage).toContainText('history unavailable (usage history not enabled)')
      await expect(usage).toContainText("not measured: Odin doesn't know this value")
      await expect(usage).not.toContainText('Usage is unavailable in this core')
    }
    if (label === 'Scheduled and running work') {
      await expect(page.getByRole('region', { name: 'Schedules', exact: true })).toContainText('No schedules yet.')
      await expect(page.getByRole('region', { name: 'Running work', exact: true })).toContainText('Nothing is running.')
      await expect(page.locator('.settings-body')).not.toContainText('Work (agents, tasks, loops, processes, workflows and schedules) is unavailable')
    }
    await audit(`real-${label}`)
    await ax(`real-${label}`)
  }
})

test('keyboard settings edits, field-associated errors, secrets and provider code AX privacy', async () => {
  await launch()
  await page.keyboard.press('Control+,')
  await tabTo(page.getByRole('checkbox', { name: 'Quiet hours', exact: true }))
  await page.keyboard.press('Space')
  await tabTo(page.getByLabel('Quiet hours start', { exact: true }))
  await tabTo(page.getByLabel('Quiet hours end', { exact: true }))
  await audit('quiet-hours')
  const quiet = JSON.parse(await ax('quiet-hours'))
  for (const name of ['Quiet hours start', 'Quiet hours end']) {
    expect(quiet.nodes.some((n: any) => !n.ignored && n.name?.value === name)).toBe(true)
  }

  await settingsSection('Tools')
  await activate(page.getByRole('button', { name: 'Parameters for read_file', exact: true }))
  await expect(page.locator('#tool-parameters-read_file')).toContainText('properties')
  const timeout = page.getByRole('spinbutton', { name: 'Default, in seconds', exact: true })
  await typeField(timeout, '0')
  await activate(page.getByRole('button', { name: 'Save timeouts', exact: true }))
  await expect(timeout).toHaveAttribute('aria-invalid', 'true')
  await expect(timeout).toHaveAttribute('aria-describedby', 'tool-timeout-error')
  const errors = JSON.parse(await ax('field-error'))
  expect(errors.nodes.some((n: any) => !n.ignored && n.description?.value?.includes('above zero'))).toBe(true)
  await audit('timeout-validation')
  await typeField(timeout, '301')
  await activate(page.getByRole('button', { name: 'Save timeouts', exact: true }))
  await expect(timeout).not.toHaveAttribute('aria-invalid', 'true')

  await settingsSection('Models and providers')
  const secret = page.locator('input[type="password"]').first()
  const sentinel = 'fixture-only-private-a11y-value'
  await typeField(secret, sentinel)
  expect(await ax('secret-editing')).not.toContain(sentinel)
  await activate(secret.locator('..').getByRole('button', { name: /^Save / }))
  await expect(secret).toHaveValue('')
  expect(await ax('secret-saved')).not.toContain(sentinel)
  await activate(page.getByRole('button', { name: 'Add account', exact: true }))
  await expect(page.locator('.login-code')).toBeVisible()
  const code = (await page.locator('.login-code').textContent())!
  expect(await ax('provider-code')).toContain(code)
  await activate(page.getByRole('button', { name: 'Copy sign-in code', exact: true }))
  await expect.poll(async () => app.evaluate(({ clipboard }) => clipboard.readText())).toBe(code)
  await audit('provider-code')
  await activate(page.getByRole('button', { name: 'Stop waiting', exact: true }))
  await expect(page.locator('.login-code')).toHaveCount(0)
  expect(await ax('provider-code-closed')).not.toContain(code)
})

test('keyboard management disclosures and editor forms are named and auditable', async () => {
  await launch()
  await page.keyboard.press('Control+,')
  await settingsSection('Skills')
  await activate(page.getByRole('button', { name: 'Open weather', exact: true }))
  await tabTo(page.getByRole('textbox', { name: 'Skill code', exact: true }))
  await audit('skill-editor')

  await settingsSection('MCP servers')
  await activate(page.getByRole('button', { name: 'Tools for LMMS', exact: true }))
  await expect(page.locator('.mcp-tools')).toContainText('create_track')
  await activate(page.getByRole('button', { name: 'Add server', exact: true }))
  await tabTo(page.getByRole('textbox', { name: 'Executable', exact: true }))
  await activate(page.getByRole('button', { name: 'Add a header', exact: true }))
  await tabTo(page.getByLabel('Header value 1', { exact: true }))
  await audit('mcp-editor')

  await settingsSection('Hosts and trust')
  await activate(page.getByRole('button', { name: 'Add host', exact: true }))
  await tabTo(page.getByRole('textbox', { name: 'Alias', exact: true }))
  await audit('host-enrollment')

  await settingsSection('Scheduled and running work')
  await activate(page.getByRole('button', { name: /^Edit schedule / }).first())
  await audit('schedule-editor')

  await settingsSection('State')
  await activate(page.getByRole('button', { name: 'Open Everywhere memory', exact: true }))
  await expect(page.getByRole('table', { name: 'Everywhere memory entries' })).toBeVisible()
  await audit('memory-disclosure')
  await settingsSection('Records')
  await tabTo(page.getByRole('searchbox', { name: 'Search the audit', exact: true }))
  await tabTo(page.getByRole('combobox', { name: 'Period', exact: true }))
  await tabTo(page.getByRole('searchbox', { name: 'Search the logs', exact: true }))
  await tabTo(page.getByRole('combobox', { name: 'Level', exact: true }))
  await audit('record-filters')
  await settingsSection('Personality')
  await tabTo(page.getByRole('combobox', { name: 'Preset', exact: true }))
  await tabTo(page.getByRole('textbox', { name: 'Name', exact: true }))
  await audit('personality-presets')
  await settingsSection('Other')
  await tabTo(page.locator('.settings-body'))
  await audit('other-settings')
})

test('real-shape service failure cards and readiness are accessible without claiming native input', async () => {
  // Explicit fixture AX lane; real lifecycle/redaction are independently proved
  // by the actual-core Broker suite, never by these displayed fixture strings.
  await launch(false, 'services-real-shape')
  await page.keyboard.press('Control+,')
  await settingsSection('Skills')
  const broken = page.getByRole('region', { name: 'Skills', exact: true }).locator('.manage-row').filter({ hasText: 'broken_sync' })
  await expect(broken).toContainText('Syntax error')
  await expect(broken.getByRole('button', { name: 'Test broken_sync', exact: true })).toBeDisabled()
  await audit('failed-skill-card')
  expect(await ax('failed-skill-card')).toContain('broken_sync')
  await settingsSection('MCP servers')
  const servers = page.getByRole('region', { name: 'MCP servers', exact: true })
  await expect(servers).toContainText('LMMS')
  await expect(servers).toContainText('Profile keyring is unavailable or locked')
  await tabTo(servers.getByRole('button', { name: 'Reconnect locked-local', exact: true }))
  await audit('per-server-keyring-reason')
  expect(await ax('per-server-keyring-reason')).toContain('Profile keyring is unavailable or locked')
  await settingsSection('Tools')
  const browser = page.getByRole('region', { name: 'Browser runtime', exact: true })
  await expect(browser).toContainText('State: unavailable')
  await expect(browser).toContainText('Not ready')
  await expect(browser).toContainText(/next .*use|next-use/i)
  await audit('browser-next-use-unavailable')
  await settingsSection('Records')
  const computer = page.getByRole('region', { name: 'Computer use', exact: true })
  await expect(computer).toContainText('No computer-use session is reported by this status')
  await expect(computer).toContainText('Native input is not qualified or supported')
  await expect(computer.getByRole('button', { name: 'Reconcile', exact: true })).toHaveCount(0)
  await audit('computer-unqualified-envelope')
  expect(await ax('computer-unqualified-envelope')).toContain('Native input is not qualified or supported')
})

test('work panel keyboard controls, focus return and target names', async () => {
  await launch()
  await send('slow agent process keyboard work')
  await expect(page.locator('.working')).toBeVisible()
  const workButton = page.locator('.work-toggle')
  await activate(workButton)
  await expect(page.getByRole('button', { name: 'Refresh work', exact: true })).toBeFocused()
  await audit('work-open')
  await activate(page.getByRole('button', { name: 'Stop process: tail -f build.log', exact: true }))
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await activate(page.getByRole('button', { name: 'Stop agent: Research agent', exact: true }))
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await ax('work-stopped')
  await page.keyboard.press('Escape')
  await expect(workButton).toBeFocused()
  await expect(page.locator('.work-panel')).toHaveCount(0)
  await page.keyboard.press('Control+,')
  await settingsSection('Scheduled and running work')
  const openConversation = page.locator('.settings-body .work-link').first()
  await activate(openConversation)
  await expect(page.getByRole('region', { name: 'Conversation history', exact: true })).toBeFocused()
  await expect(page.locator('.work-panel')).toHaveCount(0)
})

test('keyboard and accessibility tree preserve unknown work settlement and steer boundaries', async () => {
  await launch(false, 'work-settlement')
  await activate(page.locator('.work-toggle'))
  const row = page.locator('.work-item').filter({ hasText: 'Unknown release audit' })
  await expect(row).toContainText('Settlement')
  await expect(row).toContainText('unknown')
  await expect(row).toContainText('unproven')
  await expect(row).toContainText('Resource release is not confirmed')
  await audit('work-unknown-settlement')
  const tree = await ax('work-unknown-settlement')
  expect(tree).toContain('Work settlement')
  expect(tree).toContain('Resource release')
  const steer = row.getByRole('button', { name: 'Steer agent: Unknown release audit', exact: true })
  await activate(steer)
  const input = row.getByRole('textbox', { name: 'Steer agent: Unknown release audit', exact: true })
  await expect(input).toBeFocused()
  await page.keyboard.insertText('Do not infer that resources were released.')
  await expect(input).toHaveValue('Do not infer that resources were released.')
  await expect(row.getByRole('button', { name: 'Send steer to agent: Unknown release audit', exact: true })).toHaveAttribute('aria-disabled', 'false')
  await audit('work-steer-form')
  const steerTree = await ax('work-steer-form')
  expect(steerTree).toContain('Queued is not consumed')
  expect(steerTree).toContain('Unknown outcomes are not retried')
})

test('rejected assistant drafts never enter DOM or real AX tree, structural announcements remain quiet', async () => {
  await launch(false, 'privacy')
  await page.evaluate(() => {
    (window as any).a11yAnnouncements = []
    new MutationObserver(() => (window as any).a11yAnnouncements.push(document.querySelector('.chat-announcement')?.textContent))
      .observe(document.querySelector('.chat-announcement')!, { childList: true, subtree: true, characterData: true })
  })
  await send('slow privacy keyboard task')
  await expect(page.locator('.working')).toBeVisible()
  expect(await page.locator('body').textContent()).not.toContain('UNPUBLISHED_REJECTED_A11Y_DRAFT')
  expect(await ax('rejected-draft-working')).not.toContain('UNPUBLISHED_REJECTED_A11Y_DRAFT')
  await send('private steer content')
  await expect(page.locator('.steer-state')).toContainText('Odin has read it')
  await activate(page.getByRole('button', { name: 'Stop the current task', exact: true }))
  await expect(page.locator('.working')).toHaveCount(0)
  await send('committed privacy keyboard result')
  await expect(page.locator('.msg.assistant')).toContainText('committed privacy keyboard result')
  const tree = await ax('privacy-completed')
  expect(tree).not.toContain('UNPUBLISHED_REJECTED_A11Y_DRAFT')
  expect(tree).toContain('committed privacy keyboard result')
  const announcements = await page.evaluate(() => (window as any).a11yAnnouncements as string[])
  expect(announcements.join('\n')).toContain('Odin is working')
  expect(announcements.join('\n')).toContain('Odin has read the steer')
  expect(announcements.join('\n')).toContain('Task completed')
  expect(announcements.join('\n')).not.toContain('private steer content')
  expect(announcements.join('\n')).not.toContain('echo')
  await test.info().attach('structural-announcements', { body: JSON.stringify(announcements), contentType: 'application/json' })
})

test('delayed history pagination and search retain focused controls and the current message', async () => {
  await launch(false, 'history')
  await expect(page.locator('.msg.assistant')).not.toHaveCount(0)
  const older = page.getByRole('button', { name: 'Load older messages', exact: true })
  await activate(older)
  const olderButton = page.locator('.older button')
  await expect(olderButton).toHaveAttribute('aria-disabled', 'true')
  await expect(olderButton).toBeFocused()
  await expect(page.locator('.msg.assistant')).toHaveCount(130)
  await expect(olderButton).toBeFocused()
  const historyTree = await ax('all-history-offscreen')
  expect(historyTree).toContain('History anchor 0')
  expect(historyTree).toContain('History anchor 129')
  await page.keyboard.press('Control+Shift+f')
  const search = page.getByRole('searchbox', { name: 'Search all conversations', exact: true })
  await expect(search).toBeFocused()
  await page.keyboard.insertText('History anchor 110')
  await page.keyboard.press('Enter')
  await expect(page.locator('.hit')).toHaveCount(1)
  await activate(page.locator('.hit'))
  await expect(page.locator('#m-history-110')).toBeFocused()
  await tabTo(search)
  await page.keyboard.press('Enter')
  await expect(page.locator('.search-note').first()).toContainText('Searching')
  await expect(page.locator('#m-history-110')).toBeVisible()
  await expect(search).toBeFocused()
  expect(await ax('delayed-search')).toContain('History anchor 110')
  await audit('history-search-loading')
})

test('keyboard command suggestions and retained tool output', async () => {
  await launch()
  const box = page.getByRole('textbox', { name: 'Message', exact: true })
  await typeField(box, '/')
  await page.keyboard.press('End')
  await expect(box).toHaveAttribute('aria-activedescendant', /command-option-/)
  await page.keyboard.press('Home')
  await page.keyboard.press('ArrowDown')
  await audit('command-palette')
  const palette = await ax('command-palette')
  expect(palette).toContain('listbox')
  await page.keyboard.press('Escape')
  await expect(box).toHaveValue('/')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await typeField(box, '/sta')
  await page.keyboard.press('Tab')
  await expect(box).toHaveValue('/status ')
  await page.keyboard.press('Tab')
  await expect(box).not.toBeFocused()
  await tabTo(box)
  await page.keyboard.press('Shift+Tab')
  await expect(box).not.toBeFocused()
  await send('keyboard tool output detail')
  await expect(page.locator('.msg.assistant')).toContainText('keyboard tool output detail')
  await activate(page.locator('.msg.assistant .tools-toggle'))
  await activate(page.locator('.msg.assistant .tool-row'))
  await expect(page.locator('.tool-detail')).toContainText('Arguments')
  await audit('tool-detail')
  await activate(page.getByRole('button', { name: 'Show full output for echo', exact: true }))
  await expect(page.locator('.tool-detail')).toContainText('Full output')
  await audit('tool-output')
})

test('search final paging and replaced focused hit keep owned focus', async () => {
  await launch(false, 'history')
  await page.keyboard.press('Control+Shift+f')
  const search = page.getByRole('searchbox', { name: 'Search all conversations', exact: true })
  await page.keyboard.insertText('History anchor 1')
  await page.keyboard.press('Enter')
  await expect(page.locator('.hit')).toHaveCount(20)
  await activate(page.getByRole('button', { name: 'More results', exact: true }))
  await expect(page.locator('.hit')).toHaveCount(40)
  await activate(page.getByRole('button', { name: 'More results', exact: true }))
  await expect(page.getByRole('button', { name: 'More results', exact: true })).toHaveCount(0)
  await expect(page.locator('.hit').nth(40)).toBeFocused()
  // Start a replacement, then navigate to the old hit before the delayed response. No scripted focus.
  await tabTo(search, true)
  await page.keyboard.press('Control+a')
  await page.keyboard.insertText('History anchor 0')
  await page.keyboard.press('Enter')
  await tabTo(page.locator('.hit').first())
  await expect(page.locator('.hit')).toHaveCount(1)
  await expect(search).toBeFocused()
  await audit('replaced-search-result')
})
