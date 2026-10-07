// Machine-readable P4.5 case outcomes. A case is recorded only after every assertion in its test passed; a failing
// test records nothing, so a missing record is never read as a pass.
import { appendFileSync } from 'node:fs'
import { join } from 'node:path'
import type { TestInfo } from '@playwright/test'

export interface CaseRecord {
  id: string
  outcome: 'pass'
  test: string
  file: string
  source_sha: string | null
  recorded_at: string
  evidence: Record<string, unknown>
}

export async function recordCase(info: TestInfo, id: string, evidence: Record<string, unknown>): Promise<CaseRecord> {
  const record: CaseRecord = {
    id, outcome: 'pass', test: info.title, file: info.file.replace(/^.*\/app\//, 'app/'),
    source_sha: process.env.ODIN_R4_SOURCE_SHA ?? null, recorded_at: new Date().toISOString(), evidence
  }
  await info.attach(`r4-${id}`, { body: JSON.stringify(record, null, 2), contentType: 'application/json' })
  const out = process.env.ODIN_APP_E2E_OUT
  if (out) appendFileSync(join(out, 'r4-cases.jsonl'), `${JSON.stringify(record)}\n`)
  return record
}
