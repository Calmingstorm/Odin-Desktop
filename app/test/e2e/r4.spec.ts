// P4.5 R4 acceptance through the real Electron app, the real engine and a canned local provider (section 5 of
// docs/work/phase-3-app-v1.md). Each test records its case only after every assertion passed (r4-cases.ts).
import { test, expect, type ElectronApplication } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { assertIsolated, exitApp, launchApp, repository, request, snapshot, waitForCore } from './harness'
import { isolatedServicesBootstrap } from '../isolated-services-bootstrap'
import { recordCase } from './r4-cases'
import { FILE_CONTENT, IMAGE_BYTES, REPLY, TOOL_REPLY, startCannedProvider } from '../real-core-provider-fixture.mjs'

type Provider = Awaited<ReturnType<typeof startCannedProvider>>
type ProviderCall = Provider['requests'][number]
interface Message { id: string; role: string; text: string; request_id?: string; artifacts?: Array<{ ref: string; name: string }> }
interface Snapshot {
  conversation: { id: string; rev: number }
  running: { request_id: string } | null
  queued: Array<{ request_id?: string }>
  messages: { items: Message[] }
}

// The isolated runner has no keyring daemon: the core starts with the same in-memory keyring double as the
// real-core contract harness, so provider secrets can be set without touching any real keyring.
// The app accepts a development core command only as plain argv (no control characters, no empty parts), so the
// bootstrap runs from a file in the disposable root.
function memoryKeyringCore(): Record<string, string> {
  const python = process.env.ODIN_DESKTOP_ENGINE_PYTHON ?? join(repository, '.venv/bin/python')
  const script = join(process.env.ODIN_REAL_CORE_ROOT!, 'r4-memory-keyring-core.py')
  writeFileSync(script, isolatedServicesBootstrap, { mode: 0o600 })
  return { ODIN_DESKTOP_CORE_CMD: JSON.stringify([python, '-B', script, 'memory', '-', '-', 'stage']) }
}

async function call<T>(application: ElectronApplication, method: string, params: Record<string, unknown> = {}): Promise<T> {
  const answer = await request(application, method, params)
  if (!answer.ok) throw new Error(`${method} failed: ${JSON.stringify(answer)}`)
  return answer.result as T
}

// The same settings path as the real-core smoke: the app's own core methods, never a config file edit.
async function useCannedProvider(application: ElectronApplication, baseUrl: string): Promise<void> {
  const save = async (method: string, changes: Array<{ path: string; value: unknown }>): Promise<void> => {
    const schema = await call<{ revision: unknown }>(application, 'settings.schema')
    await call(application, method, { expected_revision: schema.revision, changes })
  }
  await save('providers.compat.set', [{ path: 'openai_compatible.enabled', value: false }])
  await save('providers.codex.set', [{ path: 'openai_codex.enabled', value: false }])
  await save('providers.auxiliary.set', [{ path: 'openai_codex.auxiliary.enabled', value: false }])
  await save('providers.compat.set', [
    { path: 'openai_compatible.base_url', value: baseUrl },
    { path: 'openai_compatible.model', value: 'canned-contract' },
    { path: 'openai_compatible.preset', value: 'custom' },
    { path: 'openai_compatible.reasoning_dialect', value: 'none' },
    { path: 'openai_compatible.reasoning_effort', value: 'none' },
    { path: 'openai_compatible.max_tokens', value: 4096 }
  ])
  await call(application, 'secrets.set', { path: 'openai_compatible.api_key', value: 'canned-local-test-only' })
  await save('providers.compat.set', [{ path: 'openai_compatible.enabled', value: true }])
  const schema = await call<{ revision: unknown }>(application, 'settings.schema')
  await call(application, 'models.main.set', { model: 'compat:canned-contract', expected_revision: schema.revision })
}

const textOf = (content: unknown): string => typeof content === 'string' ? content
  : Array.isArray(content) ? content.map((part) => (part as { text?: string }).text ?? '').join('\n') : ''
const everything = (recorded: ProviderCall): string => recorded.body.messages.map((m) => textOf(m.content)).join('\n')
const lastUser = (recorded: ProviderCall): string =>
  textOf([...recorded.body.messages].reverse().find((m) => m.role === 'user')?.content)
const answered = (snap: Snapshot, requestId: string, text: string): boolean =>
  snap.messages.items.some((m) => m.role === 'assistant' && m.request_id === requestId && m.text.includes(text))
const replied = (snap: Snapshot, requestId: string): boolean => answered(snap, requestId, REPLY)

test('R4-02: two conversations progress independently, one conversation runs in order, and no context leaks', async ({}, info) => {
  assertIsolated()
  const provider = await startCannedProvider({ root: join(process.env.ODIN_REAL_CORE_ROOT!, 'r4-provider-two-conversations') })
  let application: ElectronApplication | null = null
  try {
    application = await launchApp({ profile: 'r4-two-conversations', args: ['--hidden'], env: memoryKeyringCore() })
    await waitForCore(application)
    await useCannedProvider(application, provider.baseUrl)
    const app = application
    // Random markers: the leak check cannot match titles, prompts or fixture text by accident.
    const alpha = `alpha-${randomUUID().slice(0, 8)}`, bravo = `bravo-${randomUUID().slice(0, 8)}`
    const create = async (): Promise<string> =>
      (await call<{ conversation: { id: string } }>(app, 'conversations.create', {})).conversation.id
    const a = await create(), b = await create()
    const send = (conversation: string, text: string): Promise<{ request_id: string; disposition: string }> =>
      call(app, 'submission.send', { client_submission_id: randomUUID(), conversation_id: conversation, text })
    const snap = (conversation: string): Promise<Snapshot> => call(app, 'conversation.snapshot', { conversation_id: conversation })
    const reached = (marker: string): boolean => provider.requests.some((r) => lastUser(r).includes(marker))

    // A's first turn is held at the provider; a second A message must wait behind it.
    const a1 = await send(a, `[hold-stop] ${alpha} first`)
    await expect.poll(() => reached(`${alpha} first`), { timeout: 30_000 }).toBe(true)
    const a2 = await send(a, `[reply] ${alpha} second`)
    // B is not blocked by A: it completes while A's first turn is still held.
    const b1 = await send(b, `[reply] ${bravo} only`)
    await expect.poll(async () => replied(await snap(b), b1.request_id), { timeout: 30_000 }).toBe(true)
    const held = await snap(a)
    expect(held.running?.request_id).toBe(a1.request_id)
    expect(held.queued.map((item) => item.request_id)).toContain(a2.request_id)
    expect(reached(`${alpha} second`)).toBe(false)

    provider.release('[hold-stop]')
    await expect.poll(async () => {
      const done = await snap(a)
      return replied(done, a1.request_id) && replied(done, a2.request_id)
    }, { timeout: 30_000 }).toBe(true)

    // Order inside A: the second message reached the provider only after the first.
    const index = (marker: string): number => provider.requests.findIndex((r) => lastUser(r).includes(marker))
    expect(index(`${alpha} second`)).toBeGreaterThan(index(`${alpha} first`))
    // No context crosses conversations, in either direction, in any provider call.
    for (const recorded of provider.requests) {
      const all = everything(recorded)
      if (all.includes(bravo)) expect(all).not.toContain(alpha)
      if (all.includes(alpha)) expect(all).not.toContain(bravo)
    }
    // Each durable transcript holds only its own conversation.
    const finalA = await snap(a), finalB = await snap(b)
    expect(finalA.messages.items.some((m) => m.text.includes(bravo))).toBe(false)
    expect(finalB.messages.items.some((m) => m.text.includes(alpha))).toBe(false)

    await recordCase(info, 'R4-02', {
      conversations: { a, b }, requests: { a1: a1.request_id, a2: a2.request_id, b1: b1.request_id },
      provider_calls: provider.requests.map((r) => r.token),
      a_held_while_b_completed: true, a_second_queued_until_first_completed: true, cross_conversation_text: 'none'
    })
  } finally {
    if (application) await exitApp(application)
    await provider.close()
  }
})

test('R4-05: a context reset and an app restart keep the transcript, tool outcomes and files visible', async ({}, info) => {
  assertIsolated()
  const provider = await startCannedProvider({ root: join(process.env.ODIN_REAL_CORE_ROOT!, 'r4-provider-restart') })
  const profile = 'r4-restart'
  let application: ElectronApplication | null = null
  try {
    application = await launchApp({ profile, args: ['--hidden'], env: memoryKeyringCore() })
    await waitForCore(application)
    await useCannedProvider(application, provider.baseUrl)
    const app = application
    const marker = `restart-${randomUUID().slice(0, 8)}`
    const title = `R4 restart ${marker}`
    const cid = (await call<{ conversation: { id: string } }>(app, 'conversations.create', { title })).conversation.id
    const send = (text: string): Promise<{ request_id: string }> =>
      call(app, 'submission.send', { client_submission_id: randomUUID(), conversation_id: cid, text })
    const snap = (target: ElectronApplication): Promise<Snapshot> => call(target, 'conversation.snapshot', { conversation_id: cid })

    const tool = await send(`[tool] ${marker} tool`)
    await expect.poll(async () => answered(await snap(app), tool.request_id, TOOL_REPLY), { timeout: 30_000 }).toBe(true)
    const file = await send(`[artifact] ${marker} file`)
    await expect.poll(async () => answered(await snap(app), file.request_id, 'file and image posted'), { timeout: 30_000 }).toBe(true)
    const artifacts = (await snap(app)).messages.items.flatMap((m) => m.artifacts ?? [])
    expect(artifacts.map((a) => a.name)).toContain('contract.txt')

    // A context reset fences what the model sees next, not the durable history.
    await call(app, 'conversations.reset_context', { id: cid, expected_rev: (await snap(app)).conversation.rev })
    const after = await send(`[reply] ${marker} after reset`)
    await expect.poll(async () => replied(await snap(app), after.request_id), { timeout: 30_000 }).toBe(true)
    const afterCall = provider.requests.find((r) => lastUser(r).includes(`${marker} after reset`))
    expect(afterCall).toBeDefined()
    expect(everything(afterCall!)).not.toContain(`${marker} tool`)
    const before = await snap(app)

    // A full restart of app and core: every message and file is still there, and visible.
    await exitApp(app)
    application = await launchApp({ profile, env: memoryKeyringCore() })
    await waitForCore(application)
    const restored = await snap(application)
    expect(restored.messages.items.map((m) => m.id)).toEqual(before.messages.items.map((m) => m.id))
    expect(answered(restored, tool.request_id, TOOL_REPLY)).toBe(true)
    for (const artifact of artifacts) {
      const read = await request(application, 'artifacts.read', { ref: artifact.ref, offset: 0, length: 65_536 })
      expect(read.ok).toBe(true)
      if (artifact.name === 'contract.txt') {
        expect(Buffer.from((read.result as { data_b64: string }).data_b64, 'base64').toString()).toBe(FILE_CONTENT)
      }
    }
    const page = await application.firstWindow()
    await page.getByText(title, { exact: true }).first().click()
    const scroll = page.locator('.message-scroll')
    await expect(scroll).toContainText(TOOL_REPLY)
    await expect(scroll).toContainText(`${marker} after reset`)
    await expect(scroll).toContainText('contract.txt')

    const evidence = {
      conversation: cid, messages: restored.messages.items.length, artifacts: artifacts.map((a) => a.name),
      reset_fenced_model_context: true, restart_preserved_message_ids: true, visible_after_restart: true
    }
    await recordCase(info, 'R4-05', evidence)
    await recordCase(info, 'CC-07', evidence)
  } finally {
    if (application) await exitApp(application)
    await provider.close()
  }
})

type Hooks = { close(): void; show(): void; rendererCrash(): void }
const hook = (application: ElectronApplication, name: keyof Hooks): Promise<void> =>
  application.evaluate((_electron, method) => {
    (globalThis as unknown as { __odinE2E: Hooks }).__odinE2E[method as keyof Hooks]()
  }, name)

test('R4-04: closing the window and losing the renderer never lose or repeat a running turn', async ({}, info) => {
  assertIsolated()
  const provider = await startCannedProvider({ root: join(process.env.ODIN_REAL_CORE_ROOT!, 'r4-provider-reopen') })
  let application: ElectronApplication | null = null
  try {
    application = await launchApp({ profile: 'r4-reopen', env: memoryKeyringCore() })
    await waitForCore(application)
    await useCannedProvider(application, provider.baseUrl)
    const app = application
    const marker = `reopen-${randomUUID().slice(0, 8)}`
    const title = `R4 reopen ${marker}`
    const cid = (await call<{ conversation: { id: string } }>(app, 'conversations.create', { title })).conversation.id
    const send = (text: string): Promise<{ request_id: string }> =>
      call(app, 'submission.send', { client_submission_id: randomUUID(), conversation_id: cid, text })
    const snap = (): Promise<Snapshot> => call(app, 'conversation.snapshot', { conversation_id: cid })
    const calls = (text: string): number => provider.requests.filter((r) => lastUser(r).includes(text)).length
    const page = await app.firstWindow()
    await page.getByText(title, { exact: true }).first().click()
    const corePid = (await snapshot(app)).corePid

    // Close the window while a turn is running: the turn keeps running and the reopened window catches up.
    const closed = await send(`[hold-stop] ${marker} closed`)
    await expect.poll(() => calls(`${marker} closed`), { timeout: 30_000 }).toBe(1)
    await hook(app, 'close')
    expect((await snapshot(app)).visible).toBe(false)
    provider.release('[hold-stop]')
    await expect.poll(async () => replied(await snap(), closed.request_id), { timeout: 30_000 }).toBe(true)
    await hook(app, 'show')
    await expect(page.locator('.message-scroll')).toContainText(`${marker} closed`)
    await expect(page.locator('.message-scroll')).toContainText(REPLY)

    // Lose the renderer mid-turn: the core and the turn continue; the recovered window shows the result.
    const crashed = await send(`[hold-resume] ${marker} crash`)
    await expect.poll(() => calls(`${marker} crash`), { timeout: 30_000 }).toBe(1)
    await hook(app, 'rendererCrash')
    provider.release('[hold-resume]')
    await expect.poll(async () => replied(await snap(), crashed.request_id), { timeout: 30_000 }).toBe(true)
    await hook(app, 'show')
    // The renderer recovers. Under Playwright the reloaded renderer does not answer script evaluation (the page
    // object is reused), the same limit lifecycle.spec.ts works within: assert recovery, not its DOM.
    await expect.poll(() => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.webContents.isCrashed()),
      { timeout: 30_000 }).toBe(false)
    expect((await snapshot(app)).corePid).toBe(corePid)
    // Neither turn was sent to the model twice.
    expect([calls(`${marker} closed`), calls(`${marker} crash`)]).toEqual([1, 1])

    await recordCase(info, 'R4-04', {
      conversation: cid, closed_window_turn: closed.request_id, renderer_loss_turn: crashed.request_id,
      core_unchanged: true, provider_calls_per_turn: 1, renderer_recovered: true,
      scope: 'window close/reopen catch-up asserted in the DOM; renderer loss asserted through the core and recovery',
      not_automated: 'the recovered window\'s contents after a renderer loss (Playwright limit); check in the final manual run',
      covered_elsewhere: 'core/app loss: lifecycle.spec.ts'
    })
  } finally {
    if (application) await exitApp(application)
    await provider.close()
  }
})

// A stored (uncompressed) zip with one entry, built here so the test needs no archive tool.
function storedZip(name: string, data: Buffer): Buffer {
  let crc = 0xffffffff
  for (const byte of data) {
    crc ^= byte
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1))
  }
  crc = (crc ^ 0xffffffff) >>> 0
  const fileName = Buffer.from(name)
  const local = Buffer.alloc(30); local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4)
  local.writeUInt32LE(crc, 14); local.writeUInt32LE(data.length, 18); local.writeUInt32LE(data.length, 22)
  local.writeUInt16LE(fileName.length, 26)
  const central = Buffer.alloc(46); central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6)
  central.writeUInt32LE(crc, 16); central.writeUInt32LE(data.length, 20); central.writeUInt32LE(data.length, 24)
  central.writeUInt16LE(fileName.length, 28)
  const offset = local.length + fileName.length + data.length
  const end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(1, 8); end.writeUInt16LE(1, 10)
  end.writeUInt32LE(central.length + fileName.length, 12); end.writeUInt32LE(offset, 16)
  return Buffer.concat([local, fileName, data, central, fileName, end])
}

// A one-page PDF whose text is the marker.
function minimalPdf(text: string): Buffer {
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    '', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
  const stream = `BT /F1 12 Tf 10 50 Td (${text}) Tj ET`
  objects[3] = `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`
  let body = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((object, index) => { offsets.push(body.length); body += `${index + 1} 0 obj\n${object}\nendobj\n` })
  const xref = body.length
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n` + offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(body)
}

test('R4-01: text, image, PDF, archive, binary and mixed files through the real picker, paste and remove', async ({}, info) => {
  assertIsolated()
  const provider = await startCannedProvider({ root: join(process.env.ODIN_REAL_CORE_ROOT!, 'r4-provider-attachments') })
  let application: ElectronApplication | null = null
  try {
    application = await launchApp({ profile: 'r4-attachments', env: memoryKeyringCore() })
    await waitForCore(application)
    await useCannedProvider(application, provider.baseUrl)
    const app = application
    const marker = `files-${randomUUID().slice(0, 8)}`
    const title = `R4 files ${marker}`
    const cid = (await call<{ conversation: { id: string } }>(app, 'conversations.create', { title })).conversation.id
    const snap = (): Promise<Snapshot> => call(app, 'conversation.snapshot', { conversation_id: cid })
    const dir = join(process.env.ODIN_REAL_CORE_ROOT!, 'r4-files')
    mkdirSync(dir, { recursive: true, mode: 0o700 })
    const files: Record<string, Buffer> = {
      'note.txt': Buffer.from(`Plain text body ${marker}\n`),
      'pixel.png': IMAGE_BYTES,
      'doc.pdf': minimalPdf(`PDF body ${marker}`),
      'bundle.zip': storedZip('inner.txt', Buffer.from(`Archive body ${marker}\n`)),
      'blob.bin': Buffer.from([0, 255, 1, 254, 0, 0, 7, 9, 0, 128, 64, 0]),
      'mixed.txt': Buffer.from(`Mixed text body ${marker}\n`),
      'mixed.png': IMAGE_BYTES,
      'removed.txt': Buffer.from(`Removed body ${marker}\n`)
    }
    for (const [name, data] of Object.entries(files)) writeFileSync(join(dir, name), data, { mode: 0o600 })
    const page = await app.firstWindow()
    await page.getByText(title, { exact: true }).first().click()
    const box = page.getByRole('textbox', { name: 'Message', exact: true })
    const sendButton = page.locator('button.composer-send')

    const pick = async (names: string[]): Promise<void> => {
      await app.evaluate(({ dialog }, paths) => {
        dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: paths })) as typeof dialog.showOpenDialog
      }, names.map((name) => join(dir, name)))
      await page.getByRole('button', { name: 'Attach files' }).click()
      for (const name of names) await expect(page.getByRole('button', { name: `Remove ${name}` })).toBeVisible({ timeout: 30_000 })
    }
    // Sends what the composer holds, waits for the reply, and returns the stored user message and the model call.
    const send = async (label: string): Promise<{ user: Message & { attachments?: Array<{ name: string; mime: string }> }; seen: string; image: boolean }> => {
      await expect(page.getByRole('progressbar')).toHaveCount(0, { timeout: 30_000 })
      const text = `[reply] ${marker} ${label}`
      await box.fill(text)
      await expect(sendButton).toBeEnabled({ timeout: 30_000 })
      await sendButton.click()
      let user: (Message & { attachments?: Array<{ name: string; mime: string }> }) | undefined
      await expect.poll(async () => {
        const items = (await snap()).messages.items
        user = items.find((m) => m.role === 'user' && m.text.includes(text))
        return Boolean(user?.request_id && replied({ messages: { items } } as Snapshot, user.request_id))
      }, { timeout: 60_000 }).toBe(true)
      const modelCall = provider.requests.find((r) => lastUser(r).includes(text))!
      return { user: user!, seen: lastUser(modelCall), image: JSON.stringify(modelCall.body.messages.at(-1)).includes('image_url') }
    }
    const names = (user: { attachments?: Array<{ name: string }> }): string[] => (user.attachments ?? []).map((a) => a.name)

    await pick(['note.txt'])
    const text = await send('text')
    expect(names(text.user)).toEqual(['note.txt'])
    expect(text.seen).toContain('Attached file: note.txt')
    expect(text.seen).toContain(`Plain text body ${marker}`)

    await pick(['pixel.png'])
    const image = await send('image')
    expect(image.image).toBe(true)
    expect(image.seen).toContain('[User shared image: pixel.png]')

    await pick(['doc.pdf'])
    const pdf = await send('pdf')
    expect(pdf.seen).toContain('Attached PDF: doc.pdf')
    expect(pdf.seen).toContain(`PDF body ${marker}`)

    await pick(['bundle.zip'])
    const archive = await send('archive')
    expect(archive.seen).toContain('Attached archive: bundle.zip')
    expect(archive.seen).toContain(`Archive body ${marker}`)

    // An unreadable binary is saved and described honestly, never passed off as text.
    await pick(['blob.bin'])
    const binary = await send('binary')
    expect(binary.seen).toContain('[Attachment saved:')
    expect(binary.seen).toContain('application/octet-stream, 12 bytes')

    await pick(['mixed.txt', 'mixed.png'])
    const mixed = await send('mixed')
    expect(names(mixed.user).sort()).toEqual(['mixed.png', 'mixed.txt'])
    expect(mixed.seen).toContain(`Mixed text body ${marker}`)
    expect(mixed.image).toBe(true)

    // A pasted image has no file on disk: its bytes are uploaded directly.
    await box.evaluate((element, encoded) => {
      const transfer = new DataTransfer()
      transfer.items.add(new File([Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0))], 'pasted.png', { type: 'image/png' }))
      element.dispatchEvent(new ClipboardEvent('paste', { clipboardData: transfer, bubbles: true, cancelable: true }))
    }, IMAGE_BYTES.toString('base64'))
    await expect(page.getByRole('button', { name: 'Remove pasted.png' })).toBeVisible({ timeout: 30_000 })
    const pasted = await send('pasted')
    expect(names(pasted.user)).toEqual(['pasted.png'])
    expect(pasted.image).toBe(true)

    // A file removed before sending never reaches the conversation or the model.
    await pick(['removed.txt'])
    await page.getByRole('button', { name: 'Remove removed.txt' }).click()
    await expect(page.getByRole('button', { name: 'Remove removed.txt' })).toHaveCount(0)
    const removed = await send('after removal')
    expect(names(removed.user)).toEqual([])
    expect(removed.seen).not.toContain('removed.txt')
    expect(removed.seen).not.toContain(`Removed body ${marker}`)

    await recordCase(info, 'R4-01', {
      conversation: cid,
      picker: { text: 'contents read', image: 'image part', pdf: 'text extracted', archive: 'entries previewed',
        binary: 'saved and described, not read', mixed: 'text and image in one message' },
      paste: 'image bytes uploaded directly', remove_before_send: 'never reached the model',
      not_covered_here: ['upload cancel mid-transfer', 'byte-limit refusal', 'drag and drop from the desktop']
    })
  } finally {
    if (application) await exitApp(application)
    await provider.close()
  }
})
