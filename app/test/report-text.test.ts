// The core's command reports as the report panel shows them: Odin's Discord Markdown rendered, lines kept.
import { describe, expect, it } from 'vitest'
import { reportParts, reportPlainText, type ReportPart } from '../src/shared/report-text'

// The shapes the engine's render_usage, render_status and render_reload produce (src/discord/slash_commands.py).
const USAGE = [
  '**Usage — 7d** · settled turns 85 · generations 213 · error turns 0',
  'Tokens: in 3.9M (100% provider-reported) · out 17.7K',
  '**Codex quota — account 1 (current)** · observed 6s ago',
  '  7d window: 47% used · resets in 5d 21h',
  '  plan prolite · limit premium · credits 0'
].join('\n')
const STATUS = '**Odin v1.0.3** · up 20m 38s\nProvider: **codex**\nModel: **gpt-6.1-sol** · effort high'
const RELOAD = '**Context reloaded** — 2 files in context (1,024 bytes, 980 chars)\nLoaded: `notes.md`, `team_rules.md`'

const bold = (parts: ReportPart[]) => parts.filter((p) => p.bold && !p.code).map((p) => p.text)
const code = (parts: ReportPart[]) => parts.filter((p) => p.code).map((p) => p.text)

describe('report text', () => {
  it('shows bold runs without their markers and keeps every line and indent', () => {
    expect(bold(reportParts(USAGE))).toEqual(['Usage — 7d', 'Codex quota — account 1 (current)'])
    expect(reportPlainText(USAGE)).toBe(USAGE.replaceAll('**', ''))
    expect(reportPlainText(USAGE).split('\n')[3]).toBe('  7d window: 47% used · resets in 5d 21h')
    expect(bold(reportParts(STATUS))).toEqual(['Odin v1.0.3', 'codex', 'gpt-6.1-sol'])
    expect(reportPlainText(STATUS)).toBe('Odin v1.0.3 · up 20m 38s\nProvider: codex\nModel: gpt-6.1-sol · effort high')
  })

  it('shows code spans as code, and bold that holds code as both', () => {
    const parts = reportParts(RELOAD)
    expect(code(parts)).toEqual(['notes.md', 'team_rules.md'])
    expect(reportPlainText(RELOAD)).toBe('Context reloaded — 2 files in context (1,024 bytes, 980 chars)\nLoaded: notes.md, team_rules.md')
    expect(reportParts('**Loaded `a.md`**')).toEqual([
      { text: 'Loaded ', bold: true, code: false },
      { text: 'a.md', bold: true, code: true }
    ])
    // Markers inside a code span are code, not bold.
    expect(reportParts('`**x**` y')).toEqual([
      { text: '**x**', bold: false, code: true },
      { text: ' y', bold: false, code: false }
    ])
  })

  it('removes the escapes Odin puts in account labels, as Discord does', () => {
    // render_quota escapes Markdown in labels: "Primary (pro)" arrives as "Primary \(pro\)".
    expect(reportPlainText('**Codex quota — Primary \\(pro\\) \\- 1 \\(current\\)** · observed 2s ago')).toBe(
      'Codex quota — Primary (pro) - 1 (current) · observed 2s ago'
    )
    expect(bold(reportParts('**a\\*\\*b**'))).toEqual(['a**b'])
    expect(reportParts('\\*\\*not bold\\*\\*')).toEqual([{ text: '**not bold**', bold: false, code: false }])
    // A backslash before anything else is text, as a path's is.
    expect(reportPlainText('C:\\Users\\odin')).toBe('C:\\Users\\odin')
    expect(reportPlainText('ends with \\')).toBe('ends with \\')
  })

  it('shows unpaired or empty markers exactly as written', () => {
    for (const text of ['5 ** 2 = 25', 'a **b', '**', '****', 'a ** b **', '`', '``', 'one ` two'])
      expect(reportPlainText(text)).toBe(text)
    expect(bold(reportParts('a ** b **'))).toEqual([])
    // A bold marker whose only partner sits inside a code span stays text; the code span is still code.
    expect(reportParts('**open `code**`')).toEqual([
      { text: '**open ', bold: false, code: false },
      { text: 'code**', bold: false, code: true }
    ])
  })

  it('keeps blank lines and an empty report', () => {
    expect(reportPlainText('a\n\n**b**\n')).toBe('a\n\nb\n')
    expect(reportParts('')).toEqual([])
    expect(reportParts('\n')).toEqual([{ text: '\n', bold: false, code: false }])
  })
})
