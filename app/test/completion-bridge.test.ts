import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MANAGEMENT, type ManagementMethod, type OdinApi } from '../src/shared/api'
import { MANAGEMENT_SCHEMAS, parseRequest } from '../src/main/schemas'
const mock = vi.hoisted(() => ({ handlers: new Map<string, (event: unknown, raw: unknown) => Promise<unknown>>(), api: null as unknown, invoke: vi.fn() }))
vi.mock('electron', () => ({
  ipcMain: { handle: (name: string, fn: (event: unknown, raw: unknown) => Promise<unknown>) => mock.handlers.set(name, fn) },
  ipcRenderer: { invoke: mock.invoke, on: vi.fn(), removeListener: vi.fn() },
  contextBridge: { exposeInMainWorld: (_name: string, value: unknown) => { mock.api = value } },
  webUtils: { getPathForFile: vi.fn() }
}))
import { registerIpc, type IpcDeps } from '../src/main/ipc'
import '../src/preload/index'
const samples = {
  auditDiffs: { tool: 'read_file', user: 'owner', date: '2026-10', limit: 'invalid' }, auditFailures: { window: 24 },
  auditTail: { lines: 200, cursor: 'opaque' }, logsStats: {}, logsTail: { lines: 200 },
  knowledgeChunks: { source: 'note' }, knowledgeDuplicates: { threshold: 0.5 },
  knowledgeMerge: { keep_source: 'note', remove_source: 'copy' }, knowledgeVersion: { source: 'note', version: 0 },
  knowledgeDiff: { source: 'note', v1: 0, v2: 1 }, learnedList: {}, learnedUpdate: { key: 'lesson', content: '', category: '' }, learnedDelete: { key: 'lesson' },
  observabilityStats: {}, observabilityRisk: {}, observabilityFreshness: {}, observabilityBulkheads: {}, observabilityCompression: {},
  recoveryStats: {}, recoveryRecent: { limit: 20 }, capacitySnapshot: {}, poolsSsh: {}, poolsHttp: {}, poolsClose: { host: 'lab', ssh_user: 'odin' },
  openrouterCatalogue: {}, openrouterEndpoints: { model: 'author/model' }, openrouterSelect: { model: 'author/model', provider_tag: '' }, providersCompatDiagnostic: {},
  trajectoriesList: {}, trajectoriesRead: { filename: 'trace.jsonl', channel_id: 'c', user_id: 'owner', tool_name: 'read_file', errors_only: true, limit: 500 },
  trajectoriesSearch: { limit: 50 }, trajectoriesMessage: { message_id: 'm' }, codexRefresh: { index: '0' }
} satisfies Partial<Record<ManagementMethod, Record<string, unknown>>>
const event = { sender: { id: 42 }, senderFrame: { url: 'app://odin/index.html', processId: 1, routingId: 2 } }
const request = vi.fn()
beforeEach(() => {
  mock.handlers.clear(); request.mockReset(); mock.invoke.mockReset()
  registerIpc({ broker: { request }, windowId: () => 42, mainFrame: () => ({ processId: 1, routingId: 2 }) } as unknown as IpcDeps)
  mock.invoke.mockImplementation((channel, params) => mock.handlers.get(channel)!(event, params))
  request.mockResolvedValue({ ok: true, result: { received: true } })
})
describe('completion named bridge contracts', () => {
  for (const [name, params] of Object.entries(samples)) {
    const method = name as ManagementMethod
    it(`${name} reaches only its named core method with validated params`, async () => {
      const call = (mock.api as OdinApi)[method] as (params: unknown) => Promise<unknown>
      await call(params)
      const [core, passed, id] = request.mock.calls[0]!
      expect(core).toBe(MANAGEMENT[method].core)
      expect(passed).toEqual(params)
      expect(MANAGEMENT[method].command ? typeof id : id).toBe(MANAGEMENT[method].command ? 'string' : undefined)
      expect(parseRequest(MANAGEMENT_SCHEMAS[method], { ...params, unexpected: true }).ok).toBe(false)
    })
  }
  it('preserves old-core capability refusal for reads and mutations', async () => {
    const refusal = { ok: false, error: { code: 'capability_unavailable', message: 'Service is not available yet' } }
    request.mockResolvedValue(refusal)
    expect(await (mock.api as OdinApi).auditTail({ lines: 200 })).toEqual(refusal)
    expect(await (mock.api as OdinApi).codexRefresh({ index: 0 })).toEqual(refusal)
  })
  it('rejects subframes and invalid fields without reaching the core', async () => {
    const handler = mock.handlers.get(MANAGEMENT.poolsClose.channel)!
    expect(await handler({ ...event, senderFrame: { ...event.senderFrame, routingId: 3 } }, {})).toMatchObject({ ok: false, error: { code: 'unauthorized' } })
    expect(await handler(event, { unexpected: true })).toMatchObject({ ok: false, error: { code: 'bad_request' } })
    expect(request).not.toHaveBeenCalled()
  })
  it('preserves engine-owned fallback/clamp inputs', () => {
    expect(parseRequest(MANAGEMENT_SCHEMAS.auditDiffs, { limit: 'not-an-integer' }).ok).toBe(true)
    expect(parseRequest(MANAGEMENT_SCHEMAS.trajectoriesSearch, { limit: 501 }).ok).toBe(true)
    expect(parseRequest(MANAGEMENT_SCHEMAS.recoveryRecent, { limit: 0 }).ok).toBe(true)
    expect(parseRequest(MANAGEMENT_SCHEMAS.learnedUpdate, { key: 'k', content: '' }).ok).toBe(true)
  })
})
