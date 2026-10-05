// Forms that follow what Odin has while the user hasn't changed them.

/**
 * Takes Odin's values into a form, field by field, except a field the user changed since values were last taken in:
 * an answer or reread landing mid-edit never replaces what was typed or chosen.
 */
export function adoptUntouched<T extends object>(form: T, before: T | null, incoming: T): void {
  for (const key of Object.keys(incoming) as Array<keyof T>) {
    if (!before || form[key] === before[key]) form[key] = incoming[key]
  }
}
