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
