/* Shared actual-Electron assertions: isolated source regression and D11 guest.
 * Never dispatches shell, input, capture or credentials to the workstation.
 * Main-side inspection is the test observer, not a renderer capability.
 */
const assert = require('node:assert/strict')

async function probe(app, page) {
  const preferences = await app.evaluate(({ BrowserWindow, app }) => {
    const window = BrowserWindow.getAllWindows()[0]
    return { preferences: window.webContents.getLastWebPreferences(),
      arguments: process.argv, versions: process.versions,
      packaged: app.isPackaged }
  })
  assert.equal(preferences.preferences.sandbox, true)
  assert.equal(preferences.preferences.contextIsolation, true)
  assert.equal(preferences.preferences.nodeIntegration, false)
  assert.equal(preferences.preferences.webSecurity, true)
  assert.equal(preferences.arguments.includes('--no-sandbox'), false)
  assert.equal(new URL(page.url()).protocol, 'app:')
  assert.equal(new URL(page.url()).hostname, 'odin')
  const renderer = await page.evaluate(async () => {
    const names = Object.keys(window.odin).sort()
    return { names, generic: ['invoke', 'send', 'request', 'socket', 'token'].filter(k => k in window.odin),
      node: ['require', 'process', 'Buffer', 'ipcRenderer'].filter(k => typeof window[k] !== 'undefined'),
      status: await window.odin.status(),
      malformed: await window.odin.copyText({ bad: 'not a string' }),
      path: await window.odin.fetchArtifact('/var/tmp/p36-not-an-artifact'),
      fakeFile: await window.odin.attachFiles([new File(['harmless'], '/var/tmp/p36-file.txt')]) }
  })
  assert.deepEqual(renderer.generic, [])
  assert.deepEqual(renderer.node, [])
  assert.ok(renderer.names.length > 30)
  assert.equal(renderer.status.ok, true)
  assert.equal(renderer.malformed.ok, false)
  assert.equal(renderer.path.ok, false)
  assert.equal(renderer.fakeFile.ok, true)
  assert.equal(renderer.fakeFile.result.staged.length, 0)
  assert.equal(renderer.fakeFile.result.errors.length, 1)
  // Observe real default-session response headers without changing the policy.
  const csp = await app.evaluate(async ({ session }) => {
    const response = await session.defaultSession.fetch('app://odin/index.html')
    return response.headers.get('Content-Security-Policy')
  })
  assert.ok(csp.includes("connect-src 'none'"))
  assert.ok(csp.includes("script-src 'self'"))
  assert.ok(csp.includes("frame-src 'none'"))
  assert.ok(!/unsafe-(inline|eval)/.test(csp))
  const content = await page.evaluate(async () => {
    window.__p36Inert = 0
    const script = document.createElement('script')
    script.textContent = 'window.__p36Inert = 1'
    document.body.append(script)
    const button = document.createElement('button')
    button.setAttribute('onclick', 'window.__p36Inert = 2')
    document.body.append(button); button.click()
    let network = 'unexpected-success'
    try { await fetch('http://127.0.0.1:9/p36-csp'); } catch { network = 'refused' }
    script.remove(); button.remove()
    return { execution: window.__p36Inert, network }
  })
  assert.equal(content.execution, 0)
  assert.equal(content.network, 'refused')
  const permission = await page.evaluate(async () => {
    try { return await Notification.requestPermission() } catch { return 'denied' }
  })
  assert.equal(permission, 'denied')
  const popupsBefore = app.windows().length
  await page.evaluate(() => window.open('data:text/plain,p36-harmless', '_blank'))
  await page.waitForTimeout(250)
  assert.equal(app.windows().length, popupsBefore)
  const original = page.url()
  await page.evaluate(() => { location.href = 'data:text/plain,p36-harmless' })
  await page.waitForTimeout(250)
  assert.equal(page.url(), original)
  // A real second webContents with the shipped preload calls the production
  // bridge. It has the correct app origin but the wrong sender identity.
  const sender = await app.evaluate(async ({ BrowserWindow, app }) => {
    const second = new BrowserWindow({ show: false,
      webPreferences: { preload: app.getAppPath() + '/out/preload/index.js', sandbox: true,
        contextIsolation: true, nodeIntegration: false } })
    try {
      await second.loadURL('app://odin/index.html')
      return await second.webContents.executeJavaScript(
        'typeof window.odin === "undefined" ? { missing: true } : window.odin.status()')
    } finally { second.destroy() }
  })
  assert.equal(sender.ok, false)
  assert.equal(sender.error.code, 'unauthorized')
  // Invoke the installed production handler with an observed real mainFrame
  // and altered frame/origin identities. These two are synthetic-event boundary
  // checks, explicitly distinct from the real second-window transport above.
  const frames = await app.evaluate(async ({ BrowserWindow, ipcMain }) => {
    const contents = BrowserWindow.getAllWindows()[0].webContents
    const handler = ipcMain._invokeHandlers.get('odin:status')
    if (!handler) throw new Error('Named status handler missing')
    const top = contents.mainFrame
    return {
      subframe: await handler({ sender: contents, senderFrame: {
        url: top.url, processId: top.processId, routingId: top.routingId + 1 } }),
      origin: await handler({ sender: contents, senderFrame: {
        url: 'app://untrusted/index.html', processId: top.processId, routingId: top.routingId } }) }
  })
  for (const value of Object.values(frames)) {
    assert.equal(value.ok, false)
    assert.equal(value.error.code, 'unauthorized')
  }
  const view = await app.evaluate(({ BrowserWindow }) => {
    const window = BrowserWindow.getAllWindows()[0]
    const original = window.getBounds()
    window.setBounds({ ...original, width: 860, height: 660 })
    window.webContents.setZoomFactor(1.5)
    return { original, changed: window.getBounds(), zoom: window.webContents.getZoomFactor() }
  })
  assert.equal(view.zoom, 1.5)
  assert.ok(view.changed.width > 0 && view.changed.height > 0)
  const message = page.getByRole('textbox', { name: 'Message', exact: true })
  await message.focus()
  assert.equal(await message.evaluate(el => el === document.activeElement), true)
  await page.reload()
  await page.locator('.link.ready').waitFor({ timeout: 30000 })
  const recovered = await page.evaluate(async () => ({
    node: typeof window.require, status: await window.odin.status() }))
  assert.equal(recovered.node, 'undefined')
  assert.equal(recovered.status.ok, true)
  await app.evaluate(({ BrowserWindow }, original) => {
    const window = BrowserWindow.getAllWindows()[0]
    window.webContents.setZoomFactor(1); window.setBounds(original)
  }, view.original)
  return { preferences, renderer, csp, content, permission,
    popups_refused: true, navigation_refused: true, sender, frames, view, recovered,
    limitation: 'Frame/origin event variants synthetic; second-window sender is real. '
      + 'No native dialog, Orca, portal, tray, computer input or physical GPU claim.' }
}

module.exports = { probe }
