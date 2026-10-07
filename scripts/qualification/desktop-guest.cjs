/* Guest only. Playwright main inspection remains outside the renderer. */
const { execFileSync } = require('node:child_process')
const { readFileSync, writeFileSync, mkdirSync, existsSync, statSync } = require('node:fs')
const { join } = require('node:path')
const assert = require('node:assert/strict')
const { _electron } = require('./node_modules/playwright')
const { probe } = require('./desktop-probe.cjs')

;(async () => {
  assert.match(execFileSync('hostname', { encoding: 'utf8' }).trim(), /^odq-(cinnamon|gnome|kde)$/)
  assert.match(execFileSync('systemd-detect-virt', { encoding: 'utf8' }).trim(), /^(kvm|qemu)$/)
  assert.equal(readFileSync('/etc/odin-desktop-qualification', 'utf8').trim(), 'odin-desktop-qualification-v1')
  assert.equal(process.getuid(), Number(execFileSync('id', ['-u', 'odq'], { encoding: 'utf8' }).trim()))
  assert.equal(statSync(__dirname).uid, process.getuid())
  const manifest = JSON.parse(readFileSync('/opt/Odin/resources/bundle-manifest.json', 'utf8'))
  assert.equal(manifest.source.commit, process.argv[2])
  // A unique disposable candidate profile, not the lab operator's profile.
  const profile = join(__dirname, 'profile')
  assert.equal(existsSync(profile), false)
  mkdirSync(profile, { mode: 0o700 })
  const env = { ...process.env, HOME: profile, XDG_CONFIG_HOME: join(profile, 'config'),
    XDG_DATA_HOME: join(profile, 'data'), XDG_CACHE_HOME: join(profile, 'cache') }
  for (const field of ['XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME']) mkdirSync(env[field], { mode: 0o700 })
  // RUNTIME stays the owned guest compositor runtime, profile files stay private.
  const application = await _electron.launch({ executablePath: '/opt/Odin/odin-desktop',
    args: ['--force-renderer-accessibility', `--ozone-platform=${env.XDG_SESSION_TYPE === 'x11' ? 'x11' : 'wayland'}`],
    chromiumSandbox: true, env, timeout: 60000 })
  let result
  try {
    const page = await application.firstWindow()
    await page.locator('.link.ready').waitFor({ timeout: 60000 })
    result = await probe(application, page)
    assert.equal(result.preferences.packaged, true)
    await page.screenshot({ path: join(__dirname, 'renderer.png') })
    result.versions = result.preferences.versions
    result.source_sha = manifest.source.commit
    result.passed = true
  } catch (error) {
    result = { passed: false, error: String(error) }
    throw error
  } finally {
    writeFileSync(join(__dirname, 'probe.json'), JSON.stringify(result, null, 2) + '\n')
    // Normal product Exit. No process kill, no replay and no guard override.
    const closed = application.waitForEvent('close', { timeout: 60000 })
    await application.evaluate(({ Menu }) => {
      const visit = menu => {
        for (const item of menu.items) {
          if (item.label === 'Exit Odin') { item.click(); return true }
          if (item.submenu && visit(item.submenu)) return true
        }
        return false
      }
      if (!visit(Menu.getApplicationMenu())) throw new Error('Actual Exit route not found')
    })
    await closed
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
