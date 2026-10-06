/* Single native Wayland launch, full Electron stderr, native keyboard and AT-SPI. */
const { _electron } = require(process.env.ODIN_ORCA_ROOT + '/app/node_modules/playwright')
const { execFileSync } = require('node:child_process')
const { readFileSync, writeFileSync, createWriteStream } = require('node:fs')
const { join } = require('node:path')
const root = process.env.ODIN_ORCA_ROOT
const evidence = process.env.ODIN_ORCA_EVIDENCE
const helper = join(__dirname, 'focused_probe.py')
const native = (...args) => execFileSync('/usr/bin/python3', ['-B', helper, ...args], { encoding: 'utf8', timeout: 30000 })
;(async () => {
  let app
  const proof = { launches: 1, passed: false }
  const out = createWriteStream(join(evidence, 'probe-electron-stdout.log'))
  const err = createWriteStream(join(evidence, 'probe-electron-stderr.log'))
  const mark = readFileSync(process.env.ODIN_ORCA_LOG).length
  try {
    native('key', 'Escape')
    const env = { ...process.env, ELECTRON_ENABLE_LOGGING: '1', NO_AT_BRIDGE: '0', GTK_A11Y: 'always',
      GTK_MODULES: 'gail:atk-bridge', ACCESSIBILITY_ENABLED: '1',
      ODIN_DESKTOP_CORE_CMD: JSON.stringify(['/usr/bin/python3', '-B', join(root, 'app/test/e2e/accessibility-core.py'), 'privacy']) }
    app = await _electron.launch({ executablePath: env.ODIN_ORCA_ELECTRON, cwd: join(root, 'app'), env,
      args: [join(root, 'app'), '--force-renderer-accessibility', '--enable-logging=stderr', `--ozone-platform=${env.ODIN_ORCA_DESKTOP === 'cinnamon' ? 'x11' : 'wayland'}`],
      chromiumSandbox: true, timeout: 30000 })
    app.process().stdout?.pipe(out)
    app.process().stderr?.pipe(err)
    const page = await app.firstWindow()
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
    process.exitCode = 1
  } finally {
    if (app) await app.close()
    out.end(); err.end()
    writeFileSync(join(evidence, 'probe-electron.json'), JSON.stringify(proof, null, 2))
  }
})()
