import { spawnSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import { createServer, type Server } from 'node:http'
import { join } from 'node:path'
import { afterEach, describe, expect, test } from 'vitest'
import type { Broker, Settled } from '../src/main/broker'
import { ArtifactStore } from '../src/main/artifacts'
import type { ConversationSnapshot, CoreEvent } from '../src/shared/api'
import { assertIsolated, RealCoreHarness, waitFor } from './real-core-harness'

assertIsolated()

const skillName = 'skill_delivery_fixture'
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAAD0lEQVR4nGMUVDI2NjYGAAMcAQFKv5lqAAAAAElFTkSuQmCC', 'base64')
const binary = Buffer.from([0, 255, 17, 128, 10, 0])
// Loaded by the actual SkillManager from the disposable profile. No publication injection.
const fixtureSkill = `
import base64
SKILL_DEFINITION = {"name": "${skillName}", "description": "Disposable conversation delivery contract", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}
async def execute(inp, context):
    source = await context.read_file("localhost", inp["path"])
    if "owned fixture provenance" not in source:
        raise RuntimeError("The real host read did not return the owned fixture")
    await context.post_message("Skill progress xoxb-contract-message-secret")
    await context.post_file(base64.b64decode("${png.toString('base64')}"), "skill-pixels.png", "Skill image xoxb-contract-caption-secret")
    await context.post_file(bytes([0, 255, 17, 128, 10, 0]), "skill-bytes.bin", "Skill binary")
    return "Fixture callbacks completed"
`

function result<T>(answer: Settled): T {
  expect(answer.ok, JSON.stringify(answer)).toBe(true)
  if (!answer.ok) throw new Error(`Real-core request refused: ${answer.error.code}`)
  return answer.result as T
}

describe('actual Broker/core skill conversation delivery', () => {
  let core: RealCoreHarness | undefined
  let provider: Server | undefined
  let releaseFinal: (() => void) | undefined
  afterEach(async () => {
    releaseFinal?.()
    await core?.dispose()
    if (provider) await new Promise<void>((resolve, reject) => provider!.close((error) => error ? reject(error) : resolve()))
    provider = undefined
    core = undefined
    releaseFinal = undefined
  })

  test.each(['send', 'stage'] as const)('%s scheduled background skill delivers into its owning conversation and final workflow report', async (mode) => {
    core = new RealCoreHarness({ memoryKeyring: true, stageFileSkill: skillName, skillFileDelivery: mode })
    await core.start()
    const { broker } = await core.connect()
    const source = join(core.root, 'scheduled-owned-source.txt')
    writeFileSync(source, 'owned fixture provenance\n', { mode: 0o600 })
    result(await broker.request('skills.save', { name: skillName, code: fixtureSkill }, randomUUID()))
    const create = async (title: string): Promise<string> => result<{ conversation: { id: string } }>(await broker.request(
      'conversations.create', { title }, randomUUID())).conversation.id
    const conversation = await create(`${mode} scheduled skill delivery`)
    const unrelated = await create('must not receive scheduled skill callbacks')
    const snapshot = async (connection: Broker, cid = conversation): Promise<ConversationSnapshot> => result<ConversationSnapshot>(
      await connection.request('conversation.snapshot', { conversation_id: cid }))
    const events: CoreEvent[] = []
    broker.on('event', (event: CoreEvent) => events.push(event))
    result(await broker.subscribe())
    const schedule = result<{ id: string }>(await broker.request('schedules.save', {
      description: `${mode} scheduled fixture`, action: 'workflow', channel_id: conversation,
      run_at: new Date(Date.now() + 86_400_000).toISOString(), max_retries: 0,
      steps: [{ tool_name: 'invoke_skill', tool_input: { name: skillName, input: { path: source } },
        description: 'Publish fixture callbacks', on_failure: 'abort' }]
    }, randomUUID()))
    const runCommand = randomUUID()
    const runParams = { id: schedule.id }
    const run = await broker.request('schedules.run', runParams, runCommand)
    expect(result(run)).toMatchObject({ status: 'success', schedule_id: schedule.id })
    const completed = await snapshot(broker)
    expect(completed.messages.items.every((item) => item.role === 'notice')).toBe(true)
    const progress = completed.messages.items.find((item) => item.text.startsWith('Skill progress'))!
    expect(progress).toMatchObject({ role: 'notice', text: 'Skill progress [REDACTED]', request_id: expect.any(String) })
    const report = completed.messages.items.find((item) => item.text.startsWith('**Workflow:'))!
    expect(report).toMatchObject({ role: 'notice', request_id: progress.request_id,
      text: expect.stringContaining('Fixture callbacks completed') })
    expect(report.artifacts ?? [], JSON.stringify(completed.messages.items)).toHaveLength(mode === 'stage' ? 2 : 0)
    const files = completed.messages.items.flatMap((item) => item.artifacts ?? []).filter((artifact) => artifact.kind !== 'report')
    expect(files).toEqual([
      { ref: expect.any(String), name: 'skill-pixels.png', mime: 'image/png', kind: 'image', size: png.length, available: true },
      { ref: expect.any(String), name: 'skill-bytes.bin', mime: 'application/octet-stream', kind: 'file', size: binary.length, available: true }
    ])
    expect(completed.messages.items, JSON.stringify(completed.messages.items)).toHaveLength(mode === 'stage' ? 2 : 4)
    expect((await snapshot(broker, unrelated)).messages.items).toEqual([])
    const history = result<Array<{ status: string; run_binding: { conversation_id: string } }>>(await broker.request(
      'schedules.history', { id: schedule.id, limit: 10 }))
    expect(history).toHaveLength(1)
    expect(history[0]).toMatchObject({ run_binding: { conversation_id: conversation } })
    expect(result(await broker.request('work.list', { kind: 'schedule', conversation_id: conversation }))).toMatchObject({
      items: [expect.objectContaining({ kind: 'schedule', conversation_id: conversation, manager_id: schedule.id })]
    })
    for (const [index, bytes] of [png, binary].entries()) {
      const artifact = result<{ data_b64: string; eof: boolean }>(await broker.request('artifacts.read', {
        ref: files[index]!.ref, offset: 0, length: 512
      }))
      expect(artifact.eof).toBe(true)
      expect(Buffer.from(artifact.data_b64, 'base64')).toEqual(bytes)
    }
    await waitFor(() => events.filter((event) => event.type === 'artifact.published').length === 2,
      'scheduled skill artifact publications')
    for (const event of events.filter((event) => ['artifact.published', 'report.published'].includes(event.type))) {
      expect(event.payload).toMatchObject({ conversation_id: conversation, request_id: progress.request_id })
    }
    expect(await broker.request('schedules.run', runParams, runCommand)).toEqual(run)
    expect((await snapshot(broker)).messages.items).toEqual(completed.messages.items)
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    broker.close()
    const provenance = core.artifactProvenance()
    expect(provenance).toHaveLength(2)
    for (const [index, bytes] of [png, binary].entries()) {
      expect(provenance[index]).toMatchObject({ ref: files[index]!.ref, conversation_id: conversation,
        request_id: progress.request_id, tool: skillName, size: bytes.length, mime: files[index]!.mime,
        sha256: createHash('sha256').update(bytes).digest('hex') })
      expect(provenance[index]!.hosts).toEqual([expect.objectContaining({ alias: 'localhost' })])
    }
    await core.start()
    const restarted = (await core.connect()).broker
    expect((await snapshot(restarted)).messages.items).toEqual(completed.messages.items)
    expect((await snapshot(restarted, unrelated)).messages.items).toEqual([])
    for (const [index, bytes] of [png, binary].entries()) {
      const artifact = result<{ data_b64: string }>(await restarted.request('artifacts.read', {
        ref: files[index]!.ref, offset: 0, length: 512
      }))
      expect(Buffer.from(artifact.data_b64, 'base64')).toEqual(bytes)
    }
    expect(result(await restarted.request('schedules.history', { id: schedule.id, limit: 10 }))).toHaveLength(1)
  })

  test.each(['send', 'stage'] as const)('%s mode delivers true skill callbacks with request-owned bytes and final reply', async (mode) => {
    core = new RealCoreHarness({ memoryKeyring: true, stageFileSkill: mode === 'stage' ? skillName : undefined })
    // Let the real core mint the profile identity before adding user-owned skill state.
    await core.start()
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    const skills = join(core.paths.dataDir, 'skills')
    mkdirSync(skills, { recursive: true, mode: 0o700 })
    writeFileSync(join(skills, `${skillName}.py`), fixtureSkill, { mode: 0o600 })
    const source = join(core.root, 'owned-source.txt')
    writeFileSync(source, 'owned fixture provenance\n', { mode: 0o600 })
    await core.start()

    let invocations = 0
    let finalRequested = false
    let skillOffered = false
    const finalBarrier = new Promise<void>((resolve) => { releaseFinal = resolve })
    // Only the external model boundary is deterministic. The actual native dispatch,
    // SkillManager, SkillContext, request guards and durable delivery all run normally.
    provider = createServer(async (request, response) => {
      if (request.method !== 'POST' || request.url !== '/api/chat') {
        response.writeHead(404).end()
        return
      }
      const chunks: Buffer[] = []
      for await (const chunk of request) chunks.push(Buffer.from(chunk))
      const payload = JSON.parse(Buffer.concat(chunks).toString('utf8')) as {
        tools?: Array<{ function: { name: string } }>; messages: Array<{ role: string; content: string }> }
      let message: Record<string, unknown> = { role: 'assistant', content: 'COMPLETE' }
      if (payload.tools) {
        skillOffered ||= payload.tools.some((tool) => tool.function.name === skillName)
        if (!payload.messages.some((item) => item.role === 'tool')) {
          invocations += 1
          message = { role: 'assistant', content: '', tool_calls: [{ function: {
            name: 'invoke_skill', arguments: { name: skillName, input: { path: source } }
          } }] }
        } else {
          finalRequested = true
          await finalBarrier
          message = { role: 'assistant', content: 'Skill delivery complete.' }
        }
      }
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ model: 'contract-model', done: true, done_reason: 'stop', message,
        prompt_eval_count: 12, eval_count: 10 }))
    })
    await new Promise<void>((resolve) => provider!.listen(0, '127.0.0.1', resolve))
    const address = provider.address()
    if (!address || typeof address === 'string') throw new Error('Missing disposable provider port')
    const { broker } = await core.connect()
    const schema = result<{ revision: string }>(await broker.request('settings.schema'))
    result(await broker.request('providers.ollama.set', { expected_revision: schema.revision, changes: [
      { path: 'ollama.model', value: 'contract-model' },
      { path: 'ollama.base_url', value: `http://127.0.0.1:${address.port}` },
      { path: 'ollama.enabled', value: true }
    ] }))
    const configured = result<{ revision: string }>(await broker.request('settings.schema'))
    result(await broker.request('models.main.set', { model: 'ollama:contract-model', expected_revision: configured.revision }))
    const create = async (title: string): Promise<string> => result<{ conversation: { id: string } }>(await broker.request(
      'conversations.create', { title }, randomUUID())).conversation.id
    const conversation = await create(`${mode} skill delivery`)
    const unrelated = await create('must not receive skill callbacks')
    const events: CoreEvent[] = []
    broker.on('event', (event: CoreEvent) => events.push(event))
    result(await broker.subscribe())
    const submission = { client_submission_id: randomUUID(), conversation_id: conversation, text: 'Execute the delivery fixture.' }
    const command = randomUUID()
    const accepted = result<{ request_id: string }>(await broker.request('submission.send', submission, command))
    try {
      await waitFor(() => {
        const failed = events.find((event) => event.type === 'request.failed' && event.payload.request_id === accepted.request_id)
        if (failed) throw new Error('Skill request failed before reaching the final-reply barrier')
        return finalRequested
      }, `real ${mode} skill execution before final reply`, 20_000)
    } catch (error) {
      throw new Error(`${String(error)}\nInvocations: ${invocations}, offered: ${skillOffered}\n${core.diagnostics}\n${JSON.stringify(events)}`)
    }
    expect(invocations).toBe(1)
    expect(skillOffered).toBe(true)
    const snapshot = async (connection: Broker, cid = conversation): Promise<ConversationSnapshot> => result<ConversationSnapshot>(
      await connection.request('conversation.snapshot', { conversation_id: cid }))
    const pending = await snapshot(broker)
    expect(pending.messages.items.filter((item) => item.role === 'assistant')).toEqual([])
    expect(pending.messages.items.find((item) => item.text.startsWith('Skill progress'))).toMatchObject({
      role: 'notice', text: 'Skill progress [REDACTED]', request_id: accepted.request_id
    })
    const publications = (): CoreEvent[] => events.filter((event) => event.type === 'artifact.published')
    expect(publications()).toHaveLength(mode === 'send' ? 2 : 0)
    expect(pending.messages.items.flatMap((item) => item.artifacts ?? [])).toHaveLength(mode === 'send' ? 2 : 0)
    expect((await snapshot(broker, unrelated)).messages.items).toEqual([])
    releaseFinal!()
    await waitFor(() => events.some((event) => event.type === 'request.completed' && event.payload.request_id === accepted.request_id),
      `real ${mode} skill final-reply completion`, 20_000)
    const completed = await snapshot(broker)
    const assistant = completed.messages.items.find((item) => item.role === 'assistant')!
    expect(assistant).toMatchObject({ text: 'Skill delivery complete.', request_id: accepted.request_id })
    expect(assistant.artifacts ?? []).toHaveLength(mode === 'stage' ? 2 : 0)
    expect(completed.messages.items.filter((item) => item.role === 'notice')).toHaveLength(mode === 'send' ? 3 : 1)
    const artifacts = completed.messages.items.flatMap((item) => item.artifacts ?? [])
    expect(artifacts).toEqual([
      { ref: expect.any(String), name: 'skill-pixels.png', mime: 'image/png', kind: 'image', size: png.length, available: true },
      { ref: expect.any(String), name: 'skill-bytes.bin', mime: 'application/octet-stream', kind: 'file', size: binary.length, available: true }
    ])
    expect(publications()).toHaveLength(2)
    for (const event of publications()) expect(event.payload).toMatchObject({ conversation_id: conversation, request_id: accepted.request_id })
    expect(events.some((event) => event.type === 'request.failed')).toBe(false)
    expect(JSON.stringify(completed)).not.toContain('xoxb-contract-')
    if (mode === 'send') expect(completed.messages.items.find((item) => item.artifacts?.[0]?.mime === 'image/png')).toMatchObject({
      role: 'notice', text: 'Skill image [REDACTED]', request_id: accepted.request_id
    })
    const store = new ArtifactStore(broker, join(core.root, 'artifact-cache'), () => 7, {
      openPath: async () => { throw new Error('No live desktop actions allowed') },
      showItemInFolder: () => { throw new Error('No live desktop actions allowed') }
    })
    const image = result<Buffer>(await store.fetchBytes(artifacts[0]!.ref))
    expect(image).toEqual(png)
    expect(result<Buffer>(await store.fetchBytes(artifacts[1]!.ref))).toEqual(binary)
    const decoded = spawnSync(core.python, ['-c',
      'import json,sys; from io import BytesIO; from PIL import Image; im=Image.open(BytesIO(sys.stdin.buffer.read())); im.load(); print(json.dumps({"format":im.format,"size":im.size,"pixels":list(im.convert("RGB").getdata())}))'],
    { input: image, env: core.env, encoding: 'utf8', timeout: 5_000 })
    expect(decoded.status, decoded.stderr).toBe(0)
    expect(JSON.parse(decoded.stdout)).toEqual({ format: 'PNG', size: [2, 1], pixels: [[17, 34, 51], [68, 85, 102]] })
    expect(await broker.request('submission.send', submission, command)).toMatchObject({ ok: true, result: accepted })
    expect((await snapshot(broker)).messages.items).toEqual(completed.messages.items)
    expect(publications()).toHaveLength(2)
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    broker.close()
    const provenance = core.artifactProvenance()
    expect(provenance).toHaveLength(2)
    for (const [index, bytes] of [png, binary].entries()) {
      expect(provenance[index]).toMatchObject({ ref: artifacts[index]!.ref, conversation_id: conversation,
        request_id: accepted.request_id, tool: skillName, size: bytes.length, mime: artifacts[index]!.mime,
        sha256: createHash('sha256').update(bytes).digest('hex') })
      expect(provenance[index]!.hosts).toEqual([expect.objectContaining({ alias: 'localhost' })])
    }
    await core.start()
    const restarted = (await core.connect()).broker
    expect((await snapshot(restarted)).messages.items).toEqual(completed.messages.items)
    expect((await snapshot(restarted, unrelated)).messages.items).toEqual([])
    for (const [index, bytes] of [png, binary].entries()) {
      const restored = result<{ data_b64: string; eof: boolean }>(await restarted.request('artifacts.read', {
        ref: artifacts[index]!.ref, offset: 0, length: 512
      }))
      expect(restored.eof).toBe(true)
      expect(Buffer.from(restored.data_b64, 'base64')).toEqual(bytes)
    }
    expect(invocations).toBe(1)
  })
})
