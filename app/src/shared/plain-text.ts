// The text a reader sees, without Markdown syntax: for "Copy as plain text" in the renderer and for notification
// previews in the main process, which parse exactly as the chat view does. Lists keep their markers.
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

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
