// Seed a checkpoint by executing and interrupting an owned real core, not by
// synthesizing ledger rows. Electron then launches normally, no restart bypass.
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'
import { RealCoreHarness } from './real-core-harness'
import { configureCannedProvider } from '../src/main/real-core-smoke'

// The smoke script is a child of #25's PID-1 runner, just like the contract tests.
export { assertIsolated } from './real-core-harness'

export async function seed(baseUrl: string, generationStarted: () => Promise<void>): Promise<void> {
  const core = new RealCoreHarness({ memoryKeyring: true, profileRoot: process.env.ODIN_REAL_CORE_ROOT })
  await core.start()
  const { broker } = await core.connect()
  const request = async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
    const result = await broker.request(method, params)
    if (!result.ok) throw new Error(`${method} failed: ${JSON.stringify(result)}`)
    return result.result as Record<string, unknown>
  }
  try {
    await configureCannedProvider(broker, baseUrl)
    const conversation = (await request('conversations.create', { title: 'Typed resume smoke' })).conversation as { id: string }
    const sent = await request('submission.send', { conversation_id: conversation.id,
      client_submission_id: randomUUID(), text: '[hold-resume] preserved smoke generation' })
    await generationStarted()
    core.child.kill('SIGKILL')
    await core.waitExit()
    writeFileSync(join(core.root, 'resume-seed.json'), JSON.stringify({ ...sent, conversation_id: conversation.id }))
  } finally {
    broker.close()
    await core.dispose()
  }
}
