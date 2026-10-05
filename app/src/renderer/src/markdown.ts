// Renders committed message text. HTML in messages is never interpreted (markdown-it `html: false`), and the result
// is sanitized again before display. Links open in the user's browser, never inside the app.
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'
import MarkdownIt from 'markdown-it'

/** Larger code blocks are shown unhighlighted, which keeps highlighting any one block to tens of milliseconds. */
export const HIGHLIGHT_MAX_CHARS = 100_000

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight: (code, language) => {
    if (language && code.length <= HIGHLIGHT_MAX_CHARS && hljs.getLanguage(language)) {
      try {
        return hljs.highlight(code, { language, ignoreIllegals: true }).value
      } catch {
        /* fall back to plain, escaped code */
      }
    }
    return ''
  }
})

const defaultLinkOpen =
  md.renderer.rules.link_open ?? ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))

md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  if (token) {
    token.attrSet('target', '_blank')
    token.attrSet('rel', 'noopener noreferrer')
  }
  return defaultLinkOpen(tokens, idx, options, env, self)
}

// Images in message text render as links: the window loads nothing remote. Files Odin produced arrive as artifacts.
md.renderer.rules.image = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const src = String(token?.attrGet('src') ?? '')
  const label = self.renderInlineAsText(token?.children ?? [], options, env) || src
  return `<a href="${md.utils.escapeHtml(src)}" target="_blank" rel="noopener noreferrer">${md.utils.escapeHtml(label)}</a>`
}

// Every code block gets a copy button; the message view handles the click.
for (const rule of ['fence', 'code_block'] as const) {
  const original =
    md.renderer.rules[rule] ?? ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
  md.renderer.rules[rule] = (tokens, idx, options, env, self) =>
    `<div class="code-block"><button type="button" class="code-copy" aria-label="Copy code">Copy</button>${original(tokens, idx, options, env, self)}</div>`
}

/** The HTML markdown-it produces, before sanitizing. Exported for tests. */
export function renderHtml(text: string): string {
  return md.render(text)
}

export function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(renderHtml(text), {
    ALLOWED_URI_REGEXP: /^(?:https?:|mailto:)/i,
    ADD_ATTR: ['target']
  })
}

/** The text a reader sees, without Markdown syntax: for "Copy as plain text". Lists keep their markers. */
export function plainTextOf(text: string): string {
  const blocks: string[] = []
  let current = ''
  let rows: string[] | null = null // a table's rows, one per line
  const lists: Array<{ ordered: boolean; next: number }> = []
  let listLines: string[] = []
  let marker = ''
  // A finished piece of text: a line of the enclosing list, or a block of its own.
  const emit = (piece: string): void => {
    if (!lists.length) {
      blocks.push(piece)
      return
    }
    const indent = '  '.repeat(lists.length - 1)
    piece.split('\n').forEach((line, i) => listLines.push(indent + (i === 0 && marker ? marker : '  ') + line))
    marker = ''
  }
  for (const token of md.parse(text, {})) {
    switch (token.type) {
      case 'inline':
        for (const child of token.children ?? []) {
          if (child.type === 'text' || child.type === 'code_inline' || child.type === 'image') current += child.content
          else if (child.type === 'softbreak' || child.type === 'hardbreak') current += '\n'
        }
        break
      case 'fence':
      case 'code_block':
        emit(token.content.replace(/\n$/, ''))
        break
      case 'paragraph_close':
      case 'heading_close':
        if (rows) break // a cell's paragraph
        emit(current)
        current = ''
        break
      case 'bullet_list_open':
      case 'ordered_list_open':
        lists.push({ ordered: token.type === 'ordered_list_open', next: Number(token.attrGet('start') ?? 1) })
        break
      case 'list_item_open': {
        const list = lists[lists.length - 1]
        marker = list?.ordered ? `${list.next++}. ` : '- '
        break
      }
      case 'bullet_list_close':
      case 'ordered_list_close':
        lists.pop()
        if (!lists.length) {
          blocks.push(listLines.join('\n'))
          listLines = []
        }
        break
      case 'table_open':
        rows = []
        break
      case 'th_close':
      case 'td_close':
        current += '\t'
        break
      case 'tr_close':
        rows?.push(current.replace(/\t$/, ''))
        current = ''
        break
      case 'table_close':
        if (rows) emit(rows.join('\n'))
        rows = null
        break
    }
  }
  if (current) blocks.push(current)
  return blocks.filter((b) => b !== '').join('\n\n').trim()
}
