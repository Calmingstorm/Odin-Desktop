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
  .object({ client_submission_id: z.uuid(), conversation_id: coreId, text: z.string().min(1).max(32_000) })
  .strict()

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
