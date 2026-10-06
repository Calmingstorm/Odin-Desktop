import { closeSync, fstatSync, openSync, readSync } from 'node:fs'

export interface SpeechRecord { text: string; raw: string }

/** Only Orca's emission records count. AT-SPI events and speech-generator dumps do not. */
export function speechRecords(log: string): SpeechRecord[] {
  const records: SpeechRecord[] = []
  // Orca 46 debug.println prefixes timestamps and indents embedded newlines by 18 spaces.
  const lines = log.split('\n')
  for (let i = 0; i < lines.length; i++) {
    let raw = lines[i]!
    if (!/^(?:\d{2}:\d{2}:\d{2}\.\d+ - )?SPEECH OUTPUT: '/.test(raw)) continue
    while (i + 1 < lines.length && /^ {18}/.test(lines[i + 1]!)) raw += '\n' + lines[++i]!.slice(18)
    // The final quote is followed by the voice dictionary or the end of the record.
    const match = raw.match(/SPEECH OUTPUT: '([\s\S]*)'(?: \{[^\n]*\})?\s*$/)
    if (match) records.push({ text: match[1]!, raw })
  }
  return records
}

export function speechText(log: string): string {
  return speechRecords(log).map((r) => r.text).join('\n')
}

export function occurrences(text: string, phrase: string): number {
  return text.toLowerCase().split(phrase.toLowerCase()).length - 1
}

/** Bounded, inode-bound cursor. Old startup speech cannot satisfy a new focus assertion. */
export class OrcaSpeech {
  private readonly fd: number
  private offset = 0
  private readonly inode: number
  constructor(path: string, uid = process.getuid!()) {
    this.fd = openSync(path, 'r')
    const stat = fstatSync(this.fd)
    if (!stat.isFile() || stat.uid !== uid || stat.size > 64 * 1024 * 1024) {
      closeSync(this.fd)
      throw new Error('Orca debug log must be a bounded regular file owned by the guest user')
    }
    this.inode = stat.ino
  }
  mark(): number { this.offset = fstatSync(this.fd).size; return this.offset }
  read(from = this.offset): string {
    const stat = fstatSync(this.fd)
    if (stat.ino !== this.inode || stat.size < from || stat.size - from > 32 * 1024 * 1024) {
      throw new Error('Orca log truncated or exceeded the per-task evidence budget')
    }
    const buffer = Buffer.alloc(stat.size - from)
    const count = readSync(this.fd, buffer, 0, buffer.length, from)
    return buffer.subarray(0, count).toString('utf8')
  }
  text(from?: number): string { return speechText(this.read(from)) }
  close(): void { closeSync(this.fd) }
}
