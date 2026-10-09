// The core's command reports (/status, /usage, /reload) are Odin's Discord slash-command text, which uses three pieces
// of Markdown: **bold**, `code` and backslash escapes. The report panel shows them as Discord does and keeps every line
// and space as written. Anything else, an unpaired marker included, shows exactly as written.

export interface ReportPart {
  text: string
  bold: boolean
  code: boolean
}

/** ASCII punctuation, which a backslash escapes. */
const ESCAPABLE = /[!-\/:-@\[-`{-~]/

function escapes(line: string, at: number): boolean {
  return line[at] === '\\' && ESCAPABLE.test(line[at + 1] ?? '')
}

/** Where a code span opening at `at` closes, or -1 when it has no closing backtick or no content. */
function codeEnd(line: string, at: number): number {
  if (line[at] !== '`') return -1
  const end = line.indexOf('`', at + 1)
  return end > at + 1 ? end : -1
}

/** Where a bold run whose content starts at `from` closes: the next `**` after text, outside code and escapes. */
function boldEnd(line: string, from: number): number {
  for (let at = from; at < line.length; at++) {
    if (escapes(line, at)) at++
    else if (codeEnd(line, at) >= 0) at = codeEnd(line, at)
    else if (line.startsWith('**', at) && at > from && line[at - 1] !== ' ') return at
  }
  return -1
}

/** Text without bold markers: code spans apart, escapes removed. */
function spans(text: string, bold: boolean, parts: ReportPart[]): void {
  let plain = ''
  for (let at = 0; at < text.length; at++) {
    const end = codeEnd(text, at)
    if (escapes(text, at)) {
      plain += text[++at]
    } else if (end >= 0) {
      if (plain) parts.push({ text: plain, bold, code: false })
      plain = ''
      parts.push({ text: text.slice(at + 1, end), bold, code: true })
      at = end
    } else {
      plain += text[at]
    }
  }
  if (plain) parts.push({ text: plain, bold, code: false })
}

function lineParts(line: string, parts: ReportPart[]): void {
  let start = 0 // the first character not yet in a part
  for (let at = 0; at < line.length; at++) {
    if (escapes(line, at)) {
      at++
    } else if (codeEnd(line, at) >= 0) {
      at = codeEnd(line, at)
    } else if (line.startsWith('**', at)) {
      const end = line[at + 2] === ' ' ? -1 : boldEnd(line, at + 2)
      if (end < 0) {
        at++ // an unpaired marker is text
        continue
      }
      spans(line.slice(start, at), false, parts)
      spans(line.slice(at + 2, end), true, parts)
      start = end + 2
      at = end + 1
    }
  }
  spans(line.slice(start), false, parts)
}

/** A report as parts, line by line; a "\n" part separates lines. */
export function reportParts(text: string): ReportPart[] {
  const parts: ReportPart[] = []
  text.split('\n').forEach((line, index) => {
    if (index) parts.push({ text: '\n', bold: false, code: false })
    lineParts(line, parts)
  })
  return parts
}

/** The text the report panel shows. */
export function reportPlainText(text: string): string {
  return reportParts(text)
    .map((part) => part.text)
    .join('')
}
