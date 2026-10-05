import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { DraftStore } from '../src/main/drafts'

const dirs: string[] = []
afterEach(() => {
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true })
})

function store(): { drafts: DraftStore; path: string } {
  const dir = mkdtempSync(join(tmpdir(), 'odin-drafts-'))
  dirs.push(dir)
  const path = join(dir, 'profile', 'drafts.json')
  return { drafts: new DraftStore(path, 5), path }
}

describe('draft store', () => {
  it('keeps a draft per conversation in an owner-only file that survives a restart', () => {
    const { drafts, path } = store()
    drafts.set('c1', 'half a thought')
    drafts.set('c2', 'another')
    drafts.flush()
    expect(statSync(path).mode & 0o777).toBe(0o600)
    const reopened = new DraftStore(path)
    expect(reopened.get('c1')).toBe('half a thought')
    expect(reopened.get('c2')).toBe('another')
    expect(reopened.get('c3')).toBe('')
  })

  it('removes an emptied draft and caps a draft at 32,000 characters', () => {
    const { drafts, path } = store()
    drafts.set('c1', 'x'.repeat(40_000))
    drafts.set('c2', 'keep')
    drafts.set('c2', '')
    drafts.flush()
    const saved = JSON.parse(readFileSync(path, 'utf8')) as Record<string, string>
    expect(saved.c1).toHaveLength(32_000)
    expect('c2' in saved).toBe(false)
  })

  it('starts empty from a missing or malformed file', () => {
    const { drafts, path } = store()
    expect(drafts.get('c1')).toBe('') // no file yet
    drafts.set('c1', 'ok')
    drafts.flush()
    for (const broken of ['[1, 2, 3]', '{not json', '"a string"']) {
      writeFileSync(path, broken)
      expect(new DraftStore(path).get('c1')).toBe('')
    }
  })
})
