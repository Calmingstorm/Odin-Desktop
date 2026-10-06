// Development-only assertions, invoked exclusively by the isolated smoke runner.
// Exercise the named preload bridge and rendered app, not a second mock client.
import { strict as assert } from 'node:assert'
import { readFileSync, writeFileSync } from 'node:fs'
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
  for (const method of ['status.get', 'events.subscribe', 'runtime.shutdown', 'settings.schema', 'settings.set',
    'tools.list', 'tools.timeouts.get', 'personality.get', 'hosts.list', 'hosts.public_key',
    'memory.get', 'lists.list', 'knowledge.list', 'audit.query', 'logs.search', 'turn_state.list', 'usage.get',
    'skills.list', 'skills.save', 'skills.validate', 'mcp.status', 'mcp.save', 'mcp.tools', 'computer.status', 'computer.reconcile']) {
    assert(status.capabilities.includes(method), `${method} must be published by the real management core`)
  }

  // Later-slice reads are genuine core refusals, not empty successful lists.
  assert(!status.capabilities.includes('skills.test'), 'unwired skill execution must not be advertised')
  for (const method of ['work.list', 'schedules.list', 'skills.test']) {
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
  const count = (selector: string): Promise<number> => run(`document.querySelectorAll(${JSON.stringify(selector)}).length`)
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
  // Main now serves conversations. Only observe the genuinely empty profile here;
  // no model/account connection or full chat implementation is part of this slice.
  const conversations = await run<{ ok: boolean; result: { items: Array<{ id: string; title: string }> } }>('window.odin.listConversations()')
  assert(conversations.ok)
  // The app may create its initial real Chat conversation on mount. It is not
  // fixture history: compare real IDs and assert every transcript remains empty.
  for (const conversation of conversations.result.items) {
    const transcript = await run<{ ok: boolean; result: { items: unknown[] } }>(`window.odin.listMessages(${JSON.stringify({ conversation_id: conversation.id })})`)
    assert(transcript.ok)
    assert.deepEqual(transcript.result.items, [])
  }
  await until(async () => !(await text('nav[aria-label="Conversations"]')).includes('Loading'), 'empty real conversations')
  screens.push({ screen: 'Chat / empty real profile', text: await text('.main') })
  assert.equal(await run('document.querySelectorAll(".conv-row").length'), conversations.result.items.length, 'sidebar must reflect real core state, never fixture conversations')

  // Slash commands remain useful without chat. Exercise the actual command
  // palette and bridge; /status and /usage now use real step-five observations.
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
      await until(async () => (await text('.composer .panel-text')).length > 0, '/usage report')
      screens.push({ screen: '/usage', text: await text('.composer .panel-text') })
      await click('.composer .panel button')
    }
  }

  await click('button[title="Search all conversations (Ctrl+Shift+F)"]')
  await run(`(() => {
    const input = document.querySelector('.search-form input');
    input.value = 'smoke query'; input.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('.search-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  })()`)
  await until(async () => (await text('.search-panel')).includes('No matches.'), 'real empty search')
  screens.push({ screen: 'Search / empty real profile', text: await text('.search-panel') })
  assert.equal(await run('document.querySelectorAll(".search-hits li").length'), 0)
  await click('.work-toggle')
  await recordUnavailable('Work', '.work-panel')
  assert.equal(await run('document.querySelectorAll(".work-item").length'), 0)
  writeFileSync(out, (await win.webContents.capturePage()).toPNG())

  await click('button[title="Settings (Ctrl+,)"]')
  await until(async () => (await run<number>('document.querySelectorAll(".settings-nav-item").length')) > 1, 'settings navigation')
  await until(async () => (await count('.settings-group .schema-form')) > 0, 'real settings schema before enumerating all sections')
  const sections = await run<string[]>('Array.from(document.querySelectorAll(".settings-nav-item"), b => b.innerText)')
  for (const expected of ['General', 'Models and providers', 'Personality', 'Tools', 'Skills', 'MCP servers', 'Hosts and trust', 'Scheduled and running work', 'State', 'Records', 'Other']) {
    assert(sections.includes(expected), `missing settings section ${expected}`)
  }
  const servicePanels: Record<string, string[]> = {
    'Scheduled and running work': ['section[aria-label="Schedules"]', 'section[aria-label="Running work"]']
  }
  const observations = await run<Record<string, { ok: boolean; result?: unknown; error?: { code: string; message: string } }>>(`(async () => ({
    settings: await window.odin.settingsSchema(), hosts: await window.odin.hostsList({}),
    key: await window.odin.hostsPublicKey({}), tools: await window.odin.toolsList({}),
    timeouts: await window.odin.toolsTimeoutsGet({}), personality: await window.odin.personalityGet({}),
    memory: await window.odin.memoryList({}), lists: await window.odin.listsList({}),
    knowledge: await window.odin.knowledgeList({}), audit: await window.odin.auditQuery({}),
    logs: await window.odin.logsSearch({ level: 'all' }), turns: await window.odin.turnStateList({}),
    usage: await window.odin.usage('7d'), accounts: await window.odin.codexAccounts()
  }))()`)
  for (const [name, answer] of Object.entries(observations)) {
    if (name === 'accounts') {
      assert(answer.ok || answer.error?.code === 'keyring_unavailable', 'accounts must report empty accounts or distinct keyring failure')
    } else assert(answer.ok, `named bridge ${name} failed: ${JSON.stringify(answer.error)}`)
  }
  const hostData = observations.hosts!.result as { hosts: Array<{ alias: string; trust_state: string }>; default_host: string }
  assert.equal(hostData.hosts.length, 1, 'fresh core must have only its actual local host')
  assert.equal(hostData.hosts[0]!.alias, 'localhost')
  assert.equal(hostData.hosts[0]!.trust_state, 'local')
  assert.equal(hostData.default_host, 'localhost')
  assert.deepEqual(observations.audit!.result, [], 'fresh audit must have no invented tool records')
  assert.deepEqual((observations.logs!.result as { entries: unknown[] }).entries, [])
  assert.equal((observations.turns!.result as { availability: string }).availability, 'not_enabled')
  // All operations cross the named preload bridge. The fixture is local stdio,
  // implements initialize/tools-list, and has no account or network listener.
  const invoke = <T = unknown>(name: string, params: unknown = {}): Promise<T> =>
    run(`window.odin[${JSON.stringify(name)}](${JSON.stringify(params)})`)
  type Answer = { ok: boolean; result?: unknown; error?: { code: string; message: string } }
  const observedService = async (name: string, params: unknown = {}): Promise<unknown> => {
    const answer = await invoke<Answer>(name, params)
    assert(answer.ok, `${name}: ${JSON.stringify(answer.error)}`)
    observations[name] = answer
    return answer.result
  }
  const skillCode = readFileSync(process.env.ODIN_SMOKE_SKILL_FIXTURE!, 'utf8')
  const validation = await observedService('skillsValidate', { code: skillCode }) as { valid: boolean }
  assert(validation.valid, 'harmless constant must validate')
  await observedService('skillsSave', { name: 'slice4_constant', code: skillCode, create: true })
  const skill = await observedService('skillsGet', { name: 'slice4_constant' }) as { code: string }
  assert.equal(skill.code, skillCode)
  const unavailableTest = await invoke<Answer>('skillsTest', { name: 'slice4_constant' })
  assert(!unavailableTest.ok && unavailableTest.error?.code === 'capability_unavailable', 'named skill test must honestly refuse, never claim execution')
  observations.skillsTest = unavailableTest
  type McpStatus = { revision: string; server_count: number; servers: Array<{ name: string; state: string; published_count: number }> }
  const mcpMutation = async (name: string, params: Record<string, unknown>): Promise<void> => {
    const before = await observedService('mcpStatus') as McpStatus
    await observedService(name, { ...params, expected_revision: before.revision })
  }
  await mcpMutation('mcpSave', { name: 'slice4_local', transport: 'stdio', command: process.env.ODIN_DESKTOP_ENGINE_PYTHON, args: ['-B', process.env.ODIN_SMOKE_MCP_FIXTURE] })
  await mcpMutation('mcpSetGlobalEnabled', { enabled: true })
  await until(async () => (await observedService('mcpStatus') as McpStatus).servers.some((row) => row.name === 'slice4_local' && row.state === 'connected'), 'real stdio MCP handshake')
  const tools = await observedService('mcpTools', { name: 'slice4_local' }) as { tools: unknown[] }
  assert.equal(tools.tools.length, 1, 'real discovery must publish the constant tool')
  assert(JSON.stringify(tools.tools).includes('constant'))
  await mcpMutation('mcpRefreshTools', { name: 'slice4_local' })
  const computer = await observedService('computerStatus') as { session: unknown; readiness: { input_supported: boolean; native_qualified: boolean } }
  assert.equal(computer.session, null)
  assert.equal(computer.readiness.input_supported, false)
  assert.equal(computer.readiness.native_qualified, false)
  const health = await observedService('healthGet') as { browser: { state: string; ready: boolean; retry_available: boolean } }
  assert.deepEqual({ state: health.browser.state, ready: health.browser.ready, retry_available: health.browser.retry_available }, { state: 'disabled', ready: false, retry_available: false })
  for (let i = 0; i < sections.length; i++) {
    await click(`.settings-nav-item:nth-of-type(${i + 2})`)
    if (sections[i] === 'Models and providers') {
      await until(async () => !(await text('.codex-accounts')).includes('Loading'), 'real account observation')
      assert(!/not (?:yet )?available|not served/i.test(await text('.codex-accounts')), 'served account management must not remain capability-unavailable')
      assert.equal(await run('document.querySelectorAll(".account").length'), 0, 'real session must not display fixture accounts')
      await until(async () => (await run<number>('document.querySelectorAll(".schema-form").length')) > 0, 'real provider settings')
    }
    if (sections[i] === 'Personality') {
      await until(async () => await run<boolean>('Boolean(document.querySelector("section[aria-label=Personality] select"))'), 'real personality settings')
    }
    if (sections[i] === 'Tools') {
      await until(async () => (await count('section[aria-label="Built-in tools"] .manage-row')) > 0, 'real built-in tools')
      assert((await text('section[aria-label="Tool timeouts"]')).includes('Timeouts'))
      await until(async () => /disabled/i.test(await text('section[aria-label="Browser runtime"]')), 'real disabled browser state')
    }
    if (sections[i] === 'Skills') {
      await until(async () => (await text('section[aria-label="Skills"]')).includes('slice4_constant'), 'real skill card')
      assert((await text('section[aria-label="Skills"]')).includes('Test is unavailable in this core.'), 'unwired skill test must be explicit')
    }
    if (sections[i] === 'MCP servers') {
      await until(async () => (await text('section[aria-label="MCP servers"]')).includes('slice4_local'), 'real MCP row')
      assert((await text('section[aria-label="MCP servers"]')).includes('connected'), 'MCP UI must show real handshake state')
      await click('button[aria-label="Tools for slice4_local"]')
      await until(async () => (await text('.mcp-tools')).includes('constant'), 'rendered real MCP tools disclosure')
    }
    if (sections[i] === 'Hosts and trust') {
      await until(async () => (await text('section[aria-label=Hosts]')).includes('localhost'), 'real localhost row')
      assert.equal(await run('document.querySelector("section[aria-label=Hosts] select").value'), 'localhost')
      await until(async () => (await text('section[aria-label="Odin\'s key"]')).includes('ssh-ed25519'), 'fresh provisioned SSH public key')
    }
    for (const selector of servicePanels[sections[i]!] ?? []) {
      await recordUnavailable(`Settings / ${sections[i]} / ${selector}`, selector)
    }
    if (sections[i] === 'State') {
      // Context reload is deliberately on demand, not a screen-mount side effect.
      await click('section[aria-label="Context"] button')
      await until(async () => !(await text('section[aria-label="Context"]')).includes('Reloading…') && /reload|loaded|context/i.test(await text('section[aria-label="Context"]')), 'real context reload')
      assert(!(await text('.settings-body')).includes('Loading'))
      assert((await text('section[aria-label="Named lists"]')).includes('No lists.'))
    }
    if (sections[i] === 'Records') {
      await until(async () => (await text('section[aria-label=Audit]')).includes('Nothing recorded.'), 'real empty audit')
      await until(async () => (await text('section[aria-label=Logs]')).includes('No entries.'), 'real empty logs')
      await until(async () => (await text('section[aria-label="Turn state"]')).includes('Turn state is off.'), 'real turn-state availability')
      assert((await text('section[aria-label="Health"]')).includes('host(s) configured'), 'real health must observe profile hosts')
      await until(async () => /no .*session|no .*task/i.test(await text('section[aria-label="Computer use"]')), 'real absent computer session')
      assert(/unqualified|not qualified|qualification/i.test(await text('section[aria-label="Computer use"]')), 'computer input must remain explicitly unqualified')
    }
    assert(!(await text('.settings-body')).includes('Service is not available yet'), `${sections[i]} must not leak a generic capability refusal`)
    screens.push({ screen: `Settings / ${sections[i]}`, text: await text('.settings-body') })
    if (i === 0) {
      assert((await text('.settings-body')).includes('Start Odin when you log in'), 'app-local settings remain available')
    }
    writeFileSync(out.replace(/\.png$/i, '') + `-settings-${i + 1}.png`, (await win.webContents.capturePage()).toPNG())
  }
  writeFileSync(out.replace(/\.png$/i, '') + '-settings.png', (await win.webContents.capturePage()).toPNG())
  await observedService('skillsDelete', { name: 'slice4_constant' })
  await mcpMutation('mcpSetGlobalEnabled', { enabled: false })
  await mcpMutation('mcpDelete', { name: 'slice4_local' })
  assert.equal(broker.linkState, 'ready')
  writeFileSync(out.replace(/\.png$/i, '') + '-evidence.json', JSON.stringify({ link: broker.linkState, status, observations, screens }, null, 2) + '\n')
  process.stdout.write(`real-core-smoke: evidence ${JSON.stringify({ link: broker.linkState, status, screens: screens.map(({ screen }) => screen), observations: Object.fromEntries(Object.entries(observations).map(([name, answer]) => [name, answer.ok ? 'observed' : answer.error?.code])) })}\n`)
  process.stdout.write(`real-core-smoke: ok link=ready version=${status.version} screens=${screens.length}\n`)
}
