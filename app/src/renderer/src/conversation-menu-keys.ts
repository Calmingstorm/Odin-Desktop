/** Menu behavior kept separate from the DOM adapter for small navigation regression tests. */
export function menuKey(key: string, index: number, count: number): number | 'close' | null {
  if (key === 'Escape' || key === 'Tab') return 'close'
  if (!count) return null
  if (key === 'ArrowDown') return (index + 1 + count) % count
  if (key === 'ArrowUp') return index < 0 ? count - 1 : (index - 1 + count) % count
  if (key === 'Home') return 0
  if (key === 'End') return count - 1
  return null
}
