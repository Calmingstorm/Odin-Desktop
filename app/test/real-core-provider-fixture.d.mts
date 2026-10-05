export const REPLY: string
export const TOOL_REPLY: string
export const FILE_CONTENT: string
export const PAGED_TEXT: string
export const IMAGE_BYTES: Buffer
export function startCannedProvider(options: { root: string }): Promise<{
  baseUrl: string; configPath: string; imagePath: string
  requests: { token: string; body: { messages: { role: string; content: unknown }[]; stream: boolean; tools?: unknown[]; model: string } }[]
  release(token: string): void
  close(): Promise<void>
}>
