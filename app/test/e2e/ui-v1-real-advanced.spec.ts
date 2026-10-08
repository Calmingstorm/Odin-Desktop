// C12 only: production core, real schema, synthetic disposable fresh profile.
import { createHash } from 'node:crypto'
import { readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { join, resolve, sep } from 'node:path'
import { expect, test, type ElectronApplication } from '@playwright/test'
import type { ConfigMeta } from '../../src/shared/api'
import { advancedPresentation as presentation, assertAdvancedInventory, assertAdvancedScrollCoverage, type ScrollFrame } from '../../src/main/advanced-capture-contract'
import { assertIsolated, exitApp, launchApp, repository, request, snapshot, waitForCore } from './harness'

if (process.env.ODIN_APP_REAL_ADVANCED_CAPTURE !== '1') throw new Error('Use scripts/real-core-advanced-capture.mjs after parent declares source stable')
const variant = { key: '1180x780-dark', width: 1180, height: 780, theme: 'dark' }
const hash = (bytes: Buffer): string => createHash('sha256').update(bytes).digest('hex')
test('C12: REAL engine full Advanced inventory and top-to-bottom dark capture', async () => {
  assertIsolated()
  const output = resolve(process.env.ODIN_APP_E2E_OUT!)
  if (!process.env.ODIN_APP_E2E_OUT || output === repository || output.startsWith(repository + sep)) throw new Error('External evidence path required')
  const command = [process.env.ODIN_DESKTOP_ENGINE_PYTHON!, '-B', '-P', '-m', 'src']
  const isolation = { uid: process.getuid?.(), gid: process.getgid?.(), home: process.env.HOME,
    pidNamespace: readlinkSync('/proc/self/ns/pid'), outerPidNamespace: process.env.ODIN_REAL_CORE_OUTER_PID_NS,
    display: process.env.DISPLAY, privateDbus: Boolean(process.env.DBUS_SESSION_BUS_ADDRESS) }
  const receipt: Record<string, unknown> = { outcome: 'running', realCore: true, fixture: false, variant, command,
    profile: 'synthetic disposable fresh profile; unmodified REAL engine schema and defaults', isolation }
  let application: ElectronApplication | undefined
  try {
    application = await launchApp({ profile: 'c12-real-advanced', realCore: true,
      env: { ODIN_DESKTOP_CORE_CMD: JSON.stringify(command) } })
    const core = await waitForCore(application)
    receipt.core = core
    // The runner shares this verified private PID namespace with Electron.
    // Read here rather than assuming CommonJS require in the evaluated main context.
    const coreProcess = {
      args: readFileSync(`/proc/${core.pid}/cmdline`, 'utf8').split('\0').filter(Boolean),
      cwd: readlinkSync(`/proc/${core.pid}/cwd`), pidNamespace: readlinkSync(`/proc/${core.pid}/ns/pid`)
    }
    expect(coreProcess.args.slice(0, 5)).toEqual(command)
    expect(coreProcess.cwd).toBe(repository)
    expect(coreProcess.pidNamespace).toBe(isolation.pidNamespace)
    receipt.coreProcess = coreProcess
    const status = await request(application, 'status.get')
    expect(status.ok).toBe(true)
    expect((status.result as { core_instance_id: string }).core_instance_id).toBe(core.instanceId)
    receipt.engineVersion = (status.result as { version: string }).version
    const schemaAnswer = await request(application, 'settings.schema')
    expect(schemaAnswer.ok, 'production settings.schema must be served').toBe(true)
    const schema = schemaAnswer.result as ConfigMeta
    expect(schema.fields.length).toBeGreaterThan(100)
    const page = await application.firstWindow()
    await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: null })
    await application.evaluate(({ BrowserWindow }, dimensions) => {
      const window = BrowserWindow.getAllWindows()[0]!
      window.setContentSize(dimensions.width, dimensions.height)
      window.webContents.setZoomFactor(1)
    }, variant)
    await expect.poll(() => page.evaluate(() => ({ width: innerWidth, height: innerHeight }))).toEqual({ width: 1180, height: 780 })
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(page.locator('#settings-section-title')).toHaveText('General')
    await page.getByRole('group', { name: 'Theme', exact: true }).getByRole('button', { name: 'Dark', exact: true }).click()
    await expect.poll(() => page.evaluate(() => matchMedia('(prefers-color-scheme: dark)').matches)).toBe(true)
    await expect(page.getByRole('navigation', { name: 'Settings sections', exact: true }).getByRole('button', { name: 'Advanced settings', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Advanced settings', exact: true }).click()
    await expect(page.locator('#settings-section-title')).toHaveText('Advanced settings')
    const body = page.locator('.settings-body')
    await expect(body.locator('.settings-section-header > h3')).toHaveText(presentation.categories)
    const selector = ':is(input, select, textarea, output, div)[id^="settings-curated-"]:not([id^="settings-curated-record-"])'
    const owners = body.locator(selector)
    await expect(owners).toHaveCount(presentation.fields.length)
    const paths = await owners.evaluateAll((elements) => elements.map((element) => decodeURIComponent(element.id.slice('settings-curated-'.length))))
    const categories = await body.locator('.settings-section-header > h3').allTextContents()
    assertAdvancedInventory(schema.fields, paths, categories, presentation)
    receipt.inventory = presentation.fields.map((entry) => ({ ...entry,
      schemaPaths: schema.fields.filter((field) => field.path === entry.path || field.path.startsWith(`${entry.path}.`)).map((field) => field.path) }))
    receipt.categories = categories
    // Export public Advanced metadata only, not the whole schema's credential/location fields.
    const advancedSchema = { schema_version: schema.schema_version, revision: schema.revision,
      fields: schema.fields.filter((field) => presentation.fields.some((entry) => field.path === entry.path || field.path.startsWith(`${entry.path}.`))) }
    writeFileSync(join(output, 'advanced-schema.json'), JSON.stringify(advancedSchema, null, 2) + '\n', { mode: 0o600 })
    receipt.schema = { revision: schema.revision, schemaVersion: schema.schema_version, fullFieldCount: schema.fields.length,
      advancedSchemaFieldCount: advancedSchema.fields.length, file: join(output, 'advanced-schema.json') }
    const values: unknown[] = []
    for (const entry of presentation.fields) {
      const field = schema.fields.find((field) => field.path === entry.path)
      const owner = page.locator(`[id=${JSON.stringify(`settings-curated-${encodeURIComponent(entry.path)}`)}]`)
      await expect(owner).toHaveCount(1)
      const row = owner.locator('xpath=ancestor-or-self::*[contains(concat(" ", normalize-space(@class), " "), " settings-row ")][1]')
      await expect(row.locator('.settings-row-label')).toHaveText(entry.label)
      await expect(row.locator('.settings-row-description')).toHaveText(entry.help)
      const observed = await owner.evaluate((element) => {
        const input = element as HTMLInputElement
        return { tag: element.tagName.toLowerCase(), type: input.type, value: input.value,
          checked: input.checked, min: input.min, max: input.max,
          options: element instanceof HTMLSelectElement ? Array.from(element.options, (option) => option.value) : undefined,
          optionDisabled: element instanceof HTMLSelectElement ? Array.from(element.options, (option) => option.disabled) : undefined,
          text: element.textContent?.trim(), structured: element.classList.contains('settings-structured'),
          recordKeys: Array.from(element.querySelectorAll(':scope > fieldset > legend'), (legend) => legend.textContent?.trim()) }
      })
      if (field && ['input', 'select', 'textarea'].includes(observed.tag)) {
        if (field.type === 'boolean') expect(observed.checked, entry.path).toBe(field.desired === true)
        else expect(observed.value, `${entry.path} must show REAL saved value`).toBe(field.desired == null ? ''
          : field.type === 'object' || field.type === 'array' ? JSON.stringify(field.desired, null, 2) : String(field.desired))
        if (field.enum) {
          const current = field.desired == null ? '' : String(field.desired)
          const placeholder = !field.enum.includes(current)
          expect(observed.options, `${entry.path} choices from real schema`).toEqual(placeholder ? [current, ...field.enum] : field.enum)
          expect(observed.optionDisabled, `${entry.path} unsupported-current placeholder must not become a choice`).toEqual(placeholder ? [true, ...field.enum.map(() => false)] : field.enum.map(() => false))
        }
        if (observed.tag === 'input' && ['integer', 'number'].includes(field.type)) {
          expect(observed.type).toBe('number')
          expect(observed.min).toBe(field.constraints.minimum === undefined ? '' : String(field.constraints.minimum))
          expect(observed.max).toBe(field.constraints.maximum === undefined ? '' : String(field.constraints.maximum))
        }
      } else if (!field) expect(observed.text).toContain('Read-only')
      else if (observed.tag === 'div') {
        expect(observed.structured, `${entry.path} retains its metadata-backed record editor`).toBe(true)
        expect(observed.recordKeys, `${entry.path} structured keys must be the REAL saved map`).toEqual(Object.keys(field.desired as object ?? {}))
      } else if (observed.tag === 'output') {
        expect(observed.text, `${entry.path} read-only value must be REAL saved value`).toBe(field.desired == null ? ''
          : field.type === 'object' || field.type === 'array' ? JSON.stringify(field.desired, null, 2) : String(field.desired))
      }
      values.push({ path: entry.path, observed })
    }
    receipt.editorChecks = values
    await expect(body.locator('.schema-form, [role="alert"]')).toHaveCount(0)
    const renderedSchema = await page.evaluate(async () => window.odin.settingsSchema())
    expect(renderedSchema.ok).toBe(true)
    if (renderedSchema.ok) expect(renderedSchema.result.fields).toEqual(schema.fields)
    const frames: (ScrollFrame & { sha256: string; width: number; viewportHeight: number })[] = []
    receipt.frames = frames
    await body.evaluate((element) => { element.scrollTop = 0 })
    for (let index = 0; index < 80; index++) {
      await page.evaluate(async () => {
        await document.fonts.ready
        await new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done())))
      })
      const frame = await body.evaluate((element, selector) => {
        const box = element.getBoundingClientRect()
        const visibleOwners = Array.from(element.querySelectorAll(selector))
          .filter((owner) => { const bounds = owner.getBoundingClientRect(); return bounds.height > 0 && bounds.bottom > box.top + 1 && bounds.top < box.bottom - 1 })
          .map((owner) => decodeURIComponent(owner.id.slice('settings-curated-'.length)))
        return { top: element.scrollTop, height: element.scrollHeight, client: element.clientHeight, visibleOwners,
          width: innerWidth, viewportHeight: innerHeight, overflow: element.scrollWidth > element.clientWidth + 1 }
      }, selector)
      expect(frame.overflow, 'Advanced must not overflow horizontally').toBe(false)
      expect({ width: frame.width, height: frame.viewportHeight }).toEqual({ width: 1180, height: 780 })
      const path = join(output, `1180x780-dark-advanced-scroll-${String(index + 1).padStart(2, '0')}.png`)
      await page.screenshot({ path, fullPage: false, animations: 'disabled', caret: 'hide', scale: 'css' })
      frames.push({ ...frame, path, sha256: hash(readFileSync(path)) })
      if (frame.top + frame.client >= frame.height - 1) break
      const target = Math.min(frame.height - frame.client, frame.top + Math.floor(frame.client * 0.8))
      await body.evaluate((element, top) => { element.scrollTop = top }, target)
      await expect.poll(() => body.evaluate((element) => element.scrollTop)).toBeCloseTo(target, 0)
    }
    assertAdvancedScrollCoverage(frames, paths)
    const afterSchema = await request(application, 'settings.schema')
    expect(afterSchema.ok).toBe(true)
    expect((afterSchema.result as ConfigMeta).revision, 'read-only capture must not write engine settings').toBe(schema.revision)
    receipt.app = await snapshot(application)
    await exitApp(application)
    application = undefined
    receipt.cleanup = { orderlyExit: true }
    receipt.outcome = 'passed'
  } catch (error) { receipt.outcome = 'failed'; receipt.error = String(error); throw error }
  finally {
    if (application) {
      try { await exitApp(application); receipt.cleanup = { orderlyExit: true } }
      catch (error) { receipt.cleanup = { orderlyExit: false, error: String(error) }; await application.close().catch(() => {}) }
    }
    writeFileSync(join(output, 'real-advanced-receipt.json'), JSON.stringify(receipt, null, 2) + '\n', { mode: 0o600 })
  }
})
