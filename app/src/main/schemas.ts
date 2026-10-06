// Shapes of every request the window may make. Anything that doesn't match is refused before it reaches the core.
import { z } from 'zod'
import type { CoreError, ManagementMethod } from '../shared/api'

const coreId = z.string().min(1).max(128).regex(/^[A-Za-z0-9_.:-]+$/)

/** The window names each conversation command, so a lost answer is reconciled by its late receipt, never re-sent. */
const commandId = z.uuid()

export const createConversationSchema = z
  .object({
    command_id: commandId,
    title: z.string().trim().min(1).max(200).optional(),
    parent_id: coreId.optional(),
    from_message_id: coreId.optional()
  })
  .strict()

const revision = z.number().int().nonnegative()

export const updateConversationSchema = z
  .object({
    command_id: commandId,
    id: coreId,
    expected_rev: revision,
    title: z.string().trim().min(1).max(200).optional(),
    archived: z.boolean().optional()
  })
  .strict()

export const conversationRevisionSchema = z.object({ command_id: commandId, id: coreId, expected_rev: revision }).strict()

export const markReadSchema = z.object({ id: coreId, through_message_id: coreId }).strict()

export const searchSchema = z
  .object({
    // Odin sets no query limit. The frame limit is the only bound, and the broker refuses a larger request by name.
    query: z.string().trim().min(1),
    conversation_id: coreId.optional(),
    limit: z.number().int().min(1).max(50).optional(),
    cursor: z.string().max(64).optional()
  })
  .strict()

export const messagesAroundSchema = z
  .object({
    conversation_id: coreId,
    message_id: coreId,
    before: z.number().int().min(0).max(50).optional(),
    after: z.number().int().min(0).max(50).optional()
  })
  .strict()

export const listMessagesSchema = z
  .object({ conversation_id: coreId, before: coreId.optional(), limit: z.number().int().min(1).max(100).optional() })
  .strict()

export const snapshotConversationSchema = z
  .object({ conversation_id: coreId, limit: z.number().int().min(1).max(100).optional() })
  .strict()

// 32,000 characters matches Odin's existing chat API limit.
export const submitSchema = z
  .object({
    client_submission_id: z.uuid(),
    conversation_id: coreId,
    text: z.string().max(32_000),
    attachments: z
      .array(z.object({ ref: coreId, add_to_knowledge: z.boolean() }).strict())
      // The core's attachments_per_turn applies; this bound only keeps one submission inside a frame.
      .max(1000)
      .optional()
  })
  .strict()
  // As on Discord, a message may be only attachments.
  .refine((v) => v.text.trim().length > 0 || (v.attachments?.length ?? 0) > 0, { message: 'a message needs text or attachments' })

export const usageSchema = z.object({ period: z.enum(['24h', '7d', '30d', 'all']) }).strict()

export const reloadSchema = z.object({ scope: z.enum(['skills', 'config', 'context']) }).strict()

export const draftGetSchema = z.object({ conversation_id: coreId }).strict()

export const draftSetSchema = z.object({ conversation_id: coreId, text: z.string().max(32_000) }).strict()

// No count of its own: the renderer applies the core's announced per-turn limit to every way of attaching.
export const attachPathsSchema = z.object({ paths: z.array(z.string().min(1).max(4_096)).min(1) }).strict()

export const attachBytesSchema = z
  .object({
    name: z.string().min(1).max(255),
    mime: z.string().min(1).max(127),
    data: z.custom<Uint8Array>((value) => value instanceof Uint8Array, 'expected bytes')
  })
  .strict()

export const uploadAttachmentSchema = z.object({ id: z.uuid(), conversation_id: coreId }).strict()

export const cancelAttachmentSchema = z.object({ id: z.uuid() }).strict()

const workKind = z.enum(['agent', 'task', 'loop', 'process', 'schedule', 'workflow'])

export const workListSchema = z.object({ kind: workKind.optional(), conversation_id: coreId.optional() }).strict()

export const workControlSchema = z
  .object({
    control_command_id: z.uuid(),
    kind: workKind,
    id: coreId,
    action: z.enum(['stop', 'cancel', 'restart', 'pause', 'resume', 'run_now'])
  })
  .strict()

export const toolDetailSchema = z.object({ request_id: coreId, invocation_id: coreId }).strict()

export const toolOutputSchema = z
  .object({ cursor: z.string().min(1).max(512), limit: z.number().int().min(1).max(65_536) })
  .strict()

export const fetchArtifactSchema = z.object({ ref: coreId }).strict()

export const artifactActionSchema = z.object({ ref: coreId, name: z.string().min(1).max(255) }).strict()

export const reportPageSchema = z.object({ report_id: coreId, page: z.number().int().min(1).max(100_000) }).strict()

export const copyTextSchema = z.object({ text: z.string().max(2_000_000) }).strict()

export const controlSchema = z
  .object({
    control_command_id: z.uuid(),
    conversation_id: coreId,
    request_id: coreId,
    generation: z.number().int().nonnegative()
  })
  .strict()

// 4,000 characters per steer item is Odin's existing steering limit.
export const steerSchema = controlSchema.extend({ text: z.string().min(1).max(4_000) }).strict()

export const setAutostartSchema = z.object({ enabled: z.boolean() }).strict()

const clock = z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/)

export const setNotificationsSchema = z
  .object({
    enabled: z.boolean().optional(),
    previews: z.boolean().optional(),
    quietHours: z.object({ enabled: z.boolean().optional(), start: clock.optional(), end: clock.optional() }).strict().optional()
  })
  .strict()

export const setMutedSchema = z.object({ conversation_id: coreId, muted: z.boolean() }).strict()

const settingsPath = z.string().min(1).max(200).regex(/^[A-Za-z0-9_]+(\.[A-Za-z0-9_-]+)*$/)
/** Any JSON value a settings leaf can hold, bounded so one change can't flood the core. */
const leafValue = z.json().refine((v) => JSON.stringify(v).length <= 64 * 1024, 'value too large')

export const settingsSetSchema = z
  .object({
    // Odin's revision is a hash of the whole configuration, so any change elsewhere changes it.
    expected_revision: z.string().min(1).max(128),
    changes: z
      .array(
        z.union([
          z.object({ path: settingsPath, value: leafValue }).strict(),
          z.object({ path: settingsPath, delete: z.literal(true) }).strict()
        ])
      )
      .min(1)
      .max(200)
  })
  .strict()

export const secretSetSchema = z.object({ path: settingsPath, value: z.string().min(1).max(16_384) }).strict()
export const secretClearSchema = z.object({ path: settingsPath }).strict()

/** The dedicated desktop methods a field may name as its apply handler. Nothing else passes. */
export const imageIntentSchema = z
  .object({
    expected_revision: z.string().min(1).max(128),
    operations: z
      .object({ image_model: z.enum(['follow', 'pin']).optional(), outer_model: z.enum(['follow', 'pin']).optional() })
      .strict()
      .refine((ops) => Object.keys(ops).length > 0, 'name image_model and/or outer_model')
  })
  .strict()

export const LEAF_EDITORS = ['models.main.set', 'models.agents.set'] as const
export const editLeafSchema = z
  .object({ method: z.enum(LEAF_EDITORS), params: z.record(z.string().regex(/^[A-Za-z0-9_]+$/), leafValue) })
  .strict()
  .refine((v) => Object.keys(v.params).filter((key) => key !== 'expected_revision').length === 1, 'one leaf at a time')
  .refine((v) => v.params.expected_revision === undefined ||
    (typeof v.params.expected_revision === 'string' && v.params.expected_revision.length > 0 && v.params.expected_revision.length <= 128),
  'invalid settings revision')

const accountIndex = z.number().int().min(0).max(63)
export const codexIndexSchema = z.object({ index: accountIndex }).strict()
export const codexLabelSchema = z.object({ index: accountIndex, label: z.string().max(80) }).strict()
export const codexPollSchema = z.object({ device_auth_id: z.string().min(1).max(512), user_code: z.string().min(1).max(64) }).strict()

export type ParseResult<T> = { ok: true; value: T } | { ok: false; error: CoreError }

export function parseRequest<T>(schema: z.ZodType<T>, raw: unknown): ParseResult<T> {
  const parsed = schema.safeParse(raw)
  if (parsed.success) return { ok: true, value: parsed.data }
  const first = parsed.error.issues[0]
  const where = first?.path.length ? ` at ${first.path.join('.')}` : ''
  return {
    ok: false,
    error: { code: 'bad_request', message: `invalid request${where}: ${first?.message ?? 'malformed'}`, disposition: 'rejected' }
  }
}

// ---- Management methods: one schema each (shared/api.ts, MANAGEMENT) -----------------------------------------------
// Bounds follow Odin's own: skill names up to 100 characters and code up to 50,000 (web/api_common.py), MCP server
// names as Odin's manager accepts them (tools/mcp/manager.py).

const empty = z.object({}).strict()
const toolName = z.string().min(1).max(128)
const skillName = z.string().min(1).max(100)
const skillCode = z.string().min(1).max(50_000)
const mcpName = z.string().min(1).max(128).regex(/^[A-Za-z_][A-Za-z0-9_]*$/)
const text = z.string().max(16_384)
const secretMap = z.record(z.string().min(1).max(256), text)
const hostAlias = z.string().min(1).max(64)
// Odin's rules for a new host (tools/hosts/control.py): existing aliases are only looked up, so they stay plain text.
const newHostAlias = z.string().regex(/^[A-Za-z][A-Za-z0-9_.-]{0,63}$/)
const sshUser = z.string().regex(/^[A-Za-z_][A-Za-z0-9_.-]{0,63}$/)
const fingerprint = z.string().regex(/^SHA256:[A-Za-z0-9+/]{20,64}$/)
const scheduleId = z.string().min(1).max(64)
const memoryScope = z.string().min(1).max(128)
const memoryKey = z.string().min(1).max(256)
// Existing source labels are exact store identities. Only new ingestion trims and caps them.
const knowledgeSource = z.string().refine((value) => value.trim().length > 0, 'source is required')
const scheduleFields = {
  description: z.string().min(1).max(500).optional(),
  channel_id: z.string().max(128).optional(),
  cron: z.string().min(1).max(256).optional(),
  run_at: z.string().min(1).max(64).optional(),
  cron_timezone: z.string().min(1).max(64).optional(),
  message: z.string().max(4000).optional(),
  tool_name: z.string().min(1).max(128).optional(),
  tool_input: z.record(z.string(), z.json()).optional(),
  report_format: z.string().max(64).optional(),
  steps: z.array(z.json()).min(1).max(100).optional(),
  webhook_config: z.record(z.string(), z.json()).optional(),
  max_retries: z.number().int().min(0).max(100).optional(),
  retry_backoff_seconds: z.number().int().min(0).max(86_400).optional()
}

export const MANAGEMENT_SCHEMAS: Record<ManagementMethod, z.ZodType> = {
  auditDiffs: z.object({ tool: z.string().optional(), user: z.string().optional(), date: z.string().optional(), limit: z.union([z.number(), z.string()]).optional() }).strict(),
  auditFailures: z.object({ window: z.union([z.number(), z.string()]).optional() }).strict(),
  auditTail: z.object({ cursor: z.string().optional(), lines: z.number().int().optional() }).strict(),
  logsStats: empty,
  logsTail: z.object({ cursor: z.string().optional(), lines: z.number().int().optional() }).strict(),
  knowledgeChunks: z.object({ source: knowledgeSource }).strict(),
  knowledgeDuplicates: z.object({ threshold: z.union([z.number(), z.string()]).optional() }).strict(),
  knowledgeMerge: z.object({ keep_source: knowledgeSource, remove_source: knowledgeSource }).strict(),
  knowledgeVersion: z.object({ source: knowledgeSource, version: z.number().int().min(0) }).strict(),
  knowledgeDiff: z.object({ source: knowledgeSource, v1: z.number().int().min(0), v2: z.number().int().min(0) }).strict(),
  learnedList: empty,
  learnedUpdate: z.object({ key: z.string(), content: z.string().optional(), category: z.string().optional() }).strict(),
  learnedDelete: z.object({ key: z.string() }).strict(),
  observabilityStats: empty,
  observabilityRisk: empty,
  observabilityFreshness: empty,
  observabilityBulkheads: empty,
  observabilityCompression: empty,
  recoveryStats: empty,
  recoveryRecent: z.object({ limit: z.union([z.number(), z.string()]).optional() }).strict(),
  capacitySnapshot: empty,
  poolsSsh: empty,
  poolsHttp: empty,
  poolsClose: z.object({ host: z.string().optional(), ssh_user: z.string().optional() }).strict(),
  openrouterCatalogue: empty,
  openrouterEndpoints: z.object({ model: z.string() }).strict(),
  openrouterSelect: z.object({ model: z.string(), provider_tag: z.string().optional(), expected_revision: z.string().optional() }).strict(),
  providersCompatDiagnostic: empty,
  trajectoriesList: empty,
  trajectoriesRead: z.object({ filename: z.string(), limit: z.union([z.number(), z.string()]).optional(), channel_id: z.string().optional(), user_id: z.string().optional(), tool_name: z.string().optional(), errors_only: z.union([z.boolean(), z.string()]).optional() }).strict(),
  trajectoriesSearch: z.object({ limit: z.union([z.number(), z.string()]).optional(), channel_id: z.string().optional(), user_id: z.string().optional(), tool_name: z.string().optional(), errors_only: z.union([z.boolean(), z.string()]).optional() }).strict(),
  trajectoriesMessage: z.object({ message_id: z.string() }).strict(),
  codexRefresh: z.object({ index: z.union([z.number().int(), z.string().regex(/^[+-]?\d+$/)]) }).strict(),
  toolsList: empty,
  toolsSetEnabled: z.object({ name: toolName, enabled: z.boolean() }).strict(),
  toolsTimeoutsGet: empty,
  toolsTimeoutsSet: z
    .object({ default_timeout: z.number().int().positive().optional(), overrides: z.record(toolName, z.number().int().positive()).optional() })
    .strict(),
  skillsList: empty,
  skillsGet: z.object({ name: skillName }).strict(),
  skillsSave: z.object({ name: skillName, code: skillCode, create: z.boolean() }).strict(),
  skillsValidate: z.object({ code: skillCode }).strict(),
  skillsTest: z.object({ name: skillName }).strict(),
  skillsSetEnabled: z.object({ name: skillName, enabled: z.boolean() }).strict(),
  skillsDelete: z.object({ name: skillName }).strict(),
  skillsConfigGet: z.object({ name: skillName }).strict(),
  skillsConfigSet: z.object({ name: skillName, config: z.record(z.string().max(256), z.json()) }).strict(),
  mcpStatus: empty,
  mcpSave: z
    .object({
      name: mcpName,
      create: z.boolean(),
      transport: z.enum(['stdio', 'http']).optional(),
      command: text.optional(),
      args: z.array(text).max(256).optional(),
      url: text.optional(),
      cwd: text.optional(),
      timeout_seconds: z.number().positive().max(86_400).optional(),
      enabled: z.boolean().optional(),
      tool_allowlist: z.array(z.string().max(256)).max(4096).nullable().optional(),
      headers_set: secretMap.optional(),
      headers_remove: z.array(z.string().max(256)).max(256).optional(),
      env_set: secretMap.optional(),
      env_remove: z.array(z.string().max(256)).max(256).optional()
    })
    .strict(),
  mcpSetEnabled: z.object({ name: mcpName, enabled: z.boolean() }).strict(),
  mcpDelete: z.object({ name: mcpName }).strict(),
  mcpReconnect: z.object({ name: mcpName }).strict(),
  mcpRefreshTools: z.object({ name: mcpName }).strict(),
  mcpTools: z.object({ name: mcpName }).strict(),
  mcpSetGlobalEnabled: z.object({ enabled: z.boolean() }).strict(),
  mcpSetLimits: z
    .object({
      max_published_tools_per_server: z.number().int().min(0).max(1_000_000).optional(),
      max_published_tools_global: z.number().int().min(0).max(1_000_000).optional()
    })
    .strict(),
  hostsList: empty,
  hostsSettings: z.object({ default_host: z.string().max(64).optional(), allow_host_tofu: z.boolean().optional() }).strict(),
  hostsPublicKey: empty,
  hostsPrepare: z
    .object({
      alias: newHostAlias,
      address: z.string().min(1).max(253),
      ssh_user: sshUser,
      port: z.number().int().min(1).max(65_535).optional(),
      os: z.enum(['linux', 'macos']).optional(),
      description: z.string().max(200).optional(),
      enabled: z.boolean().optional(),
      trust_mode: z.enum(['pinned', 'ca', 'tofu']),
      expected_fingerprints: z.array(fingerprint).max(16).optional(),
      candidate_fingerprints: z.array(fingerprint).max(16).optional(),
      confirm_tofu: z.boolean().optional(),
      confirm_local: z.boolean().optional()
    })
    .strict(),
  hostsTest: z.object({ token: z.uuid() }).strict(),
  hostsCommit: z.object({ token: z.uuid() }).strict(),
  hostsSetEnabled: z.object({ alias: hostAlias, enabled: z.boolean() }).strict(),
  hostsReferences: z.object({ alias: hostAlias }).strict(),
  hostsDelete: z.object({ alias: hostAlias }).strict(),
  hostsForceRevoke: z.object({ alias: hostAlias }).strict(),
  schedulesList: empty,
  // A new schedule names its action; a change names the schedule, and its action stays what it was.
  schedulesSave: z.union([
    z.object({ ...scheduleFields, action: z.enum(['reminder', 'check', 'workflow', 'webhook']).optional() }).strict(),
    z.object({ ...scheduleFields, id: scheduleId, paused: z.boolean().optional() }).strict()
  ]),
  schedulesDelete: z.object({ id: scheduleId }).strict(),
  schedulesRun: z.object({ id: scheduleId }).strict(),
  schedulesResetFailures: z.object({ id: scheduleId }).strict(),
  schedulesHistory: z.object({ id: scheduleId.optional(), limit: z.number().int().min(1).max(500).optional() }).strict(),
  schedulesValidateCron: z.object({ expression: z.string().min(1).max(256) }).strict(),
  personalityGet: empty,
  personalitySet: z
    .object({
      preset: z.string().min(1).max(64),
      custom_name: z.string().max(200).optional(),
      custom_identity: z.string().max(20_000).optional(),
      custom_voice: z.string().max(20_000).optional()
    })
    .strict(),
  personalityPresetsSave: z
    .object({
      name: z.string().min(1).max(64),
      display_name: z.string().max(200).optional(),
      identity: z.string().max(20_000).optional(),
      voice: z.string().max(20_000).optional()
    })
    .strict(),
  personalityPresetsDelete: z.object({ name: z.string().min(1).max(64) }).strict(),
  memoryList: empty,
  memoryGet: z.object({ scope: memoryScope, key: memoryKey.optional() }).strict(),
  memorySet: z.object({ scope: memoryScope, key: memoryKey, value: z.json() }).strict(),
  memoryDelete: z.object({ scope: memoryScope, key: memoryKey }).strict(),
  memoryBulkDelete: z.object({ entries: z.array(z.object({ scope: memoryScope, key: memoryKey }).strict()).min(1).max(1000) }).strict(),
  listsList: empty,
  listsGet: z.object({ name: z.string().min(1).max(200) }).strict(),
  listsDelete: z.object({ name: z.string().min(1).max(200) }).strict(),
  knowledgeList: empty,
  knowledgeSearch: z.object({ q: z.string().trim().min(1), limit: z.number().int().min(1).max(100).optional() }).strict(),
  knowledgeIngest: z.object({ source: z.string().trim().min(1).max(100), content: z.string().trim().min(1).max(500_000) }).strict(),
  knowledgeReingest: z.object({ source: knowledgeSource }).strict(),
  knowledgeDelete: z.object({ source: knowledgeSource }).strict(),
  knowledgeVersions: z.object({ source: knowledgeSource }).strict(),
  knowledgeRestore: z.object({ source: knowledgeSource, version: z.number().int().min(0) }).strict(),
  auditQuery: z
    .object({
      tool: z.string().max(128).optional(),
      user: z.string().max(128).optional(),
      host: z.string().max(128).optional(),
      q: z.string().max(1000).optional(),
      date: z.string().max(32).optional(),
      error_only: z.boolean().optional(),
      limit: z.number().int().min(1).max(1000).optional()
    })
    .strict(),
  auditVerify: empty,
  healthGet: empty,
  logsSearch: z
    .object({
      q: z.string().max(1000).optional(),
      level: z.enum(['error', 'info', 'all']).optional(),
      tool: z.string().max(128).optional(),
      start: z.string().max(64).optional(),
      end: z.string().max(64).optional(),
      limit: z.number().int().min(1).max(1000).optional()
    })
    .strict(),
  turnStateList: z.object({ limit: z.number().int().min(1).max(500).optional() }).strict(),
  computerStatus: empty,
  computerReconcile: z.object({ session_id: z.string().min(1).max(128), generation: z.number().int().min(0), acknowledgment: z.string().max(300) }).strict()
}

