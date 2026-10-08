/** Measures off-layout: never collapse the visible field or write to message history scroll. */
export function fitComposer(field: HTMLTextAreaElement, mirror: HTMLDivElement): void {
  const css = getComputedStyle(field)
  const line = Number.parseFloat(css.lineHeight) || Number.parseFloat(css.fontSize) * 1.2 || 20
  const padding = (Number.parseFloat(css.paddingTop) || 0) + (Number.parseFloat(css.paddingBottom) || 0)
  const border = (Number.parseFloat(css.borderTopWidth) || 0) + (Number.parseFloat(css.borderBottomWidth) || 0)
  // Decide scrolling at full usable width, not the width narrowed by an older
  // draft's scrollbar. That avoids hysteresis at the eight-line boundary.
  mirror.style.width = `${field.offsetWidth ? field.offsetWidth - border : field.clientWidth}px`
  for (const property of ['fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'fontStretch', 'fontVariant',
    'lineHeight', 'letterSpacing', 'wordSpacing', 'textTransform', 'textIndent', 'tabSize',
    'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'] as const) {
    mirror.style[property] = css[property]
  }
  // A trailing newline occupies its own line, even though a div would otherwise omit it.
  mirror.textContent = `${field.value}\u200b`
  const minimum = Math.max(38, line + padding + border)
  const viewportCap = Number.parseFloat(css.maxHeight)
  const maximum = Math.max(minimum, Math.min(line * 8 + padding + border, Number.isFinite(viewportCap) ? viewportCap : Infinity))
  const natural = Math.ceil(mirror.scrollHeight + border)
  const height = `${Math.min(maximum, Math.max(minimum, natural))}px`
  const overflow = natural > maximum ? 'auto' : 'hidden'
  // Unchanged writes are avoided, so observing our own style attribute settles, not loops.
  if (field.style.height !== height) field.style.height = height
  if (field.style.overflowY !== overflow) field.style.overflowY = overflow
}

/** Coalesces input/layout/font invalidation and owns every observer/listener it creates. */
export function observeComposer(field: HTMLTextAreaElement, mirror: HTMLDivElement): { update: () => void; dispose: () => void } {
  let disposed = false
  let queued = false
  const update = (): void => {
    if (disposed || queued) return
    queued = true
    void Promise.resolve().then(() => {
      queued = false
      if (!disposed && field.clientWidth > 0) fitComposer(field, mirror)
    })
  }
  let width = field.clientWidth
  const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
    const next = field.clientWidth
    if (next === width) return
    width = next
    update()
  })
  resize?.observe(field)
  // Theme/zoom typography can change without a width change or a new font download.
  const typography = typeof MutationObserver === 'undefined' ? null : new MutationObserver(update)
  for (let element: Element | null = field; element; element = element.parentElement) {
    typography?.observe(element, { attributes: true, attributeFilter: ['class', 'style'] })
  }
  const fonts = document.fonts
  fonts?.addEventListener('loadingdone', update)
  fonts?.addEventListener('loadingerror', update)
  void fonts?.ready.then(update)
  window.addEventListener('resize', update)
  update()
  return {
    update,
    dispose: () => {
      disposed = true
      resize?.disconnect()
      typography?.disconnect()
      fonts?.removeEventListener('loadingdone', update)
      fonts?.removeEventListener('loadingerror', update)
      window.removeEventListener('resize', update)
    }
  }
}
