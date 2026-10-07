import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from 'vitest'
import { admissionReceipt } from './e2e/admission-receipt'

test('an empty or partial reserved fence is not a published admission receipt', () => {
  const root = mkdtempSync(join(tmpdir(), 'odin-admission-'))
  const path = join(root, 'admitted.json')
  try {
    expect(admissionReceipt(path)).toBeNull()
    for (const content of ['', '{"records":', '{"records":[]}']) {
      writeFileSync(path, content)
      expect(admissionReceipt(path)).toBeNull()
    }
    const complete = { records: [{ supervisorPid: 123 }], result: 'admitted' }
    writeFileSync(path, JSON.stringify(complete))
    expect(admissionReceipt(path)).toEqual(complete)
  } finally { rmSync(root, { recursive: true, force: true }) }
})
