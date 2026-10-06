# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: orca.spec.ts >> orca-chat-results-attach-cancel-save-copy-report
- Location: test/e2e/orca.spec.ts:195:5

# Error details

```
Error: Error: Owned active native dialog required: Attach files

Owned active native dialog required: Attach files

expect(received).toBe(expected) // Object.is equality

Expected: true
Received: false

Call Log:
- Timeout 20000ms exceeded while waiting on the predicate
Last AT-SPI lookup: {"native_dialog_lookup": [{"peer": ":1.18", "path": "/org/a11y/atspi/accessible/1", "error": "org.freedesktop.DBus.Error.NameHasNoOwner: Could not get UID of name ':1.18': no such name"}]}
{"passed": false, "error": "No owned active AT-SPI dialog: Attach files"}

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - navigation "Conversations" [ref=e4]:
    - generic [ref=e5]:
      - generic [ref=e6]: Odin
      - generic [ref=e7]:
        - button "Search" [ref=e8] [cursor=pointer]
        - button "New conversation" [ref=e9] [cursor=pointer]: + New
    - list [ref=e10]:
      - listitem [ref=e11]:
        - button "Chat" [ref=e12] [cursor=pointer]
        - button "Actions for Chat" [ref=e14] [cursor=pointer]: ⋯
      - listitem [ref=e15]:
        - button "New chat" [ref=e16] [cursor=pointer]
        - button "Actions for New chat" [ref=e18] [cursor=pointer]: ⋯
  - main [ref=e19]:
    - generic [ref=e20]:
      - heading "New chat" [level=1] [ref=e21]
      - button "Work" [ref=e22] [cursor=pointer]
      - button "Settings" [ref=e23] [cursor=pointer]
    - status [ref=e24]: Task completed.
    - region "Conversation history" [ref=e25]:
      - article "You message at 07:23 AM" [ref=e26]:
        - generic [ref=e27]:
          - generic [ref=e28]: You
          - time [ref=e29]: 07:23 AM
          - generic [ref=e30]:
            - status
            - button "Copy You message at 07:23 AM" [ref=e31] [cursor=pointer]: Copy
            - 'button "Thread from here: You message at 07:23 AM" [ref=e32] [cursor=pointer]': Thread from here
        - generic [ref=e33]:
          - paragraph [ref=e34]: file report script keyboard result
          - generic [ref=e35]:
            - button "Copy code" [ref=e36] [cursor=pointer]: Copy
            - code [ref=e38]: keyboard-code
      - article "Odin message at 07:23 AM" [ref=e39]:
        - generic [ref=e40]:
          - status [ref=e41]
          - 'button "1 tool call: Tool activity" [ref=e42] [cursor=pointer]': 1 tool call ▸
        - generic [ref=e43]:
          - generic [ref=e44]: Odin
          - time [ref=e45]: 07:23 AM
          - generic [ref=e46]:
            - status
            - button "Copy Odin message at 07:23 AM" [ref=e47] [cursor=pointer]: Copy
            - 'button "Thread from here: Odin message at 07:23 AM" [ref=e48] [cursor=pointer]': Thread from here
        - generic [ref=e49]:
          - paragraph [ref=e50]: "Echo: file report script keyboard result"
          - generic [ref=e51]:
            - button "Copy code" [ref=e52] [cursor=pointer]: Copy
            - code [ref=e54]: keyboard-code
        - generic [ref=e55]:
          - generic [aria-hidden] [ref=e56]: TXT
          - generic [ref=e57]:
            - generic "notes.txt" [ref=e58]
            - generic [ref=e59]: 25 B · text/plain
          - status
          - generic [ref=e60]:
            - button "Open notes.txt" [ref=e61] [cursor=pointer]: Open
            - button "Save as… notes.txt" [ref=e62] [cursor=pointer]: Save as…
            - 'button "Show in folder: notes.txt" [ref=e63] [cursor=pointer]': Show in folder
        - generic [ref=e64]:
          - generic [aria-hidden] [ref=e65]: SH
          - generic [ref=e66]:
            - generic "cleanup.sh" [ref=e67]
            - generic [ref=e68]: 21 B · text/x-shellscript
          - status
          - generic [ref=e69]:
            - button "Open cleanup.sh" [ref=e70] [cursor=pointer]: Open
            - button "Save as… cleanup.sh" [ref=e71] [cursor=pointer]: Save as…
            - 'button "Show in folder: cleanup.sh" [ref=e72] [cursor=pointer]': Show in folder
        - region "Health report" [ref=e73]:
          - generic [ref=e74]:
            - strong [ref=e75]: Health report
            - generic [ref=e76]: Page 1 of 3
            - generic "Pages are the stored result; paging never runs the check again." [ref=e77]:
              - button "Previous page of Health report" [disabled] [ref=e78] [cursor=pointer]: Previous
              - button "Next page of Health report" [ref=e79] [cursor=pointer]: Next
              - button "Copy page of Health report" [ref=e80] [cursor=pointer]: Copy page
              - button "Retry loading Health report" [disabled] [ref=e81] [cursor=pointer]: Retry
          - status [ref=e82]: Copied page 1 of Health report.
          - generic [ref=e83]:
            - heading "Page 1" [level=2] [ref=e84]
            - paragraph [ref=e85]: Stored result, page 1 of 3.
    - generic [ref=e86]:
      - status [ref=e87]
      - generic [ref=e88]:
        - generic [ref=e89]:
          - textbox "Message" [ref=e90]:
            - /placeholder: Message Odin… (/ for commands)
          - generic [ref=e91]:
            - button "Send" [disabled] [ref=e92]
            - button "Attach files" [active] [ref=e93] [cursor=pointer]: Attach
        - paragraph [ref=e94]: Enter to send; Shift+Enter for a new line. For commands, use Up/Down or Home/End, Tab to complete, Enter to run, Escape to dismiss.
  - contentinfo "Odin status" [ref=e95]:
    - status [ref=e96]: ● Connected
    - button "Core fixture-0 · ready" [ref=e97] [cursor=pointer]
    - button "fixture-echo · none" [ref=e98] [cursor=pointer]
    - 'generic "fixture: ok" [ref=e99]': ● fixture
    - button "Context ~0% · Quota — · ~15 tokens in 24h" [ref=e100] [cursor=pointer]
    - generic [ref=e101]: core 959e54fb
    - generic [ref=e102]:
      - checkbox "Start at login" [ref=e103]
      - text: Start at login
```

# Test source

```ts
  75  |     : JSON.stringify(['/usr/bin/python3', '-B', join(__dirname, 'accessibility-core.py'), scenario])
  76  |   const platform = process.env.ODIN_ORCA_DESKTOP === 'cinnamon' ? 'x11' : 'wayland'
  77  |   app = await electron.launch({ executablePath: process.env.ODIN_ORCA_ELECTRON ?? require('electron'), cwd: appDir, env,
  78  |     args: [appDir, '--force-renderer-accessibility', `--ozone-platform=${platform}`], chromiumSandbox: true })
  79  |   page = await app.firstWindow()
  80  |   await expect(page.locator('.link.ready')).toContainText('Connected')
  81  |   launchEvidence = await app.evaluate(({ BrowserWindow }) => {
  82  |     const window = BrowserWindow.getAllWindows()[0]!
  83  |     window.show()
  84  |     window.focus()
  85  |     const contents = window.webContents as unknown as {
  86  |       getLastWebPreferences: () => { sandbox: boolean; contextIsolation: boolean; nodeIntegration: boolean }
  87  |     }
  88  |     const prefs = contents.getLastWebPreferences()
  89  |     return { sandbox: prefs.sandbox, contextIsolation: prefs.contextIsolation,
  90  |       nodeIntegration: prefs.nodeIntegration, visible: window.isVisible(), focused: window.isFocused(),
  91  |       minimized: window.isMinimized(), arguments: process.argv, versions: process.versions }
  92  |   })
  93  |   expect(launchEvidence).toMatchObject({ sandbox: true, contextIsolation: true, nodeIntegration: false,
  94  |     visible: true, minimized: false })
  95  |   // Wayland focus requests are asynchronous. Verify the native frame as the
  96  |   // passing focused probe does, not an immediate isFocused snapshot.
  97  |   execFileSync('/usr/bin/python3', ['-B', join(process.env.ODIN_ORCA_ROOT!,
  98  |     'scripts/qualification/lab/guest/focused_probe.py'), 'key', 'Escape'], { timeout: 15_000 })
  99  |   await expect.poll(() => {
  100 |     const tree = JSON.parse(execFileSync('/usr/bin/python3', ['-B', join(process.env.ODIN_ORCA_ROOT!,
  101 |       'scripts/qualification/lab/guest/focused_probe.py'), 'snapshot'], { encoding: 'utf8', timeout: 30_000 }))
  102 |     return tree.nodes.some((node: { name: string; states?: string[] }) => node.name === 'Odin'
  103 |       && node.states?.includes('SHOWING') && node.states?.includes('ACTIVE'))
  104 |   }, { timeout: 30_000 }).toBe(true)
  105 |   expect(JSON.stringify(launchEvidence)).not.toContain('--no-sandbox')
  106 | }
  107 | 
  108 | async function hear(from: number, ...patterns: RegExp[]): Promise<string> {
  109 |   try {
  110 |     await expect.poll(() => patterns.every((p) => p.test(speech!.text(from))), {
  111 |       message: `Actual Orca SPEECH OUTPUT must contain ${patterns.join(', ')}`
  112 |     }).toBe(true)
  113 |   } catch (error) {
  114 |     await test.info().attach('failed-speech-window', { body: JSON.stringify({ from,
  115 |       patterns: patterns.map(String), records: speechRecords(speech!.read(from)) }), contentType: 'application/json' })
  116 |     throw error
  117 |   }
  118 |   const result = speech!.text(from)
  119 |   await test.info().attach(`speech-assertion-${test.info().attachments.length}`, {
  120 |     body: JSON.stringify({ patterns: patterns.map(String), records: speechRecords(speech!.read(from)) }), contentType: 'application/json'
  121 |   })
  122 |   return result
  123 | }
  124 | 
  125 | async function press(key: string): Promise<void> {
  126 |   await page.keyboard.press(key)
  127 |   await page.waitForTimeout(100)
  128 | }
  129 | 
  130 | async function tabTo(target: Locator, name?: RegExp, role?: RegExp, state?: RegExp): Promise<void> {
  131 |   await expect(target).toBeVisible()
  132 |   const from = speech!.mark()
  133 |   if (await target.evaluate((el) => el === document.activeElement)) {
  134 |     await press('Shift+Tab')
  135 |     await page.waitForTimeout(350)
  136 |   }
  137 |   for (let n = 0; n < 200; n++) {
  138 |     if (await target.evaluate((el) => el === document.activeElement)) {
  139 |       if (name) await hear(from, name, ...(role ? [role] : []), ...(state ? [state] : []))
  140 |       return
  141 |     }
  142 |     const reverse = await target.evaluate((el) => Boolean(el.compareDocumentPosition(document.activeElement!) & Node.DOCUMENT_POSITION_FOLLOWING))
  143 |     await press(reverse ? 'Shift+Tab' : 'Tab')
  144 |     await page.waitForTimeout(250)
  145 |   }
  146 |   throw new Error(`Not keyboard reachable: ${await target.getAttribute('aria-label') ?? await target.textContent()}`)
  147 | }
  148 | 
  149 | async function activate(target: Locator, name?: RegExp, role = /(?:push )?button/i): Promise<void> {
  150 |   await tabTo(target, name, role)
  151 |   await press('Enter')
  152 | }
  153 | 
  154 | async function send(text: string): Promise<void> {
  155 |   await tabTo(page.getByRole('textbox', { name: 'Message', exact: true }), /Message/i, /(?:entry|text)/i)
  156 |   await press('Control+a')
  157 |   await page.keyboard.insertText(text)
  158 |   await press('Enter')
  159 | }
  160 | 
  161 | async function native(title: string, action: 'cancel' | 'file' | 'describe', path?: string): Promise<void> {
  162 |   let lookup = ''
  163 |   // Poll observation ONLY. No error after typing or submission can replay input.
  164 |   await expect.poll(() => {
  165 |     try {
  166 |       execFileSync('/usr/bin/python3', ['-B', guest, 'native', title, 'describe'],
  167 |         { encoding: 'utf8', timeout: 30_000 })
  168 |       return true
  169 |     } catch (error) {
  170 |       const output = (error as { stdout?: string }).stdout ?? String(error)
  171 |       if (output.includes('No owned active AT-SPI dialog')) { lookup = output; return false }
  172 |       throw new Error(`Native dialog observation failed: ${output}`)
  173 |     }
  174 |   }, { message: `Owned active native dialog required: ${title}` }).toBe(true).catch((error) => {
> 175 |     throw new Error(`${error}\nLast AT-SPI lookup: ${lookup}`)
      |           ^ Error: Error: Owned active native dialog required: Attach files
  176 |   })
  177 |   if (action !== 'describe') {
  178 |     execFileSync('/usr/bin/python3', ['-B', guest, 'native', title, action, ...(path ? [path] : [])],
  179 |       { encoding: 'utf8', timeout: 30_000 })
  180 |   }
  181 | }
  182 | 
  183 | async function section(name: string): Promise<void> {
  184 |   await activate(page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name, exact: true }),
  185 |     new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'))
  186 |   await expect(page.locator('.settings-body')).toContainText(name)
  187 | }
  188 | 
  189 | test('orca-bridge-named-message-and-native-button-role', async () => {
  190 |   await launch()
  191 |   await tabTo(page.getByRole('textbox', { name: 'Message', exact: true }), /Message/i, /entry|text/i)
  192 |   await tabTo(page.getByRole('button', { name: 'Attach files', exact: true }), /Attach files/i, /button/i)
  193 | })
  194 | 
  195 | test('orca-chat-results-attach-cancel-save-copy-report', async () => {
  196 |   await launch()
  197 |   await activate(page.getByRole('button', { name: 'New conversation', exact: true }), /New conversation/i)
  198 |   const completed = speech!.mark()
  199 |   await send('file report script keyboard result\n```text\nkeyboard-code\n```')
  200 |   await expect(page.locator('.msg.assistant')).toContainText('keyboard result')
  201 |   await hear(completed, /Task completed/i)
  202 |   await activate(page.locator('.msg.assistant').getByRole('button', { name: /^Copy Odin message/ }), /Copy Odin message/i)
  203 |   await activate(page.locator('.msg.assistant').getByRole('button', { name: 'Copy as Markdown', exact: true }), /Copy as Markdown/i)
  204 |   await expect.poll(() => app!.evaluate(({ clipboard }) => clipboard.readText())).toContain('keyboard result')
  205 |   await activate(page.locator('.msg.assistant .code-copy').first(), /Copy/i)
  206 |   await expect.poll(() => app!.evaluate(({ clipboard }) => clipboard.readText())).toContain('keyboard-code')
  207 |   await activate(page.locator('.report').getByRole('button', { name: 'Next page of Health report', exact: true }), /Next page of Health report/i)
  208 |   await expect(page.locator('.report')).toContainText('Page 2')
  209 |   await activate(page.locator('.report').getByRole('button', { name: 'Previous page of Health report', exact: true }), /Previous page of Health report/i)
  210 |   await expect(page.locator('.report')).toContainText('Page 1')
  211 |   await activate(page.locator('.report').getByRole('button', { name: 'Copy page of Health report', exact: true }), /Copy page of Health report/i)
  212 |   await expect.poll(() => app!.evaluate(({ clipboard }) => clipboard.readText())).toContain('Stored result, page 1 of 3')
  213 |   let from = speech!.mark()
  214 |   await activate(page.getByRole('button', { name: 'Attach files', exact: true }), /Attach files/i)
  215 |   await native('Attach files', 'describe')
  216 |   await hear(from, /Attach files/i, /table|file chooser|dialog/i)
  217 |   await native('Attach files', 'cancel')
  218 |   await expect(page.locator('.attachments')).toHaveCount(0)
  219 |   const chosen = join(root, 'keyboard-attachment.txt')
  220 |   writeFileSync(chosen, 'keyboard-only attachment\n')
  221 |   await activate(page.getByRole('button', { name: 'Attach files', exact: true }), /Attach files/i)
  222 |   await native('Attach files', 'file', chosen)
  223 |   await expect(page.locator('.attachment')).toContainText('keyboard-attachment.txt')
  224 |   await activate(page.locator('.attachment').getByRole('button', { name: /Remove/ }), /Remove/i)
  225 |   await expect(page.locator('.attachments')).toHaveCount(0)
  226 |   const saved = join(root, 'keyboard-saved.txt')
  227 |   from = speech!.mark()
  228 |   await activate(page.locator('.file-card').filter({ hasText: 'notes.txt' }).getByRole('button', { name: /Save/ }), /Save/i)
  229 |   await native('Save file', 'describe')
  230 |   await hear(from, /Save file/i, /entry|table|file chooser|dialog/i)
  231 |   await native('Save file', 'file', saved)
  232 |   await expect.poll(() => existsSync(saved)).toBe(true)
  233 |   expect(readFileSync(saved, 'utf8')).toContain('Generated notes')
  234 | })
  235 | 
  236 | test('orca-conversation-child-modal-search', async () => {
  237 |   await launch()
  238 |   await activate(page.getByRole('button', { name: 'New conversation', exact: true }), /New conversation/i)
  239 |   const opener = page.getByRole('button', { name: /Actions for/ }).last()
  240 |   let from = speech!.mark()
  241 |   await activate(opener, /Actions for/i)
  242 |   await hear(from, /Rename/i, /menu/i)
  243 |   await press('Enter')
  244 |   await expect(page.getByRole('dialog', { name: 'Rename conversation' })).toBeVisible()
  245 |   await hear(from, /Rename conversation/i, /dialog/i, /Title/i, /entry|text/i)
  246 |   await press('Escape')
  247 |   await expect(opener).toBeFocused()
  248 |   from = speech!.mark()
  249 |   await press('Enter')
  250 |   await hear(from, /menu/i, /Rename/i)
  251 |   from = speech!.mark()
  252 |   await press('ArrowDown')
  253 |   await hear(from, /New thread from here/i)
  254 |   await press('Enter')
  255 |   await expect(page.locator('.inherited')).toContainText('continued from')
  256 |   await activate(page.getByRole('button', { name: 'Open the original', exact: true }), /Open the original/i)
  257 |   await expect(page.locator('.inherited')).toHaveCount(0)
  258 |   await send('searchable keyboard anchor')
  259 |   await expect(page.locator('.msg.assistant')).toContainText('searchable keyboard anchor')
  260 |   from = speech!.mark()
  261 |   await press('Control+Shift+f')
  262 |   const search = page.getByRole('searchbox', { name: 'Search all conversations', exact: true })
  263 |   await expect(search).toBeFocused()
  264 |   await hear(from, /Search all conversations/i, /entry|text/i)
  265 |   await page.keyboard.insertText('searchable')
  266 |   await press('Enter')
  267 |   await expect(page.locator('.search-hits .hit')).toHaveCount(2)
  268 |   await activate(page.locator('.search-hits .hit').first(), /searchable keyboard anchor/i)
  269 |   await expect(page.locator('.msg.highlight')).toContainText('searchable')
  270 | })
  271 | 
  272 | test('orca-busy-steer-consumed-queued-stop-resume-unknown-no-flood', async () => {
  273 |   await launch()
  274 |   const from = speech!.mark()
  275 |   await send('slow privacy keyboard task')
```