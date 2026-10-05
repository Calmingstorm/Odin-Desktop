// Development-only proof through the rendered app and named preload bridge.
import { strict as assert } from 'node:assert'
import { randomUUID } from 'node:crypto'
import { readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { dialog, type BrowserWindow } from 'electron'
import type { Broker } from './broker'

const pause = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))
interface SmokeMessage { id: string; role: string; text: string; request_id?: string; attachments?: unknown[]; artifacts?: unknown[] }

export async function realCoreSmoke(win: BrowserWindow, broker: Broker, out: string): Promise<void> {
  const root = process.env.ODIN_REAL_CORE_ROOT
  assert(root && process.env.HOME === root && root.startsWith('/tmp/odrc-'), 'smoke requires disposable HOME')
  assert(process.getuid?.() !== 0, 'smoke must not run as root')
  assert(process.env.ODIN_REAL_CORE_OUTER_PID_NS && readlinkSync('/proc/self/ns/pid') !== process.env.ODIN_REAL_CORE_OUTER_PID_NS,
    'smoke requires the isolated PID namespace runner')
  assert(readFileSync('/proc/1/cmdline', 'utf8').split('\0').includes('--inside-run'), 'unexpected isolation owner')
  assert(process.env.ODIN_SMOKE_REAL_CORE === '1' && process.argv.includes('--smoke-test'), 'development smoke only')
  const events: Array<{ type: string; payload: Record<string, unknown> }> = []
  const observe = (event: { type: string; payload: Record<string, unknown> }): void => { events.push(event) }
  broker.on('event', observe)
  const screens: Array<{ screen: string; text: string }> = []
  const evidence: Record<string, unknown> = {
    isolation: { home: 'throwaway', pidNamespace: 'private', display: 'xvfb' },
    provider: 'canned loopback OpenAI-compatible, real provider client, no accounts',
    limitations: ['File/save chooser selections injected in main under isolation; native chooser UI not tested.',
      'No default-app launch or folder reveal. Resume without a durable checkpoint not claimed successful.']
  }
  const run = async <T = unknown>(script: string): Promise<T> => {
    try { return await win.webContents.executeJavaScript(script, true) as T }
    catch (error) { throw new Error(`UI assertion failed: ${script}: ${String(error)}`) }
  }
  const text = (selector: string): Promise<string> => run(`document.querySelector(${JSON.stringify(selector)})?.innerText ?? ''`)
  const click = async (selector: string): Promise<void> => {
    assert(await run(`Boolean(document.querySelector(${JSON.stringify(selector)}))`), `missing UI control ${selector}`)
    await run(`document.querySelector(${JSON.stringify(selector)}).click()`)
  }
  const until = async (predicate: () => Promise<boolean>, label: string, timeout = 15_000): Promise<void> => {
    const end = Date.now() + timeout
    while (!await predicate()) {
      if (Date.now() >= end) throw new Error(`UI did not settle for ${label}. Rendered page: ${await text('body')}`)
      await pause(100)
    }
  }
  const record = async (screen: string, selector: string): Promise<void> => { screens.push({ screen, text: await text(selector) }) }
  const bridge = <T = unknown>(method: string, params?: unknown): Promise<T> =>
    run(`window.odin[${JSON.stringify(method)}](${params === undefined ? '' : JSON.stringify(params)})`)
  let activeCid = ''
  const setInput = async (selector: string, value: string): Promise<void> => {
    await run(`(() => { const input = document.querySelector(${JSON.stringify(selector)}); input.value = ${JSON.stringify(value)}; input.dispatchEvent(new Event('input', { bubbles: true })); })()`)
    await pause(50)
  }
  const send = async (value: string): Promise<void> => {
    await setInput('.composer textarea', value)
    await until(() => run('document.querySelector(".composer button[type=submit]")?.disabled === false'), 'sendable composer')
    await run('document.querySelector(".composer form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))')
    await until(() => run('document.querySelector(".composer textarea").value === ""'), 'submit admission/receipt')
  }
  const idle = (): Promise<void> => until(async () => {
    const snapshot = await bridge<{ ok: boolean; result: { running: unknown; queued: unknown[]; recent: Array<{ request_id: string }>; messages: { items: SmokeMessage[] } } }>('snapshotConversation', { conversation_id: activeCid })
    if (!snapshot.ok || snapshot.result.running || snapshot.result.queued.length) return false
    const last = snapshot.result.messages.items.filter((m) => m.role === 'user').at(-1)
    return Boolean(last && snapshot.result.recent.some((r) => r.request_id === last.request_id)) && await run<boolean>('!document.querySelector(".composer button.danger")')
  }, 'settled real request')
  const originalOpen = dialog.showOpenDialog
  const originalSave = dialog.showSaveDialog
  try {
    await until(async () => broker.linkState === 'ready' && !win.webContents.isLoading() && await run<boolean>('Boolean(window.odin)'), 'app handshake', 30_000)
    const response = await bridge<{ ok: boolean; result: { phase: string; version: string; capabilities: string[] } }>('status')
    assert(response.ok)
    const status = response.result
    assert.equal(status.phase, 'ready')
    // Assert advertised method names as well as their actual bridge results.
    for (const method of ['submission.send', 'control.stop', 'control.steer', 'conversations.reset_context',
      'attachments.begin', 'attachments.commit', 'tool.detail', 'tool.output', 'search.query']) {
      assert(status.capabilities.includes(method), `real core capability missing: ${method}`)
    }
    evidence.status = status
    await until(async () => (await text('.status')).includes(status.version), 'real status bar')
    // The renderer legitimately creates its first conversation on an empty
    // served core. Never confuse that successful command with fixture seeding.
    if (await run<number>('document.querySelectorAll(".conv-row").length') === 0) await click('button[title="New conversation"]')
    await until(() => run('document.querySelectorAll(".conv-row").length === 1 && !document.querySelector(".composer textarea")?.disabled'), 'real conversation creation')
    await until(async () => !(await text('.composer')).includes('Loading this conversation'), 'snapshot catch-up')
    const conversations = await bridge<{ ok: boolean; result: { items: Array<{ id: string }> } }>('listConversations')
    assert(conversations.ok)
    const cid = conversations.result.items[0]!.id
    activeCid = cid
    evidence.conversationId = cid
    const snapshot = async (): Promise<{ messages: SmokeMessage[] }> => {
      const result = await bridge<{ ok: boolean; result: { messages: { items: SmokeMessage[] } } }>('snapshotConversation', { conversation_id: cid })
      assert(result.ok, 'actual snapshot bridge succeeds')
      return { messages: result.result.messages.items }
    }

    await send('[reply] smoke-search-needle')
    await until(async () => (await text('.msg.assistant .body')).includes('Canned provider reply:'), 'D9 committed reply')
    await idle()
    const replied = (await snapshot()).messages.find((m) => m.role === 'assistant')
    assert(replied?.request_id && replied.text, 'reply is a real committed request-bound assistant message')
    evidence.guardedReply = replied
    await record('Guarded reply', '.messages')

    await send('[paged-tool]')
    await until(() => run('document.querySelectorAll(".tools-toggle").length > 0'), 'real tool card')
    await idle()
    await click('.tools-toggle')
    await until(() => run('Boolean(document.querySelector(".tool-row"))'), 'tool row')
    await click('.tool-row')
    await until(async () => (await text('.tool-detail')).includes('preview') || await run<boolean>('Boolean(document.querySelector(".tool-output button"))'), 'real tool details')
    let pages = 0
    if (await run('Boolean(document.querySelector(".tool-output button"))')) {
      await click('.tool-output button')
      await until(() => run('Boolean(document.querySelector(".tool-output pre"))'), 'retained first page')
      pages = 1
    }
    while (await run('Boolean(document.querySelector(".tool-output button"))')) {
      assert(pages < 20, 'paging must reach EOF')
      const old = await run<number>('document.querySelector(".tool-output pre").innerText.length')
      await click('.tool-output button')
      await until(() => run(`!document.querySelector('.tool-output button') || document.querySelector('.tool-output pre').innerText.length > ${old}`), 'retained next page')
      pages++
    }
    evidence.outputPaging = { pages, finalLength: await run<number>('document.querySelector(".tool-output pre")?.innerText.length ?? 0'),
      ...(pages === 0 ? { limitation: 'Real core tool.detail supplied preview only, no retained output cursor; rendered paging unavailable.' } : {}) }
    assert(pages > 1, 'canned retained output must exercise multiple real pages')
    const fullOutput = await text('.tool-output pre')
    assert(fullOutput.includes('Evidence line 0000:') && fullOutput.includes('Evidence line 0899:'), 'paging reaches both ends of real retained evidence')
    assert.equal(fullOutput.match(/Evidence line 0000:/g)?.length, 1, 'paging never appends the first page twice')
    await record('Tool details and retained output', '.tool-detail')
    await click('.tools-toggle')

    const attachment = join(root, 'smoke-upload.txt')
    writeFileSync(attachment, 'Real adapter chunked upload smoke.\n'.repeat(20_000))
    assert(status.capabilities.includes('attachments.chunk'))
    evidence.attachmentTransfer = { bytes: 700_000, chunkBytes: (response.result as typeof status & { limits: { chunk_bytes: number } }).limits.chunk_bytes,
      selection: 'main-injected disposable file picker; actual Attach UI and app adapter' }
    assert((evidence.attachmentTransfer as { chunkBytes: number }).chunkBytes < 700_000, 'attachment requires multiple protocol chunks')
    // Main-only selection. Stage/begin/chunk/commit/request claim remain real.
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [attachment] })) as typeof dialog.showOpenDialog
    await click('button[title="Attach files"]')
    await until(() => run('Boolean(document.querySelector(".attachment.ready"))'), 'actual chunked attachment commit')
    await record('Attachment committed through app adapter', '.attachments')
    dialog.showOpenDialog = originalOpen
    await send('[reply] attachment receipt')
    await until(async () => (await text('.msg-attachments')).includes('smoke-upload.txt'), 'posted attachment')
    await idle()
    const attached = (await snapshot()).messages.find((m) => m.attachments?.length)
    assert(attached?.attachments?.length === 1, 'durable message claims committed attachment')
    evidence.attachment = attached

    await send('[artifact]')
    await until(() => run('Boolean(document.querySelector(".msg .file-card"))'), 'real posted file')
    await idle()
    const saved = join(root, 'saved-artifact.txt')
    dialog.showSaveDialog = (async () => ({ canceled: false, filePath: saved })) as typeof dialog.showSaveDialog
    await click('.msg .file-card .file-actions button:nth-child(2)')
    await until(async () => (await text('.msg .file-card')).includes('Saved.'), 'actual artifact save bridge')
    assert(readFileSync(saved).length > 0, 'artifact downloaded into disposable path')
    dialog.showSaveDialog = originalSave
    await record('Posted file and download', '.msg .file-card')
    await until(() => run('Boolean(document.querySelector(".artifact-image img"))'), 'posted image through actual artifact adapter')
    evidence.postedImage = await run('document.querySelector(".artifact-image img")?.complete && document.querySelector(".artifact-image img")?.naturalWidth > 0')
    assert(evidence.postedImage, 'posted image really decodes')

    await send('[fail]')
    await until(async () => (await snapshot()).messages.some((m) => m.text === '[fail]'), 'failure request admitted')
    await idle()
    const failedMessages = (await snapshot()).messages
    const failedRequest = failedMessages.filter((m) => m.role === 'user' && m.text === '[fail]').at(-1)?.request_id
    const failureState = await bridge<{ ok: boolean; result: { recent: Array<{ request_id: string; outcome: string }> } }>('snapshotConversation', { conversation_id: cid })
    assert(failureState.ok && failureState.result.recent.some((r) => r.request_id === failedRequest && r.outcome === 'failed'), 'provider failure is a real terminal failure')
    evidence.providerFailureRendered = failedMessages.filter((m) => m.request_id === failedRequest)
    const failure = failedMessages.find((m) => m.role === 'notice' && m.request_id === failedRequest && /fail|error|couldn't|unable/i.test(m.text))
    evidence.failureNotice = failure ?? { limitation: 'Base real core terminates provider failure without committing the later #22 failure notice; not qualified.' }
    if (!failure) process.stdout.write('real-core-smoke: limitation: base core provider failure notice is not yet served; terminal failure only.\n')
    await record('Provider failure outcome', '.messages')
    await send('[hold-stop]')
    await until(() => run('Boolean(document.querySelector(".composer button.danger"))'), 'running Stop control')
    const stopTarget = await bridge<{ ok: boolean; result: { running: { request_id: string; generation: number } | null } }>('snapshotConversation', { conversation_id: cid })
    assert(stopTarget.ok && stopTarget.result.running, 'Stop bound to real running request')
    const stopId = stopTarget.result.running.request_id
    await click('.composer button.danger')
    await idle()
    await record('Stop receipt and outcome', '.messages')
    await until(async () => events.some((e) => /request\.(?:cancelled|interrupted|suspended)/.test(e.type) && e.payload.request_id === stopId), 'Stop terminal event for exact request')
    evidence.stoppedRequest = stopTarget.result.running
    const stoppedSnapshot = await bridge<{ ok: boolean; result: { recent: Array<{ request_id: string; generation: number }> } }>('snapshotConversation', { conversation_id: cid })
    assert(stoppedSnapshot.ok)
    const stopped = stoppedSnapshot.result.recent.at(-1)!
    const resume = await bridge<{ ok: boolean; result?: { disposition: string; reason?: string }; error?: unknown }>('resumeRequest', {
      control_command_id: randomUUID(), conversation_id: cid, request_id: stopped.request_id, generation: stopped.generation
    })
    evidence.resumeWithoutCheckpoint = resume
    assert(resume.ok && resume.result?.disposition === 'rejected' && resume.result.reason === 'not_resumable', `Resume must honestly deny a terminal cancelled task: ${JSON.stringify(resume)}`)

    await send('[hold-steer]')
    await until(() => run('Boolean(document.querySelector(".composer button.danger"))'), 'running Steer control')
    const steerTarget = await bridge<{ ok: boolean; result: { running: { request_id: string; generation: number } | null } }>('snapshotConversation', { conversation_id: cid })
    assert(steerTarget.ok && steerTarget.result.running)
    const queueStart = events.length
    await click('.composer input[value="queue"]')
    await send('[reply] queued smoke follow-up')
    await until(async () => events.slice(queueStart).some((e) => e.type === 'request.queued' && e.payload.conversation_id === cid), 'real queued follow-up')
    await click('.composer input[value="steer"]')
    await send('smoke steering instruction')
    await until(async () => /waiting for Odin|Odin has read|not used/.test(await text('.messages')), 'Steer receipt')
    await record('Steer receipt before release', '.messages')
    assert(process.env.ODIN_SMOKE_PROVIDER_BASE_URL?.startsWith('http://127.0.0.1:'), 'loopback only')
    const released = await fetch(new URL('/release', process.env.ODIN_SMOKE_PROVIDER_BASE_URL), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: '[hold-steer]' })
    })
    assert(released.ok, 'held response release')
    await idle()
    await until(async () => events.some((e) => e.type === 'control.receipt' && e.payload.disposition === 'consumed' && e.payload.request_id === steerTarget.result.running!.request_id), 'Steer consumed for exact request')
    evidence.steeredRequest = steerTarget.result.running
    evidence.queuedFollowup = (await snapshot()).messages.find((m) => m.text === '[reply] queued smoke follow-up')

    await click('button[title="Search all conversations (Ctrl+Shift+F)"]')
    await setInput('.search-form input', 'smoke-search-needle')
    await run('document.querySelector(".search-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))')
    await until(() => run('document.querySelectorAll(".search-hits .hit").length > 0'), 'real search')
    await record('Real search', '.search-panel')
    await click('.search-hits .hit')
    await until(() => run('Boolean(document.querySelector(".msg.highlight"))'), 'jump to real message')
    await click('button[title="Close search"]')
    if (await run('Boolean(document.querySelector(".jump-banner button"))')) await click('.jump-banner button')
    await click('.conv-row .conv-more')
    await click('.menu button:nth-child(5)')
    await until(() => run('Boolean(document.querySelector(".dialog"))'), 'existing reset confirmation')
    await click('.dialog button[type=submit]')
    await until(() => run('document.querySelector(".messages")?.textContent.includes("Model context reset.") ?? false'), 'context reset boundary')
    evidence.resetNotice = (await snapshot()).messages.find((m) => m.text === 'Model context reset.')
    assert(evidence.resetNotice, 'reset boundary persists')
    await record('Context reset retaining history', '.messages')
    await click('.conv-row .conv-more')
    await click('.menu button:first-child')
    await until(() => run('Boolean(document.querySelector(".dialog input"))'), 'rename dialog')
    await setInput('.dialog input', 'Real smoke conversation')
    await click('.dialog button[type=submit]')
    await until(async () => (await text('.conv-title')).includes('Real smoke conversation'), 'real rename')
    const child = await bridge<{ ok: boolean; result: { conversation: { id: string; rev: number; parent_id: string; inherited_from: unknown } } }>('createConversation', {
      command_id: randomUUID(), title: 'Disposable smoke child', parent_id: cid, from_message_id: replied.id
    })
    assert(child.ok && child.result.conversation.parent_id === cid && child.result.conversation.inherited_from, `real child inheritance: ${JSON.stringify(child)}`)
    const archived = await bridge<{ ok: boolean; result: { conversation: { rev: number; archived: boolean } } }>('updateConversation', {
      command_id: randomUUID(), id: child.result.conversation.id, expected_rev: child.result.conversation.rev, archived: true
    })
    assert(archived.ok && archived.result.conversation.archived, 'real archive')
    const unarchived = await bridge<{ ok: boolean; result: { conversation: { rev: number; archived: boolean } } }>('updateConversation', {
      command_id: randomUUID(), id: child.result.conversation.id, expected_rev: archived.result.conversation.rev, archived: false
    })
    assert(unarchived.ok && !unarchived.result.conversation.archived, 'real unarchive')
    const deleted = await bridge<{ ok: boolean }>('deleteConversation', {
      command_id: randomUUID(), id: child.result.conversation.id, expected_rev: unarchived.result.conversation.rev
    })
    assert(deleted.ok, 'real child deletion')
    evidence.conversationLifecycle = { rename: 'rendered dialog', child: child.result.conversation, archived: true, unarchived: true, deleted: true }
    writeFileSync(out, (await win.webContents.capturePage()).toPNG())

    const unavailable = /not (?:yet )?available|unavailable|not served|later (?:step|slice)/i
    await click('.work-toggle')
    await until(async () => unavailable.test(await text('.work-panel')), 'honest unserved Work')
    assert.equal(await run('document.querySelectorAll(".work-item").length'), 0)
    await record('Unserved Work', '.work-panel')
    await click('button[title="Settings (Ctrl+,)"]')
    await until(() => run('document.querySelectorAll(".settings-nav-item").length > 1'), 'settings')
    const sections = await run<string[]>('Array.from(document.querySelectorAll(".settings-nav-item"), b => b.innerText)')
    for (let i = 0; i < sections.length; i++) {
      await click(`.settings-nav-item:nth-of-type(${i + 2})`)
      await until(async () => unavailable.test(await text('.settings-body')), `unserved Settings / ${sections[i]}`)
      assert.equal(await run('document.querySelectorAll(".settings-body .manage-row, .settings-body .work-item, .settings-body .account").length'), 0)
      await record(`Unserved Settings / ${sections[i]}`, '.settings-body')
    }
    assert.equal(broker.linkState, 'ready')
    Object.assign(evidence, { link: broker.linkState, screens, events })
    writeFileSync(out.replace(/\.png$/i, '') + '-evidence.json', JSON.stringify(evidence, null, 2) + '\n')
    process.stdout.write(`real-core-smoke: ok link=ready version=${status.version} screens=${screens.length} output-pages=${pages}\n`)
  } catch (error) {
    Object.assign(evidence, { error: String(error), screens, events, renderedPage: await text('body').catch(() => '') })
    writeFileSync(out, (await win.webContents.capturePage()).toPNG())
    writeFileSync(out.replace(/\.png$/i, '') + '-evidence.json', JSON.stringify(evidence, null, 2) + '\n')
    throw error
  } finally {
    dialog.showOpenDialog = originalOpen
    dialog.showSaveDialog = originalSave
    broker.off('event', observe)
  }
}
