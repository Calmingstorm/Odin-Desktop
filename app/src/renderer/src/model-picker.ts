import type { ConfigField } from '../../shared/api'

export type ModelProvider = 'codex' | 'compat' | 'ollama'
export type ModelRow = { ref: string; name?: string; capability?: string; effort_capabilities?: { values: string[] | null; restrictions_known: boolean; source: string } }
export type ProviderStatus = { configured?: boolean; base_url?: string; model?: string; preset?: string; openrouter_recognized?: boolean }
export type ModelStatus = { model_catalogue?: Record<string, ModelRow[]>; serving_provider?: string | null; active_provider?: string; codex?: ProviderStatus; ollama?: ProviderStatus; openai_compatible?: ProviderStatus }
export type ModelOption = { ref: string; label: string; disabled: boolean }

const enabledPaths: Record<ModelProvider, string> = { codex: 'openai_codex.enabled', compat: 'openai_compatible.enabled', ollama: 'ollama.enabled' }
const providerNames: Record<ModelProvider, string> = { codex: 'Codex', compat: 'OpenAI-compatible', ollama: 'Ollama' }
export function modelProvider(model: string): ModelProvider {
  return model.startsWith('compat:') ? 'compat' : model.startsWith('ollama:') ? 'ollama' : 'codex'
}
export function providerEnabled(model: string, fields: readonly ConfigField[]): boolean {
  // Saved enablement, not a constructed client or an unsaved toggle, owns picker eligibility.
  return fields.find((field) => field.path === enabledPaths[modelProvider(model)])?.desired === true
}
export function catalogueRows(status: ModelStatus): ModelRow[] {
  const seen = new Set<string>()
  return Object.values(status.model_catalogue ?? {}).flat().filter((row) => {
    if (typeof row.ref !== 'string' || !row.ref || seen.has(row.ref)) return false
    seen.add(row.ref)
    return true
  })
}
export function catalogueModelLabel(row: ModelRow): string {
  const name = row.name?.trim()
  return !name || name === row.ref ? row.ref : `${name} · ${row.ref}`
}
export function modelSelectionNote(model: string, rows: readonly ModelRow[], fields: readonly ConfigField[]): string {
  if (!model) return ''
  if (!providerEnabled(model, fields)) return `${providerNames[modelProvider(model)]} is off. This saved selection is kept.`
  return rows.some((row) => row.ref === model) ? '' : 'This saved model is not in the current choices. It is kept until you choose another.'
}
export function modelOptions(rows: readonly ModelRow[], fields: readonly ConfigField[], selected: string): ModelOption[] {
  const options = rows.filter((row) => providerEnabled(row.ref, fields)).map((row) => ({ ref: row.ref, label: catalogueModelLabel(row), disabled: false }))
  if (!options.some((option) => option.ref === selected)) {
    const row = rows.find((item) => item.ref === selected)
    options.unshift({ ref: selected, label: row ? catalogueModelLabel(row) : selected || 'Choose a model', disabled: true })
  }
  return options
}
export function modelEffortPath(model: string, rows: readonly ModelRow[]): string {
  if (rows.find((row) => row.ref === model)?.effort_capabilities?.values?.length === 0) return ''
  const provider = modelProvider(model)
  return provider === 'codex' ? 'openai_codex.reasoning_effort' : provider === 'compat' ? 'openai_compatible.reasoning_effort' : ''
}
