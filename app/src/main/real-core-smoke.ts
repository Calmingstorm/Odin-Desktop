// Development-only assertions, invoked exclusively by the isolated smoke runner.
// Exercise the named preload bridge and rendered app, not a second mock client.
import { strict as assert } from 'node:assert'
import { writeFileSync } from 'node:fs'
import type { BrowserWindow } from 'electron'
import type { Broker } from './broker'

const pause = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

export async function realCoreSmoke(win: BrowserWindow, broker: Broker, out: string): Promise<void> {
  const deadline = Date.now() + 30_000
  while (broker.linkState !== 'ready' || win.webContents.isLoading()) {
    assert(Date.now() < deadline, 'real-core smoke timed out waiting for the app and handshake')
    await pause(100)
  }
  const result = await broker.request('status.get')
  assert(result.ok, 'real status.get must succeed')
  const status = result.result as { phase: string; version: string; core_instance_id: string; capabilities: string[] }
  assert.equal(status.phase, 'ready')
  assert.equal(status.core_instance_id, broker.coreInstanceId)
  assert.equal(status.version, process.env.ODIN_SMOKE_EXPECT_VERSION ?? '0.1.0.dev1')
  assert.deepEqual(status.capabilities, ['status.get', 'events.subscribe', 'runtime.shutdown'])

  // Later-slice reads are genuine core refusals, not empty successful lists.
  for (const method of ['conversations.list', 'search.query', 'work.list', 'settings.schema', 'codex.accounts.list', 'usage.get']) {
    const refused = await broker.request(method)
    assert(!refused.ok && refused.error.code === 'capability_unavailable', `${method} must honestly refuse`)
  }

  const run = async <T = unknown>(script: string): Promise<T> => {
    try {
      return await win.webContents.executeJavaScript(script, true) as T
    } catch (error) {
      throw new Error(`UI assertion failed: ${script}: ${String(error)}`)
    }
  }
  const text = (selector: string): Promise<string> => run(`document.querySelector(${JSON.stringify(selector)})?.innerText ?? ''`)
  const click = async (selector: string): Promise<void> => {
    assert(await run(`Boolean(document.querySelector(${JSON.stringify(selector)}))`), `missing UI control ${selector}`)
    await run(`document.querySelector(${JSON.stringify(selector)}).click()`)
  }
  const until = async (predicate: () => Promise<boolean>, label: string): Promise<void> => {
    const end = Date.now() + 8_000
    while (!await predicate()) {
      if (Date.now() >= end) {
        writeFileSync(out, (await win.webContents.capturePage()).toPNG())
        throw new Error(`real-core smoke: UI did not settle for ${label}. Rendered page: ${await text('body')}`)
      }
      await pause(100)
    }
  }
  const screens: Array<{ screen: string; text: string }> = []
  const unavailable = /not (?:yet )?available|unavailable|not served|later (?:step|slice)/i
  const recordUnavailable = async (screen: string, selector: string): Promise<void> => {
    await until(async () => unavailable.test(await text(selector)), screen)
    const rendered = await text(selector)
    assert(!/Loading…|Searching…/.test(rendered), `${screen} is still loading`)
    assert(!/Service is not available yet/.test(rendered), `${screen} presents a generic core error instead of an unavailable state`)
    screens.push({ screen, text: rendered })
  }

  await until(async () => (await text('.status')).includes(status.version), 'real core status bar')
  screens.push({ screen: 'Status', text: await text('.status') })
  await recordUnavailable('Chat and conversations', '.main')
  await recordUnavailable('Conversation sidebar', 'nav[aria-label="Conversations"]')
  const sidebarInset = await run<number>(`(() => {
    const nav = document.querySelector('nav[aria-label="Conversations"]').getBoundingClientRect();
    return document.querySelector('.sidebar-notice').getBoundingClientRect().left - nav.left;
  })()`)
  assert(sidebarInset >= 12, 'conversation unavailable notice must retain the sidebar inset')
  assert.equal(await run('document.querySelectorAll(".conv-row").length'), 0, 'real session must never seed fixture conversations')
  assert(await run('document.querySelector(".composer button[type=submit]")?.disabled === true'), 'unavailable chat must not offer a sendable composer')
  assert(await run(`document.querySelector(${JSON.stringify('button[aria-label="Attach files"]')})?.disabled === true`), 'unavailable chat must not offer attachments')
  await click('button[title="New conversation"]')
  await until(async () => unavailable.test(await text('.composer .notice:last-child')), 'new conversation refusal')
  assert.equal(await run('document.querySelectorAll(".conv-row").length'), 0, 'refused creation must not invent a conversation')

  // Slash commands remain useful without chat. Exercise the actual command
  // palette and bridge; /status must use served fields, /usage must refuse.
  for (const command of ['/status', '/usage']) {
    await run(`(() => {
      const input = document.querySelector('.composer textarea');
      input.value = ${JSON.stringify(command)}; input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`)
    await pause(50)
    await run(`document.querySelector('.composer form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))`)
    if (command === '/status') {
      await until(async () => (await text('.composer .panel-text')).includes(status.version), '/status report')
      screens.push({ screen: '/status', text: await text('.composer .panel-text') })
      await click('.composer .panel button')
    } else {
      await until(async () => /Usage.*unavailable/i.test(await text('.status')), '/usage refusal in the status bar')
      assert(!/Usage.*unavailable/i.test(await text('.composer')), 'usage refusal must not be duplicated below the composer')
      screens.push({ screen: '/usage', text: await text('.status') })
    }
  }

  await click('button[title="Search all conversations (Ctrl+Shift+F)"]')
  await run(`(() => {
    const input = document.querySelector('.search-form input');
    input.value = 'smoke query'; input.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('.search-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  })()`)
  await recordUnavailable('Search', '.search-panel')
  assert.equal(await run('document.querySelectorAll(".search-hits li").length'), 0)
  await click('.work-toggle')
  await recordUnavailable('Work', '.work-panel')
  assert.equal(await run('document.querySelectorAll(".work-item").length'), 0)
  writeFileSync(out, (await win.webContents.capturePage()).toPNG())

  await click('button[title="Settings (Ctrl+,)"]')
  await until(async () => (await run<number>('document.querySelectorAll(".settings-nav-item").length')) > 1, 'settings navigation')
  const sections = await run<string[]>('Array.from(document.querySelectorAll(".settings-nav-item"), b => b.innerText)')
  assert.deepEqual(sections, ['General', 'Models and providers', 'Personality', 'Tools', 'Skills', 'MCP servers', 'Hosts and trust', 'Scheduled and running work', 'State', 'Records', 'Other'])
  // These are the new screens' own service reads, not just the outer settings.schema refusal.
  const servicePanels: Record<string, string[]> = {
    'Models and providers': ['.codex-accounts'],
    Personality: ['section[aria-label="Personality"]'],
    Tools: ['section[aria-label="Built-in tools"]', 'section[aria-label="Tool timeouts"]'],
    Skills: ['section[aria-label="Skills"]'],
    'MCP servers': ['section[aria-label="MCP servers"]'],
    'Hosts and trust': ['section[aria-label="Hosts"]'],
    'Scheduled and running work': ['section[aria-label="Schedules"]', 'section[aria-label="Running work"]'],
    State: ['section[aria-label="Memory"]', 'section[aria-label="Named lists"]', 'section[aria-label="Knowledge"]'],
    Records: ['section[aria-label="Health"]', 'section[aria-label="Usage"]', 'section[aria-label="Audit"]', 'section[aria-label="Logs"]', 'section[aria-label="Turn state"]', 'section[aria-label="Computer use"]']
  }
  for (let i = 0; i < sections.length; i++) {
    await click(`.settings-nav-item:nth-of-type(${i + 2})`)
    if (sections[i] === 'Models and providers') {
      await until(async () => /Codex accounts.*unavailable/i.test(await text('.codex-accounts')), 'account capability refusal')
      assert(!(await text('.codex-accounts')).includes('Add account'), 'unavailable accounts must not offer login')
      assert.equal(await run('document.querySelectorAll(".account").length'), 0, 'real session must not display fixture accounts')
    }
    for (const selector of servicePanels[sections[i]!] ?? []) {
      await recordUnavailable(`Settings / ${sections[i]} / ${selector}`, selector)
    }
    if (sections[i] === 'State') {
      // Context reload is deliberately on demand, not a screen-mount side effect.
      await click('section[aria-label="Context"] button')
      await recordUnavailable('Settings / State / Context reload', 'section[aria-label="Context"]')
      assert.equal(await run('document.querySelectorAll("section[aria-label=Context] button").length'), 0, 'refused context reload must not remain offered')
    }
    await recordUnavailable(`Settings / ${sections[i]}`, '.settings-body')
    assert.equal(await run('document.querySelectorAll(".settings-body .warn, .settings-body [role=alert]").length'), 0, `${sections[i]} must not present capability refusal as a fault`)
    assert.equal(await run('document.querySelectorAll(".settings-body .manage-row, .settings-body .work-item, .settings-body .account").length'), 0, `${sections[i]} must not display cached or fixture rows`)
    assert(!/No schedules yet|No lists\.|Nothing recorded\.|Nothing preserved\.|No servers\.|No entries\./.test(await text('.settings-body')), `${sections[i]} must not claim a successful empty read`)
    assert.equal(await run('document.querySelectorAll(".settings-group .schema-form").length'), 0, 'unavailable core settings must not use a fixture schema')
    if (i === 0) {
      assert((await text('.settings-body')).includes('Start Odin when you log in'), 'app-local settings remain available')
    }
    writeFileSync(out.replace(/\.png$/i, '') + `-settings-${i + 1}.png`, (await win.webContents.capturePage()).toPNG())
  }
  writeFileSync(out.replace(/\.png$/i, '') + '-settings.png', (await win.webContents.capturePage()).toPNG())
  assert.equal(broker.linkState, 'ready')
  writeFileSync(out.replace(/\.png$/i, '') + '-evidence.json', JSON.stringify({ link: broker.linkState, status, screens }, null, 2) + '\n')
  process.stdout.write(`real-core-smoke: evidence ${JSON.stringify({ link: broker.linkState, status, screens })}\n`)
  process.stdout.write(`real-core-smoke: ok link=ready version=${status.version} screens=${screens.length}\n`)
}
