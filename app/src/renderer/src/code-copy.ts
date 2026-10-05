// Copy buttons inside rendered code blocks (markdown.ts adds them): one delegated click handler for every surface that
// shows rendered Markdown, so none is left with buttons that do nothing.

interface Clicked {
  closest?: (selector: string) => Element | null
}

export function onCodeCopyClick(event: Pick<MouseEvent, 'target'>): void {
  const button = (event.target as Clicked | null)?.closest?.('.code-copy') as HTMLButtonElement | null
  if (!button) return
  const code = button.parentElement?.querySelector('code')?.textContent ?? ''
  void window.odin.copyText(code).then((result) => {
    button.textContent = result.ok ? 'Copied' : "Couldn't copy"
    setTimeout(() => (button.textContent = 'Copy'), 1500)
  })
}
