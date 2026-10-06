import { describe, expect, it } from 'vitest'
import { mkdtempSync, writeFileSync, appendFileSync, rmSync, truncateSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { OrcaSpeech, occurrences, speechRecords, speechText } from './e2e/orca-speech'

describe('Orca native emission evidence', () => {
  it('does not mistake AX, events or generated utterances for spoken output', () => {
    expect(speechRecords('EVENT object:state-changed:busy SPEECH OUTPUT: \'Odin is working\'\n' +
      'SPEECH GENERATOR: New conversation push button\n' +
      'name: SPEECH OUTPUT: \'Task completed\'\n')).toEqual([])
  })
  it('parses timestamped emissions, embedded apostrophes, multiline and voice dictionaries', () => {
    expect(speechRecords("12:34:56.123456 - SPEECH OUTPUT: 'Odin has read the steer.' {'established': True}\n" +
      "SPEECH OUTPUT: 'Odin doesn’t know'\n" +
      "12:34:57.123456 - SPEECH OUTPUT: 'Page 1\n                    Stored result' {'rate': 50}\n" +
      "SPEECH OUTPUT: 'Odin's message' {'family': {'name': 'default'}}\n").map((r) => r.text))
      .toEqual(['Odin has read the steer.', 'Odin doesn’t know', 'Page 1\n  Stored result', "Odin's message"])
  })
  it('rejects incomplete records and counts flooding without case sensitivity', () => {
    expect(speechText("SPEECH OUTPUT: 'unfinished\nEVENT not speech")).toBe('')
    expect(occurrences('Task completed. task COMPLETED.', 'Task completed.')).toBe(2)
  })
  it('uses fresh bounded offsets and refuses truncation', () => {
    const dir = mkdtempSync(join(tmpdir(), 'orca-log-test-'))
    const path = join(dir, 'orca.log')
    writeFileSync(path, "SPEECH OUTPUT: 'stale focus'\n")
    const log = new OrcaSpeech(path)
    try {
      log.mark()
      expect(log.text()).toBe('')
      appendFileSync(path, "SPEECH OUTPUT: 'Message entry'\n")
      expect(log.text()).toBe('Message entry')
      truncateSync(path)
      expect(() => log.text()).toThrow('truncated')
    } finally { log.close(); rmSync(dir, { recursive: true }) }
  })
  it('refuses wrong ownership and oversized per-task data', () => {
    const dir = mkdtempSync(join(tmpdir(), 'orca-log-test-'))
    const path = join(dir, 'orca.log')
    writeFileSync(path, '')
    expect(() => new OrcaSpeech(path, -1)).toThrow('owned')
    const log = new OrcaSpeech(path)
    try {
      truncateSync(path, 32 * 1024 * 1024 + 1)
      expect(() => log.read()).toThrow('budget')
    } finally { log.close(); rmSync(dir, { recursive: true }) }
  })
})
