/* Single native Wayland launch, full Electron stderr, native keyboard and AT-SPI. */
const { _electron } = require(process.env.ODIN_ORCA_ROOT + '/app/node_modules/playwright')
const { execFileSync } = require('node:child_process')
const { readFileSync, writeFileSync, createWriteStream, mkdirSync, existsSync } = require('node:fs')
const { randomUUID, createHash } = require('node:crypto')
const { join } = require('node:path')
const root = process.env.ODIN_ORCA_ROOT
const evidence = process.env.ODIN_ORCA_EVIDENCE
const helper = join(__dirname, 'focused_probe.py')
const native = (...args) => execFileSync('/usr/bin/python3', ['-B', helper, ...args], { encoding: 'utf8', timeout: 30000 })
;(async () => {
  let app
  let page
  const filesMode = process.env.ODIN_ORCA_PROBE === 'native-files'
  const proof = { kind: 'focused-probes-not-qualification', probe: process.env.ODIN_ORCA_PROBE, launches: 1, passed: false }
  const out = createWriteStream(join(evidence, 'probe-electron-stdout.log'))
  const err = createWriteStream(join(evidence, 'probe-electron-stderr.log'))
  const mark = readFileSync(process.env.ODIN_ORCA_LOG).length
  try {
    native('key', 'Escape')
    const env = { ...process.env, ELECTRON_ENABLE_LOGGING: '1', NO_AT_BRIDGE: '0', GTK_A11Y: 'always',
      GTK_MODULES: 'gail:atk-bridge', ACCESSIBILITY_ENABLED: '1',
      ODIN_DESKTOP_CORE_CMD: JSON.stringify(['/usr/bin/python3', '-B', join(root, 'app/test/e2e/accessibility-core.py'), 'privacy']) }
    if (filesMode) {
      // Fresh private profile, no reuse of task or user configuration. Kept until guest cleanup.
      proof.profile = join(root, `probe-files-${randomUUID()}`)
      mkdirSync(proof.profile, { mode: 0o700 })
      for (const name of ['config', 'data', 'cache']) mkdirSync(join(proof.profile, name), { mode: 0o700 })
      Object.assign(env, { HOME: proof.profile, XDG_CONFIG_HOME: join(proof.profile, 'config'),
        XDG_DATA_HOME: join(proof.profile, 'data'), XDG_CACHE_HOME: join(proof.profile, 'cache') })
    }
    app = await _electron.launch({ executablePath: env.ODIN_ORCA_ELECTRON, cwd: join(root, 'app'), env,
      args: [join(root, 'app'), '--force-renderer-accessibility', '--enable-logging=stderr', `--ozone-platform=${env.ODIN_ORCA_DESKTOP === 'cinnamon' ? 'x11' : 'wayland'}`],
      chromiumSandbox: true, timeout: 30000 })
    app.process().stdout?.pipe(out)
    app.process().stderr?.pipe(err)
    page = await app.firstWindow()
    await page.locator('.link.ready').filter({ hasText: 'Connected' }).waitFor({ timeout: 30000 })
    proof.window = await app.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows()[0]
      window.show(); window.focus()
      return { visible: window.isVisible(), focused: window.isFocused(), minimized: window.isMinimized(),
        preferences: window.webContents.getLastWebPreferences(), arguments: process.argv }
    })
    await page.waitForTimeout(1000)
    native('key', 'Escape')
    for (let i = 0; i < 24; i++) {
      native('key', 'Tab')
      await page.waitForTimeout(250)
      if (await page.getByRole('textbox', { name: 'Message', exact: true }).evaluate(el => el === document.activeElement)) break
    }
    proof.message_focused = await page.getByRole('textbox', { name: 'Message', exact: true }).evaluate(el => el === document.activeElement)
    native('key', 'Shift+Tab')
    await page.waitForTimeout(500)
    native('key', 'Tab')
    await page.waitForTimeout(2000)
    const tree = JSON.parse(native('snapshot'))
    writeFileSync(join(evidence, 'probe-electron-atspi.json'), JSON.stringify(tree, null, 2))
    execFileSync('/usr/local/lib/odq/capture', [join(evidence, 'probe-electron.png')], { timeout: 75000 })
    const speech = readFileSync(env.ODIN_ORCA_LOG).subarray(mark).toString().split('\n').filter(x => /^\d{2}:\d{2}:\d{2}\.\d+ - SPEECH OUTPUT: '/.test(x))
    writeFileSync(join(evidence, 'probe-electron-speech.json'), JSON.stringify(speech, null, 2))
    proof.speech_message = speech.some(x => /Message/.test(x) && /text|entry/i.test(x))
    proof.native_frame = tree.nodes.some(n => n.name === 'Odin' && n.states?.includes('SHOWING') && n.states?.includes('ACTIVE'))
    const prefs = proof.window.preferences
    proof.safe_preferences = prefs.sandbox === true && prefs.contextIsolation === true && prefs.nodeIntegration === false
    proof.passed = proof.window.visible && !proof.window.minimized && proof.message_focused && proof.speech_message && proof.native_frame && proof.safe_preferences
    if (!proof.passed) throw new Error('Native mapped window, focused Message, speech and AT-SPI frame all required')
    if (filesMode) {
      const speechAt = offset => readFileSync(env.ODIN_ORCA_LOG).subarray(offset).toString().split('\n')
        .filter(x => /^\d{2}:\d{2}:\d{2}\.\d+ - SPEECH OUTPUT: '/.test(x))
      const poll = async (predicate, reason) => {
        for (let i = 0; i < 60; i++) {
          if (await predicate()) return
          await page.waitForTimeout(250)
        }
        throw new Error(reason)
      }
      const hear = async (label, offset, patterns) => {
        await poll(() => patterns.every(pattern => pattern.test(speechAt(offset).join('\n'))), `Actual Orca speech missing: ${label}`)
        const records = speechAt(offset)
        writeFileSync(join(evidence, `probe-${label}-speech.json`), JSON.stringify(records, null, 2))
        return { records: records.length, patterns: patterns.map(String), passed: true }
      }
      const checkpoint = async label => {
        execFileSync('/usr/local/lib/odq/capture', [join(evidence, `probe-${label}.png`)], { timeout: 75000 })
        writeFileSync(join(evidence, `probe-${label}-atspi.json`), native('snapshot'))
        writeFileSync(join(evidence, `probe-${label}-speech.json`), JSON.stringify(speechAt(mark), null, 2))
        writeFileSync(join(evidence, `probe-${label}-dialogs.json`), JSON.stringify(
          await app.evaluate(() => globalThis.__odqNativeFileResults), null, 2))
      }
      const tabTo = async target => {
        if (await target.evaluate(el => el === document.activeElement)) {
          native('key', 'Shift+Tab')
          await page.waitForTimeout(250)
        }
        for (let i = 0; i < 160; i++) {
          if (await target.evaluate(el => el === document.activeElement)) return
          const reverse = await target.evaluate(el => Boolean(el.compareDocumentPosition(document.activeElement) & Node.DOCUMENT_POSITION_FOLLOWING))
          native('key', reverse ? 'Shift+Tab' : 'Tab')
          await page.waitForTimeout(150)
        }
        throw new Error('Target not keyboard reachable')
      }
      const activate = async (target, label, patterns) => {
        const offset = readFileSync(env.ODIN_ORCA_LOG).length
        await tabTo(target)
        await hear(label, offset, patterns)
        native('key', 'Enter')
      }
      const dialogCommand = async (title, action, path, prefix) => {
        // Retry ONLY an observation before input. Actual native commands are never replayed.
        let binding
        await poll(() => {
          try { binding = JSON.parse(native('dialog', title)); return true } catch (error) {
            if (!String(error.stdout || error).includes('No owned active AT-SPI dialog')) throw error
            return false
          }
        }, `No owned native dialog: ${title}`)
        writeFileSync(join(evidence, `probe-${prefix}-${action}-binding.json`), JSON.stringify(binding, null, 2))
        execFileSync('/usr/bin/python3', ['-B', join(root, 'app/test/e2e/orca-guest.py'), 'native', title, action, ...(path ? [path] : [])],
          { encoding: 'utf8', timeout: 60000, env: { ...process.env, ODIN_ORCA_NATIVE_EVIDENCE_PREFIX: `probe-${prefix}` } })
      }
      // Observe the original OS-dialog result. No substituted selection, option or IPC result.
      await app.evaluate(({ dialog }) => {
        globalThis.__odqNativeFileResults = []
        for (const method of ['showOpenDialog', 'showSaveDialog']) {
          const original = dialog[method]
          dialog[method] = async function (...args) {
            const result = await Reflect.apply(original, this, args)
            globalThis.__odqNativeFileResults.push({ method, result, recordedAt: Date.now() })
            return result
          }
        }
      })
      const attach = page.getByRole('button', { name: 'Attach files', exact: true })
      let offset = readFileSync(env.ODIN_ORCA_LOG).length
      await activate(attach, 'attach-button', [/Attach files/i, /button/i])
      await dialogCommand('Attach files', 'describe', null, 'attach-cancel')
      proof.attach_dialog_speech = await hear('attach-dialog', offset, [/Attach files/i, /table|file chooser|dialog/i])
      await checkpoint('attach-cancel-open')
      await dialogCommand('Attach files', 'cancel', null, 'attach-cancel')
      await poll(async () => (await app.evaluate(() => globalThis.__odqNativeFileResults)).length === 1, 'Cancel did not return')
      const cancelled = await app.evaluate(() => globalThis.__odqNativeFileResults[0])
      proof.attach_cancelled = cancelled.method === 'showOpenDialog' && cancelled.result.canceled === true && await page.locator('.attachments').count() === 0
      await checkpoint('attach-cancel-after')
      if (!proof.attach_cancelled) throw new Error('Native cancel returned unexpected result or attachments')
      const chosen = join(proof.profile, 'keyboard-attachment.txt')
      const attachmentBytes = Buffer.from('keyboard-only attachment\n')
      writeFileSync(chosen, attachmentBytes, { flag: 'wx', mode: 0o600 })
      await activate(attach, 'attach-positive-button', [/Attach files/i, /button/i])
      await dialogCommand('Attach files', 'file', chosen, 'native-attach')
      await checkpoint('attach-entry-after')
      await poll(async () => (await app.evaluate(() => globalThis.__odqNativeFileResults)).length === 2, 'Positive Attach did not return')
      const selected = await app.evaluate(() => globalThis.__odqNativeFileResults[1])
      proof.attach_result = selected
      proof.attach_selected = selected.method === 'showOpenDialog' && selected.result.canceled === false && selected.result.filePaths.includes(chosen)
      if (!proof.attach_selected) throw new Error('Native Attach did not return actual selected file')
      await poll(async () => (await page.locator('.attachment').allTextContents()).join('\n').includes('keyboard-attachment.txt'), 'Returned file absent from attachment UI')
      proof.attachment_sha256 = createHash('sha256').update(readFileSync(chosen)).digest('hex')
      proof.attachment_visible = true
      await checkpoint('attach-positive-after')
      await activate(page.locator('.attachment').getByRole('button', { name: /Remove/ }), 'attachment-remove', [/Remove/i, /button/i])
      await poll(async () => await page.locator('.attachments').count() === 0, 'Attachment removal not confirmed')
      await activate(page.getByRole('button', { name: 'New conversation', exact: true }), 'new-conversation', [/New conversation/i, /button/i])
      await tabTo(page.getByRole('textbox', { name: 'Message', exact: true }))
      await page.keyboard.press('Control+a')
      await page.keyboard.insertText('file keyboard result')
      await page.keyboard.press('Enter')
      const file = page.locator('.file-card').filter({ hasText: 'notes.txt' })
      await file.waitFor({ timeout: 30000 })
      proof.generated_notes_visible = (await file.textContent()).includes('notes.txt')
      offset = readFileSync(env.ODIN_ORCA_LOG).length
      await activate(file.getByRole('button', { name: /Save/ }), 'save-button', [/Save/i, /button/i])
      await dialogCommand('Save file', 'describe', null, 'save-dialog')
      proof.save_dialog_speech = await hear('save-dialog', offset, [/Save file/i, /entry|table|file chooser|dialog/i])
      await checkpoint('save-open')
      const saved = join(proof.profile, 'keyboard-saved.txt')
      if (existsSync(saved)) throw new Error('Save destination already exists')
      await dialogCommand('Save file', 'file', saved, 'native-save')
      await checkpoint('save-entry-after')
      await poll(() => existsSync(saved), 'Native Save did not create a file')
      const savedBytes = readFileSync(saved)
      proof.saved = { path: saved, bytes: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex'),
        exact_bytes: savedBytes.equals(Buffer.from('Generated notes\nline two\n')) }
      if (!proof.saved.exact_bytes) throw new Error('Actual saved bytes differ from generated notes')
      proof.native_files = true
      await checkpoint('native-files-complete')
    }
    if (env.ODIN_ORCA_PROBE === 'native-attach') {
      const attach = page.getByRole('button', { name: 'Attach files', exact: true })
      for (let i = 0; i < 24 && !await attach.evaluate(el => el === document.activeElement); i++) {
        native('key', 'Tab')
        await page.waitForTimeout(250)
      }
      if (!await attach.evaluate(el => el === document.activeElement)) throw new Error('Attach button not native-keyboard focused')
      native('key', 'Enter')
      let binding
      for (let i = 0; i < 20; i++) {
        try { binding = JSON.parse(native('dialog')); break } catch (error) {
          console.error(String(error.stdout || error))
          if (!String(error.stdout || error).includes('No owned active AT-SPI dialog')) throw error
          await page.waitForTimeout(250)
        }
      }
      if (!binding) {
        execFileSync('/usr/local/lib/odq/capture', [join(evidence, 'probe-attach-failed.png')], { timeout: 75000 })
        throw new Error('No measured active native Attach dialog')
      }
      writeFileSync(join(evidence, 'probe-attach-binding.json'), JSON.stringify(binding, null, 2))
      execFileSync('/usr/local/lib/odq/capture', [join(evidence, 'probe-attach.png')], { timeout: 75000 })
      execFileSync('/usr/bin/python3', ['-B', join(root, 'app/test/e2e/orca-guest.py'), 'native', 'Attach files', 'cancel'], { encoding: 'utf8', timeout: 30000 })
      await page.waitForTimeout(1000)
      const after = JSON.parse(native('snapshot'))
      writeFileSync(join(evidence, 'probe-attach-after-atspi.json'), JSON.stringify(after, null, 2))
      proof.attach_cancelled = !after.nodes.some(n => n.name === 'Attach files' && n.states?.includes('ACTIVE') && n.states?.includes('SHOWING'))
      proof.passed = proof.passed && proof.attach_cancelled
      if (!proof.passed) throw new Error('Native Attach cancellation not confirmed')
    }
  } catch (error) {
    proof.passed = false
    proof.error = String(error.stack || error)
    console.error(proof.error)
    if (app) {
      try { execFileSync('/usr/local/lib/odq/capture', [join(evidence, 'probe-failure.png')], { timeout: 75000 }) } catch (captureError) { proof.capture_error = String(captureError) }
      try { writeFileSync(join(evidence, 'probe-failure-atspi.json'), native('snapshot')) } catch (snapshotError) { proof.snapshot_error = String(snapshotError) }
      try { writeFileSync(join(evidence, 'probe-failure-dialogs.json'), JSON.stringify(await app.evaluate(() => globalThis.__odqNativeFileResults ?? []), null, 2)) } catch (resultError) { proof.dialog_result_error = String(resultError) }
      writeFileSync(join(evidence, 'probe-failure-speech.json'), JSON.stringify(readFileSync(process.env.ODIN_ORCA_LOG).subarray(mark).toString().split('\n').filter(x => /^\d{2}:\d{2}:\d{2}\.\d+ - SPEECH OUTPUT: '/.test(x)), null, 2))
    }
    process.exitCode = 1
  } finally {
    if (app) await app.close()
    out.end(); err.end()
    writeFileSync(join(evidence, 'probe-electron.json'), JSON.stringify(proof, null, 2))
  }
})()
