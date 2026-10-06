import { test, expect, _electron as electron, type ElectronApplication, type Page, type Locator } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { join, resolve } from 'node:path'
import { OrcaSpeech, occurrences, speechRecords } from './orca-speech'

// Separate VM lane. Part 1's host-isolation guards remain unchanged.
const appDir = resolve(__dirname, '../..')
const guest = join(__dirname, 'orca-guest.py')
const secret = 'fixture-only-private-orca-value'
const rejected = 'UNPUBLISHED_REJECTED_A11Y_DRAFT'
let app: ElectronApplication | undefined
let page: Page
let root: string
let speech: OrcaSpeech | undefined
let start: number
let launchEvidence: unknown

function guard(): unknown {
  return JSON.parse(execFileSync('/usr/bin/python3', ['-B', guest, 'guard'], { encoding: 'utf8' }))
}

test.beforeEach(() => {
  guard()
  speech = new OrcaSpeech(process.env.ODIN_ORCA_LOG!)
  start = speech.mark()
  app = undefined
})

test.afterEach(async () => {
  if (!speech) return
  try {
    if (app) {
      // Native full-screen capture is independent evidence, not a substitute for speech.
      const capture = join(process.env.ODIN_ORCA_EVIDENCE!, `guest-${test.info().title.replace(/[^a-z0-9-]/g, '-')}.png`)
      const child = app.process()
      try {
        execFileSync('/usr/local/lib/odq/capture', [capture], { timeout: 75_000 })
        await test.info().attach('guest-desktop', { path: capture, contentType: 'image/png' })
      } finally { await app.close() }
      await expect.poll(() => child.exitCode !== null || child.signalCode !== null).toBe(true)
    }
    const records = speechRecords(speech.read(start))
    await test.info().attach('orca-speech-output', { body: JSON.stringify(records, null, 2), contentType: 'application/json' })
    await test.info().attach('guest-launch', { body: JSON.stringify({ guard: guard(), launch: launchEvidence }), contentType: 'application/json' })
    expect(records.map((r) => r.text).join('\n')).not.toContain(secret)
    expect(records.map((r) => r.text).join('\n')).not.toContain(rejected)
  } finally {
    speech.close()
    speech = undefined
    if (root) rmSync(root, { recursive: true, force: true })
  }
})

async function launch(scenario = 'privacy', real = false): Promise<void> {
  // Measured focused-probe behavior, including GNOME's startup overview.
  execFileSync('/usr/bin/python3', ['-B', join(process.env.ODIN_ORCA_ROOT!,
    'scripts/qualification/lab/guest/focused_probe.py'), 'key', 'Escape'], { timeout: 15_000 })
  root = join(process.env.ODIN_ORCA_ROOT!, `task-${randomUUID()}`)
  mkdirSync(root, { mode: 0o700 })
  for (const name of ['config', 'data', 'cache']) mkdirSync(join(root, name), { mode: 0o700 })
  const keep = ['PATH', 'LANG', 'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR', 'CHROME_DEVEL_SANDBOX',
    'DBUS_SESSION_BUS_ADDRESS', 'XDG_SESSION_ID', 'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP',
    'AT_SPI_BUS_ADDRESS', 'SPEECHD_ADDRESS']
  const env: Record<string, string> = {}
  for (const [key, value] of Object.entries(process.env)) {
    if (value && (keep.includes(key) || key.startsWith('ODIN_ORCA_'))) env[key] = value
  }
  Object.assign(env, { HOME: root, USER: 'odq', LOGNAME: 'odq', LANG: 'C.UTF-8',
    XDG_CONFIG_HOME: join(root, 'config'), XDG_DATA_HOME: join(root, 'data'), XDG_CACHE_HOME: join(root, 'cache'),
    PYTHONDONTWRITEBYTECODE: '1', PYTHONNOUSERSITE: '1', ACCESSIBILITY_ENABLED: '1',
    NO_AT_BRIDGE: '0', GTK_A11Y: 'always', GTK_MODULES: 'gail:atk-bridge' })
  env.ODIN_DESKTOP_CORE_CMD = real ? process.env.ODIN_ORCA_REAL_CORE_CMD!
    : JSON.stringify(['/usr/bin/python3', '-B', join(__dirname, 'accessibility-core.py'), scenario])
  const platform = process.env.ODIN_ORCA_DESKTOP === 'cinnamon' ? 'x11' : 'wayland'
  app = await electron.launch({ executablePath: process.env.ODIN_ORCA_ELECTRON ?? require('electron'), cwd: appDir, env,
    args: [appDir, '--force-renderer-accessibility', `--ozone-platform=${platform}`], chromiumSandbox: true })
  page = await app.firstWindow()
  await expect(page.locator('.link.ready')).toContainText('Connected')
  launchEvidence = await app.evaluate(({ BrowserWindow }) => {
    const window = BrowserWindow.getAllWindows()[0]!
    window.show()
    window.focus()
    const contents = window.webContents as unknown as {
      getLastWebPreferences: () => { sandbox: boolean; contextIsolation: boolean; nodeIntegration: boolean }
    }
    const prefs = contents.getLastWebPreferences()
    return { sandbox: prefs.sandbox, contextIsolation: prefs.contextIsolation,
      nodeIntegration: prefs.nodeIntegration, visible: window.isVisible(), focused: window.isFocused(),
      minimized: window.isMinimized(), arguments: process.argv, versions: process.versions }
  })
  expect(launchEvidence).toMatchObject({ sandbox: true, contextIsolation: true, nodeIntegration: false,
    visible: true, minimized: false })
  // Wayland focus requests are asynchronous. Verify the native frame as the
  // passing focused probe does, not an immediate isFocused snapshot.
  execFileSync('/usr/bin/python3', ['-B', join(process.env.ODIN_ORCA_ROOT!,
    'scripts/qualification/lab/guest/focused_probe.py'), 'key', 'Escape'], { timeout: 15_000 })
  await expect.poll(() => {
    const tree = JSON.parse(execFileSync('/usr/bin/python3', ['-B', join(process.env.ODIN_ORCA_ROOT!,
      'scripts/qualification/lab/guest/focused_probe.py'), 'snapshot'], { encoding: 'utf8', timeout: 30_000 }))
    return tree.nodes.some((node: { name: string; states?: string[] }) => node.name === 'Odin'
      && node.states?.includes('SHOWING') && node.states?.includes('ACTIVE'))
  }, { timeout: 30_000 }).toBe(true)
  expect(JSON.stringify(launchEvidence)).not.toContain('--no-sandbox')
}

async function hear(from: number, ...patterns: RegExp[]): Promise<string> {
  try {
    await expect.poll(() => patterns.every((p) => p.test(speech!.text(from))), {
      message: `Actual Orca SPEECH OUTPUT must contain ${patterns.join(', ')}`
    }).toBe(true)
  } catch (error) {
    await test.info().attach('failed-speech-window', { body: JSON.stringify({ from,
      patterns: patterns.map(String), records: speechRecords(speech!.read(from)) }), contentType: 'application/json' })
    throw error
  }
  const result = speech!.text(from)
  await test.info().attach(`speech-assertion-${test.info().attachments.length}`, {
    body: JSON.stringify({ patterns: patterns.map(String), records: speechRecords(speech!.read(from)) }), contentType: 'application/json'
  })
  return result
}

async function press(key: string): Promise<void> {
  await page.keyboard.press(key)
  await page.waitForTimeout(100)
}

async function tabTo(target: Locator, name?: RegExp, role?: RegExp, state?: RegExp): Promise<void> {
  await expect(target).toBeVisible()
  const from = speech!.mark()
  if (await target.evaluate((el) => el === document.activeElement)) {
    await press('Shift+Tab')
    await page.waitForTimeout(350)
  }
  for (let n = 0; n < 200; n++) {
    if (await target.evaluate((el) => el === document.activeElement)) {
      if (name) await hear(from, name, ...(role ? [role] : []), ...(state ? [state] : []))
      return
    }
    const reverse = await target.evaluate((el) => Boolean(el.compareDocumentPosition(document.activeElement!) & Node.DOCUMENT_POSITION_FOLLOWING))
    await press(reverse ? 'Shift+Tab' : 'Tab')
    await page.waitForTimeout(250)
  }
  throw new Error(`Not keyboard reachable: ${await target.getAttribute('aria-label') ?? await target.textContent()}`)
}

async function activate(target: Locator, name?: RegExp, role = /(?:push )?button/i): Promise<void> {
  await tabTo(target, name, role)
  await press('Enter')
}

async function send(text: string): Promise<void> {
  await tabTo(page.getByRole('textbox', { name: 'Message', exact: true }), /Message/i, /(?:entry|text)/i)
  await press('Control+a')
  await page.keyboard.insertText(text)
  await press('Enter')
}

async function native(title: string, action: 'cancel' | 'file' | 'describe', path?: string): Promise<void> {
  let lookup = ''
  // Poll observation ONLY. No error after typing or submission can replay input.
  await expect.poll(() => {
    try {
      execFileSync('/usr/bin/python3', ['-B', guest, 'native', title, 'describe'],
        { encoding: 'utf8', timeout: 30_000 })
      return true
    } catch (error) {
      const output = (error as { stdout?: string }).stdout ?? String(error)
      if (output.includes('No owned active AT-SPI dialog')) { lookup = output; return false }
      throw new Error(`Native dialog observation failed: ${output}`)
    }
  }, { message: `Owned active native dialog required: ${title}` }).toBe(true).catch((error) => {
    throw new Error(`${error}\nLast AT-SPI lookup: ${lookup}`)
  })
  if (action !== 'describe') {
    execFileSync('/usr/bin/python3', ['-B', guest, 'native', title, action, ...(path ? [path] : [])],
      { encoding: 'utf8', timeout: 30_000 })
  }
}

async function section(name: string): Promise<void> {
  await activate(page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name, exact: true }),
    new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'))
  await expect(page.locator('.settings-body')).toContainText(name)
}

test('orca-bridge-named-message-and-native-button-role', async () => {
  await launch()
  await tabTo(page.getByRole('textbox', { name: 'Message', exact: true }), /Message/i, /entry|text/i)
  await tabTo(page.getByRole('button', { name: 'Attach files', exact: true }), /Attach files/i, /button/i)
})

test('orca-chat-results-attach-cancel-save-copy-report', async () => {
  await launch()
  await activate(page.getByRole('button', { name: 'New conversation', exact: true }), /New conversation/i)
  const completed = speech!.mark()
  await send('file report script keyboard result\n```text\nkeyboard-code\n```')
  await expect(page.locator('.msg.assistant')).toContainText('keyboard result')
  await hear(completed, /Task completed/i)
  await activate(page.locator('.msg.assistant').getByRole('button', { name: /^Copy Odin message/ }), /Copy Odin message/i)
  await activate(page.locator('.msg.assistant').getByRole('button', { name: 'Copy as Markdown', exact: true }), /Copy as Markdown/i)
  await expect.poll(() => app!.evaluate(({ clipboard }) => clipboard.readText())).toContain('keyboard result')
  await activate(page.locator('.msg.assistant .code-copy').first(), /Copy/i)
  await expect.poll(() => app!.evaluate(({ clipboard }) => clipboard.readText())).toContain('keyboard-code')
  await activate(page.locator('.report').getByRole('button', { name: 'Next page of Health report', exact: true }), /Next page of Health report/i)
  await expect(page.locator('.report')).toContainText('Page 2')
  await activate(page.locator('.report').getByRole('button', { name: 'Previous page of Health report', exact: true }), /Previous page of Health report/i)
  await expect(page.locator('.report')).toContainText('Page 1')
  await activate(page.locator('.report').getByRole('button', { name: 'Copy page of Health report', exact: true }), /Copy page of Health report/i)
  await expect.poll(() => app!.evaluate(({ clipboard }) => clipboard.readText())).toContain('Stored result, page 1 of 3')
  let from = speech!.mark()
  await activate(page.getByRole('button', { name: 'Attach files', exact: true }), /Attach files/i)
  await native('Attach files', 'describe')
  await hear(from, /Attach files/i, /table|file chooser|dialog/i)
  await native('Attach files', 'cancel')
  await expect(page.locator('.attachments')).toHaveCount(0)
  const chosen = join(root, 'keyboard-attachment.txt')
  writeFileSync(chosen, 'keyboard-only attachment\n')
  await activate(page.getByRole('button', { name: 'Attach files', exact: true }), /Attach files/i)
  await native('Attach files', 'file', chosen)
  await expect(page.locator('.attachment')).toContainText('keyboard-attachment.txt')
  await activate(page.locator('.attachment').getByRole('button', { name: /Remove/ }), /Remove/i)
  await expect(page.locator('.attachments')).toHaveCount(0)
  const saved = join(root, 'keyboard-saved.txt')
  from = speech!.mark()
  await activate(page.locator('.file-card').filter({ hasText: 'notes.txt' }).getByRole('button', { name: /Save/ }), /Save/i)
  await native('Save file', 'describe')
  await hear(from, /Save file/i, /entry|table|file chooser|dialog/i)
  await native('Save file', 'file', saved)
  await expect.poll(() => existsSync(saved)).toBe(true)
  expect(readFileSync(saved, 'utf8')).toContain('Generated notes')
})

test('orca-conversation-child-modal-search', async () => {
  await launch()
  await activate(page.getByRole('button', { name: 'New conversation', exact: true }), /New conversation/i)
  const opener = page.getByRole('button', { name: /Actions for/ }).last()
  let from = speech!.mark()
  await activate(opener, /Actions for/i)
  await hear(from, /Rename/i, /menu/i)
  await press('Enter')
  await expect(page.getByRole('dialog', { name: 'Rename conversation' })).toBeVisible()
  await hear(from, /Rename conversation/i, /dialog/i, /Title/i, /entry|text/i)
  await press('Escape')
  await expect(opener).toBeFocused()
  from = speech!.mark()
  await press('Enter')
  await hear(from, /menu/i, /Rename/i)
  from = speech!.mark()
  await press('ArrowDown')
  await hear(from, /New thread from here/i)
  await press('Enter')
  await expect(page.locator('.inherited')).toContainText('continued from')
  await activate(page.getByRole('button', { name: 'Open the original', exact: true }), /Open the original/i)
  await expect(page.locator('.inherited')).toHaveCount(0)
  await send('searchable keyboard anchor')
  await expect(page.locator('.msg.assistant')).toContainText('searchable keyboard anchor')
  from = speech!.mark()
  await press('Control+Shift+f')
  const search = page.getByRole('searchbox', { name: 'Search all conversations', exact: true })
  await expect(search).toBeFocused()
  await hear(from, /Search all conversations/i, /entry|text/i)
  await page.keyboard.insertText('searchable')
  await press('Enter')
  await expect(page.locator('.search-hits .hit')).toHaveCount(2)
  await activate(page.locator('.search-hits .hit').first(), /searchable keyboard anchor/i)
  await expect(page.locator('.msg.highlight')).toContainText('searchable')
})

test('orca-busy-steer-consumed-queued-stop-resume-unknown-no-flood', async () => {
  await launch()
  const from = speech!.mark()
  await send('slow privacy keyboard task')
  await expect(page.locator('.working')).toBeVisible()
  await hear(from, /Odin is working/i)
  // Stay on the already-qualified entry so navigating to it cannot consume the
  // fixture's running window before steering. Native speech is still asserted.
  const consumed = speech!.mark()
  await page.keyboard.insertText('private steer content')
  await press('Enter')
  await expect(page.locator('.steer-state')).toContainText('Odin has read it')
  await hear(consumed, /Odin has read the steer/i)
  const queue = page.getByRole('radio', { name: 'Queue as a follow-up' })
  await tabTo(page.getByRole('radio', { name: 'Steer the current task' }), /Steer the current task/i, /radio button/i, /(?<!not )(?:selected|checked)/i)
  const queued = speech!.mark()
  await press('ArrowRight')
  await expect(queue).toBeChecked()
  await hear(queued, /Queue as a follow-up/i, /radio button/i, /(?<!not )(?:selected|checked)/i)
  await tabTo(page.getByRole('textbox', { name: 'Message', exact: true }), /Message/i, /entry|text/i)
  await page.keyboard.insertText('queued keyboard follow up')
  await press('Enter')
  await expect(page.locator('.queued')).toBeVisible()
  await hear(queued, /1 follow-up queued/i)
  await activate(page.getByRole('button', { name: 'Stop the current task', exact: true }), /Stop the current task/i)
  await expect(page.locator('.msg.assistant').last()).toContainText('queued keyboard follow up')
  await expect(page.locator('.working')).toHaveCount(0)
  await hear(from, /Task completed/i)
  await send('interrupt keyboard task')
  await expect(page.locator('.resume-banner')).toBeVisible()
  await activate(page.locator('.resume-banner').getByRole('button', { name: /Resume/ }), /Resume/i)
  await expect(page.locator('.resume-banner')).toHaveCount(0)
  await expect(page.locator('.msg.assistant').last()).toContainText('interrupt keyboard task')
  const unknown = speech!.mark()
  await send('unknown keyboard effect')
  await expect(page.locator('.resume-banner')).toContainText('reconciled')
  await hear(unknown, /An action has an unknown outcome/i, /It will not be repeated/i)
  const idle = speech!.mark()
  await page.waitForTimeout(2000)
  expect(speech!.text(idle)).not.toMatch(/Odin is working|Task completed|follow-up queued|has read the steer|unknown outcome/i)
  const text = speech!.text(from)
  for (const phrase of ['Odin has read the steer.', '1 follow-up queued.', 'An action has an unknown outcome.']) {
    expect(occurrences(text, phrase), `No repeated structural announcement: ${phrase}`).toBe(1)
  }
  expect(occurrences(text, 'Odin is working.')).toBeLessThanOrEqual(6)
  expect(occurrences(text, 'Task completed.')).toBeLessThanOrEqual(3)
  const structural = speechRecords(speech!.read(from)).filter((r) => /Odin has read the steer|follow-up queued|An action has an unknown outcome/.test(r.text))
  expect(structural.map((r) => r.text).join('\n')).not.toContain('private steer content')
})

test('orca-all-eleven-settings-names-roles-states-errors-secret', async () => {
  await launch()
  await press('Control+,')
  const names = ['General', 'Models and providers', 'Tools', 'Skills', 'MCP servers', 'Hosts and trust',
    'Scheduled and running work', 'State', 'Records', 'Personality', 'Other']
  const nav = page.getByRole('navigation', { name: 'Settings sections' })
  await expect(nav.getByRole('button', { name: 'Other', exact: true })).toBeVisible()
  expect((await nav.locator('.settings-nav-item').allTextContents()).map((s) => s.trim()).sort()).toEqual([...names].sort())
  for (const name of names) await section(name)
  await section('General')
  const quiet = page.getByRole('checkbox', { name: 'Quiet hours', exact: true })
  await tabTo(quiet, /Quiet hours/i, /check box|checkbox/i, /not checked|unchecked/i)
  const changed = speech!.mark()
  await press('Space')
  await expect(quiet).toBeChecked()
  await hear(changed, /(?<!not )checked/i)
  await tabTo(page.getByLabel('Quiet hours start', { exact: true }), /Quiet hours start/i)
  await tabTo(page.getByLabel('Quiet hours end', { exact: true }), /Quiet hours end/i)
  await section('Tools')
  await activate(page.getByRole('button', { name: 'Parameters for read_file', exact: true }), /Parameters for read_file/i)
  const timeout = page.getByRole('spinbutton', { name: 'Default, in seconds', exact: true })
  await tabTo(timeout, /Default, in seconds/i, /spin button/i)
  await press('Control+a')
  await page.keyboard.insertText('0')
  const invalid = speech!.mark()
  await activate(page.getByRole('button', { name: 'Save timeouts', exact: true }), /Save timeouts/i)
  await expect(timeout).toHaveAttribute('aria-invalid', 'true')
  await tabTo(timeout, /Default, in seconds/i, /spin button/i, /invalid/i)
  await hear(invalid, /above zero/i)
  await section('Models and providers')
  const password = page.locator('input[type="password"]').first()
  await tabTo(password, /key|token/i, /password/i)
  await page.keyboard.insertText(secret)
  await activate(password.locator('..').getByRole('button', { name: /^Save / }), /Save/i)
  await expect(password).toHaveValue('')
  await section('Skills')
  await activate(page.getByRole('button', { name: 'Open weather', exact: true }), /Open weather/i)
  await tabTo(page.getByRole('textbox', { name: 'Skill code', exact: true }), /Skill code/i, /entry|text/i)
  await section('MCP servers')
  await activate(page.getByRole('button', { name: 'Add server', exact: true }), /Add server/i)
  await tabTo(page.getByRole('textbox', { name: 'Executable', exact: true }), /Executable/i, /entry|text/i)
  await section('Hosts and trust')
  await activate(page.getByRole('button', { name: 'Add host', exact: true }), /Add host/i)
  await tabTo(page.getByRole('textbox', { name: 'Alias', exact: true }), /Alias/i, /entry|text/i)
  await section('Scheduled and running work')
  await activate(page.getByRole('button', { name: /^Edit schedule / }).first(), /Edit schedule/i)
  await section('State')
  await activate(page.getByRole('button', { name: 'Open Everywhere memory', exact: true }), /Open Everywhere memory/i)
  await expect(page.getByRole('table', { name: 'Everywhere memory entries' })).toBeVisible()
  await section('Records')
  await tabTo(page.getByRole('searchbox', { name: 'Search the audit', exact: true }), /Search the audit/i, /entry|text/i)
  await tabTo(page.getByRole('combobox', { name: 'Period', exact: true }), /Period/i, /combo box/i)
  await tabTo(page.getByRole('searchbox', { name: 'Search the logs', exact: true }), /Search the logs/i, /entry|text/i)
  await tabTo(page.getByRole('combobox', { name: 'Level', exact: true }), /Level/i, /combo box/i)
  await section('Personality')
  await tabTo(page.getByRole('combobox', { name: 'Preset', exact: true }), /Preset/i, /combo box/i)
  await tabTo(page.getByRole('textbox', { name: 'Name', exact: true }), /Name/i, /entry|text/i)
  await section('Other')
})

test('orca-delayed-history-search-retains-focused-current-message', async () => {
  await launch('history')
  await expect(page.locator('.msg.assistant')).not.toHaveCount(0)
  await activate(page.getByRole('button', { name: 'Load older messages', exact: true }), /Load older messages/i)
  await expect(page.locator('.older button')).toBeFocused()
  await expect(page.locator('.msg.assistant')).toHaveCount(130)
  await press('Control+Shift+f')
  await tabTo(page.getByRole('searchbox', { name: 'Search all conversations', exact: true }), /Search all conversations/i, /entry|text/i)
  await page.keyboard.insertText('History anchor 110')
  await press('Enter')
  await expect(page.locator('.hit')).toHaveCount(1)
  await activate(page.locator('.hit'), /History anchor 110/i)
  await expect(page.locator('#m-history-110')).toBeFocused()
})

test('orca-real-core-services-when-explicitly-provisioned', async () => {
  if (process.env.ODIN_ORCA_REAL_CORE_REQUIRED === '1') expect(process.env.ODIN_ORCA_REAL_CORE_CMD).toBeTruthy()
  test.skip(!process.env.ODIN_ORCA_REAL_CORE_CMD, 'Guest real-core services not provisioned; fixture qualification is separate')
  await launch('privacy', true)
  const from = speech!.mark()
  await send('/status')
  await expect(page.getByRole('region', { name: 'Status', exact: true }).locator('.panel-text')).toContainText('Odin')
  await hear(from, /Status report ready/i)
  const usage = speech!.mark()
  await send('/usage')
  await expect(page.getByRole('region', { name: 'Usage, 7d', exact: true })).toBeVisible()
  await hear(usage, /Usage, 7d report ready/i)
  await press('Control+,')
  const nav = page.getByRole('navigation', { name: 'Settings sections' })
  await expect(nav.getByRole('button', { name: 'Other', exact: true })).toBeVisible()
  const names = (await nav.locator('.settings-nav-item').allTextContents()).map((s) => s.trim())
  expect(names).toHaveLength(11)
  for (const name of names) await section(name)
})
