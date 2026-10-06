// Retained tool output that is binary: each page is a file the user can open or save, read in bounded chunks like any
// other artifact, and never decoded as text.
import type { ArtifactRef, ToolOutputPage } from '../../shared/api'

const EXTENSIONS: Record<string, string> = { 'application/octet-stream': 'bin', 'application/gzip': 'gz', 'text/plain': 'txt' }

/** A retained binary page as a file to open or save. */
export function outputFile(tool: string, attachment: ToolOutputPage['attachments'][number], index: number): ArtifactRef {
  const subtype = attachment.mime.split('/')[1] ?? ''
  const extension = EXTENSIONS[attachment.mime] ?? (/^[a-z0-9]{1,5}$/.test(subtype) ? subtype : 'bin')
  return {
    ref: attachment.ref,
    name: `${tool}-output-${index + 1}.${extension}`,
    mime: attachment.mime,
    size: attachment.size,
    kind: attachment.kind === 'image' ? 'image' : 'file',
    available: true
  }
}

/** What has been read of one tool call's retained output. */
export interface OutputView {
  text: string
  files: ArtifactRef[]
  next: string | null
  eof: boolean
}

/** Adds one page: its text, and each binary attachment as a file. */
export function appendPage(view: OutputView, tool: string, page: ToolOutputPage): void {
  view.text += page.text
  // ToolDetailsStore returns the bundle's binary refs on every text page.
  // Those are the same files, not new copies of them.
  const known = new Set(view.files.map((file) => file.ref))
  for (const attachment of page.attachments ?? []) {
    if (known.has(attachment.ref)) continue
    view.files.push(outputFile(tool, attachment, view.files.length))
    known.add(attachment.ref)
  }
  view.next = page.next_cursor ?? null
  view.eof = page.eof
}
