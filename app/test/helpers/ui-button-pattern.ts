// Match the stylesheet's actual control patterns, not unrelated empty class names.
export function buttonPattern(className: string, context: string): string {
  const classes = className.split(/\s+/).filter(Boolean).sort()
  if (context === 'segmented') return 'settings-segmented'
  if (context === 'menu') return 'menu-item'
  if (context === 'form-actions' && classes.includes('primary')) return 'settings-form-primary'
  if (classes.some((name) => ['ghost', 'primary', 'danger'].includes(name))) return `shared:${classes.join(' ')}`
  return classes.length ? `specialized:${classes.join(' ')}` : 'native-unclassed'
}

export function comparableButtonPattern(pattern: string): boolean {
  return pattern.startsWith('shared:') || ['settings-segmented', 'menu-item', 'settings-form-primary'].includes(pattern)
}
