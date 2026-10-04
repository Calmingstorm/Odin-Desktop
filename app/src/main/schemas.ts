// Shapes of every request the window may make. Anything that doesn't match is refused before it reaches the core.
import { z } from 'zod'
import type { CoreError } from '../shared/api'

const coreId = z.string().min(1).max(128).regex(/^[A-Za-z0-9_.:-]+$/)

export const createConversationSchema = z
  .object({ title: z.string().trim().min(1).max(200).optional(), parent_id: coreId.optional() })
  .strict()

export const listMessagesSchema = z
  .object({ conversation_id: coreId, before: coreId.optional(), limit: z.number().int().min(1).max(100).optional() })
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
