import { mkdtempSync, mkdirSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
// Executable ESM runner is side-effect free when imported.
// @ts-expect-error focused executable runner has no declaration file
import { composerOutput, composerFixtureCommand, validateComposerReceipts, COMPOSER_PROOFS } from '../scripts/composer-geometry.mjs'

const roots: string[] = []
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }) })
function temporary(): string { const root = mkdtempSync(join(tmpdir(), 'composer-runner-test-')); roots.push(root); return root }
function passing() { return COMPOSER_PROOFS.map((name: string) => ({ name, outcome: 'passed', measurements: [{ screenshot: '/external/evidence.png' }] })) }

describe('focused Composer runner evidence guards', () => {
  it('accepts exactly the five complete unique passing proofs in any order', () => {
    expect(() => validateComposerReceipts(passing().reverse())).not.toThrow()
  })
  it('refuses missing, duplicate, extra and unknown proof names', () => {
    expect(() => validateComposerReceipts([])).toThrow('five unique')
    const duplicate = passing(); duplicate[4] = duplicate[0]
    expect(() => validateComposerReceipts(duplicate)).toThrow('five unique')
    expect(() => validateComposerReceipts([...passing(), { name: 'extra', outcome: 'passed', measurements: [{}] }])).toThrow('five unique')
    const unknown = passing(); unknown[0].name = 'unknown'
    expect(() => validateComposerReceipts(unknown)).toThrow('Missing complete passing')
    expect(() => validateComposerReceipts(null)).toThrow('five unique')
  })
  it('refuses failed outcomes, unknown cleanup and missing or malformed measurements', () => {
    for (const change of [{ outcome: 'failed' }, { cleanupError: 'release unknown' }, { measurements: [] }, { measurements: null }, { measurements: 'not an array' }]) {
      const receipts = passing(); Object.assign(receipts[0], change)
      expect(() => validateComposerReceipts(receipts)).toThrow('Missing complete passing')
    }
  })
  it('keeps output outside repository including unresolved descendants and symlinks', () => {
    const root = temporary()
    expect(composerOutput(join(root, 'nested', 'not-yet-created'))).toBe(join(root, 'nested', 'not-yet-created'))
    const repository = resolve(import.meta.dirname, '../..')
    expect(() => composerOutput(repository)).toThrow('outside repository')
    expect(() => composerOutput(join(repository, 'uncreated-composer-evidence'))).toThrow('outside repository')
    symlinkSync(repository, join(root, 'repo-alias'), 'dir')
    expect(() => composerOutput(join(root, 'repo-alias', 'uncreated-proof'))).toThrow('outside repository')
    mkdirSync(join(root, 'real-output'))
    symlinkSync(join(root, 'real-output'), join(root, 'output-alias'), 'dir')
    expect(composerOutput(join(root, 'output-alias', 'run'))).toBe(join(root, 'real-output', 'run'))
  })
  it('uses explicit printable Python fixture bootstrap and seeds through fixture methods', () => {
    const command = composerFixtureCommand('/owned/python', '/owned/fixture.py')
    expect(command.slice(0, 4)).toEqual(['/owned/python', '-B', '-P', '-c'])
    expect(command.at(-1)).toBe('/owned/fixture.py')
    expect(command[4]).not.toContain('\n')
    expect(command[4]).toContain('self.m_conv_create')
    expect(command[4]).toContain('self.commit_message')
    expect(command.join(' ')).not.toContain('--no-sandbox')
  })
  it('refuses implicit or relative Python and fixture paths', () => {
    for (const [python, fixture] of [['python', '/owned/f.py'], ['/owned/python', 'f.py'], ['', '/owned/f.py'], ['/owned/python', '']]) {
      expect(() => composerFixtureCommand(python, fixture)).toThrow('absolute Python and fixture')
    }
  })
})
