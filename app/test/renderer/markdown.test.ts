import { describe, expect, it } from 'vitest'
import { HIGHLIGHT_MAX_CHARS, plainTextOf, renderHtml } from '../../src/renderer/src/markdown'

describe('rendering committed replies', () => {
  it('highlights code and gives every code block a copy button, fenced or indented', () => {
    const fenced = renderHtml('```python\ndef f():\n    return 1\n```')
    expect(fenced).toContain('<div class="code-block"><button type="button" class="code-copy"')
    expect(fenced).toContain('hljs-keyword')
    expect(renderHtml('Run this:\n\n    make test\n')).toContain('<div class="code-block"><button type="button" class="code-copy"')
  })

  it('leaves very large code blocks unhighlighted', () => {
    const big = `\`\`\`python\n${'x = 1\n'.repeat(HIGHLIGHT_MAX_CHARS / 6 + 10)}\`\`\``
    const html = renderHtml(big)
    expect(html).toContain('<pre><code class="language-python">x = 1')
    expect(html).not.toContain('hljs-')
  })

  it('renders tables, and shows raw HTML as text rather than running it', () => {
    expect(renderHtml('| a | b |\n|---|---|\n| 1 | 2 |')).toContain('<table>')
    const html = renderHtml('<script>alert(1)</script> <img src=x onerror=alert(1)>')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;script&gt;')
  })

  it('renders Markdown images as links, so the window loads nothing remote', () => {
    const html = renderHtml('![a chart](https://example.com/chart.png)')
    expect(html).toContain('<a href="https://example.com/chart.png" target="_blank" rel="noopener noreferrer">a chart</a>')
    expect(html).not.toContain('<img')
  })
})

describe('copy as plain text', () => {
  it('drops Markdown syntax from text, code and tables', () => {
    const text = '# Title\n\nSome **bold** and [a link](https://example.com).\n\n```sh\nls -la\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |'
    expect(plainTextOf(text)).toBe('Title\n\nSome bold and a link.\n\nls -la\n\na\tb\n1\t2')
  })

  it('keeps list markers and nesting, one item per line', () => {
    const text = 'Steps:\n\n1. Pull\n2. Build\n   - fast\n   - clean\n3. Ship\n\n- one\n- two'
    expect(plainTextOf(text)).toBe('Steps:\n\n1. Pull\n2. Build\n  - fast\n  - clean\n3. Ship\n\n- one\n- two')
  })
})

describe('review round 1: code copy buttons work wherever Markdown is rendered', () => {
  it('copies the code of the block whose button was clicked', async () => {
    const copied: string[] = []
    ;(globalThis as unknown as { window: unknown }).window = {
      odin: { copyText: async (text: string) => (copied.push(text), { ok: true, result: { copied: true } }) }
    }
    const { onCodeCopyClick } = await import('../../src/renderer/src/code-copy')
    const button = { textContent: 'Copy', parentElement: { querySelector: () => ({ textContent: 'make test' }) } }
    onCodeCopyClick({ target: { closest: (selector: string) => (selector === '.code-copy' ? button : null) } as unknown as EventTarget })
    await new Promise((r) => setTimeout(r, 0))
    expect(copied).toEqual(['make test'])
    expect(button.textContent).toBe('Copied')
    onCodeCopyClick({ target: { closest: () => null } as unknown as EventTarget }) // a click elsewhere copies nothing
    expect(copied).toHaveLength(1)
  })
})

