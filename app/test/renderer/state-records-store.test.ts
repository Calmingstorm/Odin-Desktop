// The state and records sections' stores, through a fake bridge: newer answers win, and an ingest says what it did.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result } from '../../src/shared/api'

type State = typeof import('../../src/renderer/src/stores/state')
type Records = typeof import('../../src/renderer/src/stores/records')

let state: State
let records: Records
let held: Array<(answer: Result<unknown>) => void>
let calls: Record<string, Array<Record<string, unknown>>>

const ok = <T>(result: T): Result<T> => ({ ok: true, result })

beforeEach(async () => {
  vi.resetModules()
  held = []
  calls = {}
  const hold = (name: string) => (params: Record<string, unknown>) => {
    ;(calls[name] ??= []).push(params)
    return new Promise<Result<unknown>>((resolve) => held.push(resolve))
  }
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      knowledgeSearch: hold('search'),
      auditQuery: hold('audit'),
      logsSearch: hold('logs'),
      knowledgeIngest: hold('ingest'),
      knowledgeList: async () => ok([])
    }
  }
  state = await import('../../src/renderer/src/stores/state')
  records = await import('../../src/renderer/src/stores/records')
})

const settle = () => new Promise((r) => setTimeout(r, 0))

describe('state and records', () => {
  it('shows the answer to the newest knowledge search, never an older one', async () => {
    void state.searchKnowledge('old words')
    void state.searchKnowledge('new words')
    held[1]!(ok([{ chunk_id: 'a:0', content: 'new', source: 'a', score: 1, chunk_index: 0 }]))
    await settle()
    held[0]!(ok([{ chunk_id: 'b:0', content: 'old', source: 'b', score: 1, chunk_index: 0 }]))
    await settle()
    expect(state.stateStore.hits?.map((h) => h.content)).toEqual(['new'])
  })

  it('shows the newest audit and log answers, never older ones', async () => {
    void records.loadAudit({ q: 'first' })
    void records.loadAudit({ q: 'second' })
    held[1]!(ok([{ timestamp: 't2', tool_name: 'second' }]))
    held[0]!(ok([{ timestamp: 't1', tool_name: 'first' }]))
    await settle()
    expect(records.records.audit.map((e) => e.tool_name)).toEqual(['second'])
    expect(calls.audit?.[1]).toEqual({ limit: 100, q: 'second' })
    void records.searchLogs({ q: 'a' })
    void records.searchLogs({ q: 'b', level: 'error' })
    held[3]!(ok({ entries: [{ timestamp: 't', level: 'ERROR', message: 'b' }], count: 1 }))
    held[2]!(ok({ entries: [{ timestamp: 't', level: 'INFO', message: 'a' }], count: 1 }))
    await settle()
    expect(records.records.logs.map((e) => e.message)).toEqual(['b'])
  })

  it('says what an ingest did, and keeps the text when nothing was stored', async () => {
    expect(state.ingestNote({ source: 's', chunks: 3, status: 'stored', outcome: 'created' })).toBe('Stored as 3 chunks.')
    expect(state.ingestNote({ source: 's', status: 'x', outcome: 'duplicate', message: "Identical content is already stored as 'a'." })).toMatch(/already stored as 'a'/)
    const adding = state.ingest('copy.md', 'text')
    held[0]!(ok({ source: 'copy.md', status: 'not ingested', outcome: 'duplicate', message: 'Identical content is already stored.' }))
    expect(await adding).toBe(false) // the view keeps the text, so nothing typed is lost
  })
})

describe('review round 4: records say what they know', () => {
  const failed = { ok: false, error: { code: 'unavailable', message: 'core restarting', disposition: 'not_dispatched' } } as const
  const odin = () => (window as unknown as { odin: Record<string, unknown> }).odin
  const status = (fields: Record<string, unknown>) => ({ available: true, state: 'quarantined', session_id: 's1', generation: 1, session_generation: 3, ...fields })

  it("shows the usage for the period chosen last, whatever order the answers come in (16.R4.4)", async () => {
    const answers: Array<(answer: Result<unknown>) => void> = []
    odin().usage = () => new Promise((resolve) => answers.push(resolve))
    void records.loadUsage('7d')
    void records.loadUsage('24h')
    answers[1]!(ok({ period: '24h', tokens: { value: 24, kind: 'measured' }, quota: [], summary: '' }))
    await settle()
    answers[0]!(ok({ period: '7d', tokens: { value: 700, kind: 'measured' }, quota: [], summary: '' }))
    await settle()
    expect(records.records.usage?.period).toBe('24h')
  })

  it("keeps a failed read's reason, and never counts it as an answer (16.R4.5)", async () => {
    odin().logsSearch = async () => failed
    odin().turnStateList = async () => failed
    await records.searchLogs()
    await records.loadTurns()
    expect(records.records.errors).toMatchObject({ logs: 'core restarting', turns: 'core restarting' })
    expect(records.records.loaded.logs).toBeUndefined()
    odin().logsSearch = async () => ok({ entries: [], count: 0 })
    await records.searchLogs()
    expect(records.records.errors.logs).toBeUndefined()
    expect(records.records.loaded.logs).toBe(true)
  })

  it('gives no verdict when the record could not be checked (16.R4.5)', async () => {
    odin().auditVerify = async () => ok({ valid: true, total: 3, verified: 3 })
    await records.verifyAudit()
    odin().auditVerify = async () => failed
    await records.verifyAudit()
    expect(records.records.verify).toBeNull()
    expect(records.records.errors.verify).toBe('core restarting')
  })

  it("reconciles under the session's own generation, and says only what Odin recorded (16.R4.1)", async () => {
    const sent: Array<Record<string, unknown>> = []
    let answer: Result<unknown> = ok(status({ recovery: { status: 'unknown', reason: 'owned_process_remaining', complete: false } }))
    odin().computerReconcile = async (params: Record<string, unknown>) => (sent.push(params), answer)
    odin().computerStatus = async () => answer
    await records.reconcileComputer(status({}) as never)
    expect(sent[0]).toMatchObject({ session_id: 's1', generation: 3 })
    const { management } = await import('../../src/renderer/src/stores/management')
    expect(management.notes['computer:s1']).toBe('Not released: a process the session started is still running. The session stays quarantined.')
    answer = ok(status({ state: 'closed', recovery: { status: 'operator_acknowledged_unverified', reason: 'operator_verified_external_cleanup', complete: false } }))
    await records.reconcileComputer(status({}) as never)
    expect(management.notes['computer:s1']).toBe('Acknowledged: Odin closed the session on your word. Its cleanup stays unverified.')
    expect(records.reconcileOutcome(status({ state: 'closed', recovery: { status: 'absence_verified', reason: 'recorded_processes_gone', complete: true } }) as never)).toBe(
      'Released: Odin verified nothing of the session remains.'
    )
  })
})
