import { describe, expect, it } from 'vitest'
import { MANAGEMENT } from '../src/shared/api'
import {
  MANAGEMENT_SCHEMAS,
  attachPathsSchema,
  controlSchema,
  createConversationSchema,
  editLeafSchema,
  imageIntentSchema,
  parseRequest,
  searchSchema,
  steerSchema,
  submitSchema
} from '../src/main/schemas'

const uuid = '0b6f1c1e-9a3e-4a8e-9d43-2f1f0c7d5a10'

describe('bridge request validation', () => {
  it('accepts a revision-bound model leaf without admitting a second change', () => {
    const base = { method: 'models.main.set', params: { model: 'gpt-6-luna', expected_revision: 'rev-1' } }
    expect(parseRequest(editLeafSchema, base).ok).toBe(true)
    expect(parseRequest(editLeafSchema, { ...base, params: { ...base.params, other: true } }).ok).toBe(false)
    expect(parseRequest(editLeafSchema, { ...base, params: { ...base.params, expected_revision: 2 } }).ok).toBe(false)
  })
  it('accepts a well-formed submission', () => {
    const r = parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: 'c_1', text: 'hi' })
    expect(r.ok).toBe(true)
  })

  it('refuses unknown fields, bad IDs and oversized text', () => {
    expect(parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: 'c_1', text: 'hi', extra: 1 }).ok).toBe(false)
    expect(parseRequest(submitSchema, { client_submission_id: 'not-a-uuid', conversation_id: 'c_1', text: 'hi' }).ok).toBe(false)
    expect(parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: '../etc', text: 'hi' }).ok).toBe(false)
    // As on Discord, a message may be only attachments, but never nothing at all.
    const attachment = { ref: 'a_1', add_to_knowledge: false }
    expect(parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: 'c_1', text: '', attachments: [attachment] }).ok).toBe(true)
    expect(parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: 'c_1', text: '  ' }).ok).toBe(false)
    // The core's attachments_per_turn decides how many go with a message; the bridge only bounds the frame.
    expect(parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: 'c_1', text: 'hi', attachments: Array(11).fill(attachment) }).ok).toBe(true)
    expect(parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: 'c_1', text: 'hi', attachments: Array(1001).fill(attachment) }).ok).toBe(false)
    expect(parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: 'c_1', text: 'x'.repeat(32_001) }).ok).toBe(false)
  })

  it('binds controls to an exact request and generation', () => {
    const base = { control_command_id: uuid, conversation_id: 'c_1', request_id: 'r_1', generation: 1 }
    expect(parseRequest(controlSchema, base).ok).toBe(true)
    expect(parseRequest(controlSchema, { ...base, generation: -1 }).ok).toBe(false)
    expect(parseRequest(controlSchema, { control_command_id: uuid, conversation_id: 'c_1' }).ok).toBe(false)
  })

  it('caps steer text at Odin’s 4,000-character limit', () => {
    const base = { control_command_id: uuid, conversation_id: 'c_1', request_id: 'r_1', generation: 1 }
    expect(parseRequest(steerSchema, { ...base, text: 'x'.repeat(4_000) }).ok).toBe(true)
    expect(parseRequest(steerSchema, { ...base, text: 'x'.repeat(4_001) }).ok).toBe(false)
  })

  it('reports where a request was invalid', () => {
    const r = parseRequest(submitSchema, { client_submission_id: uuid, conversation_id: 'c_1' })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toMatchObject({ code: 'bad_request', disposition: 'rejected' })
  })
})

describe('review round 1: no limits Odin does not have', () => {
  it('accepts a search query longer than 500 characters (D17)', () => {
    expect(parseRequest(searchSchema, { query: 'x'.repeat(501) }).ok).toBe(true)
  })

  it('puts no count of its own on dropped or pasted files: the core announces the limit (D17)', () => {
    const paths = Array.from({ length: 21 }, (_, i) => `/home/user/file-${i}.txt`)
    expect(parseRequest(attachPathsSchema, { paths }).ok).toBe(true)
    expect(parseRequest(attachPathsSchema, { paths: Array.from({ length: 1001 }, (_, i) => `/f${i}`) }).ok).toBe(true)
  })

  it('puts no character cap on a search query: only the frame limit bounds it (D17)', () => {
    expect(parseRequest(searchSchema, { query: 'x'.repeat(200_001) }).ok).toBe(true)
  })

  it('requires the window to name each conversation command', () => {
    expect(parseRequest(createConversationSchema, { title: 'Chat' }).ok).toBe(false)
    expect(parseRequest(createConversationSchema, { command_id: crypto.randomUUID(), title: 'Chat' }).ok).toBe(true)
  })
})

describe('management methods', () => {
  it('give every bridge method its own channel, one core method and its own strict schema', () => {
    const names = Object.keys(MANAGEMENT)
    expect(Object.keys(MANAGEMENT_SCHEMAS).sort()).toEqual([...names].sort())
    expect(new Set(names.map((n) => MANAGEMENT[n as keyof typeof MANAGEMENT].channel)).size).toBe(names.length)
    for (const name of names) {
      // An unknown field never reaches the core.
      expect(parseRequest(MANAGEMENT_SCHEMAS[name as keyof typeof MANAGEMENT_SCHEMAS], { surprise: true }).ok).toBe(false)
    }
  })

  it("follows Odin's bounds: skill names up to 100 characters, MCP server names as Odin's manager accepts them", () => {
    expect(parseRequest(MANAGEMENT_SCHEMAS.skillsGet, { name: 'a skill with spaces' }).ok).toBe(true)
    expect(parseRequest(MANAGEMENT_SCHEMAS.skillsGet, { name: 'x'.repeat(101) }).ok).toBe(false)
    expect(parseRequest(MANAGEMENT_SCHEMAS.skillsSave, { name: 's', code: 'x'.repeat(50_000), create: true }).ok).toBe(true)
    expect(parseRequest(MANAGEMENT_SCHEMAS.mcpDelete, { name: '_Lmms2' }).ok).toBe(true)
    expect(parseRequest(MANAGEMENT_SCHEMAS.mcpDelete, { name: '2lmms' }).ok).toBe(false)
  })
})

describe('review round 2: image-model intent', () => {
  it('takes follow or pin for the two image leaves, bound to a revision, and nothing else', () => {
    expect(parseRequest(imageIntentSchema, { expected_revision: 'r', operations: { image_model: 'pin' } }).ok).toBe(true)
    expect(parseRequest(imageIntentSchema, { expected_revision: 'r', operations: {} }).ok).toBe(false)
    expect(parseRequest(imageIntentSchema, { expected_revision: 'r', operations: { image_model: 'lock' } }).ok).toBe(false)
    expect(parseRequest(imageIntentSchema, { expected_revision: 'r', operations: { quality: 'pin' } }).ok).toBe(false)
    expect(parseRequest(imageIntentSchema, { operations: { outer_model: 'follow' } }).ok).toBe(false)
  })
})

describe('hosts and schedules bridge methods', () => {
  it('imports only a named existing host, without accepting trust overrides or activation fields', () => {
    expect(parseRequest(MANAGEMENT_SCHEMAS.hostsImportLegacy, { alias: 'old-host' }).ok).toBe(true)
    for (const request of [{}, { alias: '' }, { alias: 'a'.repeat(65) }, { alias: 'old-host', tested: true }, { alias: 'old-host', trust_mode: 'tofu' }, { alias: 'old-host', token: 'x' }]) {
      expect(parseRequest(MANAGEMENT_SCHEMAS.hostsImportLegacy, request).ok).toBe(false)
    }
  })
  it("takes a new host only under Odin's alias, user and fingerprint rules", () => {
    const host = { alias: 'gpu_box', address: '10.0.0.9', ssh_user: 'odin', trust_mode: 'pinned', expected_fingerprints: ['SHA256:' + 'A'.repeat(43)] }
    expect(parseRequest(MANAGEMENT_SCHEMAS.hostsPrepare, host).ok).toBe(true)
    expect(parseRequest(MANAGEMENT_SCHEMAS.hostsPrepare, { ...host, alias: '-gpu' }).ok).toBe(false)
    expect(parseRequest(MANAGEMENT_SCHEMAS.hostsPrepare, { ...host, ssh_user: 'a b' }).ok).toBe(false)
    expect(parseRequest(MANAGEMENT_SCHEMAS.hostsPrepare, { ...host, expected_fingerprints: ['MD5:aa'] }).ok).toBe(false)
    expect(parseRequest(MANAGEMENT_SCHEMAS.hostsPrepare, { ...host, trust_mode: 'legacy' }).ok).toBe(false)
    expect(parseRequest(MANAGEMENT_SCHEMAS.hostsSettings, { default_host: '' }).ok).toBe(true)
  })

  it('names the action when a schedule is created, and never when it is changed', () => {
    expect(parseRequest(MANAGEMENT_SCHEMAS.schedulesSave, { description: 'x', action: 'check', cron: '0 9 * * *' }).ok).toBe(true)
    expect(parseRequest(MANAGEMENT_SCHEMAS.schedulesSave, { id: 'ab12cd34', description: 'y', paused: true }).ok).toBe(true)
    expect(parseRequest(MANAGEMENT_SCHEMAS.schedulesSave, { id: 'ab12cd34', action: 'reminder' }).ok).toBe(false)
    expect(parseRequest(MANAGEMENT_SCHEMAS.schedulesSave, { description: 'x', paused: true }).ok).toBe(false)
    expect(parseRequest(MANAGEMENT_SCHEMAS.schedulesSave, { description: 'x'.repeat(501) }).ok).toBe(false)
  })
})

describe('personality, state and records bridge methods', () => {
  it('take only their own fields, within bounds', () => {
    expect(parseRequest(MANAGEMENT_SCHEMAS.memorySet, { scope: 'global', key: 'k', value: { nested: [1, 'two'] } }).ok).toBe(true)
    expect(parseRequest(MANAGEMENT_SCHEMAS.memorySet, { scope: 'global', key: '', value: 'x' }).ok).toBe(false)
    expect(parseRequest(MANAGEMENT_SCHEMAS.memoryBulkDelete, { entries: [] }).ok).toBe(false)
    expect(parseRequest(MANAGEMENT_SCHEMAS.knowledgeRestore, { source: 'a', version: 0 }).ok).toBe(true)
    expect(parseRequest(MANAGEMENT_SCHEMAS.knowledgeRestore, { source: 'a', version: -1 }).ok).toBe(false)
    expect(parseRequest(MANAGEMENT_SCHEMAS.logsSearch, { level: 'debug' }).ok).toBe(false)
    expect(parseRequest(MANAGEMENT_SCHEMAS.computerReconcile, { session_id: 's', generation: 3, acknowledgment: 'ACKNOWLEDGE UNVERIFIED CLEANUP s' }).ok).toBe(true)
    expect(parseRequest(MANAGEMENT_SCHEMAS.personalitySet, { preset: 'odin', surprise: 1 }).ok).toBe(false)
  })
})

