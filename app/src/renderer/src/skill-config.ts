// A skill's own settings, from its config schema: the value a control gives, typed as the schema says.

export type ConfigSpec = Record<string, unknown>

/** The value for a setting: an enum's own option by its place in the list, a number as a number, a switch as true or false. */
export function configValue(spec: ConfigSpec, raw: string | boolean, optionIndex?: number): unknown {
  if (Array.isArray(spec.enum) && optionIndex !== undefined && optionIndex >= 0) return spec.enum[optionIndex]
  if (spec.type === 'boolean') return raw === true || raw === 'true'
  if (spec.type === 'integer' || spec.type === 'number') return Number(raw)
  return raw
}
