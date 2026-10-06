// Retained tool output, page by page: text is kept as text, binary pages become files to open or save.
import { describe, expect, it } from 'vitest'
import { appendPage, type OutputView } from '../../src/renderer/src/tool-output'

describe('review round 2: binary tool output', () => {
  it('deduplicates the same bundle refs returned on every real-core text page', () => {
    const view: OutputView = { text: '', files: [], next: null, eof: false }
    const attachments = [{ ref: 'artifact:retained', kind: 'file', mime: 'application/octet-stream', size: 5, sha256: 'ab' }]
    appendPage(view, 'run_command', { text: 'first', attachments, next_cursor: 'next:5', eof: false, expires_at: '' })
    appendPage(view, 'run_command', { text: 'second', attachments, eof: true, expires_at: '' })
    expect(view.files).toHaveLength(1)
    expect(view.text).toBe('firstsecond')
    expect(view.next).toBeNull()
  })
  it('keeps a binary-only last page as files, with nothing lost when the reading ends', () => {
    const view: OutputView = { text: '', files: [], next: null, eof: false }
    appendPage(view, 'run_command', { text: 'header\n', attachments: [], next_cursor: 'c2', eof: false, expires_at: '2026-10-06T00:00:00Z' })
    appendPage(view, 'run_command', {
      text: '',
      attachments: [
        { ref: 'out:1', kind: 'file', mime: 'application/octet-stream', size: 4096, sha256: 'ab' },
        { ref: 'out:2', kind: 'image', mime: 'image/png', size: 900, sha256: 'cd' }
      ],
      eof: true,
      expires_at: '2026-10-06T00:00:00Z'
    })
    expect(view).toMatchObject({ text: 'header\n', next: null, eof: true })
    expect(view.files).toEqual([
      { ref: 'out:1', name: 'run_command-output-1.bin', mime: 'application/octet-stream', size: 4096, kind: 'file', available: true },
      { ref: 'out:2', name: 'run_command-output-2.png', mime: 'image/png', size: 900, kind: 'image', available: true }
    ])
  })
})
