// In-window shortcuts use the platform's command key: ⌘ on a Mac, Ctrl elsewhere. A Mac also accepts Ctrl, so a
// shortcut someone learned on another system still works there. Electron reports every Mac as "MacIntel".
export const onMac = /^Mac/i.test(globalThis.navigator?.platform ?? '')

/** Whether the event carries the platform's command key. */
export function commandKey(event: Pick<KeyboardEvent, 'ctrlKey' | 'metaKey'>, mac = onMac): boolean {
  return event.ctrlKey || (mac && event.metaKey)
}

/** A shortcut as the platform writes it: "⌘," or "⇧⌘F" on a Mac, "Ctrl+," or "Ctrl+Shift+F" elsewhere. */
export function shortcutLabel(key: string, { shift = false }: { shift?: boolean } = {}, mac = onMac): string {
  return mac ? `${shift ? '⇧' : ''}⌘${key}` : `Ctrl+${shift ? 'Shift+' : ''}${key}`
}
