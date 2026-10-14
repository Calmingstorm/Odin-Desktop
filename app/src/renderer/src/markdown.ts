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

// The text a reader sees, shared with the main process's notification previews.
export { plainTextOf } from '../../shared/plain-text'
