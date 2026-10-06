/** Stable, collision-free DOM IDs for settings paths and management identities. No values or secrets belong here. */
export function settingsControlId(kind: string, identity: string): string {
  return `settings-${kind}-${encodeURIComponent(identity)}`
}
