import { readFileSync } from 'node:fs'

/** The fixture reserves its restart fence before publishing the admission JSON. */
export function admissionReceipt(path: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(readFileSync(path, 'utf8'))
    if (!value || typeof value !== 'object' || !('records' in value) || !Array.isArray(value.records)
      || !value.records.length) return null
    return value as Record<string, unknown>
  } catch (error) {
    if (error instanceof SyntaxError || (error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw error
  }
}
