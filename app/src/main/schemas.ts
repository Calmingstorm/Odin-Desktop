// Shapes of every request the window may make. Anything that doesn't match is refused before it reaches the core.
import { z } from 'zod'
import type { CoreError } from '../shared/api'

const coreId = z.string().min(1).max(128).regex(/^[A-Za-z0-9_.:-]+$/)

export const createConversationSchema = z
  .object({ title: z.string().trim().min(1).max(200).optional(), parent_id: coreId.optional(), from_message_id: coreId.optional() })
  .strict()

const revision = z.number().int().nonnegative()

export const updateConversationSchema = z
  .object({ id: coreId, expected_rev: revision, title: z.string().trim().min(1).max(200).optional(), archived: z.boolean().optional() })
  .strict()

export const conversationRevisionSchema = z.object({ id: coreId, expected_rev: revision }).strict()

export const markReadSchema = z.object({ id: coreId, through_message_id: coreId }).strict()

export const searchSchema = z
  .object({
    query: z.string().trim().min(1).max(500),
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
      .max(10)
      .optional()
  })
  .strict()
  // As on Discord, a message may be only attachments.
  .refine((v) => v.text.trim().length > 0 || (v.attachments?.length ?? 0) > 0, { message: 'a message needs text or attachments' })

export const usageSchema = z.object({ period: z.enum(['session', 'day', 'week']) }).strict()

export const reloadSchema = z.object({ scope: z.enum(['skills', 'config', 'context']) }).strict()

export const draftGetSchema = z.object({ conversation_id: coreId }).strict()

export const draftSetSchema = z.object({ conversation_id: coreId, text: z.string().max(32_000) }).strict()

export const attachPathsSchema = z.object({ paths: z.array(z.string().min(1).max(4_096)).min(1).max(20) }).strict()

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
