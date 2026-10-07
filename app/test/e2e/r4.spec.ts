// P4.5 R4 acceptance through the real Electron app, the real engine and a canned local provider (section 5 of
// docs/work/phase-3-app-v1.md). Each test records its case only after every assertion passed (r4-cases.ts).
import { test, expect, type ElectronApplication } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { assertIsolated, exitApp, launchApp, repository, request, waitForCore } from './harness'
import { isolatedServicesBootstrap } from '../isolated-services-bootstrap'
import { recordCase } from './r4-cases'
import { FILE_CONTENT, REPLY, TOOL_REPLY, startCannedProvider } from '../real-core-provider-fixture.mjs'

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
